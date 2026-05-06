"""
api/routes/model.py — Model version registry and retrain trigger.
"""
from fastapi import APIRouter, Depends, HTTPException
from database.connection import get_db
from api.auth import get_current_user

router = APIRouter(prefix="/model", tags=["model"])


def _require_admin(user):
    if user["plan"] not in {"elite"}:
        raise HTTPException(403, "Admin access required")


@router.get("/versions")
async def list_versions(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    rows = await db.fetch(
        """SELECT id, version, oos_sharpe, oos_win_rate, training_samples,
                  active, created_at
           FROM model_versions
           ORDER BY created_at DESC"""
    )
    return [
        {
            "version":   r["version"],
            "trained_at": r["created_at"].strftime("%b %d") if r["created_at"] else "—",
            "samples":   r["training_samples"] or 0,
            "oos_sharpe": float(r["oos_sharpe"]) if r["oos_sharpe"] else 0.0,
            "oos_wr":    round(float(r["oos_win_rate"]) * 100, 1) if r["oos_win_rate"] else 0.0,
            "is_active": r["active"],
        }
        for r in rows
    ]


@router.get("/shap")
async def get_shap_features(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    # Pull SHAP values from the most recent approved signal that has them
    row = await db.fetchrow(
        """SELECT shap_values FROM trade_signals
           WHERE shap_values IS NOT NULL
           ORDER BY created_at DESC LIMIT 1"""
    )
    if not row or not row["shap_values"]:
        return []
    import json
    data = row["shap_values"] if isinstance(row["shap_values"], dict) else json.loads(row["shap_values"])
    pos = data.get("pos", [])
    features = [
        {"feature": f, "importance": round(abs(v) * 10, 1), "delta": "+"}
        for f, v in pos[:6]
    ]
    return features


@router.post("/retrain")
async def trigger_retrain(user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "ai_model", "Manual retrain triggered via dashboard",
    )
    # Fire Celery task if available, otherwise return queued status
    try:
        from scheduler.tasks import retrain_model
        retrain_model.delay()
    except Exception:
        pass
    return {"status": "queued"}


@router.post("/rollback/{version}")
async def rollback_version(version: str, user=Depends(get_current_user), db=Depends(get_db)):
    _require_admin(user)
    row = await db.fetchrow("SELECT id FROM model_versions WHERE version=$1", version)
    if not row:
        raise HTTPException(404, f"Version {version} not found")
    async with db.transaction():
        await db.execute("UPDATE model_versions SET active=FALSE WHERE active=TRUE")
        await db.execute("UPDATE model_versions SET active=TRUE WHERE version=$1", version)
    await db.execute(
        "INSERT INTO audit_log(user_id, action, detail) VALUES($1,$2,$3)",
        user["sub"], "ai_model", f"Rolled back to model version {version}",
    )
    return {"status": "rolled_back", "version": version}
