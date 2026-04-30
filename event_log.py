"""Local append-only event log, one JSONL file per auction.

Not synced to Postgres: we want bid pings to stay cheap and private to
this machine. The file is the source of truth for the timeline UI
(auction page + report page)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EVENTS_DIR = Path("./data/events")
EVENTS_DIR.mkdir(parents=True, exist_ok=True)


def _path(auction_id: str) -> Path:
    return EVENTS_DIR / f"{auction_id}.jsonl"


def log_event(auction_id: str, event_type: str, **payload: Any) -> dict:
    event = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "type": event_type,
        **payload,
    }
    with open(_path(auction_id), "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")
    return event


def read_events(auction_id: str) -> list[dict]:
    p = _path(auction_id)
    if not p.exists():
        return []
    events: list[dict] = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def clear_events(auction_id: str) -> None:
    p = _path(auction_id)
    if p.exists():
        p.unlink()
