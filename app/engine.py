"""I/O-free VR calculations in native currency.

Prices in an adjusted historical model represent model units, not actual
broker shares. The caller supplies that distinction in ``basis``.
"""

import math
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.schemas import VRSettings


def _decimal(value, name, *, minimum=0, positive=False):
    if isinstance(value, bool):
        raise ValueError(f'{name}: 숫자를 입력하세요.')
    try:
        number = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f'{name}: 숫자를 입력하세요.') from exc
    if not number.is_finite() or number < minimum or (positive and number == 0):
        raise ValueError(f'{name}: 유한한 유효 숫자를 입력하세요.')
    return number


def _quantity(qty):
    number = _decimal(qty, 'qty')
    if number != number.to_integral_value():
        raise ValueError('qty: 주식 수량은 0 이상의 정수여야 합니다.')
    return int(number)


def _flow(value):
    # External cash flows are signed; every resulting cash balance is checked.
    return _decimal(value, 'flow', minimum=Decimal('-Infinity'))


def _bands(v, settings):
    band = Decimal(str(settings.band))
    return v * (1 - band), v * (1 + band)


def _as_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('계산 결과가 표현 가능한 숫자 범위를 초과했습니다.')
    return result


def initialize(capital, allocation, price, settings, qty_override=None,
               pool_override=None, v_override=None, basis='actual'):
    """Create a seed, including fees, or accept explicit migration balances."""
    settings = VRSettings.model_validate(settings)
    capital = _decimal(capital, 'capital', positive=True)
    allocation = _decimal(allocation, 'allocation')
    if allocation > 1:
        raise ValueError('allocation: 초기 매수 비율은 0~1이어야 합니다.')
    price = _decimal(price, 'price', positive=True)
    fee = Decimal(str(settings.fee))
    qty = (_quantity(qty_override) if qty_override is not None
           else int((capital * allocation / (price * (1 + fee))).to_integral_value(rounding=ROUND_FLOOR)))
    gross = price * qty
    initial_fee = gross * fee
    pool = (_decimal(pool_override, 'pool_override') if pool_override is not None
            else _decimal(capital - gross - initial_fee, 'pool'))
    v = (_decimal(v_override, 'v_override', positive=True) if v_override is not None
         else _decimal(gross, 'v', positive=True))
    return {'qty': qty, 'pool': _as_float(pool), 'v': _as_float(v),
            'initial_cost': _as_float(gross + initial_fee),
            'initial_fee': _as_float(initial_fee), 'basis': basis}


def next_cycle(v, pool, qty, last_price, settings, flow=0, basis='actual'):
    """Apply previous Pool growth, skilled correction, then this cycle's flow."""
    settings = VRSettings.model_validate(settings)
    v = _decimal(v, 'v', positive=True)
    pool = _decimal(pool, 'pool')
    qty = _quantity(qty)
    flow = _flow(flow)
    pool_start = _decimal(pool + flow, 'pool_start')
    previous_equity = None
    if last_price is not None:
        previous_equity = _decimal(last_price, 'last_price', positive=True) * qty
    components = {'previous_v': _as_float(v), 'previous_pool': _as_float(pool),
                  'previous_equity': None if previous_equity is None else _as_float(previous_equity),
                  'pool_growth': _as_float(pool / Decimal(str(settings.g))),
                  'skill_adjustment': 0, 'rounded_v_before_flow': None,
                  'flow': _as_float(flow)}
    result = {'qty': qty, 'pool_start': _as_float(pool_start), 'basis': basis,
              'components': components, 'waiting': False}
    if settings.mode == 'skilled' and previous_equity is None:
        components['waiting_reason'] = '직전 회차의 확정 종가가 필요합니다.'
        result.update(v=None, lower=None, upper=None, budget=None, waiting=True)
        return result
    growth = pool / Decimal(str(settings.g))
    correction = Decimal(0)
    if settings.mode == 'skilled':
        correction = (previous_equity - v) / (2 * Decimal(str(settings.g)).sqrt())
    before_flow = v + growth + correction
    if settings.mode == 'skilled':
        before_flow = before_flow.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    updated_v = _decimal(before_flow + flow, 'next_v', positive=True)
    lower, upper = _bands(updated_v, settings)
    components.update(skill_adjustment=_as_float(correction),
                      rounded_v_before_flow=_as_float(before_flow))
    result.update(v=_as_float(updated_v), lower=_as_float(lower), upper=_as_float(upper),
                  budget=_as_float(pool_start * Decimal(str(settings.pool_usage))))
    return result


