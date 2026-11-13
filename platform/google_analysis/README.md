# Thurrock Google Aggregate and Overture quality analysis

This folder contains the count-only Google Places Aggregate API scripts and a
separate Overture candidate quality review.

## Overture review

Install dependencies:

```powershell
python -m pip install -r google_analysis/requirements.txt
```

Run from the project root:

```powershell
python google_analysis/review_overture_candidates.py `
  --input google_analysis/overture_candidates.csv `
  --out google_analysis/quality_review
```

The Overture review reuses the API's shared candidate-quality rules and uses the official ONS Thurrock boundary (E06000034). It creates
review-only outputs, and does not connect to the Everguide database or Google.

## Google Aggregate scripts

`thurrock_places_aggregate_count.py` and
`thurrock_places_aggregate_categories.py` request count-only insights. They do
not request individual place details. Keep API keys in the local environment;
never put them in this repository or share them in chat. Check the current
Google Maps Platform agreement before retaining or using aggregate outputs.
