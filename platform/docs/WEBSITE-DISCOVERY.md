# Automatic website discovery — v0.6.1

Everguide uses a provider-independent search adapter interface. `SEARCH_PROVIDER` selects the adapter; `brave` is the implemented default. The architecture allows another provider to be added without changing the regional discovery task or candidate storage.

## Configuration
Set `SEARCH_PROVIDER=brave` and `BRAVE_SEARCH_API_KEY` in the project-root `.env`. Choose a Brave plan whose contractual terms permit storing and using search result metadata. Keep the key secret. Restart API and worker after editing `.env`.

Brave API docs: https://api-dashboard.search.brave.com/app/documentation/web-search
Plans: https://brave.com/search/api/

Google Custom Search JSON API is not offered to new customers. Selecting `SEARCH_PROVIDER=google` currently returns an explanatory configuration error; a Google adapter is not implemented in this release. Do not use unsupported scraping of Google Search pages.

## Operation
The admin dashboard queues one query per configured England regional anchor. Results are deduplicated by URL and stored with query region, title, URL, domain, snippet and retrieval timestamp. SAIF and NAFD directory domains are excluded. Search results are candidate URLs only, not verified official provider websites.

## Current boundary
This release does not yet resolve each Google Place ID into a named business, verify candidate-domain ownership, fetch candidate pages, extract business facts, or create/update providers and branches. No candidate is published automatically.