def ladder(v, qty, pool, remaining_budget, settings, max_orders=40, basis='actual'):
    """One-share reservation steps with cumulative fee-inclusive buy limits."""
    settings = VRSettings.model_validate(settings)
    v = _decimal(v, 'v', positive=True)
    qty = _quantity(qty)
    pool = _decimal(pool, 'pool')
    budget = _decimal(remaining_budget, 'remaining_budget')
    if isinstance(max_orders, bool) or not isinstance(max_orders, int) or not 1 <= max_orders <= 1000:
        raise ValueError('max_orders: 1~1000의 정수를 입력하세요.')
    lower, upper = _bands(v, settings)
    tick = Decimal(str(settings.tick))
    fee = Decimal(str(settings.fee))
    buys, sells = [], []
    cumulative = Decimal(0)
    for step in range(1, max_orders + 1):
        price = (lower / (qty + step) / tick).to_integral_value(rounding=ROUND_FLOOR) * tick
        if price <= 0:
            break
        cost = price * (1 + fee)
        if cumulative + cost > min(pool, budget):
            break
        cumulative += cost
        buys.append({'step': step, 'qty': 1, 'after_qty': qty + step,
                     'price': _as_float(price), 'fee': _as_float(price * fee),
                     'cost': _as_float(cost), 'cumulative_cost': _as_float(cumulative)})
    cumulative = Decimal(0)
    for step in range(1, min(max_orders, qty - 1) + 1):
        price = (upper / (qty - step) / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        proceeds = price * (1 - fee)
        cumulative += proceeds
        sells.append({'step': step, 'qty': 1, 'after_qty': qty - step,
                      'price': _as_float(price), 'fee': _as_float(price * fee),
                      'proceeds': _as_float(proceeds), 'cumulative_proceeds': _as_float(cumulative)})
    return {'buy': buys, 'sell': sells, 'lower': _as_float(lower),
            'upper': _as_float(upper), 'remaining_budget': _as_float(budget), 'basis': basis}


def close_trade(v, qty, pool, remaining_budget, price, settings, basis='adjusted_model'):
    """Apply one daily close decision; proceeds never replenish buy budget."""
    settings = VRSettings.model_validate(settings)
    v = _decimal(v, 'v', positive=True)
    qty = _quantity(qty)
    pool = _decimal(pool, 'pool')
    budget = _decimal(remaining_budget, 'remaining_budget')
    price = _decimal(price, 'price', positive=True)
    lower, upper = _bands(v, settings)
    fee = Decimal(str(settings.fee))
    equity = price * qty
    trade = None
    if equity < lower:
        target = int((lower / price).to_integral_value(rounding=ROUND_FLOOR))
        affordable = int((min(pool, budget) / (price * (1 + fee))).to_integral_value(rounding=ROUND_FLOOR))
        amount = min(max(0, target - qty), affordable)
        if amount:
            gross = price * amount
            cost = gross * (1 + fee)
            qty += amount
            pool -= cost
            budget -= cost
            trade = {'side': 'buy', 'qty': amount, 'price': _as_float(price),
                     'gross': _as_float(gross), 'fee': _as_float(gross * fee),
                     'cash_delta': -_as_float(cost)}
    elif equity > upper:
        target = int((upper / price).to_integral_value(rounding=ROUND_CEILING))
        amount = max(0, qty - target)
        if amount:
            gross = price * amount
            proceeds = gross * (1 - fee)
            qty -= amount
            pool += proceeds
            trade = {'side': 'sell', 'qty': amount, 'price': _as_float(price),
                     'gross': _as_float(gross), 'fee': _as_float(gross * fee),
                     'cash_delta': _as_float(proceeds)}
    return {'qty': qty, 'pool': _as_float(pool), 'remaining_budget': _as_float(budget),
            'trade': trade, 'basis': basis}
