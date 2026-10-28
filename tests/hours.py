"""Test H: minimum hours of timed services per provider-year.

Logic
    Some billing codes are defined by time. Psychotherapy 90837 means at least 53
    minutes face to face; a 15-minute physical therapy unit means at least 8
    minutes. Multiply each timed code's services by the least time the code
    allows, add them up per provider, and you have a floor on the hours that
    provider must have spent. The floor is conservative: real sessions run
    longer, and Medicare is only part of any provider's patients. A floor
    above 8,760 hours (24 hours a day, 365 days) cannot be one person working.

    E/M visit codes are left out on purpose: they can be billed on the
    complexity of decision making instead of time, so time is not a floor.

Threshold
    hours >= 2,500   "high": more than 48 hours a week of Medicare timed work
                     for 52 weeks, every week of the year. Worth a look.
    hours >  8,760   "impossible as one person": more hours than the year has.

Control
    The planted impossible provider (tests/controls.py) must be flagged "impossible".
    On the real file, the top psychotherapy biller of the year must exceed
    8,760 hours (see real_control). If the method misses it, the method is broken.

Innocent readings (see CARE.md): the NPI is a billing identity shared by many
clinicians (group practice, supervised trainees, incident-to billing), an
organization billing under an individual's number, or a data entry error.
"""
import pandas as pd

HIGH_HOURS = 2500
IMPOSSIBLE_HOURS = 8760

# Least minutes one service of the code can represent.
PSYCHOTHERAPY_MINUTES = {
    "90832": 16, "90834": 38, "90837": 53,      # individual psychotherapy (16-37, 38-52, 53+ minutes)
    "90833": 16, "90836": 38, "90838": 53,      # add-ons to an E/M visit, same time bands
    "90839": 60, "90840": 30,                   # crisis psychotherapy: first 60 minutes, each added 30
    "90846": 26, "90847": 26,                   # family psychotherapy, 50 minutes (midpoint rule)
}
OTHER_TIMED_MINUTES = {
    **{c: 8 for c in ("97110", "97112", "97116", "97140", "97530", "97535",
                      "97032", "97035", "97113", "97124")},   # 15-minute therapy units (8-minute rule)
    "99406": 3, "99407": 11,                    # tobacco cessation counseling, 3-10 and over 10 minutes
    "99497": 16, "99498": 16,                   # advance care planning, 30 minutes each (midpoint)
}
TIMED_MINUTES = {**PSYCHOTHERAPY_MINUTES, **OTHER_TIMED_MINUTES}


def _timed_frame(minutes):
    return pd.DataFrame({"code": list(minutes), "minutes": list(minutes.values())})


def run(con, min_hours=HIGH_HOURS):
    """One row per provider at or above min_hours, biggest first."""
    con.register("timed_df", _timed_frame(TIMED_MINUTES))
    df = con.execute(f"""
        select 'H' test, pr.npi, any_value(pr.name) name, any_value(pr.cred) cred, any_value(pr.typ) typ,
               any_value(pr.loc) loc, any_value(pr.st) st,
               arg_max(pr.code, pr.srv*t.minutes) code,
               sum(pr.srv) timed_srv, sum(pr.srv*t.minutes)/60.0 hours, sum(pr.paid) paid
        from pr join timed_df t using(code)
        group by pr.npi
        having sum(pr.srv*t.minutes)/60.0 >= {float(min_hours)}
        order by hours desc""").fetchdf()
    con.unregister("timed_df")
    df["tier"] = ["impossible" if h > IMPOSSIBLE_HOURS else "high" for h in df["hours"]]
    df["hours"] = df["hours"].round(0)
    return df


def real_control(con):
    """Data control: the top psychotherapy biller of the year exceeds 8,760 hours.

    Returns (ok, detail). True only when the largest psychotherapy-only floor in
    this database is above the number of hours in a year.
    """
    con.register("psy_df", _timed_frame(PSYCHOTHERAPY_MINUTES))
    top = con.execute("""select max(h) from (select sum(pr.srv*t.minutes)/60.0 h
                         from pr join psy_df t using(code) group by pr.npi)""").fetchone()[0]
    con.unregister("psy_df")
    if top is None:
        return False, "no psychotherapy rows in this database"
    return top > IMPOSSIBLE_HOURS, f"top psychotherapy biller: {top:,.0f} floor hours (needs > {IMPOSSIBLE_HOURS:,})"
