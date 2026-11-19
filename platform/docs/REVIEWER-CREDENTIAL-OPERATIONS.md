# Reviewer credential operations

**Applies to:** `IDENTITY_REVIEW_CREDENTIALS` and the HTTP Bearer reviewer gate  
**Current implementation:** reviewer IDs mapped to SHA-256 token digests  
**Security limitation:** every configured reviewer currently receives the same reviewer-level permissions; there is no role claim, token expiry or in-application credential administration.

## Admin browser sign-in

The `/admin` page prompts for the configured reviewer Bearer token before making internal API calls. The browser keeps the token in React component memory only; it is not written to local storage, session storage or cookies. Reloading the page or selecting **Sign out** clears it. A server response of HTTP 401 clears the in-memory token and returns the page to the sign-in prompt. Every admin API call uses the same authenticated fetch wrapper.

## Credential format

Configure `IDENTITY_REVIEW_CREDENTIALS` as a JSON object mapping a stable reviewer identifier to the SHA-256 hexadecimal digest of a high-entropy token:

```json
{"reviewer-ops-1":"<64-character-sha256-hex-digest>"}
```

Generate at least 32 random bytes of token entropy. Keep the clear token in the approved password manager and deliver it only to the named reviewer. Calculate and configure only its SHA-256 digest. Do not paste clear tokens into repository files, issue descriptions, pull requests, chat, CI output or application logs. The `.env` file is ignored by Git; do not commit any local environment file.

The API authenticates the Bearer token by hashing the supplied token and comparing its digest against configured values. It derives the audit actor from the matching reviewer ID; clients cannot select their audit identity in a request body. Missing, malformed or empty credential configuration fails closed.

## Provisioning

1. Assign the reviewer a stable, non-personal identifier (for example, `reviewer-ops-1`).
2. Generate a high-entropy token using the operator-approved secret-generation process.
3. Compute the SHA-256 digest locally using a trusted tool.
4. Add the reviewer-ID/digest pair to the secured deployment environment. Preserve any other currently authorised reviewer entries.
5. Apply the environment change to the API service using the approved deployment procedure. Do not change database volumes or run migrations as part of credential rotation.
6. Verify that the new token can access a reviewer-only read endpoint and that an invalid token receives HTTP 401.
7. Deliver the clear token securely and record the issuance date and intended reviewer in the organisation's credential register (not in the application database).

## Rotation

1. Generate a replacement token and digest for the same reviewer identifier.
2. During a controlled maintenance window, update the digest in the secured environment.
3. Restart/recreate only the API service according to the deployment's approved procedure so it loads the new environment value.
4. Verify the replacement token works and the previous token receives HTTP 401.
5. Update the password-manager entry and record the rotation date.

The implementation reads configured credentials for each authentication request. Rotation takes effect for new requests after the API process receives the updated configuration; it does not provide a token-expiry grace period or a self-service rotation endpoint.

## Revocation

1. Remove the reviewer-ID/digest entry from `IDENTITY_REVIEW_CREDENTIALS`.
2. Apply the secured environment change and restart/recreate only the API service.
3. Verify the revoked token receives HTTP 401 on a reviewer-only endpoint.
4. Revoke/delete the clear token in the password manager and record the revocation reason/date in the external credential register.

If the last credential is removed or the JSON becomes invalid, reviewer-protected endpoints fail closed. Public health/readiness and directory search endpoints remain public by design.

## Incident response

If a token is suspected to be exposed, revoke it immediately using the procedure above, issue a replacement only after containment, review audit events for the affected reviewer ID and investigate any unauthorised activity. Never ask the reviewer to send the clear token to support staff; confirm only the reviewer ID and a controlled authentication test.

## Current controls and limitations

- API logs and audit rows should contain reviewer IDs and action metadata, never clear bearer tokens.
- CI uses a dummy reviewer digest only; it must never contain a real credential.
- All reviewers currently share the same reviewer-level authority. Read-only, evidence-review, identity-review and operational-admin roles are not yet separated.
- There is no configured maximum token age, automatic expiry, credential registry, self-service revocation, or credential-change audit trail. Those require a separately accepted Stage 4 RBAC and secret-lifecycle design.
- A successful CI check does not prove deployment secret storage, rotation or revocation in the target environment. Operator execution and evidence are still required.
