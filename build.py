#!/usr/bin/env python3
"""Build the DuckDB database the tests run on.

Reads the CMS "by Provider and Service" CSVs (data/d24.csv, d23.csv, d22.csv)
and creates these tables:

    y24, y23, y22   one table per year, one row per provider x code x place of
                    service, with the columns the tests use (see YEAR_SQL).
    pr              per provider-code table for the target year: individual
                    providers (entity code I) only, drug rows (HCPCS drug
                    indicator Y) removed, places of service summed.
    cs              per-code national statistics for the target year: how many
                    providers billed the code, the median and 99th percentile
                    of services per patient. Only codes with 200+ billers.
    pp23, pp22      per provider-code paid totals for the earlier years
                    (individual providers, all rows), for the history columns.
    csprev          codes that had 200+ individual billers the year before the
                    target year (so a brand new code does not flood test B).

Usage:
    python build.py                          # data/ -> data/cms.duckdb, target 2024
    python build.py --data-dir /big/disk --db /big/disk/cms.duckdb
    python build.py --year 2023              # target 2023, history 2022 and 2021
"""
import argparse
import glob
import os
import sys
import time

import duckdb

MIN_BILLERS = 200  # a code needs this many individual billers to have stable national statistics

# Column mapping from the CMS file to the short names every test uses.
YEAR_SQL = """
create or replace table y{yy} as select
    Rndrng_NPI npi, Rndrng_Prvdr_Last_Org_Name ln, Rndrng_Prvdr_First_Name fn,
    Rndrng_Prvdr_Crdntls cred, Rndrng_Prvdr_Ent_Cd ent, Rndrng_Prvdr_Type typ,
    Rndrng_Prvdr_City city, Rndrng_Prvdr_State_Abrvtn st,
    HCPCS_Cd code, HCPCS_Desc dsc, HCPCS_Drug_Ind drug, Place_Of_Srvc pos,
    Tot_Benes::double benes, Tot_Srvcs::double srv, Tot_Bene_Day_Srvcs::double bdays,
    Avg_Mdcr_Pymt_Amt::double pay
from read_csv_auto('{path}', all_varchar=true)
"""


def csv_for(data_dir, year):
    """Path of the CSV for a year, or None. Accepts dYY.csv, dYY.csv.gz or any *DYY_Prov_Svc*.csv."""
    yy = f"{year % 100:02d}"
    for name in (f"d{yy}.csv", f"d{yy}.csv.gz"):
        p = os.path.join(data_dir, name)
        if os.path.exists(p):
            return p
    hits = glob.glob(os.path.join(data_dir, f"*D{yy}_Prov_Svc*.csv"))
    return hits[0] if hits else None


def load_year(con, year, path):
    yy = f"{year % 100:02d}"
    con.execute(YEAR_SQL.format(yy=yy, path=path.replace("'", "''")))
    n, total = con.execute(f"select count(*), round(sum(srv*pay)/1e9, 2) from y{yy}").fetchall()[0]
    print(f"  y{yy}: {n:,} rows, ${total}B paid  ({os.path.basename(path)})")


def derive(con, year):
    """Create pr, cs, pp<yy>, csprev from the y<yy> tables. Used by the tests/controls too."""
    yy, p1, p2 = (f"{(year - k) % 100:02d}" for k in (0, 1, 2))
    have = {r[0] for r in con.execute("select table_name from information_schema.tables").fetchall()}
    con.execute(f"""create or replace table pr as select npi, code, any_value(dsc) dsc,
        any_value(fn)||' '||any_value(ln) name, any_value(cred) cred, any_value(typ) typ,
        any_value(city)||' '||any_value(st) loc, any_value(st) st, max(benes) benes, sum(srv) srv,
        sum(bdays) bdays, sum(srv*pay) paid
        from y{yy} where ent='I' and drug<>'Y' group by npi, code""")
    con.execute(f"""create or replace table cs as select code, count(*) n, median(srv/benes) med,
        quantile_cont(srv/benes, 0.99) p99 from pr where benes>0 group by code having count(*)>={MIN_BILLERS}""")
    for p in (p1, p2):
        if f"y{p}" in have:
            con.execute(f"""create or replace table pp{p} as select npi, code, sum(srv*pay) paid
                from y{p} where ent='I' group by npi, code""")
    if f"y{p1}" in have:
        con.execute(f"""create or replace table csprev as select code, count(*) n from
            (select npi, code from y{p1} where ent='I' group by npi, code) group by code
            having count(*)>={MIN_BILLERS}""")
    con.execute(f"create or replace table meta as select {year} as year")
    n_pr = con.execute("select count(*) from pr").fetchall()[0][0]
    n_cs = con.execute("select count(*) from cs").fetchall()[0][0]
    print(f"  pr: {n_pr:,} provider-code rows; cs: {n_cs:,} codes with {MIN_BILLERS}+ billers")


def build(data_dir, db, year, memory_limit=None):
    os.makedirs(os.path.dirname(os.path.abspath(db)), exist_ok=True)
    con = duckdb.connect(db)
    if memory_limit:
        con.execute(f"set memory_limit='{memory_limit}'")
    con.execute(f"set temp_directory='{os.path.abspath(db)}.tmp'")
    t0 = time.time()
    missing_target = True
    for y in (year, year - 1, year - 2):
        path = csv_for(data_dir, y)
        if path is None:
            print(f"  {y}: no CSV in {data_dir} (run download.py --year {y})")
            continue
        if y == year:
            missing_target = False
        load_year(con, y, path)
    if missing_target:
        sys.exit(f"error: the target year {year} file is required")
    derive(con, year)
    print(f"done in {int(time.time() - t0)} s -> {db}")
    return con


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default="data", help="folder holding dYY.csv files (default data/)")
    ap.add_argument("--db", default=None, help="DuckDB file to write (default <data-dir>/cms.duckdb)")
    ap.add_argument("--year", type=int, default=2024, help="target year, the two before it are history")
    ap.add_argument("--memory-limit", default=None, help="DuckDB memory limit, for example 5GB")
    a = ap.parse_args(argv)
    db = a.db or os.path.join(a.data_dir, "cms.duckdb")
    print(f"building {db} for {a.year}")
    build(a.data_dir, db, a.year, a.memory_limit).close()


if __name__ == "__main__":
    main()
