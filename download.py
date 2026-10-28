#!/usr/bin/env python3
"""Download the CMS "Medicare Physician & Other Practitioners - by Provider and Service" files.

The file URLs change every time CMS republishes, so they are resolved at run time
from the public catalog at https://data.cms.gov/data.json. If the catalog cannot
be read, or does not list a year, the URLs that were current when this repo was
written (2022 to 2024) are used as a fallback.

Each year is saved as <data-dir>/dYY.csv (for example data/d24.csv). Each file is
about 3 GB, so the download resumes: a partial file is kept as dYY.csv.part and
the next run continues from where it stopped. When a file is complete its SHA-256
is recorded in <data-dir>/SHA256SUMS and checked on every later run.

Examples:
    python download.py --year 2024 --dry-run      # print the URL, download nothing
    python download.py --year 2024 2023 2022      # download three years
    python download.py --year 2024 --verify       # re-check files already on disk
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

CATALOG_URL = "https://data.cms.gov/data.json"
DATASET_TITLE = "Medicare Physician & Other Practitioners - by Provider and Service"
USER_AGENT = "Mozilla/5.0 (compatible; medicare-impossible-billing/0.1)"

# URLs that were current when this repo was written. Used only when the catalog
# is unreachable or does not list the year.
FALLBACK_URLS = {
    2024: "https://data.cms.gov/sites/default/files/2026-05/b5ebab5a-f490-418a-9bce-4b9f31419356/PHY_R26_P05_V10_D24_Prov_Svc.csv",
    2023: "https://data.cms.gov/sites/default/files/2025-04/e3f823f8-db5b-4cc7-ba04-e7ae92b99757/MUP_PHY_R25_P05_V20_D23_Prov_Svc.csv",
    2022: "https://data.cms.gov/sites/default/files/2025-11/53fb2bae-4913-48dc-a6d4-d8c025906567/MUP_PHY_R25_P05_V20_D22_Prov_Svc.csv",
}

# SHA-256 of the files the README counts were measured on. CMS can republish a
# year with corrections; a mismatch is a warning, not an error, unless --strict.
REFERENCE_SHA256 = {
    2022: "915eef8d6f099af5c5f0a91aa4931d184502d07c1e3dfbd275498cc7e485c5bc",
    2023: "c6766dda7c66c74682af892d9ed5f8a347248dc0f6be2bda8aee7eecc02a902b",
    2024: "509dc7ce4cd02d8dd160d50d33ce5d942cd120ea306ff1eb2b6ece4f59cb2c23",
}


def year_of(url):
    """Data year from a CMS file name such as ..._D24_Prov_Svc.csv, else None."""
    m = re.search(r"_D(\d{2})_Prov_Svc", url)
    return 2000 + int(m.group(1)) if m else None


def open_url(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def resolve_urls(no_resolve=False, catalog_url=CATALOG_URL):
    """Return ({year: url}, {year: 'catalog' or 'fallback'})."""
    urls, source = {}, {}
    if not no_resolve:
        try:
            with open_url(catalog_url, timeout=180) as r:
                catalog = json.load(r)
            for ds in catalog.get("dataset", []):
                # the catalog lists one dataset per year, titled "<name> : <release date>"
                title = ds.get("title", "")
                if title != DATASET_TITLE and not title.startswith(DATASET_TITLE + " :"):
                    continue
                for dist in ds.get("distribution", []):
                    u = dist.get("downloadURL") or ""
                    if dist.get("mediaType") == "text/csv" and year_of(u):
                        urls[year_of(u)] = u
                        source[year_of(u)] = "catalog"
        except (urllib.error.URLError, OSError, ValueError) as e:
            print(f"note: could not read {catalog_url} ({e}); using built-in fallback URLs", file=sys.stderr)
    for y, u in FALLBACK_URLS.items():
        if y not in urls:
            urls[y] = u
            source[y] = "fallback"
    return urls, source


def sha256_of(path, block=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(block)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def read_sums(data_dir):
    path = os.path.join(data_dir, "SHA256SUMS")
    sums = {}
    if os.path.exists(path):
        for line in open(path):
            parts = line.strip().split(None, 1)
            if len(parts) == 2:
                sums[parts[1].lstrip("*")] = parts[0]
    return sums


def write_sums(data_dir, sums):
    with open(os.path.join(data_dir, "SHA256SUMS"), "w") as f:
        for name in sorted(sums):
            f.write(f"{sums[name]}  {name}\n")


def remote_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            n = r.headers.get("Content-Length")
            return int(n) if n else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def fetch(url, dst, retries=5):
    """Download url to dst with resume. Returns when dst is complete."""
    part = dst + ".part"
    total = remote_size(url)
    for attempt in range(1, retries + 1):
        have = os.path.getsize(part) if os.path.exists(part) else 0
        if total and have == total:
            break
        headers = {"Range": f"bytes={have}-"} if have else {}
        t0 = time.time()
        try:
            with open_url(url, headers) as r:
                if have and r.status != 206:
                    print("server ignored the resume request; starting over")
                    have = 0
                mode = "ab" if have else "wb"
                with open(part, mode) as f:
                    got = 0
                    while True:
                        b = r.read(1 << 22)
                        if not b:
                            break
                        f.write(b)
                        got += len(b)
            print(f"  got {got // 1_000_000} MB in {int(time.time() - t0)} s")
        except urllib.error.HTTPError as e:
            if e.code == 416:  # range not satisfiable: part file is already complete or stale
                break
            print(f"  attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(min(30, 2 ** attempt))
            continue
        except (urllib.error.URLError, OSError) as e:
            print(f"  attempt {attempt} interrupted: {e}", file=sys.stderr)
            time.sleep(min(30, 2 ** attempt))
            continue
        if not total or os.path.getsize(part) == total:
            break
    size = os.path.getsize(part) if os.path.exists(part) else 0
    if total and size != total:
        raise RuntimeError(f"incomplete download: {size} of {total} bytes; run again to resume")
    os.replace(part, dst)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, nargs="+", default=[2024], help="data year(s), default 2024")
    ap.add_argument("--data-dir", default="data", help="where to save dYY.csv files (default data/)")
    ap.add_argument("--dry-run", action="store_true", help="print the resolved URL and do not download")
    ap.add_argument("--no-resolve", action="store_true", help="skip data.json and use the built-in URLs")
    ap.add_argument("--verify", action="store_true", help="only check files already on disk against SHA256SUMS")
    ap.add_argument("--force", action="store_true", help="download again even if the file is complete")
    ap.add_argument("--strict", action="store_true", help="fail if a checksum differs from the reference value")
    a = ap.parse_args(argv)

    urls, source = resolve_urls(a.no_resolve)
    for y in a.year:
        if y not in urls:
            print(f"{y}: no URL known. Known years: {sorted(urls)}", file=sys.stderr)
            return 2
    if a.dry_run:
        for y in a.year:
            print(f"{y}: {urls[y]}  [{source[y]}]")
        return 0

    os.makedirs(a.data_dir, exist_ok=True)
    sums = read_sums(a.data_dir)
    status = 0
    for y in a.year:
        name = f"d{y % 100:02d}.csv"
        dst = os.path.join(a.data_dir, name)
        print(f"{y}: {urls[y]}  [{source[y]}]")
        if a.verify:
            if not os.path.exists(dst):
                print(f"  {name} missing")
                status = 1
                continue
        elif os.path.exists(dst) and not a.force:
            size = remote_size(urls[y])
            if size is None or size == os.path.getsize(dst):
                print(f"  have {name}, skipping download (use --force to replace)")
            else:
                print(f"  {name} is {os.path.getsize(dst)} bytes but the server says {size}; downloading again")
                a.force = True
        if not a.verify and (a.force or not os.path.exists(dst)):
            fetch(urls[y], dst)
        digest = sha256_of(dst)
        if name in sums and sums[name] != digest:
            print(f"  CHECKSUM MISMATCH for {name}: recorded {sums[name][:16]}..., now {digest[:16]}...", file=sys.stderr)
            status = 1
        else:
            print(f"  sha256 {digest[:16]}... ok")
            sums[name] = digest
        ref = REFERENCE_SHA256.get(y)
        if ref and ref != digest:
            msg = f"  note: {name} differs from the file the README counts were measured on; CMS may have republished {y}"
            print(msg, file=sys.stderr)
            if a.strict:
                status = 1
        write_sums(a.data_dir, sums)
    return status


if __name__ == "__main__":
    sys.exit(main())
