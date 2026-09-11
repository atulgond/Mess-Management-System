"""Watcher agent: compares new observations against history and raises alerts.

History is a list of observations ordered by `observed_at`. Rules come from alerts.yaml.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..models import Alert, Observation


def _key(o: Observation) -> tuple[str, str]:
    return (o.store, o.product_id)


def _by_product(history: Iterable[Observation]) -> dict[tuple[str, str], list[Observation]]:
    out: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for o in history:
        out[_key(o)].append(o)
    for v in out.values():
        v.sort(key=lambda o: o.observed_at)
    return out


def rule_drop_pct(prev: Observation, cur: Observation, pct: float) -> Alert | None:
    if prev.price_cents is None or cur.price_cents is None:
        return None
    if cur.price_cents >= prev.price_cents:
        return None
    drop = (prev.price_cents - cur.price_cents) / prev.price_cents * 100
    if drop >= pct:
        return Alert(store=cur.store, product_id=cur.product_id, rule="drop_pct",
                     message=f"{cur.name or cur.product_id}: {prev.price_cents} -> {cur.price_cents} ({drop:.1f}% drop)",
                     previous_cents=prev.price_cents, current_cents=cur.price_cents, observed_at=cur.observed_at)
    return None


def evaluate(history: list[Observation], new: list[Observation], rules: list[dict]) -> list[Alert]:
    """Evaluate `rules` for each observation in `new` against `history` (which must not include `new`)."""
    alerts: list[Alert] = []
    hist = _by_product(history)
    for cur in sorted(new, key=lambda o: o.observed_at):
        prior = hist.get(_key(cur), [])
        prev = prior[-1] if prior else None
        for rule in rules:
            if rule.get("type") == "drop_pct" and prev is not None:
                a = rule_drop_pct(prev, cur, float(rule.get("pct", 10)))
                if a:
                    alerts.append(a)
            # TODO(stage 2): below_median rule
        hist[_key(cur)] = prior + [cur]
    return alerts
