# Everguide validation

The validation scripts provide repeatable local checks without using the developer's
existing Everguide database or processing real candidates.

## One-time local setup

From the `platform` directory, install the pinned API and frontend dependencies:

```bash
python -m pip install -r apps/api/requirements.txt
npm ci --prefix apps/web
```

Activate the intended Python virtual environment before running the scripts.

## Quick validation

```bash
bash scripts/validate.sh quick
```

Runs release-version consistency checks, Python compilation, the complete API
pytest suite, frontend ESLint and TypeScript type checking. It does not build
Docker images, start containers, run migrations or touch a database.

## Full validation

```bash
bash scripts/validate.sh full
```

Runs all quick checks, creates a frontend production build, builds and starts
an isolated Docker Compose project containing API, worker, Beat, web, PostgreSQL
and Redis, then creates and audits a deterministic release archive.

The isolated project:
- uses a unique Compose project name, temporary environment file and dynamically selected localhost ports;
- uses a fresh, project-scoped PostgreSQL volume and Redis volume;
- disables Overture feed access, scheduled tasks, automatic processing and automatic approval;
- supplies no Companies House, Google Places or Brave API credentials;
- applies migrations only to its disposable database, checks migration head `0024_pricing_option_groups`, downgrades to `0023_stage3_evidence`, upgrades back to `0024_pricing_option_groups`, and verifies Stage 3 tables/columns;
- checks API readiness/version, reviewer credential forwarding, disabled automation controls, admin HTTP response, worker liveness and empty task states, and the empty Beat schedule;
- removes its containers, network and database/cache volumes on exit, including
  after a failed check.

The workflow does not connect to or modify the normal `everguide` Compose project.
It does not import candidates, call external enrichment providers or publish records.

## Docker-only validation

```bash
bash scripts/validate-docker.sh
```

This is useful when Python and frontend checks have already passed and only the
container integration needs repeating. Docker Compose and Python (for generating
a temporary password and free local ports) must be available.

## GitHub Actions

The repository workflow runs code checks and isolated Docker integration checks
for pushes to `stage1-overture-identity-provenance` and pull requests. CI uses
fresh runner services and does not require developer API credentials.


## Release archive generation and audit

The full validation command also runs:

```bash
python scripts/package_release.py
```

The script builds `releases/everguide-v{VERSION}.zip` from the maintained
`platform/` tree only. It normalises ZIP timestamps and member ordering,
validates required application/migration/documentation files, checks ZIP
integrity and release-version consistency, and excludes secrets, environment
files other than example templates, credentials, SSH/cloud keys, local
databases/data, development patch helpers, dependency trees, caches and build
outputs.

It writes a sibling `.sha256` checksum and `.package-manifest.json` containing
the source commit, size, file count, hash and exclusion policy. The output
directory is ignored by Git. The GitHub Actions workflow uploads the archive
and sidecars as a 14-day artifact. A package built by CI is an implementation
artifact, not approval to deploy or migrate a persistent database.

## Interpreting results

A successful quick run is not a release sign-off. A successful full run validates
the tested source and disposable runtime only. It does not validate production
infrastructure, production data, production credentials, or authorise deployment
or migration of the existing development database.
