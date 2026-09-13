from component_selector import evaluate_method


def test_losing_method_is_inverted_but_stats_remain_raw():
    results = ["WIN"] + ["LOSS"] * 20 + ["WIN"] * 9
    x = evaluate_method("UP", 0.8, results)
    assert x is not None
    assert x["raw_direction"] == "UP"
    assert x["sent_direction"] == "DOWN"
    assert x["inverted"] is True
    assert x["losses"] > x["wins"]
