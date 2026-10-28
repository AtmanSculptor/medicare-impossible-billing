"""Test A: services per patient far above the code's national norm.

Logic
    For a code that normally happens about once per patient per year (an
    MRI, a colonoscopy, an EEG), the national median of services per patient is
    about 1. A provider who bills the same patients for the same code many
    times over is doing something the rest of the country is not. That can
    matter even on ordinary, allowed codes, not only on odd ones.

    For each code with 200+ individual billers, compute the national median and
    99th percentile of (services / patients) across providers.

Threshold (all four must hold)
    code median of services per patient  <= 1.15   (a once-per-patient code)
    provider services per patient        >= 5 x the code median
    provider services per patient        >= the code's 99th percentile
    provider paid for the code           >= $100,000   (small amounts are noise)

Control
    The planted impossible provider (tests/controls.py) must be flagged, and a
    random sample of normal synthetic providers must not be.

Innocent readings (see CARE.md): codes billed per session or per body part
(several services per patient is the rule, not the exception), serial
treatments, a clinic billing under one NPI, a patient count that was
suppressed or rounded, or a mislabeled specialty.
"""

MAX_CODE_MEDIAN = 1.15
MIN_MULTIPLE = 5
MIN_PAID = 100_000


def run(con, min_paid=MIN_PAID):
    return con.execute(f"""
        select 'A' test, pr.*, round(cs.med, 2) med, round(cs.p99, 2) p99,
               round(pr.srv/pr.benes, 1) per_patient, round(pr.srv/pr.benes/cs.med, 1) ratio
        from pr join cs using(code)
        where cs.med <= {MAX_CODE_MEDIAN} and pr.benes > 0
          and pr.srv/pr.benes >= {MIN_MULTIPLE}*cs.med and pr.srv/pr.benes >= cs.p99
          and pr.paid >= {float(min_paid)}
        order by pr.paid desc""").fetchdf()


def eligible(con):
    """Provider-code pairs the test could have flagged (denominator for sanity checks)."""
    return con.execute(f"select count(*) from pr join cs using(code) where cs.med <= {MAX_CODE_MEDIAN}").fetchall()[0][0]
