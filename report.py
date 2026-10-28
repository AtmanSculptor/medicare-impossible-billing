#!/usr/bin/env python3
"""Run the controls and the four tests on a built database and write out/report.md.

    python report.py                      # data/cms.duckdb -> out/report.md
    python report.py --top 40             # longer tables
    python report.py --show-npi           # reveal the NPI and city columns (see below)

Why NPI columns are blank by default
    A flag is a question, not an accusation. Most flags have an innocent reading
    (CARE.md lists them), and a report that carries a name or an NPI gets
    forwarded without the caveats. So by default the NPI column is empty, the
    city is dropped, paid amounts are rounded to the nearest $10,000, and this
    program never writes a provider's name. That stops casual forwarding. It does
    NOT stop re-identification: state, specialty, code and the service counts can
    be matched back to the public CMS file. Treat the default report as sensitive
    anyway. When you are ready to follow a row up, --show-npi fills in the NPI,
    city and exact amounts, and you work through CARE.md before anyone is named.

Known-family tags
    Some code families already have a large, public explanation (skin
    substitutes, catheter supplies) or are driven by drug price, not volume.
    Those rows stay in the report but are tagged and listed last, so they do not
    bury the rest. A tag is not an excuse; read CARE.md.

The report refuses to run if the planted-row check cannot run or fails: the
planted impossible provider must be found by every test. A second check, that
the top psychotherapy biller of the year exceeds 8,760 floor hours, is a
calibration check only. If it fails, the report is still written, with a warning
that says so, because a method must be free to report that nobody is impossible.
"""
import argparse
import datetime
import os
import sys

import duckdb
import pandas as pd

from tests import hours, planted, rate, per_day, from_nothing


def family(code):
    """Known-family tag for a code, or '' if none."""
    c = str(code)
    if c.startswith(("Q41", "Q42", "Q43", "A20")):
        return "skin substitute"
    if c == "A4353":
        return "urinary catheter supplies"
    if c.startswith(("A96", "A98", "A95", "J9", "J1", "J2", "J3", "J0", "J7")):
        return "drug or radiopharmaceutical (price, not volume)"
    if c in ("36415", "99214", "99213"):
        return "high-volume routine code"
    return ""


def money(x):
    return "" if pd.isna(x) else f"${x:,.0f}"


def coarse(x):
    """Paid amount rounded to the nearest $10,000 (default output)."""
    return "" if pd.isna(x) else f"~${round(x / 10_000) * 10_000:,.0f}"


def num(x, digits=0):
    return "" if pd.isna(x) else f"{x:,.{digits}f}"


def md_table(df):
    if df.empty:
        return "_none_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for row in df.itertuples(index=False):
        lines.append("| " + " | ".join(str(v).replace("|", "/") for v in row) + " |")
    return "\n".join(lines) + "\n"


def tidy(df, test, show_npi):
    """Pick and format the columns for one test's table. NPI blank, no name, no city unless shown."""
    out = pd.DataFrame(index=df.index)
    paid_fmt = money if show_npi else coarse
    out["npi"] = df["npi"] if show_npi else ""
    out["state"] = df["st"]
    if show_npi:
        out["city"] = df["loc"].str.rsplit(" ", n=1).str[0]
    out["specialty"] = df["typ"].fillna("").str.slice(0, 28)
    out["code"] = df["code"]
    if test == "H":
        out["timed_services"] = df["timed_srv"].map(num)
        out["floor_hours"] = df["hours"].map(num)
        out["tier"] = df["tier"]
        out["paid"] = df["paid"].map(paid_fmt)
    else:
        out["description"] = df["dsc"].fillna("").str.slice(0, 40)
        out["patients"] = df["benes"].map(num)
        out["services"] = df["srv"].map(num)
        out["paid"] = df["paid"].map(paid_fmt)
        if test == "A":
            out["per_patient"] = df["per_patient"]
            out["code_median"] = df["med"]
            out["x_median"] = df["ratio"]
        if test == "B":
            out["paid_prev_yr"] = df["paid_prev"].fillna(0).map(paid_fmt)
            out["paid_2yr_ago"] = df["paid_prev2"].fillna(0).map(paid_fmt)
        if test == "C":
            out["patient_days"] = df["bdays"].map(num)
            out["per_day"] = df["per_day"]
    out["family"] = df["family"]
    return out.reset_index(drop=True)


def order(df):
    """Untagged rows first (biggest first), then tagged rows grouped by family."""
    sort_col = "paid"
    return df.assign(_tag=(df["family"] != "")).sort_values(["_tag", "family", sort_col], ascending=[True, True, False]).drop(columns="_tag")


