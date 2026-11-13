# Thurrock Overture candidate quality review

- Boundary: Thurrock (E06000034)
- Boundary source: ONS ArcGIS FeatureServer
- Candidate rows reviewed: 16
- Funeral-director candidate rows: 13
- Inside-boundary funeral-director rows: 13
- Geographically eligible rows (still awaiting provider verification): 12
- Unique branch fingerprints among eligible rows: 11
- Suggested provider groups among eligible rows: 8
- Possible duplicate groups: 1

## Service classification

- celebrant: 1
- cemetery: 1
- funeral_director_candidate: 13
- memorial_or_masonry: 1

## Review decisions

- exclude_from_funeral_director_category: 3
- hold_for_manual_location_review: 1
- retain_but_review_address_relationship: 2
- retain_but_review_possible_duplicate: 2
- retain_candidate_pending_provider_verification: 8

## Interpretation guardrails

- Overture confidence is source metadata, not proof of provider identity.
- A postcode area is a screening rule; the ONS polygon is used for point containment.
- A point inside Thurrock with a non-Thurrock postcode is held as a conflict.
- A provider can have multiple genuine branches; branch records are not merged.
- Possible duplicate observations are flagged, not deleted.
- This report does not use Google Places content and does not change Everguide's database.
- Check the licence note and upstream dataset terms before reusing candidate data.
