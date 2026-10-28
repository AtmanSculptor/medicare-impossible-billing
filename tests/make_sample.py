#!/usr/bin/env python3
"""Generate the synthetic sample in tests/sample/.

Writes d24.csv.gz, d23.csv.gz and d22.csv.gz, 50,000 rows in total (24,000,
16,000 and 10,000), in the same 28-column layout as the CMS "by Provider and
Service" files. Everything is made up: NPIs all start with 0 (a real NPI never
does), names are invented syllables, cities are fictional. It is not a model
of Medicare, only of the shape the tests need.

The 2024 file holds:
  * about 5,000 ordinary providers whose numbers stay inside normal limits, so
    the null (no test flags anyone) can be checked;
  * a few hundred organization rows (entity code O) with absurd volumes, which
    every test must ignore because organizations bill for many clinicians;
  * one planted impossible individual provider, NPI 0999999991, built to be
    caught by all four tests.

Run it again to regenerate; the output is deterministic (fixed seed).

    python tests/make_sample.py
"""
import csv
import gzip
import io
import os
import random

SEED = 20261028
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "sample")
ROWS = {2024: 24000, 2023: 16000, 2022: 10000}   # 50,000 in all
N_PROVIDERS = 5200
N_ORG_ROWS = {2024: 300, 2023: 200, 2022: 120}

PLANTED_NPI = "0999999991"
ORG_PREFIX = "0888"

COLUMNS = ["Rndrng_NPI", "Rndrng_Prvdr_Last_Org_Name", "Rndrng_Prvdr_First_Name", "Rndrng_Prvdr_MI",
           "Rndrng_Prvdr_Crdntls", "Rndrng_Prvdr_Ent_Cd", "Rndrng_Prvdr_St1", "Rndrng_Prvdr_St2",
           "Rndrng_Prvdr_City", "Rndrng_Prvdr_State_Abrvtn", "Rndrng_Prvdr_State_FIPS", "Rndrng_Prvdr_Zip5",
           "Rndrng_Prvdr_RUCA", "Rndrng_Prvdr_RUCA_Desc", "Rndrng_Prvdr_Cntry", "Rndrng_Prvdr_Type",
           "Rndrng_Prvdr_Mdcr_Prtcptg_Ind", "HCPCS_Cd", "HCPCS_Desc", "HCPCS_Drug_Ind", "Place_Of_Srvc",
           "Tot_Benes", "Tot_Srvcs", "Tot_Bene_Day_Srvcs", "Avg_Sbmtd_Chrg", "Avg_Mdcr_Alowd_Amt",
           "Avg_Mdcr_Pymt_Amt", "Avg_Mdcr_Stdzd_Amt"]

# code: (description, kind, average payment, place of service)
CODES = {
    # visits: services per patient 1 to 4, one service per patient-day
    "99213": ("Office visit, established patient, low", "visit", 68, "O"),
    "99214": ("Office visit, established patient, moderate", "visit", 100, "O"),
    "99215": ("Office visit, established patient, high", "visit", 135, "O"),
    "99203": ("Office visit, new patient, low", "visit", 90, "O"),
    "99204": ("Office visit, new patient, moderate", "visit", 135, "O"),
    "99232": ("Hospital follow-up visit, moderate", "visit", 75, "F"),
    "99233": ("Hospital follow-up visit, high", "visit", 110, "F"),
    "99306": ("Nursing facility admission, high", "visit", 110, "F"),
    "99307": ("Nursing facility visit, straightforward", "visit", 45, "F"),
    "99308": ("Nursing facility visit, low", "visit", 70, "F"),
    "99309": ("Nursing facility visit, moderate", "visit", 90, "F"),
    # once per patient: services per patient about 1
    "93000": ("Electrocardiogram, tracing and report", "once", 17, "O"),
    "71046": ("Chest x-ray, two views", "once", 25, "O"),
    "93306": ("Echocardiogram, complete", "once", 80, "O"),
    "70553": ("MRI brain with and without contrast", "once", 190, "O"),
    "72148": ("MRI lumbar spine without contrast", "once", 190, "O"),
    "77067": ("Screening mammogram, both breasts", "once", 100, "O"),
    "45378": ("Colonoscopy, diagnostic", "once", 230, "O"),
    "78452": ("Nuclear heart scan, multiple studies", "once", 400, "O"),
    "36415": ("Blood draw by venipuncture", "once", 3, "O"),
    # psychiatry and psychotherapy
    "90791": ("Psychiatric diagnostic evaluation", "once", 150, "O"),
    "90832": ("Psychotherapy, 30 minutes", "psych", 75, "O"),
    "90834": ("Psychotherapy, 45 minutes", "psych", 100, "O"),
    "90837": ("Psychotherapy, 60 minutes", "psych", 125, "O"),
    # timed therapy units
    "97110": ("Therapeutic exercise, each 15 minutes", "pt", 28, "O"),
    "97112": ("Neuromuscular re-education, each 15 minutes", "pt", 30, "O"),
    "97140": ("Manual therapy, each 15 minutes", "pt", 27, "O"),
    "97530": ("Therapeutic activities, each 15 minutes", "pt", 34, "O"),
    # a drug row: removed from pr by the drug indicator
    "J3301": ("Injection, steroid, 10 mg", "drug", 3, "O"),
}
PROFILES = {   # profile: (share, always, sometimes)
    "primary": (0.38, ["99213", "99214"], ["99215", "99203", "99204", "93000", "71046", "36415", "J3301"]),
    "facility": (0.20, ["99232", "99308"], ["99233", "99306", "99307", "99309", "99214"]),
    "behavior": (0.15, ["90834", "90837"], ["90791", "90832", "99213"]),
    "therapy": (0.10, ["97110", "97140"], ["97112", "97530"]),
    "imaging": (0.17, ["93306", "70553"], ["72148", "77067", "45378", "78452", "93000", "71046"]),
}
CRED = {"primary": ["MD", "DO", "NP"], "facility": ["MD", "NP", "PA"], "behavior": ["PhD", "LCSW", "MD"],
        "therapy": ["PT", "OTR"], "imaging": ["MD", "DO"]}
