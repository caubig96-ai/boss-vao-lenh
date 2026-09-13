from indicators import sma, ema, rsi


def test_sma():
    assert sma([1, 2, 3], 2) == 2.5
