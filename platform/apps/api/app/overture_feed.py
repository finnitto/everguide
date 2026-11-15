"""Scheduled England-wide ingestion of the latest Overture Places release.

The feed discovers releases from Overture's authoritative STAC catalogue and
queries the public cloud-hosted Places GeoParquet in place. It never downloads
the global release and never uses Overture confidence as approval evidence.
"""
from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Any

from app.celery_app import celery_app
from app.config import settings
from app.database import SessionLocal
from app.models import AuditEvent, OvertureImportRun
from app.overture_tasks import import_overture_records, _fetch_ons_england_geometry, _inside_boundary

logger = logging.getLogger(__name__)

STAC_CATALOG_URL = "https://stac.overturemaps.org/catalog.json"
PLACES_S3_TEMPLATE = "s3://overturemaps-us-west-2/release/{release}/theme=places/type=place/*.parquet"
# Broad pre-filter only. Every retained point is subsequently checked against
# official ONS England geometry before it can enter the candidate pipeline.
ENGLAND_BBOX = (-6.5, 49.8, 2.1, 55.9)
DISCOVERY_SQL = r"""
SELECT
  id AS gers_id,
  names.primary AS name,
  CAST(basic_category AS VARCHAR) AS basic_category,
  taxonomy.primary AS taxonomy_primary,
  CAST(confidence AS VARCHAR) AS confidence,
  to_json(addresses) AS addresses_json,
  to_json(phones) AS phones_json,
  to_json(websites) AS websites_json,
  to_json(sources) AS sources_json,
  ST_X(geometry) AS longitude,
  ST_Y(geometry) AS latitude
FROM read_parquet(? , hive_partitioning = true)
WHERE bbox.xmin <= ? AND bbox.xmax >= ?
  AND bbox.ymin <= ? AND bbox.ymax >= ?
  AND (
    lower(coalesce(taxonomy.primary, '')) LIKE '%funeral%'
    OR regexp_matches(lower(coalesce(names.primary, '')), '(funeral|undertaker|undertaking|mortuary|cremation|burial)')
  )
"""


def _now():
    return datetime.now(timezone.utc)