TYPE = {"primary": "Family Practice", "facility": "Internal Medicine", "behavior": "Clinical Psychologist",
        "therapy": "Physical Therapist", "imaging": "Diagnostic Radiology"}
STATES = ["AL", "AZ", "CA", "CO", "FL", "GA", "IL", "KY", "MI", "NY", "OH", "TX", "WA"]
CITIES = ["Mockford", "Sampleton", "Fakeburg", "Testville", "Placeholder Falls", "Exampleport", "Dummyridge"]
SYL1 = ["Bren", "Quel", "Tam", "Vor", "Zan", "Hesk", "Drum", "Pell", "Yorv", "Kest", "Mor", "Fisk", "Lund", "Garn", "Wex"]
SYL2 = ["volt", "mar", "squith", "lex", "dorn", "ik", "wick", "tran", "bury", "nox", "ley", "ford", "sen", "vane"]
FIRST = ["Alvin", "Brinda", "Corwen", "Dessa", "Elrick", "Fenna", "Gorvan", "Hettie", "Ivor", "Jessa", "Kolten", "Lirra",
         "Marek", "Nessa", "Orlin", "Pavla", "Quint", "Rolva", "Sander", "Telya"]


def money(x):
    return f"{x:.6f}"


def make_row(npi, last, first, cred, ent, typ, city, st, code, pos, benes, srv, bdays, pay, desc=None, drug="N"):
    d = desc or CODES.get(code, ("Synthetic service", "", 0, ""))[0]
    return [npi, last, first, "", cred, ent, "", "", city, st, "00", "00000", "1", "Metropolitan",
            "US", typ, "Y", code, d, drug, pos, int(benes), int(srv), int(bdays),
            money(pay * 3), money(pay * 1.25), money(pay), money(pay * 1.02)]


def code_numbers(rng, kind, pay):
    """benes, services, patient-days, avg payment for one ordinary provider-code pair."""
    pay = pay * rng.uniform(0.9, 1.1)
    if kind == "once":
        benes = rng.randint(11, 140)
        ratio = 1.0 if rng.random() < 0.75 else rng.uniform(1.05, 1.4)
        srv = round(benes * ratio)
        return benes, srv, srv, pay
    if kind == "visit":
        benes = rng.randint(11, 350)
        srv = round(benes * rng.uniform(1.0, 4.0))
        return benes, srv, round(srv / rng.uniform(1.0, 1.3)), pay
    if kind == "psych":
        benes = rng.randint(11, 80)
        srv = round(benes * rng.uniform(2.0, 12.0))
        return benes, srv, round(srv / rng.uniform(1.0, 1.1)), pay
    if kind == "pt":
        benes = rng.randint(11, 70)
        srv = round(benes * rng.uniform(4.0, 25.0))
        return benes, srv, round(srv / rng.uniform(1.0, 1.1)), pay
    benes = rng.randint(11, 60)   # drug
    srv = round(benes * rng.uniform(1.0, 3.0))
    return benes, srv, srv, pay


