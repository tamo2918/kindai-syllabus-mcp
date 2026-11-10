"""SQLiteキャッシュのテスト(オフライン)。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kindai_syllabus_mcp.cache import SyllabusCache
from kindai_syllabus_mcp.models import CourseDetail, CourseSummary


@pytest.fixture()
async def cache(tmp_path):
    c = SyllabusCache(db_path=tmp_path / "cache.sqlite3")
    try:
        yield c
    finally:
        await c.close()


def _detail(no: str = "2611N00215", year: int = 2026, name: str = "科目A") -> CourseDetail:
    return CourseDetail(
        syllabus_no=no,
        academic_year=year,
        course_name=name,
        url="https://example.invalid/Form/SY01010.aspx?syllabusno=" + no,
        fetched_at=datetime.now(timezone.utc),
    )


async def test_detail_roundtrip(cache: SyllabusCache) -> None:
    assert await cache.get_detail("2611N00215", ttl_seconds=None) is None
    d = _detail()
    await cache.put_detail(d)
    got = await cache.get_detail("2611N00215", ttl_seconds=None)
    assert got is not None
    assert got.syllabus_no == "2611N00215"
    assert got.cached is True
    assert got.course_name == "科目A"


async def test_detail_ttl_expiry(cache: SyllabusCache) -> None:
    await cache.put_detail(_detail())
    # TTL 0 → 期限切れ即
    assert await cache.get_detail("2611N00215", ttl_seconds=0.0) is None
    assert await cache.get_detail("2611N00215", ttl_seconds=10_000.0) is not None


async def test_detail_overwrite_updates_data(cache: SyllabusCache) -> None:
    await cache.put_detail(_detail(name="旧"))
    await cache.put_detail(_detail(name="新"))
    got = await cache.get_detail("2611N00215", ttl_seconds=None)
    assert got is not None and got.course_name == "新"


async def test_year_is_recorded_independently(cache: SyllabusCache, tmp_path) -> None:
    import sqlite3

    await cache.put_detail(_detail(year=2026))
    with sqlite3.connect(tmp_path / "cache.sqlite3") as conn:
        row = conn.execute(
            "SELECT academic_year FROM courses WHERE syllabus_no=?", ("2611N00215",)
        ).fetchone()
    assert row[0] == 2026


async def test_search_roundtrip(cache: SyllabusCache) -> None:
    items = [
        CourseSummary(syllabus_no="2611100030", academic_year=2026, course_name="Communicative English 1A（再）"),
        CourseSummary(syllabus_no="2611100031", academic_year=2026, course_name="Communicative English 1B"),
    ]
    assert await cache.get_search("key1", ttl_seconds=None) is None
    await cache.put_search("key1", 2026, items)
    got = await cache.get_search("key1", ttl_seconds=None)
    assert got is not None and len(got) == 2
    assert got[0].syllabus_no == "2611100030"
    # 期限切れ
    assert await cache.get_search("key1", ttl_seconds=0.0) is None
