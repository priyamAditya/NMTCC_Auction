"""In-memory FIFO queue + daemon that writes to Postgres in the background.

The UI thread enqueues DB writes and returns immediately. A single worker
thread drains the queue in order and retries on transient failures. Ordering
is preserved strictly: a failing job is retried in place, not re-enqueued,
so jobs that depend on earlier ones (e.g. a record_sale that assumes its
auction row exists) never run out of order.

Tradeoff: this is in-memory only. If the process dies with un-flushed jobs,
those writes are lost. For a live auction where session state is the
source of truth anyway, this matches the existing failure mode.
"""
from __future__ import annotations

import atexit
import logging
import queue
import threading
import time
from typing import Any, Callable, Optional, Tuple

log = logging.getLogger("nmtcc.sync")

_MAX_RETRIES = 5
_RETRY_BACKOFF_S = (1, 2, 5, 10, 30)

_Job = Tuple[Callable[..., Any], tuple, dict]

_q: "queue.Queue[Optional[_Job]]" = queue.Queue()
_lock = threading.Lock()
_worker: Optional[threading.Thread] = None

_stats = {
    "enqueued": 0,
    "succeeded": 0,
    "retried": 0,
    "failed": 0,
    "last_error": None,
}


def _run_worker() -> None:
    log.info("nmtcc-db-sync worker started")
    while True:
        item = _q.get()
        if item is None:
            _q.task_done()
            log.info("nmtcc-db-sync worker stopping")
            return

        fn, args, kwargs = item
        attempts = 0
        while True:
            try:
                fn(*args, **kwargs)
                _stats["succeeded"] += 1
                break
            except Exception as e:  # noqa: BLE001
                _stats["last_error"] = f"{fn.__name__}: {e}"
                log.warning("sync job %s failed (attempt %d): %s", fn.__name__, attempts + 1, e)
                attempts += 1
                if attempts > _MAX_RETRIES:
                    _stats["failed"] += 1
                    log.error("giving up on sync job %s after %d attempts", fn.__name__, attempts)
                    break
                _stats["retried"] += 1
                delay = _RETRY_BACKOFF_S[min(attempts - 1, len(_RETRY_BACKOFF_S) - 1)]
                time.sleep(delay)
        _q.task_done()


def _ensure_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run_worker, daemon=True, name="nmtcc-db-sync")
            _worker.start()


def enqueue(fn: Callable[..., Any], *args, **kwargs) -> None:
    """Schedule fn(*args, **kwargs) to run on the background worker."""
    _ensure_worker()
    _q.put((fn, args, kwargs))
    _stats["enqueued"] += 1


def backlog() -> int:
    return _q.qsize()


def stats() -> dict:
    s = dict(_stats)
    s["backlog"] = _q.qsize()
    return s


def flush(timeout: float = 30.0) -> bool:
    """Block until the queue is drained. Returns True if drained within timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _q.empty():
            # A job may still be in flight; wait for task_done
            try:
                _q.join()
                return True
            except Exception:  # noqa: BLE001
                return False
        time.sleep(0.1)
    return _q.empty()


def _on_shutdown() -> None:
    # Best-effort drain on interpreter exit. Short timeout so we don't hang.
    try:
        flush(timeout=5.0)
    except Exception:  # noqa: BLE001
        pass


atexit.register(_on_shutdown)
