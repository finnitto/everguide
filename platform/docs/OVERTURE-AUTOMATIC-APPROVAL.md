# Overture-first discovery and automatic publication

## Operating policy

Overture Places is Everguide's primary and authoritative source for discovering funeral-director locations and for the published branch name, address, postcode and coordinates. Each candidate is keyed by its Overture GERS ID. The original Overture record, release, contributor lineage, source-level licence, source observation and assessment history are retained.

Companies House and funeral-director websites are corroborating sources, not mandatory gateways. A missing company link, absent website, inaccessible website, robots restriction, missing telephone number or lack of corroborating evidence does not by itself prevent an otherwise valid Overture location from being approved. A legal registered-office address is not treated as a branch address. A trading name may legitimately differ from a legal company name.

The Overture-first ruleset is `overture-first-approval-v2.1`. It does not use Overture's place-existence confidence as a probability of business identity, field accuracy or funeral-director service. It does not apply the shared first-party website threshold used by other discovery adapters.

## Deterministic Overture checks

Before a candidate can be approved, the Overture record must:
- Have a stable GERS ID and retained source/release provenance.
- Pass the deterministic funeral-director classification; cemeteries and natural/woodland burial grounds, crematoria, celebrants, memorial masons, pet/animal services, funeral-plan-only providers, direct-cremation providers, directories and unrelated services are not classified as conventional funeral-director branches. Direct-cremation providers retain a distinct `direct_cremation_provider` service class for a separate future funeral-services category.
- Have a valid UK postcode, structured street address and locality.
- Have contributor source/licence metadata that is present and recognised.
- Pass the active geography's official ONS point-in-polygon check. Missing coordinates, incomplete boundary data or unavailable official geometry fail closed.
- Have no unresolved same-service-class duplicate or existing-provider/branch collision. A same-name/same-postcode peer only creates a funeral-director duplicate signal when that peer independently classifies as a funeral-director candidate; a cemetery, crematorium, pet service, funeral-plan provider or other service class cannot block a funeral-director candidate.
- Use matching street, telephone and website-domain signals as supporting identity evidence. When one of those signals agrees but matching same-name/same-postcode candidates are more than 100 metres apart, the record is routed to an `overture_coordinate_conflict` review instead of being labelled only as an ordinary duplicate. The 100-metre threshold is a conservative review trigger, not proof that either coordinate is wrong. Where coordinates or corroborating identity signals are missing, ambiguous same-name/same-postcode cases remain held for review.

An incomplete or invalid Overture address is not published. It remains awaiting enrichment or review; the system does not invent missing street/locality values. Telephone and website are optional fields and are not substituted for the Overture branch address.

## Corroboration and conflicts

A Companies House record is used as a conflict signal only when an authenticated reviewer has explicitly verified the Overture-to-Companies-House identity link. A verified linked entity whose Companies House status is dissolved is sent to exception review. A different registered office address, by itself, is not a branch conflict.

A provider website is checked only when Overture supplies a plausible first-party URL. It is optional corroboration and is never the source of the published branch name or address. An inaccessible site, absent site, absent branch listing or robots restriction is not treated as proof that the Overture location is wrong. A structured official-site branch address that explicitly has a different postcode from the Overture location, or an explicit closed branch status, is sent to exception review. A trading-name difference alone is not treated as a conflict.

The conflict checks are deliberately conservative. An unlinked Companies House record, a legal name difference, or a website's failure to mention a branch must not be converted into a negative assertion about the Overture location. Conflicting or ambiguous evidence is retained for human resolution; records are not silently merged or overwritten. Duplicate GERS records are never automatically merged, deleted or used to overwrite another record's coordinates. A coordinate conflict is preserved as a separate review reason.

## Outcomes

| Outcome | Meaning |
|---|---|
| `auto_approved_eligible` | Overture integrity, service, source-rights, duplicate and geography checks pass, with no detected material conflict. |
| `awaiting_enrichment` | Overture data is incomplete, a boundary cannot be confirmed, or the publication safety switch is off. |
| `exception_review` | A material identity/location conflict, same-service-class duplicate collision, coordinate inconsistency, out-of-scope location or source-rights issue needs investigation. |
| `excluded` | Deterministic classification identifies an out-of-scope service. |

When automatic approval is enabled, eligible Overture records are published from Overture fields. Provider/branch writes, source observations and audit events are committed atomically. Existing verified provider and branch data is never overwritten, merged or deleted by this pathway. The Overture source observation is linked to the resulting provider and branch. Optional website observations are stored separately and do not replace Overture provenance.

## Post-approval price enrichment queue

An Overture candidate is marked for price enrichment only after it is actually linked
to an approved provider/location:
- Automatic Overture publication queues the candidate with trigger
  `automatic_approval`.
- A reviewer changing a provider's status to `approved` queues every Overture
  candidate already linked to that provider with trigger `manual_approval`.
- The reviewer-only `POST /api/v1/overture/pricing-enrichment/queue-approved`
  endpoint performs an idempotent backfill for previously approved or published
  funeral-director providers. It only writes queue markers.
- The reviewer-only `GET /api/v1/overture/pricing-enrichment/queue` endpoint lists
  queue markers for the future retrieval worker.

The marker is stored under `OvertureCandidate.first_party_evidence.pricing_enrichment`
with status `queued`, trigger, requester, request time and attempt count. Repeated
approval events and backfills do not create duplicate queue entries. Existing
website verification metadata is retained. The candidate's approval/outcome and
the provider's publication status are not changed by queueing.

This is a hand-off, not a price scraper. Queueing does not fetch a provider website,
make an external request, extract a price, create `PricingEvidence`, or approve
pricing evidence. The price-retrieval worker is a separate implementation step.
When implemented, automated retrieval must use HTTPS provider-owned sources and
must be gated by an approved `SourcePermission` (`automated_check` or
`approved`); robots.txt is only a technical crawl instruction, not permission
or a rights basis. Any captured price evidence must remain pending reviewer
approval. An `accepted_for_provider_setup` identity/branch review is not yet a
provider approval and does not queue price enrichment.

## Development and validation safety

Keep `AUTO_APPROVE_PROVIDERS=false` throughout implementation and isolated validation. The final write-boundary guard blocks publication even if an assessor mistakenly returns an eligible outcome. Tests may enable the setting only in isolated synthetic fixtures. No Overture import, candidate processing, scheduled feed, enrichment, approval or publication is to be run against operational data during development.

Scheduled Overture polling and retries are controlled separately by `OVERTURE_SCHEDULED_TASKS_ENABLED`. `OVERTURE_FEED_ENABLED` controls feed availability and `OVERTURE_AUTO_PROCESS` controls automatic candidate processing after an import. These controls remain off unless separately authorised. The normal England-wide feed uses the authoritative Overture STAC catalogue and cloud-hosted Places GeoParquet; every retained point is checked against official ONS England boundaries.

Automatic publication must remain disabled until all five implementation stages, synthetic regression coverage, isolated migration/container checks and a separate production-readiness assessment are complete and explicitly approved.

## Configuration

```dotenv
OVERTURE_FEED_ENABLED=true
OVERTURE_SCHEDULED_TASKS_ENABLED=false
OVERTURE_FEED_DAILY_HOUR=4
OVERTURE_FEED_DAILY_MINUTE=30
OVERTURE_FEED_BATCH_SIZE=500
OVERTURE_AUTO_PROCESS=false
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
