"""S64: the numbers in plain words, built by code from the stock's own figures."""
from pflab.hq import plain


def test_pe_in_plain_words_gives_the_price_paid_the_yield_and_where_it_sits():
    lines = plain.pe(20.0, {"median": 30.0, "percentile_now": 5}, {"pe": 25.0}, {"label": "failed"})
    text = " ".join(lines)
    assert "Rs 20 for every Re 1" in text and "5.0% a year" in text and "cheaper than it was in almost every one" in text
    assert "80% of the market's level (cheaper than the market)" in text and "not a law" in text
    assert "'P/E above 50' on the Nifty 500" in text and "failed" in text and "does not settle what valuation does over years" in text
    dear = " ".join(plain.pe(60.0, {"median": 30.0, "percentile_now": 97}, None, None))
    assert "dearer than it was in almost every one" in dear and "tested the cut-off" not in dear          # no result: no claim of one


def test_growth_volatility_and_trend_sentences():
    assert "asks for more than it has delivered" in plain.growth(19.0, -26.0)
    assert "not asking for a miracle" in plain.growth(8.0, 4.0)
    assert plain.growth(None, 4.0) is None
    assert "jumpier than usual" in plain.volatility(1.4, 33.0, 24.0) and "calmer" in plain.volatility(0.7, 15.0, 22.0)
    below = plain.below_sma200(True, {"label": "passed"})
    assert "downtrend" in below and "tested headwind" in below
    above = plain.below_sma200(False, {"label": "passed"})
    assert "uptrend" in above and "headwind" not in above                       # the tested warning is for names below the average only
    assert plain.below_sma200(None) is None


def test_all_lines_skips_what_is_missing():
    assert plain.all_lines(None, None, None, None, None, {"ratio": None}, None, {}) == []
