"""Alert priority helpers used by outbox dispatch policy."""

from __future__ import annotations

from models.pair_signal import PairSignal


def priority_tuple(signal: PairSignal) -> tuple[int, int, float, float]:
    """Higher tuple means send earlier under backpressure."""
    score = signal.confidence_score if signal.confidence_score is not None else -1
    return (
        1 if signal.is_hot else 0,
        int(score),
        abs(signal.change_pct),
        signal.observed_at.timestamp(),
    )


def sort_by_priority(signals: list[PairSignal]) -> list[PairSignal]:
    return sorted(signals, key=priority_tuple, reverse=True)