def _get_latest_release() -> str:
    request = urllib.request.Request(STAC_CATALOG_URL, headers={"User-Agent": "EverguideOvertureFeed/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        catalog = json.loads(response.read().decode("utf-8"))
    latest = catalog.get("latest")
    if isinstance(latest, dict):
        latest = latest.get("id") or latest.get("version")
    release = str(latest or "").strip()
    import re
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", release):
        raise RuntimeError("Overture STAC catalogue did not return a valid latest release identifier.")
    return release


def _json_value(value: Any, default):
    if value in (None, ""):
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default
    return value


def _first_value(items: Any, keys: tuple[str, ...] = ()) -> str | None:
    if isinstance(items, str):
        return items.strip() or None
    if isinstance(items, dict):
        for key in keys:
            value = items.get(key)
            if value:
                return str(value).strip() or None
        return None
    if isinstance(items, list):
        for item in items:
            found = _first_value(item, keys)
            if found:
                return found
    return None


def _normalise_record(row: tuple) -> dict | None:
    (gers_id, name, basic_category, taxonomy_primary, confidence,
     addresses_json, phones_json, websites_json, sources_json, longitude, latitude) = row
    if not gers_id or not name or longitude is None or latitude is None:
        return None
    addresses = _json_value(addresses_json, [])
    phones = _json_value(phones_json, [])
    websites = _json_value(websites_json, [])
    sources = _json_value(sources_json, [])
    address = addresses[0] if isinstance(addresses, list) and addresses else {}
    if not isinstance(address, dict):
        address = {}
    website = _first_value(websites, ("value", "url", "website"))
    phone = _first_value(phones, ("value", "number", "phone"))
    return {
        "gers_id": str(gers_id), "name": str(name),
        "basic_category": basic_category or "", "taxonomy_primary": taxonomy_primary or "",
        "confidence": confidence or "", "address": address.get("freeform") or address.get("locality") or "",
        "postcode": address.get("postcode") or "", "phone": phone or "", "website": website or "",
        "latitude": float(latitude), "longitude": float(longitude),
        "addresses_json": addresses, "phones_json": phones, "websites_json": websites,
        "sources_json": sources, "source": "Overture Places", "geography_scope": "england",
        "source_release": None,
    }


def _query_latest_places(release: str):
    """Stream candidate rows from cloud GeoParquet and log each returned batch.

    DuckDB's initial execute can take time while it plans and scans remote
    Parquet files, so emit a log before submitting the query as well as after
    every fetched batch. This distinguishes a slow cloud scan from a dead task.
    """
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("DuckDB is required for automatic Overture Parquet ingestion.") from exc
    connection = duckdb.connect(database=":memory:")
    started = time.monotonic()
    try:
        logger.info("Overture %s: preparing DuckDB httpfs/spatial extensions", release)
        connection.execute("INSTALL httpfs")
        connection.execute("LOAD httpfs")
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.execute("SET s3_region='us-west-2'")
        connection.execute("SET enable_progress_bar=false")
        min_lon, min_lat, max_lon, max_lat = ENGLAND_BBOX
        logger.info("Overture %s: submitting England bbox Parquet query; batch_size=%s", release, settings.overture_feed_batch_size)
        cursor = connection.execute(DISCOVERY_SQL, [PLACES_S3_TEMPLATE.format(release=release), max_lon, min_lon, max_lat, min_lat])
        batch_number = 0
        rows_seen = 0
        while True:
            rows = cursor.fetchmany(max(100, min(int(settings.overture_feed_batch_size), 2000)))
            if not rows:
                break
            batch_number += 1
            rows_seen += len(rows)
            batch = []
            for row in rows:
                record = _normalise_record(row)
                if record:
                    batch.append(record)
            logger.info("Overture %s: fetched batch %s (%s rows; %s candidate rows; %.1fs elapsed)",
                        release, batch_number, len(rows), rows_seen, time.monotonic() - started)
            if batch:
                yield batch
        logger.info("Overture %s: Parquet query finished; %s rows scanned in %.1fs", release, rows_seen, time.monotonic() - started)
    finally:
        connection.close()


def _scheduled_run_for_task(db, release: str, task_id: str | None):
    """Find the import run belonging to this Celery delivery or resume its orphan.

    Late-ack Celery tasks are redelivered with the same task id after worker
    loss. Reusing the run prevents each redelivery from creating another
    permanently-running database row.
    """
    release_runs = db.query(OvertureImportRun).filter(
        OvertureImportRun.source_release == release,
    ).order_by(OvertureImportRun.id.desc()).all()
    scheduled_runs = [row for row in release_runs
        if ((row.outcomes or {}).get("_meta", {}) or {}).get("ingestion_method") == "scheduled_parquet"]
    if task_id:
        existing = next((row for row in scheduled_runs if row.celery_task_id == task_id), None)
        if existing:
            if existing.status in {"imported", "processing", "completed"}:
                return existing, False
            existing.status = "running"
            existing.error_message = None
            existing.completed_at = None
            existing.started_at = _now()
            return existing, True
    # Older releases of Everguide did not persist the scheduled task id. Reuse
    # the newest unfinished run for this release instead of duplicating it.
    unfinished = next((row for row in scheduled_runs if row.status in {"queued", "running", "failed"}), None)
    if unfinished:
        if task_id and not unfinished.celery_task_id:
            unfinished.celery_task_id = task_id
        unfinished.status = "running"
        unfinished.error_message = None
        unfinished.completed_at = None
        unfinished.started_at = _now()
        return unfinished, True
    run = OvertureImportRun(status="running", source_release=release,
        celery_task_id=task_id,
        outcomes={"_meta": {"ingestion_method": "scheduled_parquet", "geography_scope": "england", "catalogue_url": STAC_CATALOG_URL}},
        started_at=_now(), created_at=_now())
    db.add(run)
    db.flush()
    return run, False


@celery_app.task(name="everguide.overture.poll_latest_release", bind=True, max_retries=3, default_retry_delay=300)
def poll_latest_overture_release(self):
    """Check STAC daily; ingest only when a previously unseen release appears."""
    if not settings.overture_feed_enabled:
        logger.info("Overture scheduled feed is disabled; skipping release check")
        return {"status": "disabled"}
    db = SessionLocal()
    run_id = None
    task_id = getattr(getattr(self, "request", None), "id", None)
    try:
        logger.info("Overture feed task %s: checking STAC catalogue", task_id or "(unassigned)")
        release = _get_latest_release()
        logger.info("Overture feed task %s: latest release is %s", task_id or "(unassigned)", release)
        recent_runs = db.query(OvertureImportRun).order_by(OvertureImportRun.id.desc()).limit(30).all()
        for previous in recent_runs:
            meta = (previous.outcomes or {}).get("_meta", {})
            if meta.get("ingestion_method") == "scheduled_parquet" and previous.source_release == release and previous.status in {"imported", "processing", "completed"}:
                db.add(AuditEvent(entity_type="overture_feed", entity_id=0, action="latest_release_unchanged",
                    detail={"latest_release": release, "checked_at": _now().isoformat()}))
                db.commit()
                logger.info("Overture release %s already ingested (run %s, status %s)", release, previous.id, previous.status)
                return {"status": "no_new_release", "latest_release": release}
        run, resumed = _scheduled_run_for_task(db, release, task_id)
        run_id = run.id
        db.add(AuditEvent(entity_type="overture_feed", entity_id=0,
            action="release_ingestion_resumed" if resumed else "release_ingestion_started",
            detail={"release": release, "run_id": run_id, "task_id": task_id, "scope": "england"}))
        db.commit()
        logger.info("Overture release %s: %s import run %s", release, "resuming" if resumed else "created", run_id)
        logger.info("Overture release %s: retrieving official England boundary geometry", release)
        england_geometry = _fetch_ons_england_geometry()
        logger.info("Overture release %s: England boundary loaded; starting cloud Parquet scan", release)
        total = 0
        batches = 0
        for batch in _query_latest_places(release):
            batches += 1
            england_batch = [record for record in batch if _inside_boundary(
                england_geometry, record.get("longitude"), record.get("latitude")) is True]
            for record in england_batch:
                record["source_release"] = release
                record["version"] = release
            if england_batch:
                import_overture_records.run(run_id, england_batch, release, finalize=False)
                total += len(england_batch)
            # Persist progress even when a fetched batch contains no England
            # points, so operators can distinguish scanning from inactivity.
            run = db.get(OvertureImportRun, run_id)
            meta = dict((run.outcomes or {}).get("_meta", {}))
            meta.update({"ingestion_method": "scheduled_parquet", "geography_scope": "england",
                         "latest_release": release, "batches_completed": batches,
                         "england_records_seen": total, "last_batch_at": _now().isoformat()})
            run.outcomes = {**(run.outcomes or {}), "_meta": meta}
            db.commit()
            logger.info("Overture release %s run %s: batch %s complete; %s England records", release, run_id, batches, total)
        run = db.get(OvertureImportRun, run_id)
        run.records_received = total
        run.status = "imported"
        run.completed_at = _now()
        run.error_message = None
        run.outcomes = {**(run.outcomes or {}), "_meta": {**((run.outcomes or {}).get("_meta", {})), "ingestion_method": "scheduled_parquet", "geography_scope": "england", "latest_release": release, "batches_completed": batches, "england_records_seen": total}}
        db.add(AuditEvent(entity_type="overture_import_run", entity_id=run_id, action="scheduled_parquet_ingestion_completed",
            detail={"release": release, "records_discovered": total, "batches_completed": batches, "scope": "england"}))
        db.add(AuditEvent(entity_type="overture_feed", entity_id=0, action="release_ingestion_completed",
            detail={"latest_release": release, "records_discovered": total, "batches_completed": batches, "run_id": run_id, "scope": "england"}))
        db.commit()
        logger.info("Overture release %s run %s completed: %s records in %s batches", release, run_id, total, batches)
        if settings.overture_auto_process:
            from app.overture_tasks import process_overture_candidates
            process_overture_candidates.delay(run_id, min(max(total, 1), 20))
        return {"status": "imported", "run_id": run_id, "latest_release": release, "records_discovered": total, "batches_completed": batches}
    except Exception as exc:
        db.rollback()
        logger.exception("Overture feed task %s failed for run %s: %s", task_id, run_id, exc)
        db.add(AuditEvent(entity_type="overture_feed", entity_id=0, action="release_ingestion_failed",
            detail={"error": str(exc)[:1000], "task_id": task_id, "checked_at": _now().isoformat()}))
        if run_id is not None:
            run = db.get(OvertureImportRun, run_id)
            if run:
                run.status = "failed"
                run.error_message = str(exc)[:2000]
                run.completed_at = _now()
                db.add(AuditEvent(entity_type="overture_import_run", entity_id=run_id,
                    action="scheduled_parquet_ingestion_failed", detail={"error": str(exc)[:1000], "task_id": task_id}))
                db.commit()
        else:
            db.commit()
        raise self.retry(exc=exc)
    finally:
        db.close()
