import pytest
import hashlib
from pricewatch.http import Client

class MockResponse:
    def __init__(self, status_code, text, headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self.ok = status_code == 200

class MockSession:
    def __init__(self, responses):
        self.headers = {}
        self.responses = responses
        self.calls = []
        
    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)
        
    def post(self, url, json=None, **kw):
        self.calls.append(("POST", url, {"json": json}))
        return self.responses.pop(0)

def test_shield_challenge_success():
    client = Client(min_interval=0, retries=1)
    
    html = '''<html><body><div id="cf-c" data-s="test_salt" data-p="/stores/shield/item">Checking your browser before accessing Shield Outfitters...</div></body></html>'''
    
    client.session = MockSession([
        MockResponse(503, html, {"Retry-After": "1.5"}),  # First GET hits challenge
        MockResponse(200, "ok"),                          # POST challenge clears
        MockResponse(200, "success page")                 # Second GET succeeds
    ])
    
    sleeps = []
    client._sleep = sleeps.append
    
    r = client.get("http://example.com/stores/shield/item")
    
    assert r.status_code == 200
    assert r.text == "success page"
    assert len(client.session.calls) == 3
    assert client.session.calls[0][:2] == ("GET", "http://example.com/stores/shield/item")
    assert client.session.calls[1][:2] == ("POST", "http://example.com/stores/shield/challenge")
    
    expected_hash = hashlib.sha256(b"test_salt|/stores/shield/item").hexdigest()[:16]
    assert client.session.calls[1][2]["json"] == {"s": "test_salt", "p": "/stores/shield/item", "a": expected_hash}
    
    assert client.session.calls[2][:2] == ("GET", "http://example.com/stores/shield/item")
    assert len(sleeps) == 2
    assert sleeps[0] == 1.5
    assert 0.9 < sleeps[1] <= 1.0

def test_ordinary_503_behavior_unchanged():
    client = Client(min_interval=0, retries=1)
    client.session = MockSession([
        MockResponse(503, "Service Unavailable - but no shield text", {"Retry-After": "2.0"}),
        MockResponse(200, "finally ok")
    ])
    
    sleeps = []
    client._sleep = sleeps.append
    
    r = client.get("http://example.com/")
    assert r.status_code == 200
    assert r.text == "finally ok"
    assert len(client.session.calls) == 2
    assert sleeps == [2.0]
