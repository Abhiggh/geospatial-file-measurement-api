"""Standalone database-backed worker.

Run with:
    python -m app.worker
Multiple worker processes can safely run against PostgreSQL because jobs are claimed
with SELECT ... FOR UPDATE SKIP LOCKED.
"""

from __future__ import annotations

import signal
import threading

from .services.processing import worker_loop


def main() -> None:
    stop_event = threading.Event()

    def stop_handler(signum, frame):  # noqa: ARG001
        stop_event.set()

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)
    worker_loop(stop_event)


if __name__ == "__main__":
    main()
