"""Простая база на SQLite: какие машины уже присылали, чтобы не повторяться."""
import sqlite3
from contextlib import contextmanager

from . import config

DB_PATH = config.DATA_DIR / "car_finder.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_cars (
    vin TEXT PRIMARY KEY,
    make TEXT,
    model TEXT,
    year INTEGER,
    trim TEXT,
    last_price INTEGER,
    first_sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
    last_sent_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sent_messages (
    message_id INTEGER,
    chat_id TEXT,
    vin TEXT,
    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (message_id, chat_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_sent_car(conn, vin: str):
    row = conn.execute("SELECT * FROM sent_cars WHERE vin = ?", (vin,)).fetchone()
    return dict(row) if row else None


def mark_car_sent(conn, car: dict):
    existing = get_sent_car(conn, car["vin"])
    if existing:
        conn.execute(
            "UPDATE sent_cars SET last_price = ?, last_sent_at = CURRENT_TIMESTAMP WHERE vin = ?",
            (car["price"], car["vin"]),
        )
    else:
        conn.execute(
            "INSERT INTO sent_cars (vin, make, model, year, trim, last_price) VALUES (?, ?, ?, ?, ?, ?)",
            (car["vin"], car["make"], car["model"], car["year"], car["trim"], car["price"]),
        )


def link_message_to_car(conn, message_id: int, chat_id: str, vin: str):
    conn.execute(
        "INSERT OR IGNORE INTO sent_messages (message_id, chat_id, vin) VALUES (?, ?, ?)",
        (message_id, chat_id, vin),
    )


def get_car_by_message(conn, message_id: int, chat_id: str):
    row = conn.execute(
        "SELECT vin FROM sent_messages WHERE message_id = ? AND chat_id = ?",
        (message_id, str(chat_id)),
    ).fetchone()
    if not row:
        return None
    return get_sent_car(conn, row["vin"])


def get_meta(conn, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn, key: str, value: str):
    conn.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
