# Everguide release packaging

- Release version: `2.8.0-rc.1` (pre-release candidate).
- This archive contains the complete source project and all application workloads: API, web, worker, scheduler, migrations, Docker files, scripts, tests and documentation.
- The single authoritative release history is the root `CHANGELOG.md`. Do not create per-release release-notes files.
- Secrets, `.env` files, dependency folders, build output, caches, database volumes, local backups and candidate exports are excluded.
- Extract the archive contents into the project directory; files are stored at the archive root.
- Default geography is `GEOGRAPHY_MODE=local_authorities` and `GEOGRAPHY_AUTHORITIES=thurrock`. Do not enable the expanded pilot or England-wide mode until end-to-end sign-off.
- This is a source release candidate, not a production deployment approval. Complete the outstanding test/build checks and review configuration before deployment.
