"""Controls: prove the four tests can find a known-bad provider and leave normal ones alone.

A test that has never been shown to find anything is not a test. Two checks:

  1. The planted row. One synthetic impossible provider is put into the data and
     every test must find it. This runs on the shipped synthetic sample (a
     planted provider is already in tests/sample/d24.csv.gz) and, by inserting
     a second one inside a transaction that is rolled back, on any database.
  2. The null. Normal synthetic providers, and random subsamples of them, must
     not be flagged. A test that flags everyone finds nothing.

Run with:  python -m pytest
report.py runs the planted-row check on your real database before it writes a report,
and stops if any test misses it.
"""
import gzip
import os
import random
import tempfile

import pytest

from . import hours, make_sample
from .planted import (DYNAMIC_NPI, PLANTED, SAMPLE_DIR, check_planted, flagged_npis, found, load_sample,
                      plant, run_all, insert_pr)


# ---------------------------------------------------------------- pytest: the shipped sample

@pytest.fixture(scope="module")
def con():
    c = load_sample()
    yield c
    c.close()


@pytest.fixture(scope="module")
def results(con):
    return run_all(con)


@pytest.fixture(scope="module")
def normal_npis(con):
    rows = con.execute(f"""select distinct npi from y24 where ent='I' and npi <> '{PLANTED}'""").fetchall()
    return sorted(r[0] for r in rows)


def test_sample_is_50000_rows_with_no_real_npis(con):
    total = sum(con.execute(f"select count(*) from y{y}").fetchall()[0][0] for y in (22, 23, 24))
    assert total == 50_000
    bad = con.execute("""select count(*) from (select npi from y24 union select npi from y23 union select npi from y22)
                         where npi not like '0%'""").fetchall()[0][0]
    assert bad == 0, "every synthetic NPI must start with 0, which no real NPI does"


def test_sample_is_reproducible():
    """make_sample.py is deterministic: regenerating gives the same rows (compared uncompressed)."""
    with tempfile.TemporaryDirectory() as tmp:
        old = make_sample.OUT_DIR
        make_sample.OUT_DIR = tmp
        try:
            make_sample.main()
        finally:
            make_sample.OUT_DIR = old
        for f in ("d22.csv.gz", "d23.csv.gz", "d24.csv.gz"):
            with gzip.open(os.path.join(tmp, f), "rb") as new, gzip.open(os.path.join(SAMPLE_DIR, f), "rb") as old:
                assert new.read() == old.read(), f


def test_every_test_finds_the_planted_provider(results):
    codes = {"H": "90837", "A": "93000", "B": "99214", "C": "99308"}
    got = found(results, PLANTED, codes)
    assert got == {"H": True, "A": True, "B": True, "C": True}, got
    h = results["H"].set_index("npi").loc[PLANTED]
    assert h["tier"] == "impossible" and h["hours"] > hours.IMPOSSIBLE_HOURS


def test_nothing_but_the_planted_provider_is_flagged(results):
    """The null: all ordinary synthetic providers pass every test."""
    assert flagged_npis(results) == {PLANTED}, {k: sorted(set(v["npi"]) - {PLANTED}) for k, v in results.items()}


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_random_sample_of_normal_providers_is_not_flagged(normal_npis, seed):
    """Run the whole pipeline again on a random 60 percent of normal providers plus the planted one."""
    pick = set(random.Random(seed).sample(normal_npis, int(len(normal_npis) * 0.6))) | {PLANTED}
    c = load_sample(pick)
    try:
        res = run_all(c)
        assert flagged_npis(res) == {PLANTED}
    finally:
        c.close()


def test_organizations_and_drug_rows_are_ignored(con, results):
    orgs = con.execute("select count(*) from y24 where ent='O' and srv > 20000").fetchall()[0][0]
    assert orgs > 0, "the sample must contain organization rows with absurd volumes"
    assert not any(str(n).startswith(make_sample.ORG_PREFIX) for df in results.values() for n in df["npi"])
    assert con.execute("select count(*) from pr where code='J3301'").fetchall()[0][0] == 0


