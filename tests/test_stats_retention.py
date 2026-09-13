from component_selector import evaluate_method


def test_inversion_does_not_change_raw_result_counts():
    results = ["WIN"] + ["LOSS"] * 20 + ["WIN"] * 9
    item = evaluate_method("UP", 0.9, results)
    assert item["losses"] == 20
    assert item["wins"] == 10
