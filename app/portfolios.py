"""Persist immutable seeds and replay candidate ledger changes atomically."""
import copy
import json
import math
import re
from datetime import date, timedelta
from uuid import uuid4

from app.db import connect, init_db
from app.engine import initialize, initialize_existing, ladder, next_cycle
from app.prices import DEFAULT_SYMBOLS, validate_symbol
from app.schemas import VRSettings


def number(value, label, *, positive=False, signed=False):
    if isinstance(value, bool):
        raise ValueError(f"{label}: 숫자가 필요합니다.")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label}: 숫자가 필요합니다.") from exc
    if not math.isfinite(result) or (positive and result <= 0) or (not signed and result < 0):
        raise ValueError(f"{label}: 유효한 유한 숫자를 입력하세요.")
    return result


def iso_day(value):
    return date.fromisoformat(str(value)).isoformat()


def validate_event(event):
    if "date" not in event:
        raise ValueError("사건 날짜를 입력하세요.")
    event["date"] = iso_day(event["date"])
    kind = event.get("kind")
    if kind in {"buy", "sell"}:
        qty = number(event.get("qty"), "수량", positive=True)
        if qty != int(qty):
            raise ValueError("거래 수량은 양의 정수입니다.")
        if date.fromisoformat(event["date"]).weekday() >= 5:
            raise ValueError("매수·매도는 거래일 날짜를 입력하세요.")
        event["qty"] = int(qty)
        event["price"] = number(event.get("price"), "체결가", positive=True)
        if event.get("fee") is not None:
            event["fee"] = number(event["fee"], "비용률")
            if event["fee"] >= 1:
                raise ValueError("비용률은 1 미만입니다.")
    elif kind in {"dividend", "cost", "flow"}:
        event["amount"] = number(event.get("amount"), "금액", signed=kind == "flow")
    elif kind == "split":
        event["ratio"] = number(event.get("ratio"), "분할 비율", positive=True)
    else:
        raise ValueError("사건 종류는 buy/sell/dividend/cost/flow/split 중 하나입니다.")
    return event


def flow_date(event, cycles):
    """A deposit during a cycle is explicitly scheduled for the next opening."""
    day = date.fromisoformat(event["date"])
    for cycle in cycles:
        start = date.fromisoformat(cycle["start"])
        if day <= start:
            return start.isoformat()
    active = cycles[-1]
    anchor = date.fromisoformat(active["start"])
    days = active["settings"]["cycle_days"]
    steps = max(1, math.ceil((day - anchor).days / days))
    return (anchor + timedelta(days=days * steps)).isoformat()


