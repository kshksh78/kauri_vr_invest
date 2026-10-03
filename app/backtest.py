"""Daily adjusted-close VR model with cash-flow-neutral unit performance.

All decisions use the current close or an already observed previous close.
Adjusted model quantities are deliberately distinct from broker share counts.
"""
import math
from datetime import date, timedelta

from app.engine import close_trade, initialize, initialize_existing, next_cycle
from app.schemas import VRSettings


def _number(value, field):
    if isinstance(value, bool):
        raise ValueError(f'{field}: 유한한 숫자가 필요합니다.')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{field}: 유한한 숫자가 필요합니다.') from exc
    if not math.isfinite(result):
        raise ValueError(f'{field}: 유한한 숫자가 필요합니다.')
    return result


def _day(value):
    if isinstance(value, date):
        return date.fromisoformat(value.isoformat()[:10])
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError('날짜는 YYYY-MM-DD 형식이어야 합니다.') from exc


def _range(first, final):
    try:
        oldest = final.replace(year=final.year - 10)
    except ValueError:
        oldest = final.replace(year=final.year - 10, day=28)
    if first > final or first < oldest:
        raise ValueError('백테스트 범위는 순서가 맞는 최대 10년이어야 합니다.')


def _prepare(rows, start, end):
    if not rows:
        raise ValueError('백테스트에 사용할 실제 가격이 없습니다. 먼저 가격을 가져오세요.')
    ordered = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or 'date' not in row or 'adj_close' not in row:
            raise ValueError('가격 행에 date와 adj_close가 필요합니다.')
        day = _day(row['date'])
        price = _number(row.get('adj_close'), 'adj_close')
        if price <= 0 or day in seen:
            raise ValueError('가격은 양수여야 하며 같은 날짜가 중복될 수 없습니다.')
        seen.add(day)
        ordered.append({**row, 'day': day, 'price': price})
    ordered.sort(key=lambda row: row['day'])
    first = _day(start) if start else ordered[0]['day']
    final = _day(end) if end else ordered[-1]['day']
    _range(first, final)
    selected = [row for row in ordered if first <= row['day'] <= final]
    if not selected:
        raise ValueError('요청 범위에 실제 거래일 가격이 없습니다.')
    currencies = {row['currency'] for row in selected if row.get('currency')}
    symbols = {row['symbol'] for row in selected if row.get('symbol')}
    if len(currencies) > 1 or len(symbols) > 1:
        raise ValueError('종목과 통화가 같은 가격만 함께 분석할 수 있습니다.')
    warnings = [row['basis_warning'] for row in selected if row.get('basis_warning')]
    if first < selected[0]['day']:
        warnings.append('요청 시작일의 가격이 없어 첫 실제 거래일에서 시작했습니다. 상장일과 휴장일을 확인하세요.')
    if final > selected[-1]['day']:
        warnings.append('요청 종료일의 가격이 없습니다. 마지막 확보된 실제 종가까지만 분석했습니다.')
    gaps = [{'after': a['day'].isoformat(), 'before': b['day'].isoformat(),
             'calendar_days': (b['day'] - a['day']).days}
            for a, b in zip(selected, selected[1:]) if (b['day'] - a['day']).days > 4]
    if gaps:
        warnings.append('4달력일을 넘는 가격 간격이 있습니다. 휴장 또는 누락 여부를 확인하세요. 중간 가격은 보간하지 않았습니다.')
    snapshots = sorted({row['snapshot_id'] for row in selected if row.get('snapshot_id') is not None})
    if len(snapshots) > 1:
        warnings.append('여러 원본 snapshot을 사용했습니다. 수정종가 기준 일치를 위해 인터넷 전체 기간 갱신을 권장합니다.')
    metadata = {'requested_start': first.isoformat(), 'requested_end': final.isoformat(),
                'actual_start': selected[0]['day'].isoformat(), 'actual_end': selected[-1]['day'].isoformat(),
                'currency': next(iter(currencies), None), 'snapshots': snapshots,
                'basis': 'adjusted_model', 'gaps': gaps,
                'warnings': list(dict.fromkeys(warnings))}
    return selected, metadata


