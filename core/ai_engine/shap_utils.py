"""
core/ai_engine/shap_utils.py — SHAP importance helpers for the drift checker.
Called by scheduler/tasks.py::check_feature_drift (daily at 06:00 UTC).
"""
import json
from database.sync_connection import sync_fetchone, sync_fetchall


def get_current_shap_importance() -> dict[str, float]:
    """
    Returns a {feature_name: avg_abs_shap} dict from the most recent
    100 signals that have shap_values populated.
    """
    rows = sync_fetchall(
        """
        SELECT shap_values
        FROM trade_signals
        WHERE shap_values IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 100
        """
    )
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        try:
            payload = row["shap_values"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            for name, val in payload.get("pos", []) + payload.get("neg", []):
                totals[name] = totals.get(name, 0.0) + abs(float(val))
                counts[name] = counts.get(name, 0) + 1
        except Exception:
            continue
    return {f: totals[f] / counts[f] for f in totals}


def get_shap_importance_30d_avg() -> dict[str, float]:
    """
    Returns a {feature_name: avg_abs_shap} dict averaged over signals
    from the last 30 days (up to 500 rows).
    """
    rows = sync_fetchall(
        """
        SELECT shap_values
        FROM trade_signals
        WHERE shap_values IS NOT NULL
          AND created_at >= NOW() - INTERVAL '30 days'
        ORDER BY created_at DESC
        LIMIT 500
        """
    )
    totals: dict[str, float] = {}
    counts: dict[str, int] = {}
    for row in rows:
        try:
            payload = row["shap_values"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            for name, val in payload.get("pos", []) + payload.get("neg", []):
                totals[name] = totals.get(name, 0.0) + abs(float(val))
                counts[name] = counts.get(name, 0) + 1
        except Exception:
            continue
    return {f: totals[f] / counts[f] for f in totals}
