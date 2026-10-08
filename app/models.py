from datetime import datetime, timezone
from enum import StrEnum

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS"
    FAILED = "FAILED"


class MeasurementStatus(StrEnum):
    MEASURED = "MEASURED"
    NOT_REQUIRED = "NOT_REQUIRED"
    UNSUPPORTED_GEOMETRY = "UNSUPPORTED_GEOMETRY"
    INVALID_GEOMETRY = "INVALID_GEOMETRY"
    MISSING_CRS = "MISSING_CRS"
    MEASUREMENT_ERROR = "MEASUREMENT_ERROR"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileJob(Base):
    __tablename__ = "file_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default=JobStatus.QUEUED.value)
    feature_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crs: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    processed_features: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    successful_measurements: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_features: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    measurements: Mapped[list["FeatureMeasurement"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", lazy="selectin"
    )


class FeatureMeasurement(Base):
    __tablename__ = "feature_measurements"
    __table_args__ = (
        Index("ix_feature_measurements_job_index", "job_id", "feature_index"),
        Index("ix_feature_measurements_job_status", "job_id", "measurement_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("file_jobs.id", ondelete="CASCADE"), nullable=False)
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    geometry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_crs: Mapped[str | None] = mapped_column(String(128), nullable=True)
    measurement_crs: Mapped[str | None] = mapped_column(String(128), nullable=True)
    measurement_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    measurement_unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    measurement_status: Mapped[str] = mapped_column(String(64), nullable=False)
    properties_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    geometry_geojson: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    job: Mapped[FileJob] = relationship(back_populates="measurements")
