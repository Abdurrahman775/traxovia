"""core/ai_engine/model_trainer.py — Walk-forward XGBoost trainer."""
from __future__ import annotations
import json
import os
import pickle
import tempfile
from datetime import datetime

from core.ai_engine.feature_engineer import FEATURE_NAMES

MIN_SAMPLES = 50


class WalkForwardTrainer:
    def __init__(self, models_dir: str = "models"):
        self.models_dir = models_dir
        os.makedirs(models_dir, exist_ok=True)

    def run(self) -> dict:
        from database.sync_connection import get_sync_db
        with get_sync_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ai_features, outcome, pnl_r FROM feature_store "
                    "WHERE outcome IS NOT NULL ORDER BY created_at"
                )
                rows = cur.fetchall()

        if len(rows) < MIN_SAMPLES:
            raise ValueError(
                f"Insufficient training data: {len(rows)} samples. "
                f"Minimum {MIN_SAMPLES} required."
            )

        import numpy as np
        X, y = [], []
        for feat_json, outcome, _ in rows:
            feat = json.loads(feat_json) if isinstance(feat_json, str) else feat_json
            X.append([float(feat.get(k, 0.0)) for k in FEATURE_NAMES])
            y.append(1 if outcome == "win" else 0)

        X = np.array(X)
        y = np.array(y)

        try:
            import xgboost as xgb
            model = xgb.XGBClassifier(n_estimators=100, max_depth=4, use_label_encoder=False, eval_metric="logloss")
        except ImportError:
            from sklearn.ensemble import GradientBoostingClassifier
            model = GradientBoostingClassifier(n_estimators=100, max_depth=4)

        split   = int(len(X) * 0.8)
        X_train, X_test = X[:split], X[split:]
        y_train, y_test = y[:split], y[split:]
        model.fit(X_train, y_train)

        oos_wr     = float((model.predict(X_test) == y_test).mean()) if len(X_test) > 0 else 0.0
        oos_sharpe = round(oos_wr * 2 - 0.5, 2)  # simplified proxy

        version    = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        model_path = os.path.join(self.models_dir, f"xgboost_{version}.pkl")
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        return {
            "version":    version,
            "model_path": model_path,
            "oos_sharpe": oos_sharpe,
            "oos_wr":     oos_wr,
            "samples":    len(rows),
        }
