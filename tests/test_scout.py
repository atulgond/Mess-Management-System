from bs4 import BeautifulSoup
from pricewatch.agents.scout import _listing_price_for_link

def test_scout_extracts_price_ignoring_review_counts():
    html = """<div>
        <a href="/stores/zon/dp/123">Product</a>
        <div>4.5 stars (1,234 reviews) $ 1,577 . 48</div>
    </div>"""
    soup = BeautifulSoup(html, "html.parser")
    a = soup.find("a")
    assert _listing_price_for_link(a) == 157748
