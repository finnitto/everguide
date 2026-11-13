"""Build human-review registers from the conservative candidate quality CSV.

This script only creates CSV review templates. It does not contact providers,
call third-party APIs, write to Everguide's database, or publish listings.
"""
from __future__ import annotations
import argparse, csv
from collections import OrderedDict
from pathlib import Path

DEFAULT_INPUT = Path(__file__).with_name("candidate_quality_review.csv")


def read_rows(path: Path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fields, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)


def build(input_path: Path, out_dir: Path):
    rows = read_rows(input_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = OrderedDict()
    for r in rows:
        if r.get("service_class") != "funeral_director_candidate":
            continue
        gid = r.get("provider_group_id") or "UNASSIGNED"
        groups.setdefault(gid, []).append(r)

    provider_fields = [
        "provider_group_id", "candidate_provider_name", "website_domain",
        "candidate_rows", "candidate_addresses", "initial_triage",
        "source_licence_status", "service_activity_status", "trading_status",
        "provider_identity_status", "official_website_status", "provider_decision",
        "decision_reason", "evidence_log_refs", "reviewer", "reviewed_at_utc", "review_notes"
    ]
    provider_rows = []
    for gid, items in groups.items():
        first = items[0]
        addresses = " | ".join(dict.fromkeys(filter(None, [
            ", ".join(filter(None, [x.get("address", ""), x.get("postcode", "")])) for x in items
        ])))
        flags = sorted({flag for x in items for flag in (x.get("location_flags") or "").split(";") if flag})
        decisions = sorted({x.get("review_decision", "") for x in items})
        provider_rows.append({
            "provider_group_id": gid,
            "candidate_provider_name": first.get("candidate_name", ""),
            "website_domain": first.get("website_domain", ""),
            "candidate_rows": len(items),
            "candidate_addresses": addresses,
            "initial_triage": "; ".join(decisions),
            "source_licence_status": "pending_review",
            "service_activity_status": "not_checked",
            "trading_status": "not_checked",
            "provider_identity_status": "not_checked",
            "official_website_status": "not_checked",
            "provider_decision": "pending",
            "decision_reason": "",
            "evidence_log_refs": "",
            "reviewer": "",
            "reviewed_at_utc": "",
            "review_notes": ("Initial quality flags: " + ", ".join(flags)) if flags else "",
        })
    write_csv(out_dir / "provider_verification_register.csv", provider_fields, provider_rows)

    branch_fields = [
        "source_record_id", "provider_group_id", "candidate_name", "candidate_address",
        "postcode", "phone", "website", "latitude", "longitude", "point_in_thurrock",
        "location_flags", "duplicate_group_id", "branch_operating_status",
        "address_verification_status", "postcode_verification_status",
        "telephone_verification_status", "branch_identity_status", "branch_decision",
        "decision_reason", "evidence_log_refs", "reviewer", "reviewed_at_utc", "review_notes"
    ]
    branch_rows = []
    for r in rows:
        if r.get("service_class") != "funeral_director_candidate":
            continue
        branch_rows.append({
            "source_record_id": r.get("source_record_id", ""),
            "provider_group_id": r.get("provider_group_id", ""),
            "candidate_name": r.get("candidate_name", ""),
            "candidate_address": r.get("address", ""),
            "postcode": r.get("postcode", ""),
            "phone": r.get("phone", ""),
            "website": r.get("website", ""),
            "latitude": r.get("latitude", ""),
            "longitude": r.get("longitude", ""),
            "point_in_thurrock": r.get("point_in_thurrock", ""),
            "location_flags": r.get("location_flags", ""),
            "duplicate_group_id": r.get("possible_duplicate_group_id", ""),
            "branch_operating_status": "not_checked",
            "address_verification_status": "not_checked",
            "postcode_verification_status": "not_checked",
            "telephone_verification_status": "not_checked",
            "branch_identity_status": "not_checked",
            "branch_decision": "pending",
            "decision_reason": "",
            "evidence_log_refs": "",
            "reviewer": "",
            "reviewed_at_utc": "",
            "review_notes": "",
        })
    write_csv(out_dir / "branch_verification_register.csv", branch_fields, branch_rows)

    evidence_fields = ["evidence_id", "entity_type", "provider_group_id", "source_record_id", "evidence_type", "source_name", "source_url", "accessed_at_utc", "captured_by", "claim_supported", "evidence_summary", "strength", "limitations_or_conflicts", "notes"]
    write_csv(out_dir / "evidence_log.csv", evidence_fields, [])
    decision_fields = ["decision_id", "entity_type", "provider_group_id", "source_record_id", "decision", "reason", "evidence_log_refs", "reviewer", "decided_at_utc", "follow_up_required", "follow_up_due_date", "notes"]
    write_csv(out_dir / "decision_log.csv", decision_fields, [])

    summary = out_dir / "register_build_summary.txt"
    summary.write_text(
        f"Input rows: {len(rows)}\n"
        f"Funeral director candidate rows: {len(branch_rows)}\n"
        f"Provider groups represented (including held groups): {len(provider_rows)}\n"
        f"Evidence log rows: 0 (blank template)\nDecision log rows: 0 (blank template)\n\n"
        "All review fields are intentionally unverified and pending. No provider or branch has been approved.\n",
        encoding="utf-8"
    )
    return len(rows), len(branch_rows), len(provider_rows)

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--out", type=Path, default=Path(__file__).parent)
    a = p.parse_args()
    total, branches, providers = build(a.input, a.out)
    print(f"Created review registers: {total} source rows, {providers} provider groups, {branches} branch candidate rows")
