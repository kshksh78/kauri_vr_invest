"""Real daily ETF prices with immutable, coherent adjustment snapshots."""
import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from app.db import connect, init_db

DEFAULT_SYMBOLS = ("TQQQ", "QLD", "SOXL", "UPRO")


def validate_symbol(symbol):
    value = str(symbol).strip().upper()
    if not re.fullmatch(r"[A-Z0-9^][A-Z0-9.\-^=]{0,31}", value):
        raise ValueError("종목 코드는 영문·숫자·점·하이픈 등 32자 이하로 입력하세요.")
    return value


def _years(years):
    if isinstance(years, bool) or not isinstance(years, int) or not 1 <= years <= 10:
        raise ValueError("가격 조회 기간은 1~10년입니다.")


def _subtract_years(day, years):
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)


def normalize_rows(rows):
    normalized = {}
    for row in rows:
        day = date.fromisoformat(str(row["date"])[:10]).isoformat()
        result = {"date": day}
        for field in ("open", "high", "low", "close", "adj_close"):
            raw = row.get(field)
            if raw is None and field in ("open", "high", "low"):
                result[field] = None
                continue
            value = float(raw)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{day}: {field} 가격이 양수 유한값이 아닙니다.")
            result[field] = value
        volume = row.get("volume")
        if volume is not None:
            value = float(volume)
            if not math.isfinite(value) or value < 0 or value != int(value):
                raise ValueError(f"{day}: 거래량이 유효하지 않습니다.")
            volume = int(value)
        result["volume"] = volume
        normalized[day] = result
    if not normalized:
        raise ValueError("유효한 가격 행이 없습니다.")
    return [normalized[key] for key in sorted(normalized)]


def insert_snapshot(con, symbol, rows, provider, source, currency="USD", exchange_timezone="America/New_York", fetched_at=None):
    stamp = fetched_at or datetime.now(timezone.utc).isoformat()
    cursor = con.execute("""INSERT INTO price_snapshots
        (symbol,provider,source,currency,exchange_timezone,fetched_at,row_count,first_date,last_date)
        VALUES(?,?,?,?,?,?,?,?,?)""", (symbol, provider, source, currency, exchange_timezone, stamp, len(rows), rows[0]["date"], rows[-1]["date"]))
    snapshot_id = cursor.lastrowid
    con.executemany("INSERT INTO price_rows VALUES(?,?,?,?,?,?,?,?)", [
        (snapshot_id, row["date"], row["open"], row["high"], row["low"], row["close"], row["adj_close"], row["volume"])
        for row in rows
    ])
    return snapshot_id


def save_snapshot(path, symbol, rows, *, provider, source, currency="USD", exchange_timezone="America/New_York", fetched_at=None):
    symbol = validate_symbol(symbol)
    normalized = normalize_rows(rows)
    init_db(path)
    with connect(path) as con:
        return insert_snapshot(con, symbol, normalized, provider, source, currency, exchange_timezone, fetched_at)


def read_prices(path, symbol, start=None, end=None, years=5, snapshot_id=None):
    symbol = validate_symbol(symbol)
    _years(years)
    today = date.today()
    final = date.fromisoformat(end) if end else today
    first = date.fromisoformat(start) if start else _subtract_years(final, years)
    if final > today or first > final or first < _subtract_years(final, 10):
        raise ValueError("미래 날짜 또는 10년을 초과하는 가격 범위입니다.")
    init_db(path)
    with connect(path) as con:
        if snapshot_id is not None:
            selected = con.execute("SELECT id,provider FROM price_snapshots WHERE id=? AND symbol=?", (snapshot_id, symbol)).fetchone()
            if selected is None:
                raise ValueError("종목과 가격 snapshot이 일치하지 않습니다.")
            ids = [snapshot_id]
            warning = "" if selected["provider"] == "yahoo" else "원본 수정종가 기준의 가격 snapshot입니다."
        else:
            selected = con.execute("SELECT id FROM price_snapshots WHERE symbol=? AND provider='yahoo' ORDER BY id DESC LIMIT 1", (symbol,)).fetchone()
            if selected:
                ids, warning = [selected[0]], ""
            else:
                ids = [row[0] for row in con.execute("SELECT id FROM price_snapshots WHERE symbol=? ORDER BY id", (symbol,))]
                warning = "원본 파일의 수정종가 기준이 다를 수 있습니다. 인터넷 전체 기간 갱신을 권장합니다."
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        rows = con.execute(f"""SELECT p.*,s.currency,s.provider,s.source,s.exchange_timezone,s.fetched_at
            FROM price_rows p JOIN price_snapshots s ON s.id=p.snapshot_id
            WHERE p.snapshot_id IN ({placeholders}) AND p.date>=? AND p.date<=?
            ORDER BY p.snapshot_id,p.date""", (*ids, first.isoformat(), final.isoformat()))
        result = {row["date"]: {**dict(row), "basis_warning": warning} for row in rows}
        return [result[key] for key in sorted(result)]


