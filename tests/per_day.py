"""Test C: ten or more services per patient on a single day, on an E/M or psychiatry code.

Logic
    The CMS file reports, for each provider and code, how many services were
    billed (Tot_Srvcs) and how many distinct patient-days they fell on
    (Tot_Bene_Day_Srvcs). Services divided by patient-days is how many of that
    service one patient received on one day. For an office or facility visit
    or a psychotherapy session that number is normally 1, so a value of 10
    means ten of the same visit for the same patient on the same day, which
    is far outside the norm and worth a question.

Threshold
    services / patient-days >= 10, on an E/M code (99202 to 99499) or a
    psychiatry code (90785 to 90899), and paid >= $100,000.
    Other codes can legitimately repeat on a day (lab panels, units of a
    drug, supplies), so they are outside this test. So are the per-unit
    add-on codes, which are billed once per extra block of time and so
    repeat on one day by design: 99292 (critical care, each added 30
    minutes), 99417 and 99418 (prolonged visit, each 15 minutes), 99358 and
    99359 (prolonged non-face-to-face service), 90833, 90836 and 90838
    (psychotherapy add-ons to a visit) and 90840 (crisis, each added 30
    minutes). Code 90868 (accelerated TMS) stays in the test, but a
    protocol of about ten sessions a day sits right at the threshold; see
    the innocent readings in CARE.md.

Control
    The planted impossible provider (tests/controls.py) must be flagged, and a
    random sample of normal synthetic providers must not be.

Innocent readings (see CARE.md): a unit-of-time or unit-of-measure convention
for that code, accelerated transcranial magnetic stimulation (90868) protocols
that give about ten sessions a day, a facility billing many residents under
one clinician number on a census day, an add-on code missing from the list
above, or a data entry error in the patient-day count.
"""

MIN_PER_DAY = 10
MIN_PAID = 100_000

# Per-unit add-on codes: each unit is one more block of time, so many per patient-day is normal.
ADDON_CODES = ("99292", "99417", "99418", "99358", "99359", "90840", "90833", "90836", "90838")

# try_cast gives NULL for HCPCS codes with letters, which makes the comparison false.
EM_OR_PSYCH_SQL = """(length(code) = 5 and (try_cast(code as int) between 99202 and 99499
                      or try_cast(code as int) between 90785 and 90899))"""


def run(con, min_paid=MIN_PAID):
    return con.execute(f"""
        select 'C' test, pr.*, round(pr.srv/pr.bdays, 1) per_day
        from pr
        where pr.bdays > 0 and pr.srv/pr.bdays >= {MIN_PER_DAY} and pr.paid >= {float(min_paid)}
          and {EM_OR_PSYCH_SQL.replace('code', 'pr.code')}
          and pr.code not in ({", ".join(repr(c) for c in ADDON_CODES)})
        order by pr.paid desc""").fetchdf()
