from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from ..config import get_settings

settings = get_settings()

ALLOWED_EXTENSIONS = {".kml", ".zip"}


def ensure_storage_dirs() -> None:
    (settings.storage_dir / "uploads").mkdir(parents=True, exist_ok=True)
    (settings.storage_dir / "extracted").mkdir(parents=True, exist_ok=True)


def safe_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def _safe_zip_members(zf: zipfile.ZipFile) -> tuple[list[zipfile.ZipInfo], int]:
    members = zf.infolist()
    if len(members) > settings.max_archive_members:
        raise HTTPException(status_code=413, detail="ZIP archive contains too many entries.")

    total_uncompressed = 0
    files: list[zipfile.ZipInfo] = []
    for member in members:
        normalized = Path(member.filename)
        if member.is_dir():
            continue
        if normalized.is_absolute() or ".." in normalized.parts:
            raise HTTPException(status_code=400, detail="ZIP archive contains an unsafe path.")
        total_uncompressed += member.file_size
        if total_uncompressed > settings.max_extracted_size_bytes:
            raise HTTPException(status_code=413, detail="ZIP archive expands beyond the configured extraction limit.")
        files.append(member)
    return files, total_uncompressed


def validate_shapefile_archive(archive_path: Path) -> str:
    try:
        with zipfile.ZipFile(archive_path) as zf:
            if zf.testzip() is not None:
                raise HTTPException(status_code=400, detail="ZIP archive is corrupted.")
            members, _ = _safe_zip_members(zf)
            shp_members = [m.filename for m in members if Path(m.filename).suffix.lower() == ".shp"]
            if len(shp_members) != 1:
                raise HTTPException(status_code=400, detail="ZIP must contain exactly one .shp file.")
            shp_path = Path(shp_members[0])
            shp_stem = shp_path.stem.lower()
            parent = shp_path.parent
            siblings = {Path(m.filename).name.lower() for m in members if Path(m.filename).parent == parent}
            expected = {f"{shp_stem}.shp", f"{shp_stem}.shx", f"{shp_stem}.dbf"}
            missing = expected - siblings
            if missing:
                raise HTTPException(status_code=400, detail=f"Shapefile ZIP is missing required file(s): {', '.join(sorted(missing))}")
            return shp_members[0]
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded ZIP file is not valid.") from exc


def extract_shapefile_archive(archive_path: Path, job_id: str) -> Path:
    target = settings.storage_dir / "extracted" / job_id
    target.mkdir(parents=True, exist_ok=True)
    shp_member = validate_shapefile_archive(archive_path)

    try:
        with zipfile.ZipFile(archive_path) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                dest = (target / member.filename).resolve()
                if not str(dest).startswith(str(target.resolve()) + os.sep):
                    raise HTTPException(status_code=400, detail="ZIP archive contains an unsafe path.")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, dest.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Uploaded ZIP file is not valid.") from exc

    extracted_shp = target / shp_member
    if not extracted_shp.exists():
        # The path can include folders; Path handles this consistently.
        extracted_shp = next(target.rglob(Path(shp_member).name), None)
    if extracted_shp is None or not extracted_shp.exists():
        shutil.rmtree(target, ignore_errors=True)
        raise HTTPException(status_code=400, detail="Shapefile could not be extracted.")
    return extracted_shp


async def persist_upload(upload: UploadFile, job_id: str) -> tuple[str, Path, int]:
    ensure_storage_dirs()
    filename = Path(upload.filename or "upload").name
    extension = safe_extension(filename)
    if extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Only .kml or .zip files are supported.")

    safe_name = f"{uuid.uuid4().hex}_{filename}"
    destination = settings.storage_dir / "uploads" / job_id / safe_name
    destination.parent.mkdir(parents=True, exist_ok=True)

    size = 0
    try:
        with destination.open("wb") as buffer:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_size_bytes:
                    raise HTTPException(status_code=413, detail="Uploaded file exceeds the configured size limit.")
                buffer.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()

    if extension == ".zip":
        validate_shapefile_archive(destination)
    return extension.lstrip("."), destination, size