def list_symbols(path):
    init_db(path)
    with connect(path) as con:
        symbols = [row[0] for row in con.execute("SELECT DISTINCT symbol FROM price_snapshots ORDER BY symbol")]
        result = []
        for symbol in symbols:
            snapshot = con.execute("""SELECT * FROM price_snapshots WHERE symbol=?
                ORDER BY (provider='yahoo') DESC,id DESC LIMIT 1""", (symbol,)).fetchone()
            item = dict(snapshot)
            item["snapshot_id"] = item.pop("id")
            if item["provider"] != "yahoo":
                bounds = con.execute("""SELECT MIN(p.date),MAX(p.date),COUNT(DISTINCT p.date) FROM price_rows p
                    JOIN price_snapshots s ON p.snapshot_id=s.id WHERE s.symbol=?""", (symbol,)).fetchone()
                item.update(first_date=bounds[0], last_date=bounds[1], row_count=bounds[2])
            status = con.execute("SELECT * FROM price_sync_status WHERE symbol=?", (symbol,)).fetchone()
            item["last_error"] = status["last_error"] if status else None
            item["last_attempt_at"] = status["attempted_at"] if status else None
            item["basis_warning"] = "" if item["provider"] == "yahoo" else "원본 수정종가 기준: 전체 기간 온라인 갱신 권장"
            result.append(item)
        # Failed first fetches remain visible even when there is no price cache.
        for status in con.execute("SELECT * FROM price_sync_status ORDER BY symbol"):
            if status["symbol"] not in symbols:
                result.append({"symbol": status["symbol"], "row_count": 0, "last_error": status["last_error"], "last_attempt_at": status["attempted_at"], "last_date": None, "currency": None, "snapshot_id": None})
        return sorted(result, key=lambda item: item["symbol"])


def _fetch(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return response.read(20_000_001)


def _parse_yahoo(body, symbol, now):
    if len(body) > 20_000_000:
        raise ValueError("가격 응답 크기가 제한을 초과했습니다.")
    document = json.loads(body)
    chart = document["chart"]
    if chart.get("error") or not chart.get("result"):
        raise ValueError("공급자에서 가격 데이터를 반환하지 않았습니다.")
    data = chart["result"][0]
    meta = data["meta"]
    if meta["symbol"].upper() != symbol:
        raise ValueError("공급자 종목 코드가 요청과 다릅니다.")
    currency = meta["currency"]
    zone = meta["exchangeTimezoneName"]
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("공급자 통화 정보가 유효하지 않습니다.")
    exchange = ZoneInfo(zone)
    current_day = now.astimezone(exchange).date()
    regular_end = meta.get("currentTradingPeriod", {}).get("regular", {}).get("end")
    current_session_closed = False
    if isinstance(regular_end, (int, float)) and math.isfinite(regular_end):
        close_time = datetime.fromtimestamp(regular_end, timezone.utc)
        current_session_closed = close_time.astimezone(exchange).date() == current_day and now >= close_time
    quote_rows = data["indicators"]["quote"][0]
    adjusted = data["indicators"]["adjclose"][0]["adjclose"]
    prices = []
    skipped = 0
    for index, timestamp in enumerate(data["timestamp"]):
        day = datetime.fromtimestamp(timestamp, timezone.utc).astimezone(exchange).date()
        # Include today's bar only when provider session metadata confirms regular trading has ended.
        if day > current_day or (day == current_day and not current_session_closed) or day < _subtract_years(current_day, 10):
            skipped += 1
            continue
        row = {"date": day.isoformat()}
        for field in ("open", "high", "low", "close", "volume"):
            row[field] = quote_rows[field][index]
        row["adj_close"] = adjusted[index]
        if row["close"] is None or row["adj_close"] is None:
            skipped += 1
            continue
        prices.append(row)
    return normalize_rows(prices), currency, zone, skipped


def sync_prices(path, symbol, years=10, *, fetcher=None, now=None):
    symbol = validate_symbol(symbol)
    _years(years)
    init_db(path)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("조회 시각에는 timezone이 필요합니다.")
    # Fetch all supported ten years in one request regardless of UI display range.
    beginning = _subtract_years(now.date(), 10)
    period1 = int(datetime.combine(beginning, time.min, timezone.utc).timestamp())
    period2 = int((now + timedelta(days=1)).timestamp())
    tail = f"/v8/finance/chart/{quote(symbol, safe='')}?period1={period1}&period2={period2}&interval=1d&events=div%2Csplits"
    stamp = now.isoformat()
    errors = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}{tail}"
        try:
            body = (fetcher or _fetch)(url)
            rows, currency, zone, skipped = _parse_yahoo(body, symbol, now)
            with connect(path) as con:
                identifier = insert_snapshot(con, symbol, rows, "yahoo", url, currency, zone, stamp)
                con.execute("INSERT INTO price_sync_status VALUES(?,?,NULL) ON CONFLICT(symbol) DO UPDATE SET attempted_at=excluded.attempted_at,last_error=NULL", (symbol, stamp))
            return {"symbol": symbol, "status": "synced", "snapshot_id": identifier, "rows": len(rows), "first_date": rows[0]["date"], "last_date": rows[-1]["date"], "currency": currency, "exchange_timezone": zone, "fetched_at": stamp, "source": url, "skipped_rows": skipped, "requested_years": years, "snapshot_years": 10}
        except (OSError, ValueError, KeyError, IndexError, TypeError) as exc:
            errors.append(f"{host}: {type(exc).__name__}: {str(exc)[:160]}")
    message = "가격 갱신 실패. 기존 가격은 보존했습니다. " + " / ".join(errors)
    with connect(path) as con:
        con.execute("INSERT INTO price_sync_status VALUES(?,?,?) ON CONFLICT(symbol) DO UPDATE SET attempted_at=excluded.attempted_at,last_error=excluded.last_error", (symbol, stamp, message))
    raise ValueError(message)
