"""core/ai_engine/model_manager.py — Model registry with in-memory cache."""
from __future__ import annotations
import logging
import pickle
from typing import Any

logger = logging.getLogger(__name__)

_ACTIVE_VERSION_QUERY = """
    SELECT id, model_path, oos_sharpe, oos_win_rate, trained_at
    FROM   model_versions WHERE active = TRUE LIMIT 1
"""
_VERSION_BY_ID_QUERY = """
    SELECT id, model_path, oos_sharpe, oos_win_rate, trained_at
    FROM   model_versions WHERE id = %s
"""
_ARCHIVE_QUERY  = "UPDATE model_versions SET active = FALSE WHERE active = TRUE"
_ACTIVATE_QUERY = "UPDATE model_versions SET active = TRUE  WHERE id = %s"


class ModelManager:
    def __init__(self) -> None:
        self._cache: dict[int, Any] = {}

    def get_model(self, user_id: str | None = None) -> Any:
        meta = self.get_active_version()
        if meta is None:
            raise RuntimeError("No active model found in model_versions.")
        vid = meta["id"]
        if vid in self._cache:
            return self._cache[vid]
        model = self._load_artifact(meta["model_path"])
        self._cache[vid] = model
        return model

    def get_active_version(self) -> dict | None:
        from database.sync_connection import get_sync_db
        with get_sync_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_ACTIVE_VERSION_QUERY)
                row = cur.fetchone()
        if row is None:
            return None
        return {"id": int(row[0]), "model_path": str(row[1]),
                "oos_sharpe": float(row[2]), "oos_win_rate": float(row[3]),
                "trained_at": row[4]}

    def rollback(self, version_id: int) -> None:
        from database.sync_connection import get_sync_db
        with get_sync_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_VERSION_BY_ID_QUERY, (version_id,))
                row = cur.fetchone()
        if row is None:
            raise ValueError(f"rollback: version {version_id} not found")
        with get_sync_db() as conn:
            with conn.cursor() as cur:
                cur.execute(_ARCHIVE_QUERY)
                cur.execute(_ACTIVATE_QUERY, (version_id,))
            conn.commit()
        self._cache.clear()

    @staticmethod
    def _load_artifact(model_path: str) -> Any:
        with open(model_path, "rb") as fh:
            return pickle.load(fh)


_singleton: ModelManager | None = None

def get_active_model() -> Any:
    global _singleton
    if _singleton is None:
        _singleton = ModelManager()
    return _singleton.get_model()
