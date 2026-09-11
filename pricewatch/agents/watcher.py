"""Watcher agent: compares new observations against history and raises alerts.

History is a list of observations ordered by `observed_at`. Rules come from alerts.yaml.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
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


def _parse_iso(dstr: str) -> datetime:
    return datetime.fromisoformat(dstr.replace("Z", "+00:00"))


def rule_below_median(prior: list[Observation], cur: Observation, pct: float, window_days: int) -> Alert | None:
    if cur.price_cents is None:
        return None
        
    cutoff = _parse_iso(cur.observed_at) - timedelta(days=window_days)
    
    window_obs = [o for o in prior if _parse_iso(o.observed_at) >= cutoff and o.price_cents is not None]
    
    if len(window_obs) < 3:
        return None
        
    currencies = {o.currency for o in window_obs}
    currencies.add(cur.currency)
    if len(currencies) > 1:
        if cur.notes is None:
            cur.notes = []
        cur.notes.append("currency changed in window")
        return None
        
    prices = sorted([o.price_cents for o in window_obs])
    n = len(prices)
    if n % 2 == 1:
        median = prices[n // 2]
    else:
        median = (prices[n // 2 - 1] + prices[n // 2]) / 2.0
        
    threshold = median * (1 - pct / 100.0)
    
    if cur.price_cents <= threshold:
        return Alert(
            store=cur.store, 
            product_id=cur.product_id, 
            rule="below_median",
            message=f"{cur.name or cur.product_id}: {cur.price_cents} is below median {int(median)} by at least {pct}%",
            previous_cents=int(median), 
            current_cents=cur.price_cents, 
            observed_at=cur.observed_at
        )
    return None


def rule_drop_pct(prev: Observation, cur: Observation, pct: float) -> Alert | None:
    if prev.price_cents is None or cur.price_cents is None:
        return None
    if prev.pack_size != cur.pack_size:
        return None
    if prev.currency != cur.currency:
        return None
    if "stale price" in (cur.notes or []) or "stale price" in (prev.notes or []):
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
        
        valid_priors = [p for p in prior if p.price_cents is not None]
        prev = valid_priors[-1] if valid_priors else None
        
        best_alert = None
        for rule in rules:
            a = None
            if rule.get("type") == "drop_pct" and prev is not None:
                a = rule_drop_pct(prev, cur, float(rule.get("pct", 10)))
            elif rule.get("type") == "below_median":
                a = rule_below_median(prior, cur, float(rule.get("pct", 15)), int(rule.get("window_days", 30)))
                
            if a:
                if not best_alert or a.rule == "below_median":
                    best_alert = a
                    
        if best_alert:
            alerts.append(best_alert)
            
        hist[_key(cur)] = prior + [cur]
    return alerts
