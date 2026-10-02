import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.backtest import run_backtest
from app.db import init_db
from app.portfolios import PortfolioStore
from app.prices import DEFAULT_SYMBOLS, list_symbols, read_prices, sync_prices
from app.schemas import VRSettings


def create_app(db_path: str | Path | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("VR_DB_PATH", "runtime/vr.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA user_version")
    init_db(path)
    store = PortfolioStore(path)
    application = FastAPI(title="VR 투자", version="1.0.0")
    application.state.db_path = path

    @application.exception_handler(ValueError)
    async def invalid_input(request: Request, exc: ValueError):
        status = 409 if "revision 충돌" in str(exc) else 422
        return JSONResponse({"detail": str(exc)}, status_code=status)

    @application.exception_handler(KeyError)
    async def missing_object(request: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc).strip("'")}, status_code=404)

    @application.middleware("http")
    async def local_boundary(request: Request, call_next):
        host = request.headers.get("host", "")
        if urlsplit("http://" + host).hostname not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse({"detail": "로컬 주소로 접속해 주세요."}, status_code=400)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            expected = f"{request.url.scheme}://{host}"
            if (origin is not None and origin != expected) or request.headers.get("x-vr-request") != "1":
                return JSONResponse({"detail": "동일한 로컬 화면에서 요청해 주세요."}, status_code=403)
        return await call_next(request)

    @application.get("/api/health")
    def health():
        with sqlite3.connect(path) as con:
            con.execute("SELECT 1")
        return {"version": "1.0.0", "database": "ready", "sqlite_version": sqlite3.sqlite_version}

    @application.get("/api/config")
    def config():
        return {"default_symbols": DEFAULT_SYMBOLS, "default_years": 5, "max_years": 10,
                "default_start": "2026-10-02", "port": 8787}

    @application.get("/api/portfolios")
    def portfolios():
        return store.list()

    @application.post("/api/portfolios", status_code=201)
    def create_portfolio(data: dict):
        currency = next((item.get("currency") for item in list_symbols(path)
                         if item["symbol"] == str(data.get("symbol", "QLD")).upper()), None)
        if currency and str(data.get("currency") or currency).upper() != currency:
            raise ValueError(f"가격 DB 통화 {currency}와 계좌 통화가 다릅니다.")
        if currency and not data.get("currency"):
            data["currency"] = currency
        return store.create(data)

    @application.get("/api/portfolios/{key}")
    def portfolio(key: str):
        return store.get(key)

    @application.patch("/api/portfolios/{key}/settings")
    def settings(key: str, data: dict):
        return store.update_settings(key, data.get("settings", {}), data.get("revision"))

    @application.post("/api/portfolios/{key}/events", status_code=201)
    def event(key: str, data: dict):
        revision = data.pop("revision", None)
        return store.add_event(key, data, revision)

    @application.patch("/api/portfolios/{key}/events/{event_id}")
    def edit_event(key: str, event_id: str, data: dict):
        revision = data.pop("revision", None)
        return store.edit_event(key, event_id, data, revision)

    @application.delete("/api/portfolios/{key}/events/{event_id}")
    def delete_event(key: str, event_id: str, data: dict):
        return store.delete_event(key, event_id, data.get("revision"))

    @application.post("/api/portfolios/{key}/cycles", status_code=201)
    def cycle(key: str, data: dict):
        revision = data.pop("revision", None)
        return store.advance(key, data, revision)

    @application.patch("/api/portfolios/{key}/cycles/{cycle_id}")
    def edit_cycle(key: str, cycle_id: str, data: dict):
        revision = data.pop("revision", None)
        return store.edit_cycle(key, cycle_id, data, revision)

    @application.get("/api/prices")
    def price_coverage():
        return list_symbols(path)

    @application.get("/api/prices/{symbol}")
    def prices(symbol: str, start: str | None = None, end: str | None = None, years: int = 5):
        return read_prices(path, symbol, start, end, years)

    @application.post("/api/prices/sync")
    def sync(data: dict):
        return sync_prices(path, data.get("symbol", ""), data.get("years", 5))

    @application.post("/api/backtests")
    def backtests(data: dict):
        symbols = data.get("symbols", ["QLD"])
        modes = data.get("modes", [data.get("settings", {}).get("mode", "skilled")])
        if not isinstance(symbols, list) or not symbols or not isinstance(modes, list) or not modes:
            raise ValueError("종목과 VR 방식 목록을 선택하세요.")
        if len(symbols) > 20 or len(modes) > 2:
            raise ValueError("한 번에 종목 20개·VR 방식 2개까지 비교할 수 있습니다.")
        results = []
        for symbol in dict.fromkeys(symbols):
            rows = read_prices(path, symbol, data.get("start"), data.get("end"), data.get("years", 5))
            for mode in dict.fromkeys(modes):
                options = VRSettings.model_validate({**data.get("settings", {}), "mode": mode})
                result = run_backtest(rows, options, data.get("capital", 15000), data.get("allocation", 0.5),
                                      data.get("flows"), data.get("start"), data.get("end"))
                result.update(symbol=str(symbol).upper(), mode=mode)
                results.append(result)
        return {"results": results}

    static = Path(__file__).parent / "static"
    if static.is_dir():
        application.mount("/", StaticFiles(directory=static, html=True), name="web")

    return application


app = create_app()
