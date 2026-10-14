"""SQLite storage of the offers."""
import json
import re
import sqlite3
import time
import unicodedata
from pathlib import Path

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS offers (
    id TEXT PRIMARY KEY,            -- source:source_id
    source TEXT NOT NULL,
    url TEXT,
    title TEXT NOT NULL,
    company TEXT,
    city TEXT,
    country TEXT,
    lat REAL, lon REAL,
    posted_at TEXT,
    description TEXT,
    hints TEXT,                     -- JSON: structured fields from the source (languages, experience...)
    dedup_key TEXT,
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    closed INTEGER DEFAULT 0,
    commute_min INTEGER,
    extracted TEXT,                 -- JSON produced by the LLM
    score INTEGER,
    score_detail TEXT,              -- JSON: contribution of each criterion
    status TEXT DEFAULT 'new',      -- new | interested | applied | dismissed
    notified INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS offers_dedup ON offers(dedup_key);
CREATE INDEX IF NOT EXISTS offers_score ON offers(score);
CREATE TABLE IF NOT EXISTS geo_cache (query TEXT PRIMARY KEY, lat REAL, lon REAL, commute_min INTEGER);
"""


def connect() -> sqlite3.Connection:
    Path(config.DATA_DIR).mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(Path(config.DATA_DIR) / "offers.db", timeout=30)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def norm(text: str | None) -> str:
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"\((h/f|f/h|m/f|f/m|h/f/x|m/f/d|m/w/d|w/m/d|x/f/m)[^)]*\)|\b(h/f|m/f|f/h)\b", " ", text)
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def dedup_key(title: str, company: str | None, city: str | None) -> str:
    company_word = (norm(company).split(" ") or [""])[0]  # "Accent" and "ACCENT Jobs for People": same employer
    return f"{company_word}|{norm(title)}|{norm(city).split(' ')[0] if city else ''}"


def upsert(con: sqlite3.Connection, offer: dict) -> bool:
    """Insert or refresh an offer. Returns True if it is new (and not a duplicate from another source)."""
    now = time.time()
    oid = f"{offer['source']}:{offer['source_id']}"
    key = dedup_key(offer["title"], offer.get("company"), offer.get("city"))
    row = con.execute("SELECT id FROM offers WHERE id = ?", (oid,)).fetchone()
    if row:
        con.execute("UPDATE offers SET last_seen = ?, closed = 0 WHERE id = ?", (now, oid))
        return False
    duplicate = con.execute("SELECT id FROM offers WHERE dedup_key = ? AND closed = 0", (key,)).fetchone()
    con.execute(
        """INSERT INTO offers (id, source, url, title, company, city, country, lat, lon, posted_at, description,
                               hints, dedup_key, first_seen, last_seen, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (oid, offer["source"], offer.get("url"), offer["title"], offer.get("company"), offer.get("city"),
         offer.get("country"), offer.get("lat"), offer.get("lon"), offer.get("posted_at"),
         offer.get("description"), json.dumps(offer.get("hints") or {}, ensure_ascii=False), key, now, now,
         "duplicate" if duplicate else "new"),
    )
    return not duplicate


def close_missing(con: sqlite3.Connection, source: str, seen_ids: set[str]):
    """An offer missing from a complete pass over its source is considered closed."""
    for row in con.execute("SELECT id FROM offers WHERE source = ? AND closed = 0", (source,)).fetchall():
        if row["id"] not in seen_ids:
            con.execute("UPDATE offers SET closed = 1 WHERE id = ?", (row["id"],))
