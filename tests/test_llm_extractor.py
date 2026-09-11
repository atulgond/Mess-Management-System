import json
from pricewatch.agents.llm_extractor import extract_with_llm
from pricewatch.providers import Provider, ProviderTimeout, ProviderError

class MockProvider(Provider):
    name = "mock"
    def __init__(self, response: str, error=None):
        self.response = response
        self.error = error
    def complete(self, system: str, user: str, *, metadata: dict, timeout: float = 30.0) -> str:
        if self.error:
            raise self.error
        return self.response

def test_extract_valid_json():
    p = MockProvider('{"price_cents": 1234}')
    obs = extract_with_llm(p, "test", "http://x/1", "<html></html>")
    assert obs.price_cents == 1234
    
def test_extract_markdown_json():
    p = MockProvider('```json\n{"price_cents": 5678}\n```')
    obs = extract_with_llm(p, "test", "http://x/1", "<html></html>")
    assert obs.price_cents == 5678

def test_extract_timeout():
    p = MockProvider('', error=ProviderTimeout("timeout"))
    obs = extract_with_llm(p, "test", "http://x/1", "<html></html>")
    assert obs.price_cents is None
    assert "ProviderTimeout" in obs.notes[0]

def test_extract_malformed_json():
    p = MockProvider('{bad json')
    obs = extract_with_llm(p, "test", "http://x/1", "<html></html>")
    assert obs.price_cents is None
    assert "JSONDecodeError" in obs.notes[0]
