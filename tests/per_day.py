"""Test C: ten or more services per patient on a single day, on an E/M or psychiatry code.

Logic
    The CMS file reports, for each provider and code, how many services were
    billed (Tot_Srvcs) and how many distinct patient-days they fell on
    (Tot_Bene_Day_Srvcs). Services divided by patient-days is how many of that
    service one patient received on one day. For an office or facility visit
    or a psychotherapy session that number is 1. A value of 10 means ten
    visits for the same patient on the same day, which is not a thing that
    happens in care.

Threshold
    services / patient-days >= 10, on an E/M code (99202 to 99499) or a
    psychiatry code (90785 to 90899), and paid >= $100,000.
    Other codes can legitimately repeat on a day (lab panels, units of a
    drug, supplies), so they are outside this test.

Control
    The planted impossible provider (tests/controls.py) must be flagged, and a
    random sample of normal synthetic providers must not be.

Innocent readings (see CARE.md): a unit-of-time or unit-of-measure convention
for that code, a facility billing many residents under one clinician number
on a census day, prolonged-service add-ons, or a data entry error in the
patient-day count.
"""

MIN_PER_DAY = 10
MIN_PAID = 100_000

# try_cast gives NULL for HCPCS codes with letters, which makes the comparison false.
EM_OR_PSYCH_SQL = """(length(code) = 5 and (try_cast(code as int) between 99202 and 99499
                      or try_cast(code as int) between 90785 and 90899))"""


def run(con, min_paid=MIN_PAID):
    return con.execute(f"""
        select 'C' test, pr.*, round(pr.srv/pr.bdays, 1) per_day
        from pr
        where pr.bdays > 0 and pr.srv/pr.bdays >= {MIN_PER_DAY} and pr.paid >= {float(min_paid)}
          and {EM_OR_PSYCH_SQL.replace('code', 'pr.code')}
        order by pr.paid desc""").fetchdf()
