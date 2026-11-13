#!/usr/bin/env python3
"""Assess Thurrock Overture records for evidence-led automatic approval.

Optional evidence JSON maps GERS IDs to independently verified first-party
website evidence. Without it, eligible candidates remain in enrichment; no
record is represented as approved. This tool never writes to Everguide's DB.
"""
from __future__ import annotations
import argparse, csv, json, sys
from collections import Counter
from pathlib import Path

API_APP_PATH = Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(API_APP_PATH))
from app.overture_approval import assess_overture_candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="google_analysis/overture_candidates.csv")
    parser.add_argument("--evidence", help="JSON object keyed by GERS ID containing first-party verification evidence")
    parser.add_argument("--out", default="google_analysis/overture_auto_approval_assessment")
    parser.add_argument("--boundary-confirmed-ids", help="Optional text file of GERS IDs independently confirmed inside the official Thurrock boundary")
    args = parser.parse_args()
    rows = list(csv.DictReader(Path(args.input).open(encoding="utf-8-sig", newline="")))
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8")) if args.evidence else {}
    boundary_ids = set(Path(args.boundary_confirmed_ids).read_text(encoding="utf-8").splitlines()) if args.boundary_confirmed_ids else set()
    assessed = []
    for row in rows:
        result = assess_overture_candidate(
            row,
            first_party_evidence=evidence.get(row.get("gers_id", "")),
            point_in_thurrock=True if row.get("gers_id") in boundary_ids else None,
            duplicate_conflict=str(row.get("possible_duplicate", "")).lower() in {"true", "1", "yes"},
        )
        assessed.append(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(assessed[0]) if assessed else [])
        writer.writeheader(); writer.writerows(assessed)
    counts = Counter(item["outcome"] for item in assessed)
    summary = {
        "records_assessed": len(assessed),
        "outcome_counts": dict(counts),
        "auto_approval_requires_independent_first_party_verification": True,
        "overture_confidence_used_as_approval_proof": False,
        "database_modified": False,
        "note": "Assessment only. The production publication workflow must persist source observations and audit events before publishing eligible records.",
    }
    out.with_suffix(".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

if __name__ == "__main__": main()
