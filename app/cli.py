"""Local import and Yahoo cache refresh commands (no broker connection)."""
import argparse
import json
import os
from pathlib import Path

from app.importer import import_directory
from app.prices import DEFAULT_SYMBOLS, list_symbols, sync_prices


def main(argv=None):
    parser = argparse.ArgumentParser(description="VR 실제 가격 SQLite 관리")
    parser.add_argument("--db", default=os.environ.get("VR_DB_PATH", str(Path("runtime") / "vr.sqlite3")))
    commands = parser.add_subparsers(dest="command", required=True)
    importer = commands.add_parser("import")
    importer.add_argument("--directory", required=True)
    sync = commands.add_parser("sync")
    sync.add_argument("--symbol", action="append", help="생략하면 기본 4종목 전체")
    sync.add_argument("--years", type=int, default=10)
    commands.add_parser("prices")
    args = parser.parse_args(argv)
    if args.command == "import":
        reports = import_directory(args.db, args.directory)
    elif args.command == "sync":
        reports = []
        for symbol in args.symbol or DEFAULT_SYMBOLS:
            try:
                reports.append(sync_prices(args.db, symbol, args.years))
            except ValueError as exc:
                reports.append({"symbol": symbol, "status": "error", "error": str(exc)})
    else:
        reports = list_symbols(args.db)
    print(json.dumps(reports, ensure_ascii=False, indent=2))
    return int(any(report.get("status") == "error" for report in reports))


if __name__ == "__main__":
    raise SystemExit(main())
