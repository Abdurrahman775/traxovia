"""core/ai_engine/model_predictor.py — XGBoost inference with confidence tiers."""
from __future__ import annotations
import numpy as np
from core.ai_engine.feature_engineer import FEATURE_NAMES
from core.ai_engine.model_manager import ModelManager


class ModelPredictor:
    def __init__(self, manager: ModelManager | None = None):
        self._manager = manager or ModelManager()

    def predict(self, features: dict) -> dict:
        model   = self._manager.get_model()
        version = self._manager.get_active_version()
        X       = np.array([[float(features.get(k, 0.0)) for k in FEATURE_NAMES]])
        proba   = model.predict_proba(X)[0]
        prob    = float(proba[1]) if len(proba) > 1 else float(proba[0])

        if prob >= 0.70:
            tier = "high"
        elif prob >= 0.55:
            tier = "medium"
        else:
            tier = "low"

        importances = getattr(model, "feature_importances_", np.zeros(len(FEATURE_NAMES)))
        top_features = sorted(
            zip(FEATURE_NAMES, importances.tolist()),
            key=lambda x: x[1], reverse=True,
        )[:5]

        return {
            "signal_probability": prob,
            "confidence_tier":    tier,
            "top_features":       top_features,
            "model_version":      version.get("id") if version else None,
        }
