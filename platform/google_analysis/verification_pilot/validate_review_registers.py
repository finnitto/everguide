"""Validate human review decisions before any later provider/branch setup.

The script is a completeness gate only. It never writes to the Everguide DB.
Exit code 0 means no completeness blockers were found; it does not mean data is
truthful, legally reusable, or approved for publication.
"""
from __future__ import annotations
import argparse, csv, json
from pathlib import Path

ROOT = Path(__file__).parent

def rows(path):
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--directory',type=Path,default=ROOT)
    p.add_argument('--json-out',type=Path,default=None)
    a=p.parse_args(); d=a.directory
    providers=rows(d/'provider_verification_register.csv')
    branches=rows(d/'branch_verification_register.csv')
    evidence=rows(d/'evidence_log.csv')
    ev_ids={x.get('evidence_id','').strip() for x in evidence if x.get('evidence_id','').strip()}
    provider_decisions={x.get('provider_group_id'):x for x in providers}
    blockers=[]; warnings=[]
    for r in providers:
        if r.get('provider_decision')=='verified_ready_for_setup':
            required={
                'source_licence_status':'approved_for_operational_use',
                'service_activity_status':'confirmed_funeral_director',
                'trading_status':'confirmed_trading',
                'provider_identity_status':'confirmed',
                'official_website_status':'confirmed_official',
            }
            missing=[f'{k}={v}' for k,v in required.items() if r.get(k)!=v]
            refs=[x.strip() for x in (r.get('evidence_log_refs') or '').split(';') if x.strip()]
            if not refs: missing.append('evidence_log_refs')
            elif any(x not in ev_ids for x in refs): missing.append('evidence_log_refs contains unknown ID')
            if missing: blockers.append({'entity':'provider','id':r.get('provider_group_id'),'missing':missing})
    for r in branches:
        if r.get('branch_decision')=='verified_operating_branch':
            required={
                'branch_operating_status':'confirmed_public_branch',
                'address_verification_status':'confirmed_official_source',
                'postcode_verification_status':'confirmed',
                'branch_identity_status':'confirmed_linked_to_provider',
            }
            missing=[f'{k}={v}' for k,v in required.items() if r.get(k)!=v]
            parent=provider_decisions.get(r.get('provider_group_id'))
            if not parent or parent.get('provider_decision')!='verified_ready_for_setup':
                missing.append('parent provider not verified_ready_for_setup')
            refs=[x.strip() for x in (r.get('evidence_log_refs') or '').split(';') if x.strip()]
            if not refs: missing.append('evidence_log_refs')
            elif any(x not in ev_ids for x in refs): missing.append('evidence_log_refs contains unknown ID')
            if missing: blockers.append({'entity':'branch','id':r.get('source_record_id'),'missing':missing})
        if r.get('location_flags') and r.get('branch_decision')=='verified_operating_branch':
            warnings.append({'entity':'branch','id':r.get('source_record_id'),'warning':'Source quality flags remain; ensure explicitly resolved in decision notes.'})
    verified_providers=sum(x.get('provider_decision')=='verified_ready_for_setup' for x in providers)
    verified_branches=sum(x.get('branch_decision')=='verified_operating_branch' for x in branches)
    result={'providers_reviewed':len(providers),'branches_reviewed':len(branches),'evidence_records':len(evidence),'verified_providers':verified_providers,'verified_branches':verified_branches,'completeness_blockers':blockers,'warnings':warnings,'passed':not blockers,'status':('BLOCKED' if blockers else 'NO_VERIFICATION_DECISIONS' if not (verified_providers or verified_branches) else 'COMPLETENESS_CHECK_PASSED'),'disclaimer':'A passed completeness check is not a legal, factual or publication approval.'}
    print(json.dumps(result,indent=2))
    if a.json_out: a.json_out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if not blockers else 2

if __name__=='__main__': raise SystemExit(main())
