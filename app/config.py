from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Geospatial Measurement API"
    app_env: str = "development"
    database_url: str = "sqlite:///./geospatial.db"
    storage_dir: Path = Path("./storage")
    max_upload_size_mb: int = Field(default=100, ge=1, le=2048)
    max_extracted_size_mb: int = Field(default=500, ge=1, le=4096)
    max_archive_members: int = Field(default=2000, ge=1, le=10000)
    default_page_size: int = Field(default=100, ge=1, le=500)
    max_page_size: int = Field(default=500, ge=1, le=5000)
    embedded_worker: bool = True
    worker_poll_seconds: float = Field(default=0.5, gt=0.05, le=10)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("storage_dir", mode="before")
    @classmethod
    def normalize_storage_dir(cls, value: str | Path) -> Path:
        return Path(value).expanduser()

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def max_extracted_size_bytes(self) -> int:
        return self.max_extracted_size_mb * 1024 * 1024


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
