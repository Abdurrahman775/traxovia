"""api/routes/data_management.py — Admin-only historical data upload endpoint."""

import logging
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form

from database.connection import get_db
from api.auth import get_current_user
from data_engine.csv_loader import load_file, VALID_PAIRS, TABLE_MAP

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/data", tags=["admin"])

VALID_TIMEFRAMES = set(TABLE_MAP.keys())
MAX_UPLOAD_MB    = 150


def _require_admin(user):
    if not user.get("is_admin") and user.get("plan") != "elite":
        raise HTTPException(403, "Admin access required")


@router.get("/info")
async def data_info(
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """Return row counts per pair/timeframe for the admin coverage table."""
    _require_admin(user)

    pairs  = sorted(VALID_PAIRS)
    result = {}

    for tf, table in TABLE_MAP.items():
        counts = {}
        for pair in pairs:
            try:
                n = await db.fetchval(
                    f"SELECT COUNT(*) FROM {table} WHERE symbol=$1", pair
                )
                counts[pair] = int(n or 0)
            except Exception:
                counts[pair] = -1
        result[tf] = counts

    return {
        "timeframes":       result,
        "valid_pairs":      pairs,
        "valid_timeframes": sorted(VALID_TIMEFRAMES),
    }


@router.post("/upload")
async def upload_csv(
    pair:      Annotated[str, Form()],
    timeframe: Annotated[str, Form()],
    file:      UploadFile = File(...),
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """
    Upload a single historical CSV and import it into TimescaleDB.
    Max 150 MB. Duplicate rows are skipped (ON CONFLICT DO NOTHING).
    """
    _require_admin(user)

    pair      = pair.strip().upper()
    timeframe = timeframe.strip().upper()

    if pair not in VALID_PAIRS:
        raise HTTPException(400, f"Invalid pair '{pair}'. Valid: {sorted(VALID_PAIRS)}")
    if timeframe not in VALID_TIMEFRAMES:
        raise HTTPException(400, f"Invalid timeframe '{timeframe}'. Valid: {sorted(VALID_TIMEFRAMES)}")
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "File must be a .csv")

    MAX_BYTES = MAX_UPLOAD_MB * 1024 * 1024
    content   = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB} MB limit")

    suffix = f"_{pair}_{timeframe}.csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        # db is an asyncpg.Connection — pass it directly to load_file
        result = await load_file(db, tmp_path, pair, timeframe)
    except Exception as exc:
        logger.exception("CSV upload failed: %s", exc)
        raise HTTPException(500, f"Import error: {exc}")
    finally:
        tmp_path.unlink(missing_ok=True)

    if not result["ok"]:
        raise HTTPException(422, result["error"])

    return {
        "pair":          result["pair"],
        "timeframe":     result["tf"],
        "rows_read":     result["rows_read"],
        "rows_inserted": result["rows_inserted"],
        "already_in_db": result["rows_read"] - result["rows_inserted"],
        "bad_rows":      result.get("bad_rows", 0),
    }
