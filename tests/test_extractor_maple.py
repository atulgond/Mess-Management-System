"""Reproduces one symptom from tasks/ISSUE-1.md. It fails on the starter. Make it pass — and then keep going."""
from pricewatch.agents.extractor import extract_maple
from pricewatch.http import Client

HTML = """<html><body><div class="product"><h1 class="product__title">Kestrel Lumen Notebook</h1>
<div class="price"><span class="price price--compare"><s>937,20 €</s></span> <span class="price price--sale">720,92 €</span></div>
<p class="muted">In stock · prices shown in EUR</p></div></body></html>"""


def test_maple_sale_item_reports_sale_price():
    o = extract_maple(Client(), "maple", "http://x/stores/maple/products/kestrel-lumen-notebook", HTML)
    assert o.price_cents == 72092
    assert o.currency == "EUR"

def test_maple_pack_of_n_name_and_unit_price():
    html = """<html><body><div class="product"><h1 class="product__title">Pack of 4 Kestrel Lumen Notebook</h1>
    <div class="price"><span class="price price--sale">40,00 €</span></div>
    <p class="muted">In stock · prices shown in EUR</p></div></body></html>"""
    o = extract_maple(Client(min_interval=0), "maple", "http://x/stores/maple/products/kestrel-lumen-notebook", html)
    assert o.name == "Kestrel Lumen Notebook"
    assert o.pack_size == 4
    assert o.price_cents == 4000
    assert o.unit_price_cents == 1000

def test_maple_variant_selector_fallback():
    html = """<html><body><div class="product"><h1 class="product__title">Variant Item</h1>
    <div class="price"><span class="price price--sale">Select a colour to see price</span></div>
    <label>Variant <select name="variant">
      <option value="1">Select a colour</option>
      <option value="2">Red / M — 55,00 €</option>
    </select></label>
    <p class="muted">In stock</p></div></body></html>"""
    o = extract_maple(Client(min_interval=0), "maple", "http://x/stores/maple/products/variant-item", html)
    assert o.price_cents == 5500
    assert o.currency == "EUR"
