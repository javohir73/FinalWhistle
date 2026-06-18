"""Gradient-boosted W/D/L challenger (spec 2026-06-18).

A thin wrapper over scikit-learn's HistGradientBoostingClassifier (histogram
gradient boosting — the same technique as XGBoost, but already a dependency, no
native libs, free-tier-Render-safe). It outputs ONLY a W/D/L triple; it never
produces scorelines. Trained on leak-free rows from
ml.features.training_rows.build_training_rows.
"""
from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from ml.features.wdl_features import to_vector

CLASSES = ("H", "D", "A")
_SEED = 2026


class WdlBoost:
    def __init__(self, **kwargs):
        # Conservative, fast defaults; international football is low-signal so we
        # keep the model shallow to avoid overfitting. early_stopping=True holds out
        # ~10% internally for validation — fine for the full-history training set we
        # use at serve/gate time (tens of thousands of rows). If ever trained on a
        # small corpus, pass early_stopping=False via kwargs.
        params = dict(
            loss="log_loss", learning_rate=0.05, max_iter=300,
            max_leaf_nodes=15, min_samples_leaf=50, l2_regularization=1.0,
            early_stopping=True, random_state=_SEED,
        )
        params.update(kwargs)
        self._clf = HistGradientBoostingClassifier(**params)
        self._fitted = False

    def fit(self, rows: list[dict], sample_weight: list[float] | None = None) -> "WdlBoost":
        """Train on rows that each carry the FEATURE_NAMES keys plus a 'label'."""
        X = np.array([to_vector(r) for r in rows], dtype=float)
        y = np.array([r["label"] for r in rows])
        sw = np.array(sample_weight, dtype=float) if sample_weight is not None else None
        self._clf.fit(X, y, sample_weight=sw)
        self._fitted = True
        return self

    def predict_proba(self, feats: dict) -> dict[str, float]:
        """Return {'H','D','A': prob}. Classes absent from training map to 0.0."""
        if not self._fitted:
            raise RuntimeError("model not fitted")
        row = np.array([to_vector(feats)], dtype=float)
        probs = self._clf.predict_proba(row)[0]
        by_class = {cls: float(probs[i]) for i, cls in enumerate(self._clf.classes_)}
        return {c: by_class.get(c, 0.0) for c in CLASSES}


def blend_triples(
    a: tuple[float, float, float], b: tuple[float, float, float], weight: float
) -> tuple[float, float, float]:
    """Convex blend (1-weight)*a + weight*b over a W/D/L triple, renormalized."""
    mixed = [(1.0 - weight) * ai + weight * bi for ai, bi in zip(a, b)]
    total = sum(mixed) or 1.0
    return (mixed[0] / total, mixed[1] / total, mixed[2] / total)
