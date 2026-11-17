# Google Places API setup

Everguide 0.3.0 uses the Google Places API (New) for an initial regional discovery pass.

1. In Google Cloud Console, create or select a project.
2. Attach an active billing account.
3. Enable **Places API (New)** for that project.
4. Create an API key and restrict it to the Places API (New). Apply appropriate application restrictions for your local development environment.
5. Open the local Everguide `.env` file (not `.env.example`) and add:

   `GOOGLE_PLACES_API_KEY=your-key-here`

6. Save the file and run `bash scripts/deploy-local.sh` again.
7. Open `http://localhost:3000/admin` and use **Run discovery**.

Do not paste the key into chat, commit it to Git, or include it in a release ZIP. The deployment ZIP excludes `.env`.

## What one run does

The initial connector sends one Text Search request for each of 40 configured regional anchors, with a 30 km location bias. A run therefore makes up to 40 search requests before any provider-side retries or future paging enhancements. Google Cloud billing may apply; check current Google Maps Platform pricing and quotas before running it.

The connector retains Place ID references and Everguide's own anchor metadata only. It deliberately does not persist Google Places names, addresses, telephone numbers, websites or other returned business content pending a review of applicable Google Maps Platform terms, attribution and retention rules.

This first regional pass is not a boundary-validated exhaustive census of England. It is an integration milestone, not a claim of complete national coverage. A validated coverage grid, pagination, quota-aware scheduling, coverage reporting and source-policy review are required before production operation.
