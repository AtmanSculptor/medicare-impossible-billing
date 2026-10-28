"""Test B: a large payment on a provider-code pair that did not exist the year before.

Logic
    Practices usually grow gradually. A provider-code pair that paid
    $250,000 or more this year and had no row at all last year went from nothing
    to a large amount in one step. That is unusual, and it has many ordinary
    explanations (listed below and in CARE.md).

    Only codes that were already established are tested: the code needs 200+
    individual billers the year before. Otherwise every provider who started
    using a brand new code would flag.

    Medicare suppresses a row with fewer than 11 patients, so "no row last
    year" can mean "fewer than 11 patients last year" and not "no billing".
    That is why the threshold is high and why prior years are checked by hand.

Threshold
    paid this year >= $250,000, no row for the pair the year before, and the
    code had 200+ individual billers the year before.

Control
    The planted impossible provider (tests/controls.py) must be flagged, and a
    random sample of normal synthetic providers must not be.

Innocent readings (see CARE.md): a new practice, a provider who moved or
changed their NPI, a provider who joined from another state, a first year
with enough patients to leave suppression, a newly covered service.
"""
from .common import has_table, history_columns, prior_tables

MIN_PAID = 250_000


def run(con, min_paid=MIN_PAID):
    pp = prior_tables(con)
    if not pp or not has_table(con, "csprev"):
        raise RuntimeError("test B needs the year before the target year; run build.py with that year's file in the data folder")
    df = con.execute(f"""
        select 'B' test, pr.*
        from pr join csprev using(code)
        where pr.paid >= {float(min_paid)}
          and not exists (select 1 from {pp[0]} h where h.npi = pr.npi and h.code = pr.code)
        order by pr.paid desc""").fetchdf()
    return history_columns(con, df)
