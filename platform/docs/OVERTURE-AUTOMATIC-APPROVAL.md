# Overture-only discovery and automatic enrichment approval

## Operating policy

Overture Places is Everguide's sole source for importing funeral directors and related funeral-service candidates and is authoritative for candidate name, address, postcode and coordinates. Each candidate is keyed by its Overture GERS ID. The original Overture record, release, contributor lineage, source-level licence, source observation and assessment history are retained. Companies House is paused and is not consulted during this workflow.

Overture is the sole source for importing funeral directors and related services. Companies House is paused and is not consulted by this policy. Overture-supplied website URLs are used for deterministic conflict checks and enrichment. A reachable, robots-permitted Overture URL can support draft enrichment even when the page parser cannot extract identity fields. A missing or inaccessible URL remains an exception; URLs are not silently replaced by another discovery source.

The Overture-first ruleset is `overture-first-approval-v2.2`. It does not use Overture's place-existence confidence as a probability of business identity, field accuracy or funeral-director service. It does not apply the shared first-party website threshold used by other discovery adapters.

## Deterministic Overture checks

Before a candidate can be approved, the Overture record must:
- Have a stable GERS ID and retained source/release provenance.
- Pass deterministic service classification. Conventional funeral directors and supported related services (direct cremation, funeral plans, crematoria, celebrants, cemeteries and memorial/masonry) remain distinct provider types. Pet services, directories and unrelated services are excluded.
- Have a valid UK postcode, structured street address and locality.
- Have contributor source/licence metadata that is present and recognised.
- Pass the active geography's official ONS point-in-polygon check. Missing coordinates, incomplete boundary data or unavailable official geometry fail closed.
- Have no unresolved same-service-class duplicate or existing-provider/branch collision. A same-name/same-postcode peer only creates a funeral-director duplicate signal when that peer independently classifies as a funeral-director candidate; a cemetery, crematorium, pet service, funeral-plan provider or other service class cannot block a funeral-director candidate.
- Use matching street, telephone and website-domain signals as supporting identity evidence. When one of those signals agrees but matching same-name/same-postcode candidates are more than 100 metres apart, the record is routed to an `overture_coordinate_conflict` review instead of being labelled only as an ordinary duplicate. The 100-metre threshold is a conservative review trigger, not proof that either coordinate is wrong. Where coordinates or corroborating identity signals are missing, ambiguous same-name/same-postcode cases remain held for review.

An incomplete or invalid Overture address is not approved. It remains awaiting enrichment or review; the system does not invent missing street/locality values. Telephone is optional. A reachable, robots-permitted Overture-supplied URL is required for automatic enrichment approval and price retrieval, but does not replace Overture branch data. Missing website extraction is recorded as unverified corroboration, not as a positive identity conflict. Complete Overture name, street, locality and postcode are still required to create the draft branch; incomplete or invalid location data remains for review.

## Corroboration and conflicts

Legacy Companies House links and records have no effect on current Overture candidate assessment, conflict checks or enrichment approval.

A website is checked only if Overture supplied the URL. The system never searches for a replacement website from another source. A reachable, robots-permitted Overture URL can be approved for draft enrichment when no material conflict or duplicate exists, even if extraction returns no identity fields or only partial identity fields. Missing fields are unknown, not contradictory. An explicit conflict at the same branch—such as a different postcode or a different operator at the same street and locality—or an explicit closed-branch signal is sent to exception review. A trading-name difference alone is not treated as a conflict. A name-plus-postcode match remains the stronger identity evidence required before a reachable website can support automatic provider publication.

Identity mismatches, duplicate/service conflicts, invalid locations and missing required data are retained for human resolution; records are not silently merged or overwritten. Duplicate GERS records are never automatically merged, deleted or used to overwrite another record's coordinates. A coordinate conflict is preserved as a separate review reason.

## Outcomes

| Outcome | Meaning |
|---|---|
| `auto_approved_eligible` | Overture integrity, service, source-rights, duplicate and geography checks pass; provider publication is enabled separately. |
| `enrichment_approved` | A reachable, robots-permitted Overture URL passed the conflict and duplicate checks and Overture supplied complete branch data; a draft provider/branch is linked and deterministic price enrichment is queued. Website identity extraction may be unverified. This does not publish the provider. |
| `awaiting_enrichment` | Overture data or official geography is incomplete, the URL is missing/inaccessible, or a needed check cannot yet be completed. |
| `exception_review` | A material same-branch identity/location conflict, same-service-class duplicate collision, coordinate inconsistency, out-of-scope location, unavailable Overture URL or source-rights issue needs investigation. |
| `excluded` | Deterministic classification identifies an out-of-scope service. |

