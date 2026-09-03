from __future__ import annotations

import math
from datetime import datetime

from .models import MemoryRecord, RecallState, clamp


def retrieval_score(memory: MemoryRecord, now: datetime) -> float:
    """Ebbinghaus-inspired accessibility, modified by salience and interference."""

    elapsed_days = max(0.0, (now - memory.last_recalled_at).total_seconds() / 86400)
    decay = math.exp(-elapsed_days / memory.stability_days)
    salience_support = 0.15 * memory.salience + 0.10 * memory.emotional_intensity
    interference_penalty = 0.35 * memory.interference
    return clamp(memory.base_accessibility * decay + salience_support - interference_penalty)


def classify_recall(memory: MemoryRecord, now: datetime) -> RecallState:
    score = retrieval_score(memory, now)
    if score >= 0.65:
        return RecallState.ACCURATE
    if score >= 0.25:
        return RecallState.VAGUE
    return RecallState.INACCESSIBLE


def rehearse(memory: MemoryRecord, now: datetime, reminded: bool = False) -> None:
    """Retrieval reconsolidates memory; a reminder restores access without faking certainty."""

    memory.repetitions += 1
    memory.last_recalled_at = now
    memory.stability_days *= 1.18 + 0.12 * memory.salience
    memory.base_accessibility = 0.90 if reminded else 1.0
    if reminded:
        memory.confidence = min(memory.confidence, 0.85)
