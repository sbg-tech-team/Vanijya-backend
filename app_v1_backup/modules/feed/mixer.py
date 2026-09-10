"""
Feed Mixer — Weighted random slot assignment with consecutive-cap constraints.

Algorithm per slot:
  1. Build eligible types: have candidates AND below consecutive cap.
  2. Normalise eligible weights to sum 1.0.
  3. Random pick via cumulative weight band.
  4. Pull next item from chosen type's pool.
  5. Update consecutive counters.
  6. Exhausted types are dropped; weights redistributed automatically.
"""
from __future__ import annotations

import random
from typing import Optional

from app.modules.feed.schemas import FeedItem

# Max consecutive items per content type before forced break
MAX_CONSECUTIVE: dict[str, int] = {
    "post": 3,
    "news": 2,
    "group": 1,
    "connection": 1,
}

PAGE_SIZE = 20

# Queue-to-feed transition threshold: when ≤ 3 priority items remain,
# interleave standard items every 3rd slot.
TRANSITION_THRESHOLD = 3


def mix_feed(
    candidates: dict[str, list[FeedItem]],
    weights: dict[str, float],
    priority_pins: list[FeedItem],
    page_size: int = PAGE_SIZE,
) -> list[FeedItem]:
    """
    Produce a single feed page.

    Priority pins are prepended. If ≤ TRANSITION_THRESHOLD pins remain,
    they are interleaved (every 3rd slot) with mixer output.
    """
    remaining_pins = list(priority_pins)
    mixed = _run_mixer(candidates, weights, page_size)

    if len(remaining_pins) > TRANSITION_THRESHOLD:
        # All pins first, then mixed
        result = remaining_pins + mixed
        return result[:page_size]
    else:
        # Interleave: pin every 3rd slot, rest from mixed
        return _interleave(remaining_pins, mixed, page_size)


def _run_mixer(
    candidates: dict[str, list[FeedItem]],
    weights: dict[str, float],
    page_size: int,
) -> list[FeedItem]:
    pools: dict[str, list[FeedItem]] = {ct: list(items) for ct, items in candidates.items()}
    consecutive: dict[str, int] = {ct: 0 for ct in pools}
    result: list[FeedItem] = []

    for _ in range(page_size):
        eligible = {
            ct: w
            for ct, w in weights.items()
            if pools.get(ct) and consecutive.get(ct, 0) < MAX_CONSECUTIVE.get(ct, 1)
        }
        if not eligible:
            # Relax consecutive caps and retry with any non-empty pool
            eligible = {ct: w for ct, w in weights.items() if pools.get(ct)}
        if not eligible:
            break

        # Normalise
        total = sum(eligible.values())
        norm = {ct: w / total for ct, w in eligible.items()}

        chosen = _weighted_choice(norm)
        item = pools[chosen].pop(0)
        result.append(item)

        # Update consecutive counters
        for ct in consecutive:
            consecutive[ct] = consecutive[ct] + 1 if ct == chosen else 0

    return result


def _weighted_choice(norm: dict[str, float]) -> str:
    r = random.random()
    cumulative = 0.0
    for ct, w in norm.items():
        cumulative += w
        if r < cumulative:
            return ct
    return list(norm.keys())[-1]


def _interleave(
    pins: list[FeedItem],
    mixed: list[FeedItem],
    page_size: int,
) -> list[FeedItem]:
    """Insert a pin every 3rd slot (slots 2, 5, 8 …) until pins exhausted."""
    result: list[FeedItem] = []
    pin_iter = iter(pins)
    mix_iter = iter(mixed)
    slot = 0

    while len(result) < page_size:
        slot += 1
        if slot % 3 == 0:
            pin = next(pin_iter, None)
            if pin:
                result.append(pin)
                continue
        item = next(mix_iter, None)
        if item is None:
            # Drain remaining pins
            for p in pin_iter:
                if len(result) < page_size:
                    result.append(p)
            break
        result.append(item)

    return result[:page_size]