def _scheduled_flows(flows, anchor, cycle_days):
    scheduled = []
    for flow in flows or []:
        if not isinstance(flow, dict) or 'date' not in flow or 'amount' not in flow:
            raise ValueError('입출금 행에 date와 amount가 필요합니다.')
        day = _day(flow['date'])
        amount = _number(flow['amount'], 'flow')
        if day <= anchor:
            raise ValueError('초기 거래일 이전·당일 입출금은 초기 투자금에 반영하세요.')
        days = (day - anchor).days
        cycle = (days + cycle_days - 1) // cycle_days
        boundary = anchor + timedelta(days=cycle * cycle_days)
        scheduled.append({'requested_date': day.isoformat(), 'boundary': boundary,
                          'amount': amount})
    return sorted(scheduled, key=lambda flow: flow['requested_date'])


def run_backtest(rows, settings, capital=15000, allocation=0.5, flows=None,
                 start=None, end=None, initial_holdings=None):
    """Return daily states and TWR; explicit flows replace that cycle's plan.

    ``flows`` is a list of {date, amount}. Each date shifts to the first
    actual trading day of the next anchored calendar cycle on/after it.
    No new funding is applied on the seed day. A quote row can carry SQLite
    snapshot_id, currency and basis_warning for reproducible metadata.
    """
    settings = VRSettings.model_validate(settings)
    selected, metadata = _prepare(rows, start, end)
    anchor = selected[0]['day']
    scheduled = _scheduled_flows(flows, anchor, settings.cycle_days)
    existing = initial_holdings is not None
    if existing:
        if not isinstance(initial_holdings, dict) or not {'qty', 'pool'} <= initial_holdings.keys():
            raise ValueError('기존 보유 시작에는 모형 수량과 Pool이 필요합니다.')
        seed = initialize_existing(initial_holdings['qty'], initial_holdings['pool'],
                                   selected[0]['price'], settings, initial_holdings.get('v'),
                                   basis='adjusted_model')
        capital = seed['opening_equity']
    else:
        seed = initialize(capital, allocation, selected[0]['price'], settings, basis='adjusted_model')
    metadata.update(initialization_mode='existing_holdings' if existing else 'new_purchase',
                    initial_equity=capital)
    qty, pool, v = seed['qty'], seed['pool'], seed['v']
    remaining = pool * settings.pool_usage
    units = _number(capital, 'capital')
    net_contributions = units
    peak = 1.0
    mdd = 0.0
    total_fees = seed['initial_fee']
    trade_count = 1 if qty and not existing else 0
    current_cycle = 0
    previous_price = selected[0]['price']
    daily = []
    pending = 0
    for index, row in enumerate(selected):
        day, price = row['day'], row['price']
        calendar_cycle = (day - anchor).days // settings.cycle_days
        flow = 0.0
        applied = []
        if index == 0:
            trade = {'side': 'buy', 'qty': qty, 'price': price,
                     'gross': qty * price, 'fee': seed['initial_fee'],
                     'cash_delta': -seed['initial_cost'], 'initial': True} if qty and not existing else None
        else:
            if calendar_cycle > current_cycle:
                while pending < len(scheduled) and scheduled[pending]['requested_date'] <= day.isoformat():
                    applied.append(scheduled[pending])
                    pending += 1
                flow = sum(item['amount'] for item in applied) if applied else settings.periodic_flow
                pre_flow_equity = qty * price + pool
                if pre_flow_equity <= 0 or pre_flow_equity + flow <= 0:
                    raise ValueError('전액 인출 또는 자산 소진으로 백테스트를 계속할 수 없습니다.')
                next_state = next_cycle(v, pool, qty, previous_price, settings, flow,
                                        basis='adjusted_model')
                # Issue units using today's market value BEFORE cash flow and trading.
                units += flow / (pre_flow_equity / units)
                if units <= 0 or not math.isfinite(units):
                    raise ValueError('성과 단위가치를 계산할 수 없는 입출금입니다.')
                net_contributions += flow
                v, pool, remaining = next_state['v'], next_state['pool_start'], next_state['budget']
                current_cycle = calendar_cycle
            changed = close_trade(v, qty, pool, remaining, price, settings)
            qty, pool, remaining = changed['qty'], changed['pool'], changed['remaining_budget']
            trade = changed['trade']
            if trade:
                trade_count += 1
                total_fees += trade['fee']
        equity = qty * price + pool
        nav = equity / units
        peak = max(peak, nav)
        drawdown = nav / peak - 1
        mdd = min(mdd, drawdown)
        state = {'date': day.isoformat(), 'price': price, 'qty': qty, 'pool': pool,
                 'v': v, 'lower': v * (1 - settings.band), 'upper': v * (1 + settings.band),
                 'remaining_budget': remaining, 'equity': equity,
                 'net_contributions': net_contributions, 'profit': equity - net_contributions,
                 'twr': nav - 1, 'drawdown': drawdown, 'flow': flow,
                 'flow_requested_dates': [item['requested_date'] for item in applied],
                 'trade': trade, 'cycle': current_cycle, 'nav': nav,
                 'snapshot_id': row.get('snapshot_id')}
        if not all(math.isfinite(state[key]) for key in ['pool', 'v', 'equity', 'nav', 'twr', 'profit']):
            raise ValueError('계산 결과가 표현 가능한 숫자 범위를 초과했습니다.')
        daily.append(state)
        previous_price = price
    last = daily[-1]
    elapsed = (selected[-1]['day'] - anchor).days
    cagr = None
    if elapsed > 0 and last['nav'] > 0:
        try:
            annualized = math.expm1(math.log(last['nav']) * 365.2425 / elapsed)
            cagr = annualized if math.isfinite(annualized) else None
        except OverflowError:
            pass
    metadata['unapplied_flows'] = [{'date': item['requested_date'], 'amount': item['amount'],
                                    'cycle_boundary': item['boundary'].isoformat()}
                                   for item in scheduled[pending:]]
    if metadata['unapplied_flows']:
        metadata['warnings'].append('분석 기간 뒤 회차에 예정된 입출금은 적용하지 않았습니다.')
    summary = {key: last[key] for key in ['equity', 'net_contributions', 'profit', 'twr', 'qty', 'pool', 'v']}
    summary.update(mdd=mdd, cagr=cagr, total_fees=total_fees, trade_count=trade_count,
                   days=len(daily), calendar_days=elapsed,
                   roi=last['profit'] / net_contributions if net_contributions > 0 else None)
    return {'summary': summary, 'daily': daily, 'metadata': metadata,
            'settings': settings.model_dump(),
            'assumptions': [
                '수정종가와 모형 수량을 사용하며 실제 증권사 보유 주수와 다릅니다.',
                '수정종가에 반영된 배당을 현금 Pool에 다시 더하지 않습니다.',
                '현재 일별 종가로만 매매를 판단하며 장중 예약주문 체결을 재현하지 않습니다.',
                '시작일에는 추가 밴드 거래를 하지 않고 다음 거래일부터 판단합니다.',
                ('기존 보유 시작은 첫 수정종가 × 모형 수량 + Pool을 성과 기준으로 삼고 과거 매수·비용을 재현하지 않습니다.'
                 if existing else '신규 매수 시작은 초기 투자금에서 매수금과 비용을 차감합니다.'),
                '회차는 첫 실제 거래일 기준 달력일이며 직전 실제 종가로 새 V를 계산합니다.',
                '입출금은 다음 회차의 첫 실제 거래일 매매 전에 반영하며 해당 회차 예정 정기액을 대체합니다.',
                'TWR와 MDD는 입출금을 제거한 성과 단위가치로 계산하고 초기 매수 비용도 반영합니다.',
                '매도금으로 고정 회차 매수한도를 다시 늘리지 않습니다.',
            ]}
