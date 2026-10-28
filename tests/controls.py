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

import duckdb
import pandas as pd
import pytest

import build

from . import from_nothing, hours, make_sample, per_day, rate

SAMPLE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample")
PLANTED = make_sample.PLANTED_NPI
DYNAMIC_NPI = "0999999983"   # the second planted provider, inserted by plant()
TESTS = {"H": hours, "A": rate, "B": from_nothing, "C": per_day}


# ---------------------------------------------------------------- helpers used by tests and report.py

def load_sample(npis=None):
    """In-memory database built from the shipped sample by the same code the real data uses."""
    con = duckdb.connect(":memory:")
    for year in (2022, 2023, 2024):
        build.load_year(con, year, build.csv_for(SAMPLE_DIR, year))
    if npis is not None:   # keep only these individual providers (subsample), organizations stay
        con.register("keep_df", pd.DataFrame({"npi": sorted(npis)}))
        for y in ("y22", "y23", "y24"):
            con.execute(f"delete from {y} where ent='I' and npi not in (select npi from keep_df)")
    build.derive(con, 2024)
    return con


def run_all(con):
    """{'H': df, 'A': df, 'B': df, 'C': df}"""
    return {name: mod.run(con) for name, mod in TESTS.items()}


def flagged_npis(results):
    return set().union(*(set(df["npi"]) for df in results.values()))


def _insert_pr(con, npi, code, benes, srv, bdays, paid):
    con.execute("insert into pr values (?, ?, 'planted', 'Planted Provider', 'MD', 'Internal Medicine', "
                "'Nowhere XX', 'XX', ?, ?, ?, ?)", [npi, code, benes, srv, bdays, paid])


def plant(con, npi=DYNAMIC_NPI):
    """Insert one impossible provider into pr. Codes are chosen from the codes this database knows.

    Returns {test: code} for the row built to trip each test. Call inside a transaction
    and roll it back, so the database is left as it was.
    """
    rows = con.execute("""select cs.code, cs.med, cs.p99 from cs join csprev using(code)
                          where cs.med <= 1.15 order by cs.n desc limit 1""").fetchall()
    r = rows[0] if rows else None
    if r is None:
        raise RuntimeError("no once-per-patient code with 200+ billers in both years; cannot plant a rate row")
    rate_code, med, p99 = r
    n = con.execute("select code from csprev where code <> ? order by n desc limit 1", [rate_code]).fetchall()[0][0]
    per_patient = max(5 * med, p99) * 3 + 5
    _insert_pr(con, npi, "90837", 300, 12000, 12000, 1_500_000)             # H: 10,600 floor hours
    _insert_pr(con, npi, rate_code, 100, round(per_patient * 100), round(per_patient * 100), 150_000)   # A
    _insert_pr(con, npi, n, 100, 1000, 1000, 300_000)                       # B: no row last year
    _insert_pr(con, npi, "99308", 200, 3000, 250, 210_000)                  # C: 12 per patient-day
    return {"H": "90837", "A": rate_code, "B": n, "C": "99308"}


def found(results, npi, codes):
    """{test: bool}: did each test flag this NPI (and, where it has one, the expected code)?"""
    out = {}
    for name, df in results.items():
        rows = df[df["npi"] == npi]
        out[name] = bool(len(rows)) and (name == "H" or bool((rows["code"] == codes[name]).any()))
    return out


def check_planted(con):
    """Insert a planted provider, run all tests, roll back. Returns (ok, {test: bool}, detail)."""
    con.execute("begin")
    try:
        codes = plant(con)
        res = found(run_all(con), DYNAMIC_NPI, codes)
    finally:
        con.execute("rollback")
    return all(res.values()), res, codes


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
        _insert_pr(con, n, "90837", 300, 8000, 8000, 240_000)          # 7,067 hours: high, not impossible
        _insert_pr(con, n, codes["A"], 100, round(under_rate * 100), round(under_rate * 100), 150_000)
        _insert_pr(con, n, codes["B"], 100, 1000, 1000, 249_999)       # one dollar under the B line
        _insert_pr(con, n, "99308", 200, 2475, 250, 210_000)           # 9.9 per patient-day
        res = run_all(con)
        mine = {k: v[v["npi"] == n] for k, v in res.items()}
        assert mine["H"].iloc[0]["tier"] == "high"                      # over 2,500 hours, under 8,760
        assert len(mine["A"]) == 0 and len(mine["B"]) == 0 and len(mine["C"]) == 0
    finally:
        con.execute("rollback")


def test_hours_data_control_on_sample(con):
    ok, detail = hours.real_control(con)
    assert ok, detail
