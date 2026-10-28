"""Planted-row machinery shared by the pytest controls and by report.py.

No pytest import here, so report.py can run the planted-row check on a real
database without pytest installed.
"""
import duckdb
import pandas as pd

import build

from . import from_nothing, hours, make_sample, per_day, rate

SAMPLE_DIR = make_sample.OUT_DIR
PLANTED = make_sample.PLANTED_NPI
DYNAMIC_NPI = "0999999983"   # the second planted provider, inserted by plant()
TESTS = {"H": hours, "A": rate, "B": from_nothing, "C": per_day}


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


def insert_pr(con, npi, code, benes, srv, bdays, paid):
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
    insert_pr(con, npi, "90837", 300, 12000, 12000, 1_500_000)             # H: 10,600 floor hours
    insert_pr(con, npi, rate_code, 100, round(per_patient * 100), round(per_patient * 100), 150_000)   # A
    insert_pr(con, npi, n, 100, 1000, 1000, 300_000)                       # B: no row last year
    insert_pr(con, npi, "99308", 200, 3000, 250, 210_000)                  # C: 12 per patient-day
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
