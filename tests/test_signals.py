import pandas as pd

from fire25.signals import calculate_puddle_signal


def _make_base_df(close_values):
    idx = pd.date_range("2025-01-01", periods=len(close_values), freq="B")
    return pd.DataFrame(
        {
            "Close": close_values,
            "SMA_50": [100.0] * len(close_values),
            "SMA_100": [90.0] * len(close_values),
            "SMA_200": [80.0] * len(close_values),
        },
        index=idx,
    )


def test_stage1_cross_triggers_when_not_in_cooldown():
    # Prior day above SMA_50, today below SMA_50; no same cross in trailing cooldown window.
    close = [105.0] * 34 + [95.0]
    df = _make_base_df(close)

    res = calculate_puddle_signal(df, cooldown_days=30)

    assert res.stage == 1
    assert res.alert is True
    assert res.cooldown_active is False


def test_stage1_cross_suppressed_when_recent_same_cross_exists():
    close = [105.0] * 40
    close[10] = 95.0  # historical cross-below within cooldown window
    close[11] = 105.0  # recover above
    close[39] = 95.0  # today's cross-below
    df = _make_base_df(close)

    res = calculate_puddle_signal(df, cooldown_days=30)

    assert res.stage == 1
    assert res.alert is False
    assert res.cooldown_active is True
    assert res.cooldown_info is not None


def test_result_is_stable_when_evaluated_on_truncated_data():
    close = [105.0] * 45 + [95.0] + [130.0] * 10
    full_df = _make_base_df(close)
    eval_idx = 45

    prefix = full_df.iloc[: eval_idx + 1].copy()
    res_prefix = calculate_puddle_signal(prefix, cooldown_days=30)

    # Mutate future rows heavily; evaluation on the same truncated prefix must not change.
    mutated = full_df.copy()
    mutated.iloc[eval_idx + 1 :, mutated.columns.get_loc("Close")] = 1.0
    res_mutated_prefix = calculate_puddle_signal(mutated.iloc[: eval_idx + 1], cooldown_days=30)

    assert res_prefix == res_mutated_prefix


def test_stage2_cross_triggers_when_not_in_cooldown():
    # Prior day above SMA_100, today below SMA_100 while still above SMA_200.
    close = [95.0] * 34 + [85.0]
    df = _make_base_df(close)

    res = calculate_puddle_signal(df, cooldown_days=30)

    assert res.stage == 2
    assert res.alert is True
    assert res.cooldown_active is False


def test_stage3_cross_triggers_when_not_in_cooldown():
    # Prior day above SMA_200, today below SMA_200.
    close = [85.0] * 34 + [75.0]
    df = _make_base_df(close)

    res = calculate_puddle_signal(df, cooldown_days=30)

    assert res.stage == 3
    assert res.alert is True
    assert res.cooldown_active is False


def test_stage4_cross_up_triggers_when_not_in_cooldown():
    # Prior day below SMA_200, today above SMA_200.
    close = [75.0] * 34 + [85.0]
    df = _make_base_df(close)

    res = calculate_puddle_signal(df, cooldown_days=30)

    assert res.stage == 4
    assert res.alert is True
    assert res.cooldown_active is False


def test_stage4_cross_up_suppressed_when_recent_same_cross_exists():
    close = [75.0] * 40
    close[11] = 85.0  # historical cross-above within cooldown window
    close[12] = 75.0  # move back below
    close[39] = 85.0  # today's cross-above
    df = _make_base_df(close)

    res = calculate_puddle_signal(df, cooldown_days=30)

    assert res.stage == 4
    assert res.alert is False
    assert res.cooldown_active is True
    assert res.cooldown_info is not None
