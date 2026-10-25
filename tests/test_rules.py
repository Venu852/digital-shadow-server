import pytest
from app.rules import (CONTEXT_DAMP, CONTEXT_TAGS, MIN_GROUP, SIGNALS, SUGGESTION_THRESHOLD,
                       PERSONAL_SUGGESTION_THRESHOLD, display_drift, factor_breakdown, horizon_for,
                       personal_suggestions, status_for, top_signal)

def levels(switching=0, session=0, checks=0, screen=0, night=0, timing=0):
    return {'switching': switching, 'session': session, 'checks': checks,
            'screen': screen, 'night': night, 'timing': timing}

def test_constants():
    assert (MIN_GROUP, CONTEXT_DAMP, SUGGESTION_THRESHOLD, PERSONAL_SUGGESTION_THRESHOLD) == (3, 15, 30, 20)
    assert CONTEXT_TAGS == ('None', 'Exam week', 'Travel', 'Holiday or break', 'Busy period', 'New routine')
    assert [s['key'] for s in SIGNALS] == ['switching', 'session', 'checks', 'screen', 'night', 'timing']

@pytest.mark.parametrize('score,label,band', [
    (0, 'Stable', 'stable'),
    (19, 'Stable', 'stable'),
    (20, 'Early drift', 'early'),
    (44, 'Early drift', 'early'),
    (45, 'Elevated drift', 'elevated'),
    (69, 'Elevated drift', 'elevated'),
    (70, 'High drift', 'high'),
    (100, 'High drift', 'high'),
])
def test_status_bands(score, label, band):
    assert status_for(score) == {'label': label, 'band': band}

@pytest.mark.parametrize('series,expected', [
    ([], 'Not enough days yet'),
    ([10, 20, 30], 'Not enough days yet'),
    ([10, 0, 0, 19], '2 to 3 weeks if the trend continues'),     # slope 9
    ([10, 0, 0, 18], '4 to 6 weeks if the trend continues'),     # slope 8
    ([10, 0, 0, 13], '4 to 6 weeks if the trend continues'),     # slope 3
    ([10, 0, 0, 12], 'No defined trend: stable or improving'),  # slope 2
    ([50, 0, 0, 20], 'No defined trend: stable or improving'),  # falling
    ([99, 99, 10, 0, 0, 30], '2 to 3 weeks if the trend continues'),  # only last 4 matter
])
def test_horizon_thresholds(series, expected):
    assert horizon_for(series) == expected

def test_context_damp_clamped_at_zero():
    assert display_drift(40, True) == 25
    assert display_drift(15, True) == 0
    assert display_drift(10, True) == 0
    assert display_drift(40, False) == 40

def test_factor_breakdown_pct_rounding_and_order():
    # 10/80 = 12.5 -> 13 (half up), 30/80 = 37.5 -> 38, 20/80 = 25
    factors = factor_breakdown(levels(switching=10, session=30, checks=20, screen=20), 'self')
    assert [f['key'] for f in factors] == ['session', 'checks', 'screen', 'switching', 'night', 'timing']
    assert [f['pct'] for f in factors] == [38, 25, 25, 13, 0, 0]
    assert factors[0]['label'] == 'Session length'
    assert factors[0]['cause'] == 'Your time in a single app is shorter than usual.'

    # 1/3 = 33.33 -> 33
    factors = factor_breakdown(levels(switching=1, session=1, checks=1), 'manager')
    assert [f['pct'] for f in factors[:3]] == [33, 33, 33]
    assert factors[0]['cause'] == "App switching is above the group's baseline."

def test_factor_breakdown_all_zero():
    factors = factor_breakdown(levels(), 'self')
    assert [f['pct'] for f in factors] == [0] * 6
    assert set(factors[0]) == {'key', 'label', 'level', 'pct', 'cause'}

def test_top_signal_ties_follow_signal_order():
    assert top_signal(levels(screen=50, checks=50)) == 'checks'
    assert top_signal(levels(night=60, switching=10)) == 'night'
    assert top_signal(levels(timing=1)) == 'timing'

def test_every_signal_has_all_texts():
    for s in SIGNALS:
        assert set(s) == {'key', 'label', 'self', 'manager', 'action', 'personal'}

def test_personal_suggestions_top_two_ties_follow_signal_order():
    items = personal_suggestions(levels(switching=10, night=40, timing=40, checks=5))
    assert items == [
        {'signal': 'night', 'label': 'Late-night use',
         'text': 'Try putting the phone away 30 minutes earlier tonight.',
         'because': 'You are using the phone more between midnight and 5am than usual.'},
        {'signal': 'timing', 'label': 'Routine timing',
         'text': 'Try keeping your first and last phone use of the day closer to your usual times.',
         'because': 'Your phone day is starting or ending at different times than usual.'},
    ]
