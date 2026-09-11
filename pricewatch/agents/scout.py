"""Scout agent: finds product URLs on a store's index page.

Returns absolute URLs. If the index can't be read (challenge page, rate limit, robot check),
returns an empty list and a note; the orchestrator records the note.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from .normalizer import parse_money

PRODUCT_PATH = {
    "corner": r"/stores/corner/p/[^/?#]+$",
    "maple": r"/stores/maple/products/[^/?#]+$",
    "zon": r"/stores/zon/dp/[^/?#]+$",
    "shield": r"/stores/shield/item/[^/?#]+$",
    "flux": r"/stores/flux/item/[^/?#]+$",
}


@dataclass(frozen=True)
class ProductLink:
    url: str
    listing_price_cents: int | None = None


def _listing_price_for_link(a) -> int | None:
    container = a.find_parent(["article", "li", "div"]) or a.parent
    text = container.get_text(" ", strip=True) if container else a.get_text(" ", strip=True)
    m = re.search(r"\$\s*\d[\d\s,]*\.\s*\d{2}", text)
    if m:
        price, _ = parse_money(m.group(), "USD")
        return price
    return None


def discover_items(client: Client, store: str, index_url: str) -> tuple[list[ProductLink], list[str]]:
    notes: list[str] = []
    r = client.get(index_url)
    if r.status_code != 200:
        notes.append(f"index returned HTTP {r.status_code}")
        return [], notes
    if "Are you a human" in r.text:
        notes.append("index served a robot check")
        return [], notes
    soup = BeautifulSoup(r.text, "html.parser")
    pat = re.compile(PRODUCT_PATH.get(store, r".*"))
    items: list[ProductLink] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(index_url, a["href"])
        if pat.search(href) and href not in seen:
            seen.add(href)
            items.append(ProductLink(href, _listing_price_for_link(a) if store == "zon" else None))
    return items, notes


def discover(client: Client, store: str, index_url: str) -> tuple[list[str], list[str]]:
    items, notes = discover_items(client, store, index_url)
    return [item.url for item in items], notes
