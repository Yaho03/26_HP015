from exp8_evacuation_latency import percentile


def test_percentile_uses_nearest_rank():
    assert percentile(list(range(1, 31)), 0.95) == 29


def test_percentile_rejects_empty_input():
    try:
        percentile([], 0.95)
    except ValueError:
        pass
    else:
        raise AssertionError("empty input must fail")
