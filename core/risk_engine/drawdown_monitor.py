"""core/risk_engine/drawdown_monitor.py — 3-stage drawdown protocol."""
from __future__ import annotations

# Stage config: thresholds and risk caps
_STAGE_CFG = {
    0: {"threshold": 0.0,  "risk_cap": None,  "trading_allowed": True,  "block_reason": None},
    1: {"threshold": 10.0, "risk_cap": 0.005, "trading_allowed": True,  "block_reason": "Stage 1: risk capped at 0.5%"},
    2: {"threshold": 12.0, "risk_cap": 0.0025,"trading_allowed": True,  "block_reason": "Stage 2: risk capped at 0.25%"},
    3: {"threshold": 15.0, "risk_cap": 0.0,   "trading_allowed": False, "block_reason": "Stage 3: trading paused (DD ≥ 15%)"},
}


def _classify_stage(dd_pct: float) -> int:
    if dd_pct >= _STAGE_CFG[3]["threshold"]: return 3
    if dd_pct >= _STAGE_CFG[2]["threshold"]: return 2
    if dd_pct >= _STAGE_CFG[1]["threshold"]: return 1
    return 0


async def _apply_stage(user_id: str, stage: int, dd_pct: float, db) -> None:
    cfg = _STAGE_CFG[stage]
    await db.execute(
        """UPDATE risk_state
           SET drawdown_stage=$1, trading_allowed=$2, block_reason=$3, updated_at=NOW()
           WHERE user_id=$4::uuid AND date=CURRENT_DATE""",
        stage, cfg["trading_allowed"], cfg["block_reason"], user_id,
    )


async def evaluate_drawdown(user_id: str, db) -> dict:
    row = await db.fetchrow(
        """SELECT total_drawdown_pct, drawdown_stage, trading_allowed, block_reason
           FROM risk_state WHERE user_id=$1::uuid AND date=CURRENT_DATE""",
        user_id,
    )
    if not row:
        return {
            "user_id": user_id, "drawdown_pct": 0.0, "stage": 0,
            "stage_changed": False, "trading_allowed": True, "block_reason": None,
        }

    dd_pct        = float(row["total_drawdown_pct"] or 0)
    current_stage = int(row["drawdown_stage"] or 0)
    new_stage     = _classify_stage(dd_pct)
    stage_changed = new_stage != current_stage

    if stage_changed:
        await _apply_stage(user_id, new_stage, dd_pct, db)

    cfg = _STAGE_CFG[new_stage]
    return {
        "user_id":         user_id,
        "drawdown_pct":    dd_pct,
        "stage":           new_stage,
        "stage_changed":   stage_changed,
        "trading_allowed": cfg["trading_allowed"],
        "block_reason":    cfg["block_reason"],
    }
