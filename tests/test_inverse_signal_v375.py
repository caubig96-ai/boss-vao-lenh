from component_selector import inverse_direction


def test_inverse_direction():
    assert inverse_direction("UP") == "DOWN"
    assert inverse_direction("DOWN") == "UP"
