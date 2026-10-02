"""SQLite connections and versioned price storage on the local Linux filesystem."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def connect(path):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(target, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=10000")
    try:
        with con:
            yield con
    finally:
        con.close()


def init_db(path):
    with connect(path) as con:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript("""
            CREATE TABLE IF NOT EXISTS schema_versions(component TEXT PRIMARY KEY, version INTEGER NOT NULL);
            INSERT OR IGNORE INTO schema_versions VALUES('prices',1);
            CREATE TABLE IF NOT EXISTS price_snapshots(
                id INTEGER PRIMARY KEY, symbol TEXT NOT NULL, provider TEXT NOT NULL,
                source TEXT NOT NULL, currency TEXT NOT NULL, exchange_timezone TEXT NOT NULL,
                fetched_at TEXT NOT NULL, row_count INTEGER NOT NULL,
                first_date TEXT NOT NULL, last_date TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS snapshot_symbol ON price_snapshots(symbol,provider,id);
            CREATE TABLE IF NOT EXISTS price_rows(
                snapshot_id INTEGER NOT NULL REFERENCES price_snapshots(id), date TEXT NOT NULL,
                open REAL, high REAL, low REAL, close REAL NOT NULL, adj_close REAL NOT NULL,
                volume INTEGER, PRIMARY KEY(snapshot_id,date)
            );
            CREATE TABLE IF NOT EXISTS import_runs(
                id INTEGER PRIMARY KEY, file_path TEXT NOT NULL, sha256 TEXT NOT NULL,
                symbol TEXT NOT NULL, snapshot_id INTEGER NOT NULL REFERENCES price_snapshots(id),
                imported_at TEXT NOT NULL, invalid_rows INTEGER NOT NULL, duplicate_rows INTEGER NOT NULL,
                UNIQUE(sha256,symbol)
            );
            CREATE TABLE IF NOT EXISTS price_sync_status(
                symbol TEXT PRIMARY KEY, attempted_at TEXT NOT NULL, last_error TEXT
            );
        """)