When `OVERTURE_AUTO_PROCESS=true`, new official-feed candidates are automatically assessed. If there is no obvious issue, the Overture URL is reachable and robots-permitted, and Overture provides complete branch data, enrichment approval creates or links a draft provider/branch and queues deterministic price extraction. This does not publish the provider. Provider publication remains separately guarded by `AUTO_APPROVE_PROVIDERS`; a reachable website with unverified identity extraction cannot by itself unlock publication. The publication flag defaults to false. Existing verified provider and branch data is never overwritten, merged or deleted.

## Post-approval price enrichment queue

An Overture candidate is marked for price enrichment only after it is linked
to a provider/location:
- Automatic enrichment approval queues the candidate with trigger
  `automatic_overture_enrichment_approval`.
- A reviewer may approve an `exception_review` candidate for enrichment only using `POST /api/v1/overture/candidates/{candidate_id}/approve-enrichment`; the URL is rechecked and publication is not enabled by this action.
- Automatic publication (if separately enabled) and manual provider approval can also queue eligible candidates.
- The reviewer-only `POST /api/v1/overture/pricing-enrichment/queue-approved`
  endpoint performs an idempotent backfill for previously approved or published
  providers from supported Overture service classes. It only writes queue markers.
- The reviewer-only `GET /api/v1/overture/pricing-enrichment/queue` endpoint lists
  queue markers for the future retrieval worker.

The marker is stored under `OvertureCandidate.first_party_evidence.pricing_enrichment`
with status `queued`, trigger, requester, request time and attempt count. Repeated
approval events and backfills do not create duplicate queue entries. Existing
website verification metadata is retained. The candidate's approval/outcome and
the provider's publication status are not changed by queueing.

Queueing itself does not fetch a provider website or create price evidence. The separate deterministic worker fetches a bounded set of HTTPS provider-owned pages and text PDFs, checks robots rules, and stores exact quoted prices as pending evidence. It does not use OpenAI and does not mark evidence verified. A reviewer must approve extracted prices before they are presented as verified.

## Development and validation safety

Keep `AUTO_APPROVE_PROVIDERS=false` unless provider publication is separately authorised. The final write-boundary guard blocks publication even if an assessor mistakenly returns an eligible outcome. Overture processing and deterministic price enrichment can be enabled independently. Existing exceptions should only be reassessed through a scoped, tracked run that selects candidates held for a specific remediated rule; do not reimport their Overture records.

Scheduled Overture polling and retries are controlled separately by `OVERTURE_SCHEDULED_TASKS_ENABLED`. `OVERTURE_FEED_ENABLED` controls feed availability and `OVERTURE_AUTO_PROCESS` controls automatic candidate processing after an import. Local feed polling remains off while auto-processing and price enrichment are enabled. The normal England-wide feed uses the authoritative Overture STAC catalogue and cloud-hosted Places GeoParquet; every retained point is checked against official ONS England boundaries.

Automatic publication must remain disabled until all five implementation stages, synthetic regression coverage, isolated migration/container checks and a separate production-readiness assessment are complete and explicitly approved.

## Configuration

```dotenv
OVERTURE_FEED_ENABLED=true
OVERTURE_SCHEDULED_TASKS_ENABLED=false
OVERTURE_FEED_DAILY_HOUR=4
OVERTURE_FEED_DAILY_MINUTE=30
OVERTURE_FEED_BATCH_SIZE=500
OVERTURE_AUTO_PROCESS=true
AUTO_APPROVE_PROVIDERS=false
ONS_BOUNDARY_CACHE_TTL_HOURS=720
BRAVE_SEARCH_API_KEY=
```

Overture contributor licence values are retained per record and checked against the accepted source-level licence allowlist. The ONS geometry cache retains source, retrieval time and SHA-256 integrity metadata and rejects expired or invalid data.

## Admin monitoring and API

The Overture admin panel shows feed enablement and schedule, last feed check, latest release, candidate/outcome counts, automatically published providers, ingestion run history and unresolved candidates. Diagnostic feed checks and retry actions are not to be used against operational data during implementation.

- `GET /api/v1/overture/status` — feed schedule, last check, candidate counts and latest run.
- `POST /api/v1/overture/feed/check` — queue an immediate STAC release check.
- `GET /api/v1/overture/imports` — feed run history.
- `GET /api/v1/overture/candidates` — candidate decisions and evidence summaries.
- `POST /api/v1/overture/process` — retry awaiting-enrichment candidates.
- `POST /api/v1/overture/imports` — legacy import compatibility endpoint; not part of the normal admin workflow.

## Scope and limitations

The feed's taxonomy/name query is a discovery filter and may miss funeral directors whose Overture record contains neither relevant taxonomy nor relevant name terms. The Overture record is authoritative for location data within Everguide's approved source policy, but a missing/invalid address, postcode, coordinates, contributor lineage or licence is not guessed. A location absent from a later Overture release is not, by itself, proof that a provider has closed; existing records are retained for review.

## Upgrade and deployment

No deployment or operational migration is authorised by this document. Any future release migration must first be dry-run against a fresh isolated database, with backups and rollback evidence. Do not run `docker compose down -v` against a working environment.
