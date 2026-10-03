import math

import pytest

from app.backtest import run_backtest
from app.schemas import VRSettings


def test_existing_units_multiple_flows_have_zero_return_at_flat_price():
    rows = [{"date": day, "adj_close": 80, "currency": "USD"}
            for day in ["2026-01-02", "2026-01-05", "2026-01-12", "2026-01-16", "2026-01-20", "2026-01-30"]]
    result = run_backtest(rows, {"mode": "skilled", "fee": 0, "periodic_flow": 100},
                          initial_holdings={"qty": 100, "pool": 7000},
                          flows=[{"date": "2026-01-05", "amount": 2000}, {"date": "2026-01-12", "amount": 3000},
                                 {"date": "2026-01-20", "amount": 2500}])
    assert result["daily"][0]["trade"] is None
    assert result["daily"][0]["equity"] == 15000
    assert result["summary"]["equity"] == 22500
    assert result["summary"]["net_contributions"] == 22500
    assert result["summary"]["twr"] == 0
    assert result["summary"]["mdd"] == 0


def prices(days, value=100, **metadata):
    return [{'date': day, 'adj_close': value, **metadata} for day in days]


def test_flat_prices_deposit_changes_capital_not_performance():
    rows = prices(['2026-01-02', '2026-01-15', '2026-01-16', '2026-01-30'])
    result = run_backtest(rows, VRSettings(fee=0), flows=[{'date': '2026-01-10', 'amount': 5000}])
    assert result['summary']['equity'] == 20000
    assert result['summary']['net_contributions'] == 20000
    assert result['summary']['profit'] == 0
    assert result['summary']['twr'] == 0
    assert result['summary']['mdd'] == 0
    assert [row['flow'] for row in result['daily']] == [0, 0, 5000, 0]
    assert result['daily'][2]['v'] == 13250


def test_initial_fee_and_skill_cycle_independent_fixture():
    rows = [{'date': '2026-01-02', 'adj_close': 100},
            {'date': '2026-01-15', 'adj_close': 80},
            {'date': '2026-01-16', 'adj_close': 80}]
    result = run_backtest(rows, VRSettings(mode='skilled'))
    first, previous, current = result['daily']
    assert first['qty'] == 74
    assert first['pool'] == pytest.approx(7596.3)
    assert first['trade']['qty'] == 74
    assert first['equity'] == pytest.approx(14996.3)
    # Jan 15 close may buy 4 shares under the old band. The next V uses
    # this observed previous state, independently evaluated in cents.
    assert previous['qty'] == 78
    assert previous['pool'] == pytest.approx(7276.14)
    assert current['v'] == 7944.2
    assert result['summary']['mdd'] < 0


def test_weekend_start_anchor_and_next_cycle_actual_day():
    result = run_backtest(prices(['2026-01-05', '2026-01-16', '2026-01-20']),
                          VRSettings(fee=0), start='2026-01-03', end='2026-01-20')
    assert result['metadata']['actual_start'] == '2026-01-05'
    assert [day['cycle'] for day in result['daily']] == [0, 0, 1]
    assert result['daily'][2]['v'] == 8250


def test_future_price_does_not_change_past_state():
    rows = prices(['2026-01-02', '2026-01-16', '2026-01-30'])
    before = run_backtest(rows, VRSettings(mode='skilled'))
    rows[-1]['adj_close'] = 1
    after = run_backtest(rows, VRSettings(mode='skilled'))
    assert before['daily'][:2] == after['daily'][:2]


def test_actual_flow_replaces_periodic_flow_and_same_cycle_flows_sum():
    result = run_backtest(prices(['2026-01-02', '2026-01-16', '2026-01-30']),
                          VRSettings(fee=0, periodic_flow=100),
                          flows=[{'date': '2026-01-05', 'amount': 2500},
                                 {'date': '2026-01-10', 'amount': 2500}])
    assert [day['flow'] for day in result['daily']] == [0, 5000, 100]
    assert result['summary']['net_contributions'] == 20100


def test_withdrawal_is_not_loss_and_overdraw_is_rejected():
    rows = prices(['2026-01-02', '2026-01-16'])
    result = run_backtest(rows, VRSettings(fee=0), flows=[{'date': '2026-01-16', 'amount': -1000}])
    assert result['summary']['equity'] == 14000
    assert result['summary']['twr'] == 0
    with pytest.raises(ValueError):
        run_backtest(rows, VRSettings(fee=0), flows=[{'date': '2026-01-16', 'amount': -8000}])


