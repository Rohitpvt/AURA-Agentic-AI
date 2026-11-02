"""SQLite/FTS5 memory backend — zero-dependency default."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from openjarvis.core.events import EventType, get_event_bus
from openjarvis.core.registry import MemoryRegistry
from openjarvis.tools.storage._stubs import (
    MemoryBackend,
    RetrievalResult,
)


def _check_fts5(conn: sqlite3.Connection) -> bool:
    """Return True if the SQLite build includes FTS5."""
    try:
        opts = conn.execute("PRAGMA compile_options").fetchall()
        return any("FTS5" in o[0].upper() for o in opts)
    except sqlite3.Error:
        return False


@MemoryRegistry.register("sqlite")
class SQLiteMemory(MemoryBackend):
    """Full-text search memory backend using SQLite FTS5.

    Uses the compiled native Rust backend if present, with a seamless
    built-in Python ``sqlite3`` FTS5 fallback.
    """

    backend_id: str = "sqlite"

    def __init__(self, db_path: str | Path = "") -> None:
        if not db_path:
            from openjarvis.core.config import DEFAULT_CONFIG_DIR

            db_path = str(DEFAULT_CONFIG_DIR / "memory.db")

        self._db_path = str(db_path)
        self._lock = threading.Lock()
        self._rust_impl = None
        self._is_rust = False

        # Attempt to load the native Rust module
        try:
            from openjarvis._rust_bridge import RUST_AVAILABLE, get_rust_module

            if RUST_AVAILABLE:
                _rust = get_rust_module()
                self._rust_impl = _rust.SQLiteMemory(self._db_path)
                self._is_rust = True
        except Exception:
            self._is_rust = False

        if not self._is_rust:
            p = Path(self._db_path)
            if self._db_path != ":memory:" and p.parent:
                p.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.execute("PRAGMA busy_timeout = 10000")
            if self._db_path != ":memory:":
                try:
                    self._conn.execute("PRAGMA journal_mode = WAL")
                except Exception:
                    pass
            self._create_tables()
        else:
            self._conn = None  # type: ignore[assignment]

    def _create_tables(self) -> None:
        if self._conn is not None:
            with self._lock:
                self._conn.executescript("""
                    CREATE TABLE IF NOT EXISTS documents (
                        id       TEXT PRIMARY KEY,
                        content  TEXT NOT NULL,
                        source   TEXT NOT NULL DEFAULT '',
                        metadata TEXT NOT NULL DEFAULT '{}',
                        created_at REAL DEFAULT (julianday('now'))
                    );

                    CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts
                    USING fts5(
                        content,
                        source,
                        tokenize='porter unicode61'
                    );
                """)

    def store(
        self,
        content: str,
        *,
        source: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist *content* and return a unique document id."""
        if self._is_rust and self._rust_impl is not None:
            meta_json = json.dumps(metadata) if metadata else None
            doc_id = self._rust_impl.store(content, source, meta_json)
        else:
            doc_id = str(uuid.uuid4())
            meta_str = json.dumps(metadata) if metadata else "{}"
            with self._lock:
                cur = self._conn.execute(
                    "INSERT INTO documents (id, content, source, metadata) VALUES (?, ?, ?, ?)",
                    (doc_id, content, source, meta_str),
                )
                rowid = cur.lastrowid
                self._conn.execute(
                    "INSERT INTO documents_fts (rowid, content, source) VALUES (?, ?, ?)",
                    (rowid, content, source),
                )
                self._conn.commit()

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_STORE,
            {
                "backend": self.backend_id,
                "doc_id": doc_id,
                "source": source,
            },
        )
        return doc_id

    def replace_source(
        self,
        source: str,
        documents: List[tuple[str, Optional[Dict[str, Any]]]],
    ) -> List[str]:
        """Atomically replace all documents associated with *source*."""
        if self._is_rust and self._rust_impl is not None:
            payload = [
                (content, json.dumps(metadata) if metadata else None)
                for content, metadata in documents
            ]
            doc_ids = self._rust_impl.replace_source(source, payload)
        else:
            doc_ids = []
            with self._lock:
                self._conn.execute(
                    "DELETE FROM documents_fts WHERE rowid IN (SELECT rowid FROM documents WHERE source = ?)",
                    (source,),
                )
                self._conn.execute("DELETE FROM documents WHERE source = ?", (source,))
                for content, metadata in documents:
                    doc_id = str(uuid.uuid4())
                    doc_ids.append(doc_id)
                    meta_str = json.dumps(metadata) if metadata else "{}"
                    cur = self._conn.execute(
                        "INSERT INTO documents (id, content, source, metadata) VALUES (?, ?, ?, ?)",
                        (doc_id, content, source, meta_str),
                    )
                    self._conn.execute(
                        "INSERT INTO documents_fts (rowid, content, source) VALUES (?, ?, ?)",
                        (cur.lastrowid, content, source),
                    )
                self._conn.commit()

        bus = get_event_bus()
        for doc_id in doc_ids:
            bus.publish(
                EventType.MEMORY_STORE,
                {
                    "backend": self.backend_id,
                    "doc_id": doc_id,
                    "source": source,
                },
            )
        return doc_ids

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 5,
        **kwargs: Any,
    ) -> List[RetrievalResult]:
        """Search via FTS5 MATCH with BM25 ranking."""
        if not query.strip():
            return []

        if self._is_rust and self._rust_impl is not None:
            from openjarvis._rust_bridge import retrieval_results_from_json

            results = retrieval_results_from_json(
                self._rust_impl.retrieve(query, top_k),
            )
        else:
            words = re.findall(r"\w+", query)
            if not words:
                return []
            fts_query = " OR ".join(words)
            with self._lock:
                cur = self._conn.execute(
                    """SELECT d.content, d.source, d.metadata,
                              bm25(documents_fts, 1.0, 0.5) * -1 as score
                       FROM documents_fts f
                       JOIN documents d ON d.rowid = f.rowid
                       WHERE documents_fts MATCH ?
                       ORDER BY bm25(documents_fts, 1.0, 0.5)
                       LIMIT ?""",
                    (fts_query, top_k),
                )
                rows = cur.fetchall()

            results = []
            for content, source, meta_json, score in rows:
                try:
                    meta = json.loads(meta_json) if meta_json else {}
                except Exception:
                    meta = {}
                results.append(
                    RetrievalResult(
                        content=content,
                        source=source or "",
                        metadata=meta,
                        score=float(score),
                    )
                )

        bus = get_event_bus()
        bus.publish(
            EventType.MEMORY_RETRIEVE,
            {
                "backend": self.backend_id,
                "query": query,
                "num_results": len(results),
            },
        )
        return results

    def delete(self, doc_id: str) -> bool:
        """Delete a document by id."""
        if self._is_rust and self._rust_impl is not None:
            return self._rust_impl.delete(doc_id)
        with self._lock:
            self._conn.execute(
                "DELETE FROM documents_fts WHERE rowid = (SELECT rowid FROM documents WHERE id = ?)",
                (doc_id,),
            )
            changes = self._conn.execute(
                "DELETE FROM documents WHERE id = ?",
                (doc_id,),
            ).rowcount
            self._conn.commit()
            return changes > 0

    def clear(self) -> None:
        """Remove all stored documents."""
        if self._is_rust and self._rust_impl is not None:
            self._rust_impl.clear()
        else:
            with self._lock:
                self._conn.execute("DELETE FROM documents_fts")
                self._conn.execute("DELETE FROM documents")
                self._conn.commit()

    def count(self) -> int:
        """Return the number of stored documents."""
        if self._is_rust and self._rust_impl is not None:
            return self._rust_impl.count()
        with self._lock:
            cur = self._conn.execute("SELECT count(*) FROM documents")
            return cur.fetchone()[0]

    def close(self) -> None:
        """Close the database connection."""
        if not self._is_rust and self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass


__all__ = ["SQLiteMemory"]