def replay(document):
    account = copy.deepcopy(document)
    seed = account["seed"]
    cycles = account["cycles"]
    events = sorted(account["events"], key=lambda item: (item["date"], item["ordinal"]))
    for event in events:
        if event["date"] < seed["start"]:
            raise ValueError("초기 시작일 이전 사건은 입력할 수 없습니다.")
        if event["kind"] == "flow":
            event["effective_date"] = flow_date(event, cycles)
    qty, pool, v = seed["qty"], seed["pool"], seed["v"]
    invested = seed["capital"]
    results = []
    state = None
    for index, cycle in enumerate(cycles):
        settings = VRSettings.model_validate(cycle["settings"])
        opening = cycle["start"]
        ending = cycles[index + 1]["start"] if index + 1 < len(cycles) else (
            date.fromisoformat(opening) + timedelta(days=settings.cycle_days)).isoformat()
        if date.fromisoformat(ending) < date.fromisoformat(opening) + timedelta(days=settings.cycle_days):
            raise ValueError("확정 회차의 기간과 다음 시작일이 겹칩니다.")
        actual_flows = [event for event in events if event["kind"] == "flow" and event["effective_date"] == opening]
        flow = sum(event["amount"] for event in actual_flows) if actual_flows else (settings.periodic_flow if index else 0)
        if index:
            computed = next_cycle(v, pool, qty, cycle.get("previous_close"), settings, flow=flow)
        else:
            if pool + flow < 0 or v + flow <= 0:
                raise ValueError("초기 입출금 후 Pool 또는 V가 부족합니다.")
            computed = {"v": v + flow, "pool_start": pool + flow, "budget": (pool + flow) * settings.pool_usage,
                        "waiting": False, "components": {"initial_v": v, "flow": flow}}
        items = [event for event in events if event["kind"] != "flow" and opening <= event["date"] < ending]
        if computed["waiting"]:
            if items or index != len(cycles) - 1:
                raise ValueError("직전 종가 대기 회차에는 거래를 입력하거나 다음 회차로 이동할 수 없습니다.")
            state = {"qty": qty, "pool": pool, "v": None, "budget": None, "remaining_budget": None,
                     "waiting": True, "components": computed["components"], "cycle_start": opening,
                     "cycle_end": ending, "net_contributions": invested, "flow": flow}
            results.append({**cycle, "flow": flow, "actual_flow": bool(actual_flows), "result": state.copy()})
            break
        v, pool, budget = computed["v"], computed["pool_start"], computed["budget"]
        remaining = budget
        invested += flow
        for event in items:
            kind = event["kind"]
            if kind in {"buy", "sell"}:
                fee = event.get("fee")
                fee = settings.fee if fee is None else fee
                amount = event["qty"] * event["price"]
                if kind == "buy":
                    cost = amount * (1 + fee)
                    if cost > pool + 1e-8 or cost > remaining + 1e-8:
                        raise ValueError(f"{event['date']} 매수: 당시 Pool 또는 고정 회차 한도가 부족합니다.")
                    qty += event["qty"]
                    pool -= cost
                    remaining -= cost
                else:
                    if event["qty"] > qty:
                        raise ValueError(f"{event['date']} 매도: 당시 보유 수량이 부족합니다.")
                    qty -= event["qty"]
                    pool += amount * (1 - fee)
            elif kind == "dividend":
                pool += event["amount"]
            elif kind == "cost":
                if event["amount"] > pool + 1e-8:
                    raise ValueError(f"{event['date']} 비용: 당시 현금이 부족합니다.")
                pool -= event["amount"]
            elif kind == "split":
                split_qty = qty * event["ratio"]
                if abs(split_qty - round(split_qty)) > 1e-8:
                    raise ValueError("분할 후 정수 주수가 필요합니다. 단주는 실제 현금 정산 후 기록하세요.")
                qty = round(split_qty)
            pool, remaining = max(0, pool), max(0, remaining)
        state = {"qty": qty, "pool": pool, "v": v, "budget": budget, "remaining_budget": remaining,
                 "lower": v * (1 - settings.band), "upper": v * (1 + settings.band), "waiting": False,
                 "components": computed["components"], "cycle_start": opening, "cycle_end": ending,
                 "net_contributions": invested, "flow": flow}
        results.append({**cycle, "flow": flow, "actual_flow": bool(actual_flows), "result": state.copy()})
    last_end = state["cycle_end"]
    if any(event["kind"] != "flow" and event["date"] >= last_end for event in events):
        raise ValueError("해당 날짜의 회차를 먼저 시작한 뒤 거래를 입력하세요.")
    account["events"] = events
    account["cycles"] = results
    account["state"] = state
    account["pending_flows"] = [event for event in events if event["kind"] == "flow"
                                and event["effective_date"] > state["cycle_start"]]
    account["orders"] = ({"buy": [], "sell": []} if state["waiting"] else ladder(
        state["v"], qty, pool, state["remaining_budget"], cycles[-1]["settings"]))
    return account


