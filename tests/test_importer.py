import csv

from openpyxl import Workbook

from app.db import connect
from app.importer import import_directory
from app.prices import read_prices


def test_only_actual_sheet_idempotent_and_bad_row_report(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    book = Workbook()
    actual = book.active
    actual.title = "QLD"
    actual.append(["Date", "Open (USD)", "High (USD)", "Low (USD)", "Close (USD)", "Adj Close (USD)"])
    actual.append(["2026-01-02", 10, 11, 9, 10, 9])
    actual.append(["broken", 10, 11, 9, 10, 9])
    synthetic = book.create_sheet("QLD_2×NDX")
    synthetic.append(["Date", "Close"])
    synthetic.append(["1985-01-02", 1])
    book.save(raw / "QLD raw data.xlsx")
    db = tmp_path / "prices.db"
    reports = import_directory(db, raw)
    assert reports[0]["rows"] == 1
    assert reports[0]["invalid_rows"] == 1
    assert len(read_prices(db, "QLD")) == 1
    assert import_directory(db, raw)[0]["status"] == "skipped"
    with connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0] == 1


def test_csv_date_sort_duplicates_and_merge_raw(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for name, rows in [("QLD_first.csv", [("2026-01-05", 12), ("2026-01-02", 10), ("2026-01-02", 11)]), ("QLD_tail.csv", [("2026-01-06", 13)])]:
        with (raw / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["date", "open", "high", "low", "close", "adj_close", "volume", "source_url"])
            for day, price in rows:
                writer.writerow([day, price, price, price, price, price, 0, "https://example.test"])
    reports = import_directory(tmp_path / "prices.db", raw)
    assert sum(report["rows"] for report in reports) == 3
    prices = read_prices(tmp_path / "prices.db", "QLD")
    assert [price["date"] for price in prices] == ["2026-01-02", "2026-01-05", "2026-01-06"]
    assert prices[0]["close"] == 11
    assert all(price["basis_warning"] for price in prices)