def test_insert_one_impossible_provider_into_a_clean_copy(con):
    """Remove the shipped planted provider, check the null, insert a new one, check every test finds it."""
    con.execute("begin")
    try:
        con.execute("delete from pr where npi = ?", [PLANTED])
        assert flagged_npis(run_all(con)) == set()
        codes = plant(con)
        got = found(run_all(con), DYNAMIC_NPI, codes)
        assert got == {"H": True, "A": True, "B": True, "C": True}, got
    finally:
        con.execute("rollback")
    assert con.execute("select count(*) from pr where npi = ?", [PLANTED]).fetchall()[0][0] == 4


def test_check_planted_leaves_the_database_unchanged(con):
    before = con.execute("select count(*) from pr").fetchall()[0][0]
    ok, res, _ = check_planted(con)
    assert ok, res
    assert con.execute("select count(*) from pr").fetchall()[0][0] == before


def test_just_below_each_threshold_is_not_flagged(con):
    """Boundaries: rows one notch under each threshold must pass, so the thresholds mean what the docstrings say."""
    con.execute("begin")
    try:
        con.execute("delete from pr where npi = ?", [PLANTED])
        codes = plant(con)
        con.execute("delete from pr where npi = ?", [DYNAMIC_NPI])
        n = "0999999975"
        r = con.execute("select med, p99 from cs where code = ?", [codes["A"]]).fetchall()[0]
        under_rate = max(5 * r[0], r[1]) * 0.95                       # just under the 5x / p99 line
        insert_pr(con, n, "90837", 300, 8000, 8000, 240_000)          # 7,067 hours: high, not impossible
        insert_pr(con, n, codes["A"], 100, round(under_rate * 100), round(under_rate * 100), 150_000)
        insert_pr(con, n, codes["B"], 100, 1000, 1000, 249_999)       # one dollar under the B line
        insert_pr(con, n, "99308", 200, 2475, 250, 210_000)           # 9.9 per patient-day
        low = "0999999967"   # 2,499.8 floor hours: just under the 2,500 line, so H must not list it
        insert_pr(con, low, "90837", 300, 2830, 2830, 100_000)
        assert 2830 * 53 / 60 < hours.HIGH_HOURS <= 2831 * 53 / 60   # 2,499.8 vs 2,500.8: one service apart
        res = run_all(con)
        assert low not in set(res["H"]["npi"]), "2,499.8 hours must be under the H line"
        assert len(res["H"][res["H"]["npi"] == n]) == 1
        mine = {k: v[v["npi"] == n] for k, v in res.items()}
        assert mine["H"].iloc[0]["tier"] == "high"                      # over 2,500 hours, under 8,760
        assert len(mine["A"]) == 0 and len(mine["B"]) == 0 and len(mine["C"]) == 0
    finally:
        con.execute("rollback")


def test_per_day_ignores_addon_codes(con):
    """Per-unit add-on codes repeat on one day by design, so test C must not list them."""
    con.execute("begin")
    try:
        con.execute("delete from pr where npi = ?", [PLANTED])
        n = "0999999959"
        insert_pr(con, n, "99292", 100, 3000, 250, 500_000)   # critical care, each added 30 minutes
        insert_pr(con, n, "99417", 100, 3000, 250, 500_000)   # prolonged visit, each 15 minutes
        assert n not in set(run_all(con)["C"]["npi"])
        insert_pr(con, n, "99308", 100, 3000, 250, 500_000)   # an ordinary visit code at the same ratio is listed
        assert n in set(run_all(con)["C"]["npi"])
    finally:
        con.execute("rollback")


def test_hours_data_control_on_sample(con):
    ok, detail = hours.real_control(con)
    assert ok, detail


def test_report_refuses_to_write_when_planted_check_cannot_run(tmp_path, monkeypatch):
    """A read-only database means the planted-row check cannot run, so report.py must exit and write nothing."""
    import duckdb
    import build
    import report
    db = str(tmp_path / "ro.duckdb")
    build.build(SAMPLE_DIR, db, 2024).close()
    monkeypatch.setattr(report, "connect", lambda path: (duckdb.connect(path, read_only=True), False))
    out = tmp_path / "out" / "report.md"
    with pytest.raises(SystemExit) as e:
        report.main(["--db", db, "--out", str(out)])
    assert "planted-row check cannot run" in str(e.value)
    assert not out.exists()
