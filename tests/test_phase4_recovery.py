from scripts.phase4_data_recovery import classify_market_header


def test_ohlc_is_not_promoted_to_ticks_or_quotes() -> None:
    assert classify_market_header(["timestamp", "open", "high", "low", "close", "volume"]) == "ohlc_bar_only"


def test_bid_ask_requires_both_sides() -> None:
    assert classify_market_header(["time", "bid", "ask"]) == "bid_ask_quote_candidate"

