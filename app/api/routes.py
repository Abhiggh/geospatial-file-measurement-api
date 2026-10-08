from __future__ import annotations

import json
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import FeatureMeasurement, FileJob
from ..schemas import FileInfoResponse, MeasurementItem, MeasurementPage, UploadResponse
from ..services.storage import persist_upload

router = APIRouter(prefix="/api", tags=["files"])
settings = get_settings()


@router.post("/files/", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_file(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    import uuid

    job_id = str(uuid.uuid4())
    source_type, stored_path, size = await persist_upload(file, job_id)

    job = FileJob(
        id=job_id,
        filename=Path(file.filename or stored_path.name).name,
        source_type=source_type,
        stored_path=str(stored_path),
        status="QUEUED",
        source_size_bytes=size,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if settings.embedded_worker and not getattr(request.app.state, "testing", False):
        from ..services.processing import process_job

        thread = threading.Thread(target=process_job, args=(job_id,), daemon=True)
        thread.start()

    return UploadResponse(
        id=job.id,
        filename=job.filename,
        status=job.status,
        message="File accepted for processing.",
    )


@router.get("/files/{file_id}/", response_model=FileInfoResponse)
def get_file_info(file_id: str, db: Session = Depends(get_db)):
    job = db.get(FileJob, file_id)
    if job is None:
        raise HTTPException(status_code=404, detail="File not found.")
    return FileInfoResponse.model_validate(job)


@router.get("/files/{file_id}/measurements/", response_model=MeasurementPage)
def get_measurements(
    file_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    include_geometry: bool = Query(False),
    db: Session = Depends(get_db),
):
    job = db.get(FileJob, file_id)
    if job is None:
        raise HTTPException(status_code=404, detail="File not found.")

    base = select(FeatureMeasurement).where(FeatureMeasurement.job_id == file_id).order_by(FeatureMeasurement.feature_index)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.offset((page - 1) * page_size).limit(page_size)).scalars().all()

    items: list[MeasurementItem] = []
    for row in rows:
        try:
            props = json.loads(row.properties_json)
        except json.JSONDecodeError:
            props = {}
        geometry = None
        if include_geometry and row.geometry_geojson:
            try:
                geometry = json.loads(row.geometry_geojson)
            except json.JSONDecodeError:
                geometry = None
        items.append(
            MeasurementItem(
                feature_index=row.feature_index,
                geometry_type=row.geometry_type,
                source_crs=row.source_crs,
                measurement_crs=row.measurement_crs,
                measurement_type=row.measurement_type,
                measurement_value=row.measurement_value,
                measurement_unit=row.measurement_unit,
                measurement_status=row.measurement_status,
                properties=props,
                geometry=geometry,
                error_message=row.error_message,
            )
        )

    return MeasurementPage(file_id=file_id, page=page, page_size=page_size, total=total, items=items)


@router.get("/files/{file_id}/geojson/")
def get_geojson(
    file_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    db: Session = Depends(get_db),
):
    job = db.get(FileJob, file_id)
    if job is None:
        raise HTTPException(status_code=404, detail="File not found.")

    stmt = (
        select(FeatureMeasurement)
        .where(FeatureMeasurement.job_id == file_id)
        .order_by(FeatureMeasurement.feature_index)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = db.execute(stmt).scalars().all()
    features = []
    for row in rows:
        if not row.geometry_geojson:
            continue
        try:
            geometry = json.loads(row.geometry_geojson)
        except json.JSONDecodeError:
            continue
        try:
            props = json.loads(row.properties_json)
        except json.JSONDecodeError:
            props = {}
        props.update(
            {
                "feature_index": row.feature_index,
                "geometry_type": row.geometry_type,
                "measurement_type": row.measurement_type,
                "measurement_value": row.measurement_value,
                "measurement_unit": row.measurement_unit,
                "measurement_status": row.measurement_status,
            }
        )
        features.append({"type": "Feature", "geometry": geometry, "properties": props})
    return {"type": "FeatureCollection", "features": features}
