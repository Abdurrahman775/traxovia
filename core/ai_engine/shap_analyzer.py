"""
shap_analyzer.py — Async SHAP Calculation
CORRECTIONS APPLIED:
  [FIX-3] Celery tasks are synchronous workers. The original code called asyncpg
          async methods (db.fetchrow / db.execute) directly inside @app.task
          functions — this raises RuntimeError: no running event loop.

          Fix: All DB access inside Celery tasks is now done via the synchronous
          helper `get_sync_db()` (psycopg2). The WebSocket broadcast that must be
          async is wrapped with asyncio.run().
"""

import json
import asyncio
import pandas as pd
import shap

from celery import Celery
from database.sync_connection import get_sync_db          # synchronous psycopg2
from core.ai_engine.model_manager import get_active_model
from notifications.websocket_manager import websocket_manager

app = Celery('trading_ai')


def generate_plain_english_summary(top_pos: list, top_neg: list) -> str:
    """Convert SHAP feature lists into a human-readable explanation."""
    pos_str = ', '.join(f'{f} (+{v:.2f})' for f, v in top_pos)
    neg_str = ', '.join(f'{f} ({v:.2f})' for f, v in top_neg)
    parts = []
    if pos_str:
        parts.append(f'Boosted by: {pos_str}')
    if neg_str:
        parts.append(f'Held back by: {neg_str}')
    return '. '.join(parts) or 'No dominant features identified.'


@app.task
def calculate_shap_async(signal_id: str):
    """
    Celery task — runs in a sync worker.
    Calculates SHAP values for a signal and pushes result to dashboard via WebSocket.

    FIX-3: Uses get_sync_db() (psycopg2) for all DB calls inside the Celery worker.
           The asyncio.run() call at the end is safe here because Celery workers
           do NOT have a running event loop — asyncio.run() creates a fresh one.
    """
    # ── Synchronous DB access (psycopg2) ─────────────────────────────
    with get_sync_db() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT * FROM trade_signals WHERE id=%s', (signal_id,))
            row = cur.fetchone()
            if row is None:
                return  # Signal deleted before SHAP ran — safe to skip

            col_names = [desc[0] for desc in cur.description]
            signal    = dict(zip(col_names, row))

    # ── SHAP computation (CPU-bound, fine in sync Celery worker) ─────
    features    = json.loads(signal['ai_features'])
    model       = get_active_model()
    explainer   = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(pd.DataFrame([features]))[0]

    top_pos = [(f, float(v)) for f, v in zip(features.keys(), shap_values) if v > 0]
    top_neg = [(f, float(v)) for f, v in zip(features.keys(), shap_values) if v < 0]
    top_pos.sort(key=lambda x: x[1], reverse=True)
    top_neg.sort(key=lambda x: x[1])

    summary      = generate_plain_english_summary(top_pos[:3], top_neg[:2])
    shap_payload = json.dumps({'pos': top_pos[:5], 'neg': top_neg[:3]})

    # ── Write results back (sync) ─────────────────────────────────────
    with get_sync_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                'UPDATE trade_signals SET shap_values=%s, reasoning=%s WHERE id=%s',
                (shap_payload, summary, signal_id),
            )
        conn.commit()

    # ── Push WebSocket update (async) — FIX-3: wrapped with asyncio.run() ──
    # websocket_manager.broadcast_to_user is a coroutine.
    # asyncio.run() is correct here: Celery workers have no running event loop.
    asyncio.run(
        websocket_manager.broadcast_to_user(
            signal['user_id'],
            {
                'type':      'shap_ready',
                'signal_id': signal_id,
                'summary':   summary,
            },
        )
    )
