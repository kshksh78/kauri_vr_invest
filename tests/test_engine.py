import math

import pytest
from pydantic import ValidationError

from app.engine import close_trade, initialize, ladder, next_cycle
from app.schemas import VRSettings


def test_initial_independent_spreadsheet_fixture():
    state = initialize(15000, 0.5, 100, VRSettings())
    assert state['qty'] == 74
    assert state['pool'] == pytest.approx(7596.30)
    assert state['v'] == 7400
    assert state['initial_fee'] == pytest.approx(3.70)


@pytest.mark.parametrize('close,flow,expected', [(80, 0, 7925.62), (120, 0, 8393.64), (120, 100, 8493.64)])
def test_skill_formula_independent_expected(close, flow, expected):
    result = next_cycle(7400, 7596.3, 74, close, VRSettings(mode='skilled'), flow)
    assert result['v'] == expected
    assert result['pool_start'] == pytest.approx(7596.3 + flow)
    assert result['budget'] == pytest.approx((7596.3 + flow) * 0.5)
    assert result['components']['pool_growth'] == pytest.approx(759.63)
    assert result['components']['flow'] == flow


def test_half_up_rounding_before_fractional_flow():
    result = next_cycle(1.005, 0, 1, 1.005, VRSettings(mode='skilled'), 0.004)
    assert result['components']['rounded_v_before_flow'] == 1.01
    assert result['v'] == pytest.approx(1.014)


def test_basic_retains_precision_and_does_not_require_previous_close():
    result = next_cycle(1.005, 0, 0, None, VRSettings(mode='basic'))
    assert result['v'] == 1.005
    assert not result['waiting']
    waiting = next_cycle(7400, 7596.3, 74, None, VRSettings(mode='skilled'))
    assert waiting['waiting'] and waiting['v'] is None


def test_seed_manual_overrides_and_basis():
    result = initialize(15000, 0.5, 100, VRSettings(), qty_override=80, pool_override=6500, v_override=9000, basis='adjusted_model')
    assert (result['qty'], result['pool'], result['v']) == (80, 6500, 9000)
    assert result['basis'] == 'adjusted_model'


def test_ladder_rounds_buy_down_sell_up_and_accumulates_fee_cost():
    result = ladder(1000, 10, 1000, 160, VRSettings(fee=0.01), max_orders=3)
    assert len(result['buy']) == 2
    assert [row['price'] for row in result['buy']] == [77.27, 70.83]
    assert result['buy'][-1]['cumulative_cost'] == pytest.approx(149.581)
    assert [row['price'] for row in result['sell']] == [127.78, 143.75, 164.29]
    assert all(row['qty'] == 1 for row in result['buy'] + result['sell'])


def test_ladder_has_no_zero_share_divisor_and_respects_cash():
    result = ladder(1000, 1, 70, 1000, VRSettings(fee=0), max_orders=40)
    assert result['buy'] == []
    assert result['sell'] == []


def test_buy_integer_floor_and_fee_inclusive_budget():
    state = close_trade(1000, 5, 1000, 206, 100, VRSettings(fee=0.03))
    assert state['qty'] == 7
    assert state['pool'] == 794
    assert state['remaining_budget'] == 0
    assert state['trade']['qty'] == 2
    # A $0.01 smaller budget cannot buy the second share.
    limited = close_trade(1000, 5, 1000, 205.99, 100, VRSettings(fee=0.03))
    assert limited['qty'] == 6
    assert limited['remaining_budget'] == pytest.approx(102.99)


def test_buy_floor_may_leave_less_than_one_share_below_band():
    state = close_trade(1000, 8, 1000, 1000, 100, VRSettings(fee=0))
    assert state['qty'] == 8
    assert state['trade'] is None


def test_sale_ceil_retains_shares_and_does_not_replenish_budget():
    state = close_trade(1000, 15, 200, 70, 100, VRSettings(fee=0.01))
    assert state['qty'] == 12
    assert state['pool'] == 497
    assert state['remaining_budget'] == 70
    assert state['trade']['side'] == 'sell'


@pytest.mark.parametrize('field,value', [('g', 0), ('g', -1), ('g', math.nan), ('band', 1), ('fee', -0.01), ('tick', 0), ('pool_usage', 1.1), ('cycle_days', 0), ('cycle_days', 1.5)])
def test_settings_reject_invalid(field, value):
    with pytest.raises(ValidationError):
        VRSettings(**{field: value})


@pytest.mark.parametrize('args', [(0, 100, 1, 100), (100, -1, 1, 100), (100, 100, -1, 100), (100, 100, 1, 0), (100, 100, 1, math.inf)])
def test_next_rejects_invalid_states(args):
    with pytest.raises(ValueError):
        next_cycle(*args, VRSettings())


def test_insufficient_withdrawal_and_nonpositive_next_v_rejected():
    with pytest.raises(ValueError):
        next_cycle(1000, 100, 10, 100, VRSettings(), flow=-101)
    with pytest.raises(ValueError):
        next_cycle(1, 100, 1, 1, VRSettings(), flow=-20)


def test_nonfinite_and_fractional_quantity_rejected():
    with pytest.raises(ValueError):
        initialize(math.inf, 0.5, 100, VRSettings())
    with pytest.raises(ValueError):
        initialize(100, 0.5, 100, VRSettings(), qty_override=1.5)
    with pytest.raises(ValueError):
        close_trade(1000, 10, 100, -1, 100, VRSettings())
