from pricewatch.agents.extractor import extract_zon


class Response:
    def __init__(self, url, text):
        self.url = url
        self.text = text


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def get(self, url):
        assert "/offers-all" not in url
        self.requested.append(url)
        return Response(url, self.pages[url])


def page(name, buy_box, other="$ 10 . 00 from Other Direct", variants=""):
    return f"""<html><body>
    <h1>{name}</h1>
    {variants}
    <section data-random="buy">{buy_box}</section>
    <section><h3>Other sellers on Zon</h3><div>{other}</div>
    <a href="/stores/zon/dp/ABC123/offers-all">See all buying options</a></section>
    </body></html>"""


def test_zon_visible_normal_product_price():
    html = page("Halden Atlas Air Purifier", "$ 1,059 . 62 In Stock", "$ 1,209 . 62 from Other")
    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/ABC123", html)

    assert obs.price_cents == 105962
    assert obs.currency == "USD"
    assert obs.availability == "in_stock"


def test_zon_pack_price_uses_pack_not_unit():
    html = page(
        "Kestrel Slate Blender (Pack of 4)",
        "$ 264 . 76 / count <div>Pack of 4: $ 1,059 . 02</div> In Stock",
        "$ 999 . 99 from Other",
    )
    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/QZCL8BJU", html)

    assert obs.price_cents == 105902
    assert obs.pack_size == 4
    assert obs.unit_price_cents == 26476


def test_zon_other_seller_prices_are_ignored():
    html = page("Aurel Harbor Desk Lamp", "See price in cart", "$ 1,329 . 46 from Other")
    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/B71RPQ2S", html)

    assert obs.price_cents is None
    assert obs.notes == ["no price found"]


def test_zon_select_colour_fetches_allowed_variant_price():
    url = "http://x/stores/zon/dp/Y21ZF4QH"
    variant = url + "?variant=SX8WEL"
    html = page(
        "Brightline Solstice Water Bottle (Pack of 12)",
        "Select a colour to see price",
        "$ 842 . 72 from Other",
        f'<a href="?variant=SX8WEL">Black</a><a href="/stores/zon/dp/Y21ZF4QH/offers-all">bad</a>',
    )
    variant_html = page(
        "Brightline Solstice Water Bottle (Pack of 12)",
        "$ 54 . 37 / count <div>Pack of 12: $ 652 . 44</div> In Stock",
        "$ 842 . 72 from Other",
    )
    client = FakeClient({variant: variant_html})

    obs = extract_zon(client, "zon", url, html)

    assert obs.price_cents == 65244
    assert client.requested == [variant]


def test_zon_see_price_in_cart_falls_back_to_index_price():
    html = page("Kestrel Quiet Monitor Arm", "See price in cart", "$ 169 . 40 from Other")
    obs = extract_zon(
        FakeClient({}),
        "zon",
        "http://x/stores/zon/dp/D8Y2YXFA",
        html,
        listing_price_cents=16869,
    )

    assert obs.price_cents == 16869
    assert obs.notes == ["price from index listing"]


def test_zon_does_not_rely_on_generated_class_names():
    html = """<html><body>
    <h1 class="seed-changed-title">Marrow Ember Water Bottle</h1>
    <div class="totally-new-buybox">$ 1,093 . 76 <span>In Stock</span></div>
    <div class="seed-changed-other"><h3>Other sellers on Zon</h3>$ 1,184 . 79 from Other</div>
    </body></html>"""

    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/3T3U0F3B", html)

    assert obs.price_cents == 109376
    assert obs.name == "Marrow Ember Water Bottle"

def test_zon_with_list_price_ignores_list_price():
    html = page("Meridian Lamp", "$ 1,577 . 48 List Price: $ 2,135 . 91")
    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/193SWUS1", html)
    assert obs.price_cents == 157748
    assert obs.compare_at_cents == 213591

def test_zon_review_ratings_do_not_break_price():
    html = page("Water Bottle", "4.5 stars (1,234 reviews) $ 10.00")
    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/BOTTLE", html)
    assert obs.price_cents == 1000

def test_zon_spaced_usd_prices_parse_correctly():
    html = page("Spaced Item", "$   1,234   .   56   In Stock")
    obs = extract_zon(FakeClient({}), "zon", "http://x/stores/zon/dp/SPACE", html)
    assert obs.price_cents == 123456
