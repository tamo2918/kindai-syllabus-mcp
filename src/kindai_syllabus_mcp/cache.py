"""SQLiteキャッシュ(読み取り専用データのローカル再利用)。

- シラバス番号を主キーにして詳細を保存する。
- 年度は独立した列に記録する。
- 取得日時(fetched_at)を必ず保存し、返すデータに含める。
- 検索結果のキャッシュ:TTLは短め(公式の検索結果は生成されるため)。
通常の動作はキャッシュ優先。refresh=True、期限切れ、または不在のときのみ再取得。
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from .models import CourseDetail, CourseSummary

DEFAULT_DB_PATH = Path.home() / ".cache" / "kindai-syllabus-mcp" / "cache.sqlite3"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    syllabus_no   TEXT PRIMARY KEY,
    academic_year INTEGER NOT NULL,
    course_name   TEXT NOT NULL DEFAULT '',
    faculty       TEXT NOT NULL DEFAULT '',
    data_json     TEXT NOT NULL,
    fetched_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_courses_year ON courses(academic_year);

CREATE TABLE IF NOT EXISTS search_runs (
    params_key TEXT PRIMARY KEY,
    academic_year INTEGER,
    items_json TEXT NOT NULL,
    total      INTEGER NOT NULL,
    fetched_at REAL NOT NULL
);
"""


def _default_db_path() -> Path:
    env = os.environ.get("KINDAI_SYLLABUS_DB")
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB_PATH


class SyllabusCache:
    """sqlite3を用いた軽いキャッシュ。DB操作は短いのでスレッドに委譲する。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = Path(db_path) if db_path else _default_db_path()
        self._conn: Optional[sqlite3.Connection] = None
        # DB操作は同期APIをto_threadで実行する。同一connectionへの並行アクセスを
        # 全てlockで直列化する(sqlite3は接続単位でスレッド境界を跨ぐ操作に非対応)。
        self._lock = asyncio.Lock()

    # ---- ライフサイクル ----

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            # to_threadから触れるようスレッド境界を許可(操作は_lockで直列化)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    async def close(self) -> None:
        async with self._lock:
            conn = self._conn
            self._conn = None

        def _close() -> None:
            if conn is not None:
                conn.close()

        await asyncio.to_thread(_close)

    # ---- 詳細 ----

    async def get_detail(self, syllabus_no: str, ttl_seconds: float | None) -> CourseDetail | None:
        async with self._lock:

            def _read() -> dict[str, Any] | None:
                cur = self._connection().execute(
                    "SELECT data_json, fetched_at FROM courses WHERE syllabus_no = ?",
                    (syllabus_no,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                if ttl_seconds is not None and time.time() - float(row["fetched_at"]) > ttl_seconds:
                    return None
                return {"json": row["data_json"]}

            payload = await asyncio.to_thread(_read)
        if payload is None:
            return None
        detail = CourseDetail.model_validate_json(payload["json"])
        detail.cached = True
        return detail

    async def put_detail(self, detail: CourseDetail) -> None:
        data = detail.model_dump_json()

        def _write() -> None:
            conn = self._connection()
            conn.execute(
                """
                INSERT INTO courses (syllabus_no, academic_year, course_name, faculty, data_json, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(syllabus_no) DO UPDATE SET
                    academic_year = excluded.academic_year,
                    course_name  = excluded.course_name,
                    faculty      = excluded.faculty,
                    data_json    = excluded.data_json,
                    fetched_at   = excluded.fetched_at
                """,
                (detail.syllabus_no, detail.academic_year, detail.course_name, detail.faculty, data, time.time()),
            )
            conn.commit()

        async with self._lock:
            await asyncio.to_thread(_write)

    # ---- 検索 ----

    async def get_search(self, params_key: str, ttl_seconds: float | None) -> list[CourseSummary] | None:
        async with self._lock:

            def _read() -> str | None:
                cur = self._connection().execute(
                    "SELECT items_json, fetched_at FROM search_runs WHERE params_key = ?",
                    (params_key,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                if ttl_seconds is not None and time.time() - float(row["fetched_at"]) > ttl_seconds:
                    return None
                return row["items_json"]

            raw = await asyncio.to_thread(_read)
        if raw is None:
            return None
        return [CourseSummary.model_validate(item) for item in json.loads(raw)]

    async def put_search(self, params_key: str, academic_year: int | None, items: list[CourseSummary]) -> None:
        payload = json.dumps([item.model_dump() for item in items], ensure_ascii=False)

        def _write() -> None:
            conn = self._connection()
            conn.execute(
                """
                INSERT INTO search_runs (params_key, academic_year, items_json, total, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(params_key) DO UPDATE SET
                    academic_year = excluded.academic_year,
                    items_json   = excluded.items_json,
                    total        = excluded.total,
                    fetched_at   = excluded.fetched_at
                """,
                (params_key, academic_year, payload, len(items), time.time()),
            )
            conn.commit()

        async with self._lock:
            await asyncio.to_thread(_write)