@pytest.mark.parametrize('mode', ['basic', 'skilled'])
def test_price_shocks_preserve_integer_quantity_and_fixed_budget(mode):
    rows = [{'date': f'2026-01-{day:02}', 'adj_close': price}
            for day, price in [(2, 100), (5, 50), (6, 200), (7, 30), (16, 40)]]
    result = run_backtest(rows, VRSettings(mode=mode))
    for day in result['daily']:
        assert isinstance(day['qty'], int)
        assert day['pool'] >= 0 and day['remaining_budget'] >= 0
        assert all(math.isfinite(day[field]) for field in ['v', 'equity', 'twr', 'drawdown'])
    assert result['daily'][2]['remaining_budget'] == result['daily'][1]['remaining_budget']


def test_metadata_reports_snapshot_and_sparse_coverage():
    rows = prices(['2026-01-05', '2026-01-20'], snapshot_id=7, currency='USD', provider='yahoo')
    result = run_backtest(rows, {}, start='2025-12-01', end='2026-01-30')
    assert result['metadata']['snapshots'] == [7]
    assert result['metadata']['currency'] == 'USD'
    assert result['metadata']['warnings']
    assert result['metadata']['actual_end'] == '2026-01-20'


@pytest.mark.parametrize('rows', [[], [{}], [None], prices(['2026-01-02'], value=0),
                                prices(['2026-01-02'], value=float('nan')),
                                prices(['2026-01-02', '2026-01-02']),
                                [{'date': '2026-01-02', 'adj_close': 100, 'currency': 'USD'},
                                 {'date': '2026-01-05', 'adj_close': 100, 'currency': 'KRW'}]])
def test_invalid_price_inputs_rejected(rows):
    with pytest.raises(ValueError):
        run_backtest(rows, {})


def test_dates_are_sorted_and_requested_range_is_respected():
    rows = prices(['2026-01-16', '2026-01-02', '2026-01-30'])
    result = run_backtest(rows, {}, start='2026-01-02', end='2026-01-16')
    assert [day['date'] for day in result['daily']] == ['2026-01-02', '2026-01-16']
    with pytest.raises(ValueError, match='10년'):
        run_backtest(rows, {}, start='2010-01-01', end='2026-01-16')


@pytest.mark.parametrize('flow', [{}, None, {'date': '2026-01-02', 'amount': 100},
                                {'date': '2026-01-16', 'amount': float('inf')}])
def test_invalid_flow_inputs_rejected(flow):
    with pytest.raises(ValueError):
        run_backtest(prices(['2026-01-02', '2026-01-16']), {}, flows=[flow])


def test_later_flow_is_explicitly_unapplied_not_counted_as_capital():
    result = run_backtest(prices(['2026-01-02', '2026-01-16']), VRSettings(fee=0),
                          flows=[{'date': '2026-02-01', 'amount': 5000}])
    assert result['summary']['net_contributions'] == 15000
    assert result['metadata']['unapplied_flows'] == [
        {'date': '2026-02-01', 'amount': 5000, 'cycle_boundary': '2026-02-13'}]


def test_flows_before_and_on_delayed_actual_cycle_opening_apply_together():
    rows = prices(['2026-06-05', '2026-06-18', '2026-06-22', '2026-07-06'])
    result = run_backtest(rows, VRSettings(fee=0, periodic_flow=100, band=.99),
                          flows=[{'date': '2026-06-20', 'amount': 2000},
                                 {'date': '2026-06-22', 'amount': 3000},
                                 {'date': '2026-06-23', 'amount': 1000}])
    assert [row['flow'] for row in result['daily']] == [0, 0, 5000, 1000]
    assert result['daily'][2]['flow_requested_dates'] == ['2026-06-20', '2026-06-22']
    assert result['summary']['net_contributions'] == 21000
    assert result['summary']['twr'] == 0


def test_deposit_on_price_rise_uses_current_pre_flow_market_value():
    rows = [{'date': day, 'adj_close': price} for day, price in
            [('2026-01-02', 100), ('2026-01-15', 100), ('2026-01-16', 110), ('2026-01-30', 121)]]
    result = run_backtest(rows, VRSettings(mode='skilled', fee=0, band=.99),
                          initial_holdings={'qty': 75, 'pool': 7500},
                          flows=[{'date': '2026-01-16', 'amount': 5000}])
    assert result['daily'][2]['twr'] == pytest.approx(.05)
    assert result['summary']['equity'] == 21575
    assert result['summary']['twr'] == pytest.approx(21575 / (15000 + 5000 / 1.05) - 1)