class PortfolioStore:
    def __init__(self, path):
        self.path = path
        init_db(path)
        with connect(path) as con:
            con.execute("CREATE TABLE IF NOT EXISTS portfolios(id TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL)")
            con.execute("INSERT OR IGNORE INTO schema_versions VALUES('portfolios',1)")

    def create(self, data):
        symbol = validate_symbol(data.get("symbol", "QLD"))
        currency = str(data.get("currency", "USD" if symbol in DEFAULT_SYMBOLS else "")).upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("추가 종목의 실제 거래 통화 3자리 코드를 입력하세요.")
        start = iso_day(data.get("start", date.today().isoformat()))
        if date.fromisoformat(start).weekday() >= 5:
            raise ValueError("시작일은 거래일을 입력하세요.")
        settings = VRSettings.model_validate(data.get("settings", {})).model_dump()
        price = number(data.get("price"), "시작 기준 가격", positive=True)
        migration = data.get("qty_override") is not None and data.get("pool_override") is not None
        mode = data.get("initialization_mode", "existing_holdings" if migration else "new_purchase")
        if mode == "existing_holdings":
            if not migration:
                raise ValueError("기존 보유 시작에는 실제 수량과 Pool을 모두 입력하세요.")
            initial = initialize_existing(data["qty_override"], data["pool_override"], price,
                                          settings, data.get("v_override"))
            capital = initial["opening_equity"]
            allocation = initial["qty"] * price / capital
        elif mode == "new_purchase":
            capital = number(data.get("capital", 15000), "초기 자산", positive=True)
            allocation = number(data.get("allocation", 0.5), "초기 매수 비율")
            initial = initialize(capital, allocation, price, settings, data.get("qty_override"),
                                 data.get("pool_override"), data.get("v_override"))
            if data.get("pool_override") is not None or data.get("qty_override") is not None:
                capital = initial["qty"] * price + initial["pool"] + initial["initial_fee"]
            initial["initialization_mode"] = mode
        else:
            raise ValueError("시작 방식은 new_purchase 또는 existing_holdings입니다.")
        if data.get("holding_cost_basis") is not None:
            initial["holding_cost_basis"] = number(data["holding_cost_basis"], "기존 주식 취득원가")
        name = str(data.get("name", f"{symbol} VR")).strip()
        if not name or len(name) > 100:
            raise ValueError("계좌명은 1~100자입니다.")
        document = {"id": uuid4().hex, "name": name, "symbol": symbol, "currency": currency, "revision": 1,
                    "seed": {"start": start, "capital": capital, "allocation": allocation, "price": price, **initial},
                    "settings": settings, "events": [], "cycles": [
                        {"id": uuid4().hex, "start": start, "previous_close": None, "settings": settings.copy()}]}
        result = replay(document)
        with connect(self.path) as con:
            con.execute("INSERT INTO portfolios VALUES(?,?,?)", (document["id"], 1, json.dumps(document, allow_nan=False)))
        return result

    def get(self, key):
        with connect(self.path) as con:
            row = con.execute("SELECT document FROM portfolios WHERE id=?", (key,)).fetchone()
        if row is None:
            raise KeyError("계좌를 찾을 수 없습니다.")
        return replay(json.loads(row["document"]))

    def list(self):
        with connect(self.path) as con:
            rows = con.execute("SELECT document FROM portfolios ORDER BY rowid").fetchall()
        return [replay(json.loads(row[0])) for row in rows]

    def _mutate(self, key, revision, change):
        with connect(self.path) as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT document,revision FROM portfolios WHERE id=?", (key,)).fetchone()
            if row is None:
                raise KeyError("계좌를 찾을 수 없습니다.")
            if revision != row["revision"]:
                raise ValueError("revision 충돌: 계좌를 다시 불러온 뒤 수정하세요.")
            document = json.loads(row["document"])
            change(document)
            document["revision"] += 1
            result = replay(document)
            con.execute("UPDATE portfolios SET revision=?,document=? WHERE id=?",
                        (document["revision"], json.dumps(document, allow_nan=False), key))
        return result

    def update_settings(self, key, settings, revision):
        def change(document):
            document["settings"] = VRSettings.model_validate({**document["settings"], **settings}).model_dump()
        return self._mutate(key, revision, change)

    def add_event(self, key, data, revision):
        def change(document):
            event = validate_event({**data, "id": uuid4().hex,
                                    "ordinal": max([item["ordinal"] for item in document["events"]], default=0) + 1})
            document["events"].append(event)
        return self._mutate(key, revision, change)

    def edit_event(self, key, event_id, data, revision):
        def change(document):
            for index, event in enumerate(document["events"]):
                if event["id"] == event_id:
                    document["events"][index] = validate_event({**event, **data, "id": event_id, "ordinal": event["ordinal"]})
                    return
            raise KeyError("사건을 찾을 수 없습니다.")
        return self._mutate(key, revision, change)

    def delete_event(self, key, event_id, revision):
        def change(document):
            retained = [event for event in document["events"] if event["id"] != event_id]
            if len(retained) == len(document["events"]):
                raise KeyError("사건을 찾을 수 없습니다.")
            document["events"] = retained
        return self._mutate(key, revision, change)

    def advance(self, key, data, revision):
        def change(document):
            if replay(document)["state"]["waiting"]:
                raise ValueError("현재 회차의 직전 종가를 먼저 확정하세요.")
            previous = document["cycles"][-1]
            earliest = date.fromisoformat(previous["start"]) + timedelta(days=previous["settings"]["cycle_days"])
            start = iso_day(data.get("start", earliest.isoformat()))
            if date.fromisoformat(start) < earliest or date.fromisoformat(start).weekday() >= 5:
                raise ValueError("다음 회차는 기간 경과 후 거래일에 시작하세요.")
            closing = data.get("previous_close")
            closing = None if closing is None else number(closing, "직전 확정 종가", positive=True)
            document["cycles"].append({"id": uuid4().hex, "start": start, "previous_close": closing,
                                      "settings": document["settings"].copy()})
        return self._mutate(key, revision, change)

    def edit_cycle(self, key, cycle_id, data, revision):
        def change(document):
            for index, cycle in enumerate(document["cycles"]):
                if cycle["id"] == cycle_id:
                    if "settings" in data:
                        cycle["settings"] = VRSettings.model_validate({**cycle["settings"], **data["settings"]}).model_dump()
                    if "previous_close" in data and index:
                        value = data["previous_close"]
                        cycle["previous_close"] = None if value is None else number(value, "직전 확정 종가", positive=True)
                    return
            raise KeyError("회차를 찾을 수 없습니다.")
        return self._mutate(key, revision, change)
