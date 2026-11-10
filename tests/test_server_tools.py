"""MCPサーバー(stdio)のツール定義テスト。実際のstdio接続 テストは手動スクリプトで。"""

from __future__ import annotations

import json

import pytest
import respx

from kindai_syllabus_mcp.client import KindaiSyllabusClient
from kindai_syllabus_mcp.cache import SyllabusCache
from kindai_syllabus_mcp.service import SyllabusService

from .conftest import load_fixture

SEARCH_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/sy01000.aspx"
DETAIL_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/SY01010.aspx"

import kindai_syllabus_mcp.server as srv


@pytest.fixture()
async def wired_service(tmp_path):
    """サーバーモジュールの遅延サービスをテスト用に差し替える。"""
    cache = SyllabusCache(db_path=tmp_path / "cache.sqlite3")
    svc = SyllabusService(client=KindaiSyllabusClient(min_interval=0.0), cache=cache)
    old = srv._service
    srv._service = svc
    try:
        yield svc
    finally:
        srv._service = old
        await svc.aclose()


async def test_tool_get_course_returns_json_with_source(wired_service: SyllabusService) -> None:
    respx.get(DETAIL_URL).respond(200, text=load_fixture("detail_web.html"))
    fn = srv.get_course
    raw = await fn(syllabus_no="2611N00215")  # type: ignore[call-arg]
    payload = json.loads(raw)
    # 正常系(JSONに source_url と fetched_at を含む)
    assert payload.get("source_url", "").endswith("SY01010.aspx?syllabusno=2611N00215")
    assert payload.get("course_name") == "アプリケーション開発実習１"
    assert payload.get("fetched_at")


async def test_tool_get_course_not_found(wired_service: SyllabusService) -> None:
    respx.get(DETAIL_URL).respond(302, headers={"location": "/customer/include/error.html"})
    raw = await srv.get_course(syllabus_no="8888Z88888")  # type: ignore[call-arg]
    payload = json.loads(raw)
    assert payload["error"]["type"] == "CourseNotFoundError"


async def test_tool_search_paginates(wired_service: SyllabusService) -> None:
    respx.get(SEARCH_URL).respond(200, text=load_fixture("search_form.html"))
    respx.post(SEARCH_URL).respond(200, text=load_fixture("search_results.html"))
    raw = await srv.search_courses(course_name="データサイエンス", page=2, page_size=3)  # type: ignore[call-arg]
    payload = json.loads(raw)
    assert payload["page"] == 2
    assert len(payload["items"]) == 3
    assert payload["total"] >= 4


async def test_tool_search_empty_condition_returns_error(wired_service: SyllabusService) -> None:
    raw = await srv.search_courses()  # type: ignore[call-arg]
    payload = json.loads(raw)
    assert "error" in payload


async def test_tool_list_faculties(wired_service: SyllabusService) -> None:
    respx.get(SEARCH_URL).respond(200, text=load_fixture("search_form.html"))
    raw = await srv.list_faculties()  # type: ignore[call-arg]
    payload = json.loads(raw)
    codes = [item["code"] for item in payload["items"]]
    assert "111" in codes
