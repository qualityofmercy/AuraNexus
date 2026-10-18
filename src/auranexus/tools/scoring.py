"""Rubric scoring: weights/thresholds live in config/rubrics/*.yaml and are frozen before first use."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def load_rubric(config_dir: Path, name: str) -> dict[str, Any]:
    return yaml.safe_load((config_dir / "rubrics" / f"{name}.yaml").read_text(encoding="utf-8"))


def rubric_hash(rubric: dict[str, Any]) -> str:
    keep = {k: rubric[k] for k in ("weights", "thresholds", "overrides", "profile_weights") if k in rubric}
    return hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest()[:16]


def effective_weights(rubric: dict[str, Any], profile: str | None) -> dict[str, float]:
    w = dict(rubric["weights"])
    w.update((rubric.get("profile_weights") or {}).get(profile or "", {}))
    total = sum(w.values())
    if abs(total - 100) > 1e-6:
        raise ValueError(f"rubric weights must sum to 100, got {total}")
    return w


def weighted_total(scores: dict[str, float], weights: dict[str, float]) -> float:
    missing = set(weights) - set(scores)
    if missing:
        raise ValueError(f"missing dimension scores: {sorted(missing)}")
    return round(sum(max(0.0, min(100.0, float(scores[d]))) * w / 100.0 for d, w in weights.items()), 1)


def rate(total: float, thresholds: dict[str, float], forced_red: list[str]) -> str:
    if forced_red:
        return "Red"
    if total >= thresholds["green"]:
        return "Green"
    if total >= thresholds["amber"]:
        return "Amber"
    return "Red"


def drivers(scores: dict[str, float], weights: dict[str, float], n: int = 3) -> dict[str, list[dict]]:
    """Top-n positive and negative drivers by weighted distance from a neutral 75."""
    contrib = [
        {"dimension": d, "score": scores[d], "weight": w, "impact": round((scores[d] - 75) * w / 100, 2)}
        for d, w in weights.items()
    ]
    return {
        "positive": sorted((c for c in contrib if c["impact"] > 0), key=lambda c: -c["impact"])[:n],
        "negative": sorted((c for c in contrib if c["impact"] < 0), key=lambda c: c["impact"])[:n],
    }
