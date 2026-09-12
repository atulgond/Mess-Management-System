import json
import pytest
from unittest.mock import patch
from pricewatch.cli import cmd_extract
from pricewatch.agents.extractor import Observation
from argparse import Namespace

def test_part_c_llm_unknown_store():
    # Mock AnthropicProvider.complete
    with patch('pricewatch.providers.anthropic_provider.AnthropicProvider.complete') as mock_complete:
        mock_complete.return_value = json.dumps({
            "price_cents": 1234,
            "currency": "USD",
            "availability": "in_stock",
            "pack_size": 1
        })
        
        args = Namespace(
            url="https://www.unknownstore.com/item/123",
            html=None,
            store=None,
            stores_file="stores.yaml",
            llm=True,
            provider="anthropic"
        )
        
        # Test cmd_extract doesn't crash and returns the correct observation
        # Wait, cmd_extract just prints to stdout. We can catch stdout.
        import io
        from contextlib import redirect_stdout
        
        # Mock HTML fetch
        with patch('pricewatch.http.Client.get') as mock_get:
            mock_get.return_value.text = "<html><body>Fake item .34</body></html>"
            
            # We need an ANTHROPIC_API_KEY environment variable to avoid AnthropicProvider init error
            with patch.dict('os.environ', {'ANTHROPIC_API_KEY': 'fake_key'}):
                f = io.StringIO()
                with redirect_stdout(f):
                    cmd_extract(args)
                
                output = f.getvalue().strip()
                assert output, "Output should not be empty"
                obs = json.loads(output)
                assert obs["store"] == "unknown"
                assert obs["price_cents"] == 1234
                assert obs["currency"] == "USD"
                assert obs["availability"] == "in_stock"
