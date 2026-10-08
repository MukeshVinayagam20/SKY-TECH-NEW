
"""Tiny disk cache: the same document / profile / language is never sent to the AI twice.
Results are stored as JSON in the ".cache" folder. Delete that folder to clear it."""
import hashlib, json
from pathlib import Path
from pydantic import BaseModel

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def make_key(*parts) -> str:
    h = hashlib.sha256()
    for p in parts:
        if isinstance(p, BaseModel):
            p = p.model_dump_json()
        elif not isinstance(p, (bytes, str)):
            p = json.dumps(p, sort_keys=True, default=str)
        h.update(p if isinstance(p, bytes) else p.encode("utf-8"))
    return h.hexdigest()[:24]


def load(kind: str, key: str, model_cls: type[BaseModel]):
    path = CACHE_DIR / f"{kind}_{key}.json"
    if path.exists():
        try:
            return model_cls.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def save(kind: str, key: str, obj: BaseModel):
    CACHE_DIR.mkdir(exist_ok=True)
    (CACHE_DIR / f"{kind}_{key}.json").write_text(obj.model_dump_json(), encoding="utf-8")