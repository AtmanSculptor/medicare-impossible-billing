# CARE: read this before you name anyone

**A flag is a question, not an accusation.**

This repo finds rows in a public file that are unusual. Unusual is not wrong.
Most of what it flags has an ordinary explanation, and a person's name attached
to a wrong guess does real harm that a correction never fully undoes. Nothing
here is a finding until a human has done the work below and a second, independent
source agrees.

## Start with the innocent readings

Before you look at who a row is, say out loud how it could be fine. For almost
every flag, one of these is the answer.

**For all four tests**
- The NPI is a billing identity, not one person. A group, a clinic or a hospital
  department can bill under one clinician's number. Medicare shows the number,
  not the five people who used it.
- Supervised staff. Trainees, assistants and other clinicians may bill under a
  supervising provider (incident-to and similar rules). Their hours are the
  supervisor's hours in this file.
- The provider is real and busy: several locations, a large employer, a
  facility contract. The file adds locations up.
- A data error: a typo in the service count, a unit-of-measure mix-up, a wrong
  NPI on a claim. These are in the file because the file is built from claims.
- A rule change or a new code in the year. Prices and definitions move.
- The provider is a different kind of entity than the file says (an entity
  coded as an individual that is really an organization).

**Test H, floor hours**
- One NPI shared by a practice of many therapists.
- Group sessions or add-on codes billed under rules the minimum-time table
  does not model. The floors use the least time each code allows (for
  example 30 minutes for 90839, which CPT reports for 30 to 74), but the
  table is a judgment and can be wrong for a code. Check it against the
  current CPT definition.
- A supervising psychologist or physician billing for the work of several
  clinicians.

**Test A, services per patient**
- The code is billed per unit, per session or per body part, so many per
  patient is normal for that practice (a serial treatment, a course of
  injections).
- A patient count that Medicare rounded or suppressed.
- A small, genuinely sick population (dialysis, wound care, long courses).

**Test B, paid from nothing**
- The provider is new, moved, changed NPI, or joined from another state.
- Last year's row was suppressed because it had fewer than 11 patients.
- A newly covered or newly popular service.

**Test C, services per patient-day**
- Accelerated transcranial magnetic stimulation (90868). Some protocols give
  about ten sessions a day, which lands right on the threshold.
- Per-unit add-on codes, billed once per extra block of time, so many per
  patient-day is how they work: 99292 (critical care, each added 30 minutes),
  99417 and 99418 (prolonged visit), 99358 and 99359 (prolonged
  non-face-to-face service), 90833, 90836 and 90838 (psychotherapy add-ons) and
  90840 (crisis, each added 30 minutes). Test C leaves these out, but a code
  missing from that list can still look like this.
- A day-of-service convention for that code, or a facility census day.
- A typo in the patient-day count.

## The checklist

Work down it in order. Stop and drop the row the moment an innocent reading
holds up. Keep a note of what you checked and what you found, including the
checks that came back clean.

1. **Read the row cold.** Find the exact row in the raw CMS file yourself. Do
   the numbers in the report match? Does the arithmetic (services, patients,
   patient-days, payment) agree with itself?
2. **Check the prior two years.** Build the earlier years (`python build.py`
   with the files for the two years before). Is this a one-year spike or a
   pattern? A pattern that has run for three years is a different question from a
   first-year jump. Look at the neighboring codes too.
3. **Rule out the innocent readings above.** For each one that applies, find
   the fact that rules it out. "I could not think of an innocent reading" is
   not a fact.
4. **License board, not NPPES.** Look the person up with their state licensing
   board. NPPES is filled in by the provider and is often stale or wrong. The
   board tells you the license type, status and any discipline.
5. **LEIE.** Search the HHS-OIG List of Excluded Individuals/Entities
   (https://oig.hhs.gov/exclusions/). An excluded provider billing Medicare is a
   different story from a licensed one. Also check SAM.gov exclusions.
6. **Dockets.** Search court records for the person and any practice name:
   federal (PACER), state courts, and unsealed qui tam filings. A case may
   already exist, or may have already ended in the provider's favor.
7. **Enforcement news.** Search the Department of Justice, HHS-OIG, the state
   attorney general and the news. If the pattern is already public, you are
   not the first, and what is public may answer your question.
8. **A second independent source.** Something that does not come from the
   same Medicare file: a state record, a facility record, a licensing action,
   a court filing, a witness who was there. Two readings of one file are one
   source. **Nothing is published or sent without a second source.**
9. **A Skeptic read.** Hand the whole write-up, the data and your notes to
   someone who did not write it and whose job is to break it. Ask what is wrong,
   what is missing, and whether a real person could be misidentified. Fix what
   they find. Do not proceed without a clear answer from them.
10. **Right of reply, if you publish.** Give the person or practice a fair chance
    to respond, in time to matter, and print what they say.

## If it holds up

If every check above is done and the pattern still stands, you have a lead, not
a conviction. The right next step is to report it to the people whose job it is:

- HHS-OIG Hotline: https://oig.hhs.gov/fraud/report-fraud/ or 1-800-HHS-TIPS (1-800-447-8477)
- A lawyer who handles False Claims Act (qui tam) cases, if you may have
  relevant first-hand knowledge
- The state Medicaid Fraud Control Unit, for patterns that also touch Medicaid

Do not post names, NPIs or screenshots of rows. Do not contact the provider
yourself. Do not call it fraud: say what the file shows and what it does not.

## What this file cannot tell you

- It is Medicare Part B fee-for-service. Medicare Advantage, Medicaid and
  private insurance are not in it, so a provider's true workload is larger than
  what you see. That makes the floor-hours test conservative, and it also means
  you cannot see a provider's whole practice.
- It reports payments, not what happened to a patient.
- Rows with fewer than 11 patients are not shown, so absence is not proof of
  no billing.
- It tells you nothing about intent. Impossible numbers can come from carelessness,
  from billing software, from someone else using a number, and from fraud. Only
  an investigation can tell them apart.

## What the default report hides, and what it does not

`report.py` leaves the NPI column empty, drops the city, rounds paid amounts to
the nearest $10,000, and never writes a provider's name. Use `--show-npi` to
turn the first three off.

Be clear about what that buys. Blanking the NPI stops casual forwarding: nobody
can paste a row into an email and have it name someone. It does **not** stop
re-identification. Every row still carries a state, a specialty, a code and
exact service and patient counts, and those can be matched back to the public
CMS file, which holds the NPI and name, in one lookup. Treat the default report
as sensitive. Do not post it, and do not forward it without this file. The
counts in the README are safe to share because they carry no attributes; rows
are not.
