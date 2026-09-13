from candle_color_model import candle_direction, settle_prediction


def test_equal_candle_is_green_up():
    assert candle_direction(100, 100) == "UP"
    assert settle_prediction("UP", 100, 100) == "WIN"
    assert settle_prediction("DOWN", 100, 100) == "LOSS"
