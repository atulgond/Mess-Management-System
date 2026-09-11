import hashlib
import json
from pricewatch.agents.extractor import extract_flux, _FLUX_SALT_CACHE
from pricewatch.http import Client
from requests import Response

class MockResponse:
    def __init__(self, status_code, text="", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._json_data

class MockClient(Client):
    def __init__(self):
        super().__init__()
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        if "bundle.js" in url:
            return MockResponse(200, text="!function(){var _0x1=[\"salt_p1_\",\"salt_p2\"];}();")
        return MockResponse(404)

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw.get("headers"), kw.get("json")))
        if "graphql" in url:
            return MockResponse(200, json_data={
                "data": {
                    "product": {
                        "sku": "FLX-TEST",
                        "title": "Pack of 2 Test Item",
                        "offer": {
                            "amount": 99.50,
                            "unit": "major",
                            "currency": "USD",
                            "stock": "IN_STOCK",
                            "stale": True
                        }
                    }
                }
            })
        return MockResponse(404)

def test_extract_flux_success():
    _FLUX_SALT_CACHE.clear()
    html = """<html>
        <meta name="flux-build" content="b123">
        <body>
            <div class="pdp" data-sku="FLX-TEST"><h1>Pack of 2 Test Item</h1></div>
        </body>
    </html>"""
    
    client = MockClient()
    obs = extract_flux(client, "flux", "http://example.com/stores/flux/item/FLX-TEST", html)
    
    assert obs.product_id == "FLX-TEST"
    assert obs.name == "Test Item"
    assert obs.pack_size == 2
    assert obs.price_cents is None
    assert obs.currency == "USD"
    assert obs.availability == "in_stock"
    assert "stale price" in obs.notes
    assert obs.unit_price_cents is None
    
    assert len(client.calls) == 2
    assert client.calls[0][1] == "http://example.com/stores/flux/bundle.js"
    
    post_call = client.calls[1]
    assert post_call[0] == "POST"
    assert post_call[1] == "http://example.com/stores/flux/api/graphql"
    assert post_call[2]["x-flux-build"] == "b123"
    
    expected_sig = hashlib.sha256(b"salt_p1_salt_p2|FLX-TEST").hexdigest()[:24]
    assert post_call[2]["x-flux-sig"] == expected_sig

def test_extract_flux_minor_unit():
    _FLUX_SALT_CACHE.clear()
    html = """<html>
        <meta name="flux-build" content="b123">
        <body>
            <div class="pdp" data-sku="FLX-MINOR"><h1>Test Item</h1></div>
        </body>
    </html>"""
    
    class MinorClient(MockClient):
        def post(self, url, **kw):
            return MockResponse(200, json_data={
                "data": {
                    "product": {
                        "sku": "FLX-MINOR",
                        "title": "Test Item",
                        "offer": {
                            "amount": 12345,
                            "unit": "minor",
                            "currency": "GBP",
                            "stock": "OUT_OF_STOCK",
                            "stale": False
                        }
                    }
                }
            })
            
    client = MinorClient()
    obs = extract_flux(client, "flux", "http://example.com/stores/flux/item/FLX-MINOR", html)
    assert obs.price_cents == 12345
    assert obs.currency == "GBP"
    assert obs.availability == "out_of_stock"
    assert "stale price" not in obs.notes

def test_extract_flux_major_unit_float_precision():
    _FLUX_SALT_CACHE.clear()
    html = """<html>
        <meta name="flux-build" content="b123">
        <body>
            <div class="pdp" data-sku="FLX-MAJOR"><h1>Test Item</h1></div>
        </body>
    </html>"""
    
    class MajorClient(MockClient):
        def post(self, url, **kw):
            return MockResponse(200, json_data={
                "data": {
                    "product": {
                        "sku": "FLX-MAJOR",
                        "title": "Test Item",
                        "offer": {
                            "amount": 1.13,
                            "unit": "major",
                            "currency": "USD",
                            "stock": "IN_STOCK",
                            "stale": False
                        }
                    }
                }
            })
            
    client = MajorClient()
    obs = extract_flux(client, "flux", "http://example.com/stores/flux/item/FLX-MAJOR", html)
    assert obs.price_cents == 113
    assert obs.currency == "USD"

