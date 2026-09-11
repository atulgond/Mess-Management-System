"""Eval harness for the LLM extractor (Stage 3 starting point).

Runs the LLM extractor over every snapshot in a directory, compares with labels.json, and
writes report.json. This skeleton measures one number and crashes on the first provider
error — improving it IS the exercise. The report schema the grader expects is documented
in tasks/ISSUE-3.md.
"""
from __future__ import annotations

import hashlib
import json
import statistics
import time
from pathlib import Path
from typing import Any

from .agents import extractor
from .agents.llm_extractor import extract_with_llm
from .http import Client
from .providers import Provider

def _cache_key(provider_name: str, html: str) -> str:
    return hashlib.sha256(f"{provider_name}|{html}".encode()).hexdigest()

def _accuracy(correct: int, total: int) -> float:
    return correct / total if total > 0 else 0.0

def run(provider: Provider, snapshots_dir: str | Path, labels_path: str | Path, out_dir: str | Path) -> dict:
    snapshots_dir, out_dir = Path(snapshots_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    cache_dir = out_dir / "cache"
    cache_dir.mkdir(exist_ok=True)
    
    labels = {row["id"]: row for row in json.loads(Path(labels_path).read_text())}

    results = []
    store_metrics: dict[str, dict[str, Any]] = {}
    # Update errors to exact keys expected by the schema
    errors = {"timeout": 0, "malformed_output": 0, "provider_error": 0}
    latencies = []
    
    baseline_correct = 0
    client = Client()

    t0 = time.time()
    
    label_issues = []
    
    for snap_id, row in labels.items():
        html = (snapshots_dir / row["file"]).read_text()
        store = row["store"]
        url = row["url"]
        exp = row["expected"]
        
        if store not in store_metrics:
            store_metrics[store] = {"n": 0, "price_ok": 0, "currency_ok": 0, "avail_ok": 0, "pack_ok": 0}
            
        # Baseline extraction (rule-based fallback)
        try:
            base_obs = extractor.extract(client, store, store, url, html)
            if base_obs.price_cents == exp.get("price_cents"):
                baseline_correct += 1
        except Exception:
            pass
            
        # LLM extraction with caching
        c_key = _cache_key(provider.name, html)
        c_file = cache_dir / f"{c_key}.json"
        
        lat = 0.0
        obs = None
        if c_file.exists():
            from .models import Observation
            obs = Observation.from_dict(json.loads(c_file.read_text()))
        else:
            t_start = time.time()
            obs = extract_with_llm(provider, store, url, html)
            lat = (time.time() - t_start) * 1000
            
            if obs.price_cents is not None or "llm extraction failed" not in "".join(obs.notes or []):
                c_file.write_text(json.dumps(obs.to_dict()))
                latencies.append(lat)
                
        # Error tracking based on notes
        notes_str = "".join(obs.notes or [])
        is_error = False
        if "ProviderTimeout" in notes_str:
            errors["timeout"] += 1
            is_error = True
        elif "JSONDecodeError" in notes_str:
            errors["malformed_output"] += 1
            is_error = True
        elif "ProviderError" in notes_str:
            errors["provider_error"] += 1
            is_error = True

        price_ok = obs.price_cents == exp.get("price_cents")
        currency_ok = obs.currency == exp.get("currency")
        avail_ok = obs.availability == exp.get("availability")
        pack_ok = obs.pack_size == exp.get("pack_size")
        
        if is_error:
            price_ok = currency_ok = avail_ok = pack_ok = False
            
        import re
        if not price_ok and exp.get("price_cents") is not None:
            major = str(exp.get("price_cents"))[:-2]
            html_clean = re.sub(r'[\s,\.\xa0]', '', html)
            if major not in html_clean:
                label_issues.append({"id": snap_id, "reason": f"Expected major price {major} is completely mathematically absent from the raw HTML text."})

        results.append({
            "id": snap_id,
            "price_ok": price_ok,
            "currency_ok": currency_ok,
            "avail_ok": avail_ok,
            "pack_ok": pack_ok,
            "error": is_error
        })
        
        store_metrics[store]["n"] += 1
        store_metrics[store]["price_ok"] += int(price_ok)
        store_metrics[store]["currency_ok"] += int(currency_ok)
        store_metrics[store]["avail_ok"] += int(avail_ok)
        store_metrics[store]["pack_ok"] += int(pack_ok)

    n = len(results)
    
    per_store = {}
    for s, m in store_metrics.items():
        sn = m["n"]
        per_store[s] = {
            "price_exact": _accuracy(m["price_ok"], sn),
            "currency": _accuracy(m["currency_ok"], sn),
            "availability": _accuracy(m["avail_ok"], sn),
            "pack_size": _accuracy(m["pack_ok"], sn)
        }

    report = {
        "provider": provider.name,
        "model": getattr(provider, "model", "unknown"),
        "n": n,
        "overall": {
            "price_exact": _accuracy(sum(r["price_ok"] for r in results), n),
            "currency": _accuracy(sum(r["currency_ok"] for r in results), n),
            "availability": _accuracy(sum(r["avail_ok"] for r in results), n),
            "pack_size": _accuracy(sum(r["pack_ok"] for r in results), n),
        },
        "per_store": per_store,
        "errors": errors,
        "cost": {"input_tokens": 0, "output_tokens": 0, "usd_estimate": 0.0},
        "latency_ms": {
            "p50": round(statistics.median(latencies)) if latencies else 0,
            "p95": round(statistics.quantiles(latencies, n=20)[18]) if len(latencies) >= 20 else (round(max(latencies)) if latencies else 0)
        },
        "baseline": {
            "price_exact": _accuracy(baseline_correct, n)
        },
        "elapsed_s": round(time.time() - t0, 2),
    }
    
    (out_dir / "report.json").write_text(json.dumps(report, indent=2))
    (out_dir / "label_issues.json").write_text(json.dumps(label_issues, indent=2))
    
    return report