def providers(rng):
    out = []
    shares = [(k, v[0]) for k, v in PROFILES.items()]
    for i in range(N_PROVIDERS):
        prof = rng.choices([k for k, _ in shares], [s for _, s in shares])[0]
        _, always, sometimes = PROFILES[prof]
        codes = list(always) + [c for c in sometimes if rng.random() < 0.55]
        out.append({
            "npi": f"0{1000 + i:09d}", "prof": prof, "codes": codes,
            "last": rng.choice(SYL1) + rng.choice(SYL2), "first": rng.choice(FIRST),
            "cred": rng.choice(CRED[prof]), "typ": TYPE[prof], "city": rng.choice(CITIES),
            "st": rng.choice(STATES), "entry": rng.choices([2022, 2023, 2024], [0.40, 0.30, 0.30])[0],
        })
    return out


def ordinary_rows(rng, prov, year):
    rows = []
    for code in prov["codes"]:
        desc, kind, pay, pos = CODES[code]
        benes, srv, bdays, p = code_numbers(rng, kind, pay)
        drug = "Y" if kind == "drug" else "N"
        args = (prov["npi"], prov["last"], prov["first"], prov["cred"], "I", prov["typ"], prov["city"], prov["st"], code)
        if rng.random() < 0.08 and benes >= 24:   # some pairs bill in two places of service
            half = benes // 2
            rows.append(make_row(*args, "O" if pos == "F" else "F", half, srv // 2, bdays // 2, p, drug=drug))
            rows.append(make_row(*args, pos, benes - half, srv - srv // 2, bdays - bdays // 2, p, drug=drug))
        else:
            rows.append(make_row(*args, pos, benes, srv, bdays, p, drug=drug))
    return rows


def org_rows(rng, n, year):
    """Organizations (entity code O) with absurd volumes. Every test must ignore them."""
    rows = []
    for i in range(n):
        npi = f"{ORG_PREFIX}{i // 6:06d}"
        code = ["90837", "99308", "93000", "97110", "99214", "99306"][i % 6]
        desc, kind, pay, pos = CODES[code]
        benes = rng.randint(2000, 9000)
        srv = benes * rng.randint(12, 30)
        rows.append(make_row(npi, f"Sampleton Therapy Group {i // 6}", "", "", "O", "Clinic or Group Practice",
                             "Sampleton", "AZ", code, pos, benes, srv, round(srv / 12), pay))
    return rows


def planted_rows():
    """One synthetic individual provider that every test must catch (2024 only)."""
    a = (PLANTED_NPI, "Vantrip", "Zyxwell", "MD", "I", "Internal Medicine", "Mockford", "XX")
    return [
        # H: 12,000 sessions x at least 53 minutes = 10,600 hours, more than a year has
        make_row(*a, "90837", "O", 300, 12000, 12000, 125.0),
        # A: an ECG, normally once per patient, billed 90 times per patient
        make_row(*a, "93000", "O", 100, 9000, 9000, 17.0),
        # B: $300,000 on an established code with no row the year before
        make_row(*a, "99214", "O", 150, 3000, 3000, 100.0),
        # C: 12 nursing facility visits per patient per day
        make_row(*a, "99308", "F", 200, 3000, 250, 70.0),
    ]


def build_year(rng, year, provs):
    n_org = N_ORG_ROWS[year]
    base = []
    for p in provs:
        if p["entry"] <= year:
            base.extend(ordinary_rows(rng, p, year))
    extra = 4 if year == 2024 else 0   # planted rows
    target = ROWS[year] - n_org - extra
    if len(base) < target:
        raise SystemExit(f"{year}: only {len(base)} base rows, need {target}; raise N_PROVIDERS")
    drop = set(rng.sample(range(len(base)), len(base) - target))
    rows = [r for i, r in enumerate(base) if i not in drop]
    rows += org_rows(rng, n_org, year)
    if year == 2024:
        rows += planted_rows()
    rows.sort(key=lambda r: (r[0], r[17], r[20]))
    assert len(rows) == ROWS[year], (year, len(rows))
    return rows


def write_gz(path, rows):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    w.writerows(rows)
    with open(path, "wb") as raw:   # mtime=0 keeps the bytes identical on every run
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=9) as gz:
            gz.write(buf.getvalue().encode())


def main():
    rng = random.Random(SEED)
    provs = providers(rng)
    os.makedirs(OUT_DIR, exist_ok=True)
    total = 0
    for year in (2022, 2023, 2024):
        rows = build_year(random.Random(SEED + year), year, provs)
        path = os.path.join(OUT_DIR, f"d{year % 100:02d}.csv.gz")
        write_gz(path, rows)
        total += len(rows)
        print(f"{path}: {len(rows):,} rows, {os.path.getsize(path) // 1024} KB")
    print(f"total {total:,} rows")


if __name__ == "__main__":
    main()