def connect(path):
    try:
        return duckdb.connect(path), True
    except duckdb.Error:
        return duckdb.connect(path, read_only=True), False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default="data/cms.duckdb")
    ap.add_argument("--out", default="out/report.md")
    ap.add_argument("--top", type=int, default=25, help="rows per table (default 25)")
    ap.add_argument("--show-npi", action="store_true", help="fill in the NPI and city columns")
    a = ap.parse_args(argv)
    if not os.path.exists(a.db):
        sys.exit(f"{a.db} not found. Run: python build.py")
    con, writable = connect(a.db)
    has_meta = con.execute("select count(*) from information_schema.tables where table_name='meta'").fetchall()[0][0]
    year = con.execute("select year from meta").fetchall()[0][0] if has_meta else "?"

    # ---- controls: the planted-row check must run and pass; the data check only calibrates
    if not writable:
        sys.exit("STOP: the database is open read-only (or locked), so the planted-row check cannot run. "
                 "No report written. Close other programs using the file, or copy it and point --db at the copy.")
    try:
        ok, res, codes = planted.check_planted(con)
    except Exception as e:  # noqa: BLE001 - any failure to run the check means we cannot vouch for the tests
        sys.exit(f"STOP: the planted-row check could not run ({e}). No report written.")
    detail = ", ".join(f"{k} {'found' if v else 'MISSED'} ({codes[k]})" for k, v in res.items())
    print("CONTROL", "ok     " if ok else "MISSING", "planted impossible provider found by every test |", detail)
    if not ok:
        sys.exit("STOP: the planted-row control failed, so the method is broken for this data. No report written.")
    hok, hdetail = hours.real_control(con)
    calib = "ok" if hok else "WARNING"
    print("CALIBRATION", calib, "top psychotherapy biller vs 8,760 floor hours |", hdetail)
    controls = [("planted impossible provider found by every test", "ok", detail),
                ("calibration: top psychotherapy biller vs 8,760 floor hours (warning only)", calib, hdetail)]
    notes = []
    if not hok:
        notes.append("Calibration warning: no psychotherapy biller exceeds 8,760 floor hours in this data. "
                     "That is a result, not an error. It may mean the data is clean at the top, or that the "
                     "floors do not fit this year. Nothing was stopped.")

    # ---- the four tests
    results = {}
    for name, mod in planted.TESTS.items():
        try:
            df = mod.run(con)
        except RuntimeError as e:
            notes.append(f"Test {name} skipped: {e}")
            continue
        if name == "H":
            df["dsc"] = ""
            df["family"] = ""
        else:
            df["family"] = [family(c) for c in df["code"]]
        results[name] = df

    # ---- write
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    w = []
    w.append(f"# Report: Medicare by Provider and Service, {year}\n")
    w.append(f"Written {datetime.date.today().isoformat()} from `{os.path.basename(a.db)}`. "
             f"NPI, city and exact amounts are {'SHOWN' if a.show_npi else 'hidden (NPI blank, city dropped, paid rounded to $10,000)'}; names are never written. "
             f"Hidden is not anonymous: state, specialty, code and counts can be matched to the public file.\n")
    w.append("> A flag is a question, not an accusation. Every row below has innocent readings "
             "(shared billing numbers, supervised staff, new practices, data errors). Read CARE.md before anyone is named.\n")
    w.append("## Controls\n")
    w.append(md_table(pd.DataFrame(controls, columns=["control", "result", "detail"])))
    w.append("## Counts\n")
    rows = []
    if "H" in results:
        h = results["H"]
        rows.append(("H hours", "NPIs (billing numbers) with floor hours >= 2,500", len(h), "", money(h["paid"].sum())))
        rows.append(("H hours", "NPIs with floor hours > 8,760 (more than a year has)", int((h["tier"] == "impossible").sum()), "", ""))
        rows.append(("H hours", "NPIs over 2,500 hours on psychotherapy codes alone", hours.count_psychotherapy(con), "", ""))
    labels = {"A": "A rate: provider-code pairs", "B": "B from nothing: provider-code pairs", "C": "C per day: provider-code pairs"}
    for k in ("A", "B", "C"):
        if k in results:
            d = results[k]
            rows.append((labels[k], {"A": "5x the code median and >= p99, paid >= $100K",
                                     "B": "paid >= $250K, no row the year before",
                                     "C": "10+ services per patient-day on E/M or psychiatry codes, paid >= $100K"}[k],
                         len(d), int((d["family"] != "").sum()), money(d["paid"].sum())))
    w.append(md_table(pd.DataFrame(rows, columns=["test", "rule", "flagged", "known-family tagged", "paid"])))
    if "A" in results:
        el = rate.eligible(con)
        w.append(f"Sanity band for test A: {len(results['A']):,} flagged of {el:,} eligible pairs "
                 f"({100 * len(results['A']) / max(el, 1):.3f} percent). A test that flags more than 1 percent is too loose.\n")
    w.extend(f"_{n}_\n" for n in notes)

    for k, title in (("H", "Test H: floor hours of timed services"), ("A", "Test A: services per patient"),
                     ("B", "Test B: paid from nothing"), ("C", "Test C: services per patient-day")):
        if k not in results:
            continue
        d = order(results[k])
        main_rows = d[d["family"] == ""]
        w.append(f"## {title}\n")
        w.append(f"Top {min(a.top, len(main_rows))} of {len(main_rows):,} untagged rows, biggest first. "
                 f"{len(d) - len(main_rows):,} tagged rows are under Known families.\n")
        w.append(md_table(tidy(main_rows.head(a.top), k, a.show_npi)))

    tagged = [(k, order(results[k])) for k in ("A", "B", "C") if k in results]
    w.append("## Known families (listed last)\n")
    w.append("Code families with a public explanation already or driven by price. Kept, not dismissed.\n")
    for k, d in tagged:
        t = d[d["family"] != ""]
        if t.empty:
            continue
        w.append(f"### Test {k}: {len(t):,} tagged rows\n")
        by = t.groupby("family").agg(rows=("code", "size"), paid=("paid", "sum")).reset_index()
        by["paid"] = by["paid"].map(money)
        w.append(md_table(by))
        w.append(md_table(tidy(t.head(a.top), k, a.show_npi)))

    with open(a.out, "w") as f:
        f.write("\n".join(w))
    print(f"wrote {a.out}")
    for r in rows:
        print(f"  {r[0]:38s} {r[1]:70s} {r[2]:>8,}")

    # a flat file of everything flagged, same privacy rule
    flat = pd.concat([tidy(order(v), k, a.show_npi).assign(test=k) for k, v in results.items()], ignore_index=True)
    flat.to_csv(os.path.splitext(a.out)[0] + "_flags.csv", index=False)
    con.close()


if __name__ == "__main__":
    main()
