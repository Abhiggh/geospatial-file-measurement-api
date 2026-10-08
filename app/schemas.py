from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class UploadResponse(BaseModel):
    id: str
    filename: str
    status: str
    message: str


class FileInfoResponse(BaseModel):
    id: str
    filename: str
    source_type: str
    feature_count: int | None
    crs: str | None
    status: str
    source_size_bytes: int
    processed_features: int
    successful_measurements: int
    failed_features: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class MeasurementItem(BaseModel):
    feature_index: int
    geometry_type: str
    source_crs: str | None
    measurement_crs: str | None
    measurement_type: str | None
    measurement_value: float | None
    measurement_unit: str | None
    measurement_status: str
    properties: dict[str, Any]
    geometry: dict[str, Any] | None = None
    error_message: str | None = None


class MeasurementPage(BaseModel):
    file_id: str
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    items: list[MeasurementItem]
