import json
import math
import re
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.prices import _fetch, validate_symbol


def _parse_quote(body, symbol, now):
    if len(body) > 20_000_000:
        raise ValueError("가격 응답 크기가 제한을 초과했습니다.")
    chart = json.loads(body)["chart"]
    if chart.get("error") or not chart.get("result"):
        raise ValueError("공급자에서 시세를 반환하지 않았습니다.")
    data = chart["result"][0]
    meta = data["meta"]
    if meta["symbol"].upper() != symbol:
        raise ValueError("공급자 종목 코드가 요청과 다릅니다.")
    currency, zone = meta["currency"], meta["exchangeTimezoneName"]
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ValueError("공급자 통화 정보가 유효하지 않습니다.")
    ZoneInfo(zone)
    candidates = []

    def add(stamp, price, priority=0):
        if (isinstance(stamp, (int, float)) and not isinstance(stamp, bool)
                and math.isfinite(stamp) and 0 < stamp <= now.timestamp()
                and isinstance(price, (int, float)) and not isinstance(price, bool)
                and math.isfinite(price) and price > 0):
            candidates.append((stamp, priority, price))

    add(meta.get("regularMarketTime"), meta.get("regularMarketPrice"), 1)
    closes = data.get("indicators", {}).get("quote", [{}])[0].get("close", [])
    for stamp, price in zip(data.get("timestamp", []), closes):
        add(stamp, price)
    if not candidates:
        raise ValueError("조회 가능한 최근 거래 가격이 없습니다.")
    stamp, regular_trade, price = max(candidates)
    session = "regular" if regular_trade else "unknown"
    if not regular_trade:
        for name in ("pre", "regular", "post"):
            period = meta.get("currentTradingPeriod", {}).get(name, {})
            if period.get("start", 0) <= stamp < period.get("end", 0):
                session = name
                break
    return {"symbol": symbol, "price": price, "currency": currency,
            "as_of": datetime.fromtimestamp(stamp, timezone.utc).isoformat(),
            "exchange_timezone": zone, "session": session,
            "fetched_at": now.isoformat(), "provider": "Yahoo Finance"}


def fetch_quote(symbol, *, fetcher=None, now=None):
    symbol = validate_symbol(symbol)
    now = now or datetime.now(timezone.utc)
    errors = []
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = (f"https://{host}/v8/finance/chart/{quote(symbol, safe='')}"
               "?range=1d&interval=1m&includePrePost=true")
        try:
            return {**_parse_quote((fetcher or _fetch)(url), symbol, now), "source": url}
        except (OSError, ValueError, KeyError, IndexError, TypeError, OverflowError) as exc:
            errors.append(f"{host}: {type(exc).__name__}: {str(exc)[:160]}")
    raise ValueError("최신 가격 조회 실패. " + " / ".join(errors))
