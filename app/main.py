import os
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


def create_app(db_path: str | Path | None = None) -> FastAPI:
    path = Path(db_path or os.environ.get("VR_DB_PATH", "runtime/vr.sqlite3"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as con:
        con.execute("PRAGMA user_version")
    application = FastAPI(title="VR 투자", version="1.0.0")
    application.state.db_path = path

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

    return application


app = create_app()
