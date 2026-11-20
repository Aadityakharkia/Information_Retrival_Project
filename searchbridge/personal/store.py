"""Persistent store of search interactions, one anonymous profile per browser.

Kept outside the project folder by default (``~/.searchbridge/interactions.db``) so a synced or
shared project never carries anyone's history. Only document ids, the query that led to them and
timings are stored; nothing is shared between users.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional

DEFAULT_PATH = Path(os.environ.get("SEARCHBRIDGE_DATA", Path.home() / ".searchbridge")) / "interactions.db"

# open: document page opened; dwell: time spent on it; link: a link followed from one document to another;
# feedback: explicit thumbs up (+1) / down (-1); impression: shown in the top results of a search
KINDS = {"search", "impression", "open", "dwell", "link", "feedback"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT NOT NULL,
    collection TEXT NOT NULL,
    ts REAL NOT NULL,
    kind TEXT NOT NULL,
    query TEXT DEFAULT '',
    doc TEXT DEFAULT '',
    to_doc TEXT DEFAULT '',
    rank INTEGER DEFAULT 0,
    value REAL DEFAULT 0,          -- dwell seconds, feedback +1/-1
    source TEXT DEFAULT ''         -- how a document was opened: results | link | related | direct
);
CREATE INDEX IF NOT EXISTS ev_user ON events(user, collection, ts);
CREATE TABLE IF NOT EXISTS settings (user TEXT PRIMARY KEY, paused INTEGER DEFAULT 0);
"""


class InteractionStore:
    def __init__(self, path: str | Path = DEFAULT_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._lock = threading.Lock()
        self._version: Dict[tuple, int] = {}

    # ------------------------------------------------------------------ writes
    def log(self, user: str, collection: str, kind: str, query: str = "", doc: str = "", to_doc: str = "",
            rank: int = 0, value: float = 0.0, source: str = "", ts: Optional[float] = None) -> bool:
        if kind not in KINDS or not user:
            raise ValueError(f"unknown event kind {kind!r}")
        if self.paused(user) and kind != "search":
            return False
        with self._lock:
            self._db.execute("INSERT INTO events(user, collection, ts, kind, query, doc, to_doc, rank, value, source) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?)",
                             (user, collection, ts or time.time(), kind, query[:300], doc, to_doc, int(rank), float(value), source))
            self._db.commit()
            self._version[(user, collection)] = self._version.get((user, collection), 0) + 1
        return True

    def log_impressions(self, user: str, collection: str, query: str, docs: Iterable[str]) -> None:
        if self.paused(user):
            return
        now = time.time()
        rows = [(user, collection, now, "impression", query[:300], d, "", r, 0.0, "") for r, d in enumerate(docs, 1)]
        with self._lock:
            self._db.executemany("INSERT INTO events(user, collection, ts, kind, query, doc, to_doc, rank, value, source) "
                                 "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
            self._db.commit()
            self._version[(user, collection)] = self._version.get((user, collection), 0) + 1

    def clear(self, user: str, collection: Optional[str] = None) -> int:
        with self._lock:
            if collection:
                cur = self._db.execute("DELETE FROM events WHERE user=? AND collection=?", (user, collection))
            else:
                cur = self._db.execute("DELETE FROM events WHERE user=?", (user,))
            self._db.commit()
            for k in [k for k in self._version if k[0] == user]:
                self._version[k] += 1
            return cur.rowcount

    def set_paused(self, user: str, paused: bool) -> None:
        with self._lock:
            self._db.execute("INSERT INTO settings(user, paused) VALUES (?, ?) ON CONFLICT(user) DO UPDATE SET paused=excluded.paused",
                             (user, int(paused)))
            self._db.commit()

    # ------------------------------------------------------------------ reads
    def paused(self, user: str) -> bool:
        row = self._db.execute("SELECT paused FROM settings WHERE user=?", (user,)).fetchone()
        return bool(row and row[0])

    def version(self, user: str, collection: str) -> int:
        if (user, collection) not in self._version:
            row = self._db.execute("SELECT COUNT(*), MAX(id) FROM events WHERE user=? AND collection=?", (user, collection)).fetchone()
            self._version[(user, collection)] = hash(row) & 0xFFFFFFF
        return self._version[(user, collection)]

    def events(self, user: str, collection: str, kinds: Optional[Iterable[str]] = None, since: float = 0.0) -> List[Dict]:
        sql = "SELECT ts, kind, query, doc, to_doc, rank, value, source FROM events WHERE user=? AND collection=? AND ts>=?"
        args: list = [user, collection, since]
        if kinds:
            kinds = list(kinds)
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += kinds
        cols = ("ts", "kind", "query", "doc", "to_doc", "rank", "value", "source")
        return [dict(zip(cols, r)) for r in self._db.execute(sql + " ORDER BY ts", args)]

    def query_users(self, collection: str) -> Dict[str, set]:
        """query -> set of users who ran it (for k-anonymous popular-query suggestions)."""
        out: Dict[str, set] = {}
        for user, q in self._db.execute("SELECT user, lower(trim(query)) FROM events WHERE collection=? AND kind='search' AND query!=''",
                                        (collection,)):
            out.setdefault(q, set()).add(user)
        return out
