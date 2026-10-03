"""Seed a NEW isolated browser-test DB; never target the running account DB."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.prices import DEFAULT_SYMBOLS, save_snapshot  # noqa: E402

parser = argparse.ArgumentParser()
parser.add_argument("--db", required=True)
args = parser.parse_args()
target = Path(args.db)
if target.exists():
    raise SystemExit("새 테스트 DB 경로가 필요합니다. 기존 DB는 변경하지 않습니다.")
rows = [{"date": day, "open": price, "high": price, "low": price, "close": price, "adj_close": price}
        for day, price in [("2026-01-02", 100), ("2026-01-05", 95), ("2026-01-15", 80),
                           ("2026-01-16", 100), ("2026-01-30", 105), ("2026-02-13", 90)]]
for symbol in (*DEFAULT_SYMBOLS, "AAPL"):
    save_snapshot(target, symbol, rows, provider="yahoo", source="browser-fixture")
print(f"테스트 DB 준비: {target}")
