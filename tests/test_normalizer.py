from pricewatch.agents.normalizer import parse_money


def test_usd_plain():
    assert parse_money("$596.85") == (59685, "USD")


def test_usd_thousands():
    assert parse_money("$1,299.00") == (129900, "USD")


def test_no_number():
    assert parse_money("Price unavailable", "USD") == (None, "USD")


def test_parse_money_european():
    assert parse_money("937,20 €", "EUR") == (93720, "EUR")
    assert parse_money("1.037,02 €", "EUR") == (103702, "EUR")
    assert parse_money("720,92 €", "EUR") == (72092, "EUR")
    assert parse_money("1.299,00 €", "EUR") == (129900, "EUR")
    assert parse_money("1 037,02 €", "EUR") == (103702, "EUR")


def test_parse_money_whole():
    assert parse_money("1.299 €", "EUR") == (129900, "EUR")
    assert parse_money("1,299 €", "EUR") == (129900, "EUR")
    assert parse_money("100", "USD") == (10000, "USD")
    assert parse_money("1 000", "USD") == (100000, "USD")
