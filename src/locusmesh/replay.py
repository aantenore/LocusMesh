"""Replay stores invoked only after complete attestation verification."""

from __future__ import annotations

import sqlite3
from pathlib import Path


class SQLiteReplayStore:
    """Atomic SQLite nonce store with lazy file creation."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        self._connection: sqlite3.Connection | None = None

    def _connect(self) -> sqlite3.Connection:
        if self._connection is None:
            if self._path != ":memory:":
                Path(self._path).parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self._path, isolation_level=None)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS verified_nonce (
                    nonce TEXT PRIMARY KEY,
                    request_commitment TEXT NOT NULL,
                    attestation_digest TEXT NOT NULL
                ) WITHOUT ROWID
                """
            )
            self._connection = connection
        return self._connection

    def record_if_new(
        self,
        nonce: str,
        request_commitment: str,
        attestation_digest: str,
    ) -> bool:
        connection = self._connect()
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO verified_nonce (
                nonce,
                request_commitment,
                attestation_digest
            ) VALUES (?, ?, ?)
            """,
            (nonce, request_commitment, attestation_digest),
        )
        return cursor.rowcount == 1

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> SQLiteReplayStore:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()
