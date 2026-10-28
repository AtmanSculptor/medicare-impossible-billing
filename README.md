# medicare-impossible-billing

An open, runnable method for finding rows in the public Medicare "by Provider and
Service" file that cannot be one person doing ordinary work: more hours of
timed therapy than a year has, the same once-per-patient service billed dozens of
times per patient, large payments that appear from nothing, and ten visits for one
patient on one day. It downloads the public CMS files, builds a DuckDB database,
runs four tests with built-in controls, and writes a report. Anyone can rerun it
and check the counts without trusting us.

**A flag is a question, not an accusation.** Most flags have an innocent reading
(a shared billing number, supervised staff, a new practice, a data error). Read
[CARE.md](CARE.md) before you name anyone. The report hides NPIs by default for
that reason.

## Quick start

You need Python 3 and about 12 GB of free disk for three years of data. To try
the method first on a small synthetic sample, with no download, see the last
section.

```
pip install -r requirements.txt
python download.py --year 2024 2023 2022
python build.py
python report.py
python -m pytest
```

1. `download.py` resolves the file URLs from the public data.cms.gov catalog, resumes if
   interrupted, and records a SHA-256 for each file. `--dry-run` prints the URL and downloads nothing.
2. `build.py` loads the CSVs into `data/cms.duckdb`. About 3 to 5 minutes.
3. `report.py` runs the controls, then the tests, and writes `out/report.md` (and `out/report_flags.csv`).
   It stops if a control fails.
4. `python -m pytest` runs the controls on the shipped synthetic sample: the tests must find a
   planted impossible provider and must not flag normal ones.

## The four tests

Each test is one module in `tests/` with its logic, threshold and control in the docstring.

| Test | Logic | Threshold | Control it must find |
|---|---|---|---|
| **H**, `hours.py` | Add up the least time the timed codes allow (psychotherapy 90837 is at least 53 minutes; a 15-minute therapy unit is at least 8) | 2,500 floor hours is "high"; over 8,760 is more hours than a year has | The top psychotherapy biller of the year exceeds 8,760 hours |
| **A**, `rate.py` | Services per patient against the code's national median and 99th percentile, for codes meant to happen about once per patient | 5 times the code median and at or above p99, paid $100,000 or more, code median 1.15 or less | The planted provider is found |
| **B**, `from_nothing.py` | A provider-code pair paid a lot this year with no row at all the year before, only for established codes (200+ billers the year before) | Paid $250,000 or more | The planted provider is found |
| **C**, `per_day.py` | Services divided by patient-days on E/M and psychiatry codes | 10 or more per patient-day, paid $100,000 or more | The planted provider is found |

Only individual providers (entity code I) are tested, and drug rows are removed. Organizations
bill for many clinicians, so they are left out. The thresholds are in the module files; change
them there and the controls tell you whether the method still works.

### Controls

A test that has never been shown to find anything is not a test. `tests/controls.py` puts one
synthetic impossible provider into the data and asserts every test finds it, checks that a random
sample of normal synthetic providers is not flagged (the null), checks that organization and drug
rows are ignored, and checks that rows just under each threshold pass. `report.py` runs the same
planted-row check on your real database before it writes anything.

### Known families

Some code families already have a large public explanation (skin substitutes, catheter supplies)
or are driven by drug price, not volume. Those rows stay in the report but are tagged and listed
last. A tag is not a dismissal.

## The care rule

Before anything is named: check the two prior years, rule out the innocent readings, look the
person up with the state license board (not NPPES), search the exclusion list, dockets and
enforcement news, find a second independent source, and have someone who did not write it try to
break it. **Nothing is published without a second source.** The full checklist is in [CARE.md](CARE.md).

## What we found on the public 2024 file

Counts only. No names, no NPIs. Measured on the CMS 2024 file (9,781,673 rows) with the 2023 and 2022
files for history, using the SHA-256 values recorded in `download.py`.

| | Count |
|---|---|
| Individual provider-code rows tested (non-drug) | 8,555,098 |
| Providers with 2,500 or more floor hours of timed services | 155 |
| of which over 8,760 hours (more hours than a year has) | 4 |
| Providers with 2,500 or more hours on psychotherapy codes alone | 28 |
| Test A, rate: provider-code pairs flagged | 226 |
| Test B, from nothing: provider-code pairs flagged | 310 |
| Test C, per day: provider-code pairs flagged | 2 |
| Rows in A, B and C tagged as a known family | 36 (all in B) |

Test C is narrow on purpose: it looks only at E/M and psychiatry codes, where one service per patient per day is the rule. These are questions, not findings. Each row still has to go through [CARE.md](CARE.md). Counts
reproduce within 1 percent if you use the same files; CMS republishes years from time to time, so
a different file version can move them.

## Data sources

- Medicare Physician & Other Practitioners, by Provider and Service (CMS):
  https://data.cms.gov/provider-summary-by-type-of-service/medicare-physician-other-practitioners/medicare-physician-other-practitioners-by-provider-and-service
- The catalog the downloader reads: https://data.cms.gov/data.json
- Years used: 2024, with 2023 and 2022 for history. Fallback URLs for these three are in `download.py`.

The file is Medicare Part B fee-for-service. It does not include Medicare Advantage, Medicaid or
private insurance, and it hides rows with fewer than 11 patients.

## Try it without downloading anything

```
python build.py --data-dir tests/sample --db out/sample.duckdb
python report.py --db out/sample.duckdb
```

`tests/sample/` holds 50,000 synthetic rows made by `tests/make_sample.py`: invented providers
whose NPIs all start with 0 (no real NPI does), invented names and cities, and one planted
impossible provider.

## Extending

A new test is one module in `tests/` with `run(con)` returning a DataFrame, a docstring that states
logic, threshold and control, and a line in `tests/planted.py` so the planted provider has to trip it.
Hospice, Part D, ownership and reassignment joins are not in v1.

## How to cite

Rafferty, B. (2026). *medicare-impossible-billing: an open method for finding impossible billing in
the public Medicare provider-and-service file.* https://github.com/AtmanSculptor/medicare-impossible-billing

## Built by

This is Brent Rafferty's work and story, told with BT, an AI agent running on Claude.
BT's memory lives on Brent's own server.

## License

MIT, see [LICENSE](LICENSE).
