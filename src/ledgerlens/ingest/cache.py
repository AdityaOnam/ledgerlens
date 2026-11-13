"""On-disk cache of model responses, one JSON file per request.

The key is a hash of everything that shapes the answer: model, prompt version, schema and the
document itself. Re-running an audit therefore costs nothing and gives the same facts, and
changing the prompt or model naturally misses the cache instead of serving stale readings.
Only the parsed model output is stored, never credentials or request headers.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def cache_key(**parts: Any) -> str:
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None  # a torn or hand-edited entry is treated as a miss
        return data if isinstance(data, dict) else None

    def put(self, key: str, data: dict[str, Any]) -> None:
        """Write atomically, so an interrupted run never leaves half a file behind."""
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=1, sort_keys=True, ensure_ascii=False)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
