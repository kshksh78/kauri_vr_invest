import pytest

from app.portfolios import PortfolioStore


def create(store):
    return store.create({"name": "검증 계좌", "symbol": "QLD", "start": "2026-01-02", "capital": 15000,
                         "allocation": 0.5, "price": 100, "settings": {"mode": "skilled", "g": 10}})


def test_deposit_once_snapshots_and_restart(tmp_path):
    path = tmp_path / "ledger.db"
    store = PortfolioStore(path)
    account = create(store)
    key = account["id"]
    assert account["state"]["qty"] == 74
    assert account["state"]["pool"] == pytest.approx(7596.3)
    account = store.add_event(key, {"date": "2026-01-16", "kind": "flow", "amount": 5000}, account["revision"])
    account = store.advance(key, {"start": "2026-01-16", "previous_close": 80}, account["revision"])
    assert account["state"]["v"] == 12925.62
    assert account["state"]["pool"] == pytest.approx(12596.3)
    assert account["state"]["budget"] == pytest.approx(6298.15)
    account = store.update_settings(key, {"g": 20}, account["revision"])
    assert account["cycles"][1]["settings"]["g"] == 10
    assert PortfolioStore(path).get(key)["state"] == account["state"]
    with pytest.raises(ValueError, match="revision|다시"):
        store.update_settings(key, {"g": 5}, 0)


def test_chronology_budget_and_atomic_edit(tmp_path):
    store = PortfolioStore(tmp_path / "ledger.db")
    account = create(store)
    key = account["id"]
    budget = account["state"]["budget"]
    account = store.add_event(key, {"date": "2026-01-05", "kind": "sell", "qty": 10, "price": 200}, account["revision"])
    assert account["state"]["budget"] == budget
    before = store.get(key)
    with pytest.raises(ValueError):
        store.add_event(key, {"date": "2026-01-02", "kind": "buy", "qty": 100, "price": 100}, account["revision"])
    assert store.get(key) == before
    event = account["events"][0]
    with pytest.raises(ValueError):
        store.edit_event(key, event["id"], {"qty": 1000}, account["revision"])
    assert store.get(key) == before


def test_split_and_missing_close(tmp_path):
    store = PortfolioStore(tmp_path / "ledger.db")
    account = create(store)
    account = store.add_event(account["id"], {"date": "2026-01-03", "kind": "split", "ratio": 2}, account["revision"])
    assert account["state"]["qty"] == 148
    assert account["state"]["pool"] == pytest.approx(7596.3)
    assert account["state"]["v"] == 7400
    account = store.advance(account["id"], {"start": "2026-01-16"}, account["revision"])
    assert account["state"]["waiting"] is True


def test_future_flow_not_pulled_before_deposit_and_planned_replaced(tmp_path):
    store = PortfolioStore(tmp_path / "ledger.db")
    account = create(store)
    account = store.update_settings(account["id"], {"periodic_flow": 100}, account["revision"])
    account = store.add_event(account["id"], {"date": "2026-02-02", "kind": "flow", "amount": 5000}, account["revision"])
    assert account["pending_flows"][0]["effective_date"] >= "2026-02-02"
    account = store.advance(account["id"], {"start": "2026-01-16", "previous_close": 100}, account["revision"])
    assert account["state"]["flow"] == 100
    account = store.add_event(account["id"], {"date": "2026-01-30", "kind": "flow", "amount": 5000}, account["revision"])
    account = store.advance(account["id"], {"start": "2026-01-30", "previous_close": 100}, account["revision"])
    assert account["state"]["flow"] == 5000


def test_future_dividend_cannot_fund_past_buy(tmp_path):
    store = PortfolioStore(tmp_path / "ledger.db")
    account = create(store)
    account = store.add_event(account["id"], {"date": "2026-01-02", "kind": "cost", "amount": 6000}, account["revision"])
    account = store.add_event(account["id"], {"date": "2026-01-06", "kind": "dividend", "amount": 5000}, account["revision"])
    assert account["state"]["budget"] == pytest.approx(3798.15)
    before = store.get(account["id"])
    with pytest.raises(ValueError, match="당시 Pool"):
        store.add_event(account["id"], {"date": "2026-01-05", "kind": "buy", "qty": 30, "price": 100}, account["revision"])
    assert store.get(account["id"]) == before


def test_flow_delete_rolls_back_if_later_buy_needs_it(tmp_path):
    store = PortfolioStore(tmp_path / "ledger.db")
    account = create(store)
    account = store.add_event(account["id"], {"date": "2026-01-16", "kind": "flow", "amount": 5000}, account["revision"])
    event_id = account["events"][0]["id"]
    account = store.advance(account["id"], {"start": "2026-01-16", "previous_close": 80}, account["revision"])
    account = store.add_event(account["id"], {"date": "2026-01-16", "kind": "buy", "qty": 50, "price": 100}, account["revision"])
    before = store.get(account["id"])
    with pytest.raises(ValueError):
        store.delete_event(account["id"], event_id, account["revision"])
    assert store.get(account["id"]) == before


def test_pending_close_resolves_and_valid_event_delete(tmp_path):
    store = PortfolioStore(tmp_path / "ledger.db")
    account = create(store)
    account = store.add_event(account["id"], {"date": "2026-01-05", "kind": "dividend", "amount": 100}, account["revision"])
    account = store.delete_event(account["id"], account["events"][0]["id"], account["revision"])
    assert account["events"] == []
    account = store.advance(account["id"], {"start": "2026-01-16"}, account["revision"])
    account = store.edit_cycle(account["id"], account["cycles"][-1]["id"], {"previous_close": 80}, account["revision"])
    assert account["state"]["v"] == 7925.62
