from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import FeatureMeasurement, FileJob, JobStatus, MeasurementStatus
from .geospatial import iter_measurements, read_geospatial_file, read_shapefile
from .storage import extract_shapefile_archive

settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _cleanup_extracted(job_id: str) -> None:
    shutil.rmtree(settings.storage_dir / "extracted" / job_id, ignore_errors=True)


def _load_geodata(job: FileJob) -> gpd.GeoDataFrame:
    path = Path(job.stored_path)
    if not path.exists():
        raise FileNotFoundError("Stored source file no longer exists.")
    if job.source_type == "kml":
        return read_geospatial_file(str(path), "kml")
    if job.source_type == "zip":
        shp = extract_shapefile_archive(path, job.id)
        return read_shapefile(str(shp))
    raise ValueError(f"Unknown source type: {job.source_type}")


def process_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(FileJob, job_id)
        if job is None:
            return
        if job.status == JobStatus.COMPLETED.value:
            return

        job.status = JobStatus.PROCESSING.value
        job.error_message = None
        job.updated_at = _utcnow()
        db.commit()

        try:
            gdf = _load_geodata(job)
            job.feature_count = int(len(gdf))
            job.crs = gdf.crs.to_string() if gdf.crs is not None else None
            job.processed_features = 0
            job.successful_measurements = 0
            job.failed_features = 0
            db.commit()

            db.execute(delete(FeatureMeasurement).where(FeatureMeasurement.job_id == job.id))
            db.commit()

            for result in iter_measurements(gdf):
                record = FeatureMeasurement(
                    job_id=job.id,
                    feature_index=result.feature_index,
                    geometry_type=result.geometry_type,
                    source_crs=result.source_crs,
                    measurement_crs=result.measurement_crs,
                    measurement_type=result.measurement_type,
                    measurement_value=result.measurement_value,
                    measurement_unit=result.measurement_unit,
                    measurement_status=result.measurement_status,
                    properties_json=json.dumps(result.properties, ensure_ascii=False, default=str),
                    geometry_geojson=json.dumps(result.geometry_geojson, ensure_ascii=False, default=str)
                    if result.geometry_geojson is not None
                    else None,
                    error_message=result.error_message,
                )
                db.add(record)
                job.processed_features += 1
                if result.measurement_status == MeasurementStatus.MEASURED.value:
                    job.successful_measurements += 1
                elif result.measurement_status not in {MeasurementStatus.NOT_REQUIRED.value}:
                    job.failed_features += 1

                if job.processed_features % 50 == 0:
                    job.updated_at = _utcnow()
                    db.commit()

            job.updated_at = _utcnow()
            job.processed_at = _utcnow()
            if job.failed_features > 0:
                job.status = JobStatus.COMPLETED_WITH_ERRORS.value
            else:
                job.status = JobStatus.COMPLETED.value
            db.commit()
        except Exception as exc:
            db.rollback()
            job = db.get(FileJob, job_id)
            if job is not None:
                job.status = JobStatus.FAILED.value
                job.error_message = str(exc)
                job.updated_at = _utcnow()
                job.processed_at = _utcnow()
                db.commit()
        finally:
            _cleanup_extracted(job_id)
    finally:
        db.close()


def claim_next_job(db: Session) -> str | None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        with db.begin():
            stmt = (
                select(FileJob)
                .where(FileJob.status == JobStatus.QUEUED.value)
                .order_by(FileJob.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            job = db.execute(stmt).scalars().first()
            if job is None:
                return None
            job.status = JobStatus.PROCESSING.value
            job.updated_at = _utcnow()
            return job.id

    # SQLite fallback: single-process/local development queue.
    job = (
        db.execute(
            select(FileJob)
            .where(FileJob.status == JobStatus.QUEUED.value)
            .order_by(FileJob.created_at)
            .limit(1)
        )
        .scalars()
        .first()
    )
    if job is None:
        return None
    job.status = JobStatus.PROCESSING.value
    job.updated_at = _utcnow()
    db.commit()
    return job.id


def worker_loop(stop_event) -> None:
    import time

    while not stop_event.is_set():
        db = SessionLocal()
        try:
            job_id = claim_next_job(db)
        finally:
            db.close()
        if job_id:
            process_job(job_id)
            continue
        stop_event.wait(settings.worker_poll_seconds)
