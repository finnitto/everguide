# Automatic provider approval (v1.0.0)

Everguide automatically creates and publishes a new provider only when all of these conditions are met:

- The discovered candidate is classified as a provider candidate.
- The candidate's HTTPS page is reachable and robots.txt permits the fetch.
- The page contains explicit Schema.org `FuneralHome` JSON-LD with a business name and complete UK physical address (street, locality and syntactically valid UK postcode).
- The source response is HTML and within the existing bounded response-size limit.
- No existing provider has the exact normalised business name, no existing branch has the same postcode, and no existing provider website contains the candidate domain.

If these conditions are met, Everguide creates a published provider and one published branch, records a linked accepted source observation and an audit event, and stores only extracted structured facts plus a content digest. The fetched HTML body is discarded.

Any duplicate signal or incomplete/ambiguous evidence prevents automatic publication. Existing providers and branches are never overwritten. A technical website check alone is never enough.

## Important limitations

- This is deliberately a high-precision first implementation, not a promise that every funeral director can be auto-approved. Most sites that do not publish the required structured data will remain unapproved until a later evidence pathway is implemented.
- The current structured-data rule is a conservative automated eligibility rule, not legal confirmation of ownership, accuracy, permission, or compliance with website terms, database rights, privacy law or data protection law. Commercial rollout should receive legal review.
- Pricing is not extracted or approved in v1.0.0.
- Matching uses exact normalised name, postcode and website-domain collision checks. More sophisticated fuzzy/group/branch matching remains future work; possible collisions should be reviewed rather than bypassed.
