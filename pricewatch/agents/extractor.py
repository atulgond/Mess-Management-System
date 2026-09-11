"""Extractor agent: one adapter per storefront turns a fetched page into an Observation.

Adapters receive the raw HTML (already fetched by the Client) and the URL. They must not do
their own networking except through the Client they are given, so throttling and cookies
stay in one place.

Adapters are registered by name; `stores.yaml` maps each store to an adapter.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Callable, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..http import Client
from ..models import Observation
from .normalizer import parse_money, unit_price

ADAPTERS: dict[str, Callable[..., Observation]] = {}
_FLUX_SALT_CACHE: dict[str, str] = {}


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
    title_el = soup.select_one(".product__title")
    name = title_el.get_text(strip=True) if title_el else ""
    
    pack_match = re.search(r"Pack of (\d+)", name, re.I)
    pack = int(pack_match.group(1)) if pack_match else 1
    name_clean = re.sub(r"\s*\(?Pack of \d+\)?", "", name, flags=re.I).strip()

    price_el = soup.select_one(".price--sale") or soup.select_one(".price .price")
    price_text = price_el.get_text(" ", strip=True) if price_el else ""
    price_cents, currency = parse_money(price_text, "EUR") if price_text else (None, "EUR")
    
    if price_cents is None:
        select = soup.find("select", {"name": "variant"})
        if select:
            for opt in select.find_all("option"):
                opt_text = opt.get_text()
                if "—" in opt_text:
                    fallback_text = opt_text.split("—")[-1]
                    price_cents, c = parse_money(fallback_text, currency or "EUR")
                    if price_cents is not None:
                        currency = c
                        break

    compare_el = soup.select_one(".price--compare")
    compare, _ = parse_money(compare_el.get_text(" ", strip=True), currency) if compare_el else (None, None)
    avail = "out_of_stock" if "Sold out" in soup.get_text() else "in_stock"
    return Observation(
        store=store, product_id=_pid_from_url(url), url=url, name=name_clean,
        price_cents=price_cents, currency=currency or "EUR", compare_at_cents=compare, 
        availability=avail, pack_size=pack,
        unit_price_cents=unit_price(price_cents, pack) if price_cents is not None else None,
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
    m = re.search(r"window\.__STATE__\s*=\s*(\{.*?\});", html)
    if not m:
        return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                           currency="GBP", notes=["no state found"])
    
    state = json.loads(m.group(1))
    product = state.get("product", {})
    offer = product.get("offer", {})
    
    name = product.get("title", "")
    price_cents = offer.get("amount")
    compare_at_cents = offer.get("was")
    currency = offer.get("currency", "GBP")
    avail = "in_stock" if offer.get("stock") == "IN_STOCK" else "out_of_stock"
    
    pack_match = re.search(r"Pack of (\d+)", name, re.I)
    pack = int(pack_match.group(1)) if pack_match else 1
    
    return Observation(
        store=store, product_id=product.get("id") or _pid_from_url(url), url=url, 
        name=re.sub(r"\s*\(Pack of \d+\)", "", name, flags=re.I),
        price_cents=price_cents, currency=currency, compare_at_cents=compare_at_cents, 
        availability=avail, pack_size=pack,
        unit_price_cents=unit_price(price_cents, pack) if price_cents is not None else None,
    )


@adapter("flux")
def extract_flux(client: Client, store: str, url: str, html: str) -> Observation:
    soup = BeautifulSoup(html, "html.parser")
    
    meta = soup.find("meta", {"name": "flux-build"})
    if not meta:
        return Observation(store=store, product_id=_pid_from_url(url), url=url, name="", price_cents=None,
                           currency="USD", notes=["no flux-build meta found"])
    build_id = meta.get("content", "")
    
    sku = _pid_from_url(url)
    pdp = soup.find("div", {"class": "pdp"})
    if pdp and pdp.get("data-sku"):
        sku = pdp.get("data-sku")
        
    title_el = soup.find("h1")
    name = title_el.get_text(strip=True) if title_el else ""

    salt = _FLUX_SALT_CACHE.get(build_id)
    if not salt:
        bundle_url = urljoin(url, "/stores/flux/bundle.js")
        r_bundle = client.get(bundle_url)
        if r_bundle.ok:
            m = re.search(r'=\s*\[(".*?")\]', r_bundle.text)
            if m:
                parts = re.findall(r'"([^"]+)"', m.group(1))
                salt = "".join(parts)
                _FLUX_SALT_CACHE[build_id] = salt

    if not salt:
        return Observation(store=store, product_id=sku, url=url, name=name, price_cents=None,
                           currency="USD", notes=["failed to extract salt"])

    sig = hashlib.sha256(f"{salt}|{sku}".encode()).hexdigest()[:24]

    gql_url = urljoin(url, "/stores/flux/api/graphql")
    headers = {
        "content-type": "application/json",
        "x-flux-sig": sig,
        "x-flux-build": build_id
    }
    payload = {
        "query": "query($sku:String!){product(sku:$sku){sku title offer{amount unit currency stock stale}}}",
        "variables": {"sku": sku}
    }
    
    r_gql = client.post(gql_url, headers=headers, json=payload)
    if not r_gql.ok:
        return Observation(store=store, product_id=sku, url=url, name=name, price_cents=None,
                           currency="USD", notes=[f"graphql returned {r_gql.status_code}"])
                           
    try:
        data = r_gql.json()
        product = data.get("data", {}).get("product", {})
        offer = product.get("offer", {})
        
        name = product.get("title") or name
        amount = offer.get("amount")
        unit = offer.get("unit")
        currency = offer.get("currency", "USD")
        stock = offer.get("stock")
        stale = offer.get("stale")
        
        if amount is not None and not stale:
            amount_val = float(amount)
            price_cents = int(amount_val) if str(unit).lower() == "minor" else round(amount_val * 100)
        else:
            price_cents = None
            
        avail = "in_stock" if stock == "IN_STOCK" else "out_of_stock"
        
        notes = []
        if stale:
            notes.append("stale price")
            
        pack_match = re.search(r"Pack of (\d+)", name, re.I)
        pack = int(pack_match.group(1)) if pack_match else 1
        name_clean = re.sub(r"\s*\(?Pack of \d+\)?", "", name, flags=re.I).strip()
        
        return Observation(
            store=store, product_id=sku, url=url, name=name_clean,
            price_cents=price_cents, currency=currency, compare_at_cents=None,
            availability=avail, pack_size=pack,
            unit_price_cents=unit_price(price_cents, pack) if price_cents is not None else None,
            notes=notes
        )
    except Exception as e:
        return Observation(store=store, product_id=sku, url=url, name=name, price_cents=None,
                           currency="USD", notes=[f"error parsing graphql: {e}"])


def extract(client: Client, store: str, adapter_name: str, url: str, html: str, **context) -> Observation:
    fn = ADAPTERS.get(adapter_name)
    if fn is None:
        raise KeyError(f"no adapter named {adapter_name!r}")
    return fn(client, store, url, html, **context) if context else fn(client, store, url, html)
