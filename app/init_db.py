"""Database bootstrap used by Docker Compose before API/worker startup."""

from __future__ import annotations

import time

from sqlalchemy import text

from .config import get_settings
from .db import SessionLocal, create_all_tables


def main() -> None:
    settings = get_settings()
    last_error: Exception | None = None

    for attempt in range(1, 31):
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
            db.close()
            create_all_tables()
            print("Database schema is ready.", flush=True)
            return
        except Exception as exc:  # pragma: no cover - exercised by container startup
            last_error = exc
            db.close()
            print(f"Database not ready (attempt {attempt}/30): {exc}", flush=True)
            time.sleep(min(2.0, 0.5 + attempt * 0.05))

    raise RuntimeError("Database initialization failed after 30 attempts.") from last_error


if __name__ == "__main__":
    main()
