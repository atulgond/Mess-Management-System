import json
from pathlib import Path
from pricewatch import evaluate
from pricewatch.providers import Provider, ProviderTimeout

class MockEvalProvider(Provider):
    name = "mock_eval"
    def complete(self, system: str, user: str, *, metadata: dict, timeout: float = 30.0) -> str:
        url = metadata["source_url"]
        if "timeout" in url:
            raise ProviderTimeout("Simulated timeout")
        if "badjson" in url:
            return "{bad"
        return '{"price_cents": 100, "currency": "USD", "availability": "in_stock", "pack_size": 1}'

def test_eval_harness(tmp_path):
    labels_path = tmp_path / "labels.json"
    snapshots_dir = tmp_path / "snapshots"
    out_dir = tmp_path / "out"
    snapshots_dir.mkdir()
    
    labels = [
        {"id": "s1", "store": "s", "file": "1.html", "url": "http://x/1", "expected": {"price_cents": 100, "currency": "USD", "availability": "in_stock", "pack_size": 1}},
        {"id": "s2", "store": "s", "file": "2.html", "url": "http://x/timeout", "expected": {"price_cents": 100, "currency": "USD", "availability": "in_stock", "pack_size": 1}},
        {"id": "s3", "store": "s", "file": "3.html", "url": "http://x/badjson", "expected": {"price_cents": 100, "currency": "USD", "availability": "in_stock", "pack_size": 1}}
    ]
    labels_path.write_text(json.dumps(labels))
    (snapshots_dir / "1.html").write_text("html1")
    (snapshots_dir / "2.html").write_text("html2")
    (snapshots_dir / "3.html").write_text("html3")
    
    p = MockEvalProvider()
    report = evaluate.run(p, snapshots_dir, labels_path, out_dir)
    
    assert report["n"] == 3
    assert report["errors"]["timeout"] == 1
    assert report["errors"]["malformed_output"] == 1
    assert report["errors"]["provider_error"] == 0
    
    # 1/3 correct
    assert report["overall"]["price_exact"] == 1.0 / 3.0
    
    # Check cache
    cache_dir = out_dir / "cache"
    assert len(list(cache_dir.glob("*.json"))) == 1 # Only the successful one should be cached!
    
