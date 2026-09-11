"""LLM extractor: the fallback for stores we have no adapter for.

Given raw HTML and its URL, ask a model for the structured offer. This is deliberately
minimal — it is the starting point for Stage 3, not the answer to it.
"""
from __future__ import annotations

import json
import logging
import re

from bs4 import BeautifulSoup

from ..models import Observation
from ..providers import Provider, ProviderError, ProviderTimeout

SYSTEM = """You extract e-commerce offer data from a product page and answer ONLY with a JSON object:
{"name": str|null, "price_cents": int|null, "currency": "ISO-4217"|null, "availability": "in_stock"|"out_of_stock"|"unknown", "pack_size": int, "compare_at_cents": int|null}

RULES:
1. `price_cents` is the active selling price (in minor units, e.g. cents). Distinguish the actual sale price from any list/compare-at prices.
2. `pack_size` is the quantity of the item in the pack (default 1). If the title says "Pack of 3" or similar, set pack_size to 3.
3. `availability` should be "in_stock" if the item can be purchased, "out_of_stock" if unavailable (e.g. "utslogt", "sold out", "currently unavailable"), or "unknown".
4. `currency` must be the ISO-4217 code (e.g. USD, EUR, NOK, INR). Identify the correct currency based on symbols or text (e.g. kr -> NOK, ₹ -> INR, € -> EUR).
5. If the price cannot be determined, set `price_cents` to null.
6. Do NOT include markdown code blocks (e.g. ```json). Output exactly the raw JSON."""


def clean_html(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = re.sub(r"\n\s*\n+", "\n", soup.get_text("\n"))
    return text[:limit]


def extract_with_llm(provider: Provider, store: str, url: str, html: str, timeout: float = 30.0) -> Observation:
    user = f"URL: {url}\n\nPAGE TEXT:\n{clean_html(html)}"
    
    sku = url.rstrip("/").split("/")[-1]
    
    try:
        raw = provider.complete(SYSTEM, user, metadata={"source_url": url, "store": store}, timeout=timeout)
        
        # Strip potential markdown formatting
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            raw = m.group(0)
            
        data = json.loads(raw)
        
        return Observation(
            store=store, product_id=sku, url=url, 
            name=data.get("name") or "",
            price_cents=data.get("price_cents"), 
            currency=data.get("currency") or "",
            compare_at_cents=data.get("compare_at_cents"), 
            availability=data.get("availability") or "unknown",
            pack_size=int(data.get("pack_size") or 1), 
            source="llm"
        )
    except (ProviderTimeout, ProviderError, json.JSONDecodeError) as e:
        logging.warning("LLM extraction failed for %s: %s", url, e)
        return Observation(
            store=store, product_id=sku, url=url, name="",
            price_cents=None, currency="", 
            availability="unknown", source="llm",
            notes=[f"llm extraction failed: {type(e).__name__}"]
        )
