"""Extractor agent: one adapter per storefront turns a fetched page into an Observation.

Adapters receive the raw HTML (already fetched by the Client) and the URL. They must not do
their own networking except through the Client they are given, so throttling and cookies
stay in one place.

Adapters are registered by name; `stores.yaml` maps each store to an adapter.
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import Client
from ..models import Observation
from .normalizer import parse_money, unit_price

ADAPTERS: dict[str, Callable[..., Observation]] = {}


def adapter(name: str):
    def deco(fn):
        ADAPTERS[name] = fn
        return fn
    return deco


def _pid_from_url(url: str) -> str:
    return urlparse(url).path.rstrip("/").split("/")[-1]


# --------------------------------------------------------------------------- level 1
@adapter("corner")
def extract_corner(client: Client, store: str, url: str, html: str) -> Observation:
    soup = BeautifulSoup(html, "html.parser")
    ld = soup.find("script", type="application/ld+json")
    data = json.loads(ld.string) if ld and ld.string else {}
    offer = data.get("offers", {})
    price_cents, currency = parse_money(str(offer.get("price", "")), offer.get("priceCurrency"))
    was = soup.find("s")
    compare, _ = parse_money(was.get_text(), currency) if was else (None, None)
    return Observation(
        store=store, product_id=data.get("sku") or _pid_from_url(url), url=url,
        name=data.get("name") or soup.h1.get_text(strip=True),
        price_cents=price_cents, currency=currency or "USD", compare_at_cents=compare,
        availability="in_stock" if "InStock" in str(offer.get("availability", "")) else "out_of_stock",
    )


# --------------------------------------------------------------------------- level 2
@adapter("maple")
def extract_maple(client: Client, store: str, url: str, html: str) -> Observation:
    soup = BeautifulSoup(html, "html.parser")
    name = soup.select_one(".product__title").get_text(strip=True)
    price_el = soup.select_one(".price--sale") or soup.select_one(".price .price")
    price_cents, currency = parse_money(price_el.get_text(" ", strip=True), "EUR") if price_el else (None, "EUR")
    compare_el = soup.select_one(".price--compare")
    compare, _ = parse_money(compare_el.get_text(" ", strip=True), currency) if compare_el else (None, None)
    avail = "out_of_stock" if "Sold out" in soup.get_text() else "in_stock"
    return Observation(
        store=store, product_id=_pid_from_url(url), url=url, name=name,
        price_cents=price_cents, currency=currency or "EUR", compare_at_cents=compare, availability=avail,
    )


# --------------------------------------------------------------------------- level 3
def _text(soup: BeautifulSoup) -> str:
    return " ".join(soup.get_text(" ", strip=True).split())


def _zon_product_text(soup: BeautifulSoup) -> str:
    return _text(soup).split("Other sellers on Zon", 1)[0]


def _zon_price_from_product_text(text: str) -> Optional[int]:
    pack_match = re.search(r"Pack of\s+\d+\s*:\s*(\$\s*\d[\d\s,]*\.\s*\d{2})", text, re.I)
    if pack_match:
        price, _ = parse_money(pack_match.group(1), "USD")
        return price

    m = re.search(r"\$\s*\d[\d\s,]*\.\s*\d{2}", text)
    if not m:
        return None

    price, _ = parse_money(m.group(), "USD")
    return price


def _zon_availability(product_text: str) -> str:
    low = product_text.lower()
    if "currently unavailable" in low or "out of stock" in low or "back in stock" in low:
        return "out_of_stock"
    if "in stock" in low:
        return "in_stock"
    return "unknown"


def _zon_compare_at(product_text: str) -> Optional[int]:
    match = re.search(r"List Price:\s*(\$\s*\d[\d\s,]*\.\s*\d{2})", product_text, re.I)
    if not match:
        return None
    compare, _ = parse_money(match.group(1), "USD")
    return compare


def _same_zon_product_variant_urls(url: str, soup: BeautifulSoup) -> list[str]:
    parsed = urlparse(url)
    product_path = parsed.path.rstrip("/")
    urls: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"])
        p = urlparse(href)
        if p.scheme != parsed.scheme or p.netloc != parsed.netloc:
            continue
        if p.path.rstrip("/") != product_path or "variant=" not in p.query:
            continue
        if p.path.endswith("/offers-all") or "/offers-all/" in p.path:
            continue
        if href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


@adapter("zon")
def extract_zon(
    client: Client,
    store: str,
    url: str,
    html: str,
    *,
    listing_price_cents: Optional[int] = None,
) -> Observation:
    soup = BeautifulSoup(html, "html.parser")
    if "Are you a human" in html:
        return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                           currency="USD", notes=["robot check page"])
    title = soup.find("h1")
    name = title.get_text(" ", strip=True) if title else ""
    m = re.search(r"Pack of (\d+)", name)
    pack = int(m.group(1)) if m else 1
    product_text = _zon_product_text(soup)
    availability = _zon_availability(product_text)
    compare_at = _zon_compare_at(product_text)

    price_cents = _zon_price_from_product_text(product_text)
    notes: list[str] = []

    if price_cents is None and "Select a colour to see price" in product_text:
        for variant_url in _same_zon_product_variant_urls(url, soup):
            variant = client.get(variant_url)
            if "/offers-all" in urlparse(variant.url).path:
                continue
            variant_soup = BeautifulSoup(variant.text, "html.parser")
            variant_text = _zon_product_text(variant_soup)
            variant_price = _zon_price_from_product_text(variant_text)
            if variant_price is not None:
                price_cents = variant_price
                compare_at = _zon_compare_at(variant_text) or compare_at
                availability = _zon_availability(variant_text)
                break

    if price_cents is None and availability != "out_of_stock" and listing_price_cents is not None:
        price_cents = listing_price_cents
        notes.append("price from index listing")

    if price_cents is None:
        notes.append("no price found")

    return Observation(
        store=store, product_id=_pid_from_url(url), url=url, name=re.sub(r"\s*\(Pack of \d+\)", "", name),
        price_cents=price_cents, currency="USD", compare_at_cents=compare_at, availability=availability, pack_size=pack,
        unit_price_cents=unit_price(price_cents, pack),
        notes=notes,
    )


# --------------------------------------------------------------------------- levels 4-5
@adapter("shield")
def extract_shield(client: Client, store: str, url: str, html: str) -> Observation:
    # TODO: Shield fronts every page with a challenge and rate limit. See tasks/README.
    return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                       currency="GBP", notes=["shield adapter not implemented"])


@adapter("flux")
def extract_flux(client: Client, store: str, url: str, html: str) -> Observation:
    # TODO: Flux renders prices client-side from a signed API. See tasks/README.
    return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                       currency="USD", notes=["flux adapter not implemented"])


def extract(client: Client, store: str, adapter_name: str, url: str, html: str, **context) -> Observation:
    fn = ADAPTERS.get(adapter_name)
    if fn is None:
        raise KeyError(f"no adapter named {adapter_name!r}")
    return fn(client, store, url, html, **context) if context else fn(client, store, url, html)
