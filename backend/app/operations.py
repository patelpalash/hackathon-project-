"""Persistent manual observations, operational events and manager decisions."""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock

LOCK = RLock()
def parse(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Date/time must include a timezone")
    return result.astimezone(timezone.utc)

class Operations:
    def __init__(self):
        self.path = Path(os.environ.get("STORE_DIR", "store")) / "operations.json"
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {"weather": [], "events": [], "decisions": [], "revision": 0}
    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)
    def put(self, kind, record, record_id=None):
        with LOCK:
            row = {**record, "id": record_id or uuid.uuid4().hex[:12], "updated_at": datetime.now(timezone.utc).isoformat()}
            self.data[kind] = [r for r in self.data[kind] if r["id"] != row["id"]] + [row]
            if kind != "decisions": self.data["revision"] += 1
            self.save()
            return row
    def remove(self, kind, record_id):
        with LOCK:
            self.data[kind] = [r for r in self.data[kind] if r["id"] != record_id]
            self.data["revision"] += 1
            self.save()
    def overlaps(self, record, start, end):
        return parse(record["start"]) < end and parse(record["end"]) > start
    def snapshot(self):
        with LOCK:
            return json.loads(json.dumps(self.data))
