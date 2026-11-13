#!/usr/bin/env python3
"""Submit an Overture Places CSV export to Everguide's automated pipeline.

Run from the project root after Everguide is running:
  python google_analysis/import_overture_to_everguide.py --input google_analysis/overture_candidates.csv --release 2026-10-15
"""
from __future__ import annotations
import argparse
import csv
import json
import urllib.error
import urllib.request
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="google_analysis/overture_candidates.csv")
    parser.add_argument("--api", default="http://localhost:8000/api/v1/overture/imports")
    parser.add_argument("--release", default=None, help="Overture release/dataset version label")
    args = parser.parse_args()
    with Path(args.input).open(encoding="utf-8-sig", newline="") as handle:
        records = list(csv.DictReader(handle))
    for row in records:
        for key in ("sources_json", "addresses_json", "phones_json", "websites_json"):
            if row.get(key):
                try:
                    row[key] = json.loads(row[key])
                except json.JSONDecodeError:
                    pass
    body = json.dumps({"records": records, "source_release": args.release}, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(args.api, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Everguide API returned HTTP {exc.code}: {detail}")


if __name__ == "__main__":
    main()
