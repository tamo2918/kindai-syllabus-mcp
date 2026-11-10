"""サービス層(キャッシュ+フロー)のテスト。respxでオフライン。"""

from __future__ import annotations

import pytest
import respx

from kindai_syllabus_mcp.cache import SyllabusCache
from kindai_syllabus_mcp.client import KindaiSyllabusClient
from kindai_syllabus_mcp.errors import KindaiSyllabusError
from kindai_syllabus_mcp.service import SyllabusService

from .conftest import load_fixture

SEARCH_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/sy01000.aspx"
DETAIL_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/SY01010.aspx"


@pytest.fixture()
async def service(tmp_path):
    cache = SyllabusCache(db_path=tmp_path / "cache.sqlite3")
    svc = SyllabusService(
        client=KindaiSyllabusClient(min_interval=0.0),
        cache=cache,
    )
    try:
        yield svc
    finally:
        await svc.aclose()


@respx.mock
async def test_get_course_full_flow(service: SyllabusService) -> None:
    respx.get(DETAIL_URL).respond(200, text=load_fixture("detail_web.html"))
    detail = await service.get_course("2611N00215")
    assert detail.course_name == "アプリケーション開発実習１"
    assert detail.lesson_plan is not None and len(detail.lesson_plan) >= 6

    # 2回目はキャッシュから (HTTP呼び出し増えない)
    requests_before = len(respx.calls)
    again = await service.get_course("2611N00215")
    assert again.course_name == detail.course_name
    assert again.cached is True
    assert len(respx.calls) == requests_before

    # refresh=True は再取得
    refreshed = await service.get_course("2611N00215", refresh=True)
    assert len(respx.calls) == requests_before + 1
    assert refreshed.cached is False


@respx.mock
async def test_get_course_invalid_id(service: SyllabusService) -> None:
    route = respx.get(DETAIL_URL)
    with pytest.raises(KindaiSyllabusError):
        await service.get_course("not-a-number")
    assert not route.called


@respx.mock
async def test_search_full_flow_and_filters(service: SyllabusService) -> None:
    respx.get(SEARCH_URL).respond(200, text=load_fixture("search_form.html"))
    results_route = respx.post(SEARCH_URL).respond(200, text=load_fixture("search_results.html"))

    result = await service.search_courses(course_name="データサイエンス", page=1, page_size=5)
    assert results_route.called
    assert result["total"] >= 10
    assert result["page"] == 1
    assert len(result["items"]) == 5
    assert result["has_more"] is True
    assert result["source_url"] == SEARCH_URL
    assert "公式ページングではありません" in result["note"]

    body = results_route.calls[-1].request.read().decode()
    assert "txtJoukenKamokuMei=" in body

    # フィルタ: 学年と開講期(実測ラベル) -> checkbox on が送られる
    respx.post(SEARCH_URL).respond(200, text=load_fixture("search_results.html"))
    await service.search_courses(course_name="データサイエンス", year_level="1～4年次", term="前期")
    body = results_route.calls[-1].request.read().decode()
    assert "cbNEZ_0090=on" in body
    assert "cbKKK_009=on" in body

    # 学部ラベルからの解決
    respx.post(SEARCH_URL).respond(200, text=load_fixture("search_results.html"))
    await service.search_courses(course_name="データサイエンス", faculty="法学部")
    body = results_route.calls[-1].request.read().decode()
    assert "dropDownListGakubu=111" in body


@respx.mock
async def test_search_unknown_filter_is_error(service: SyllabusService) -> None:
    respx.get(SEARCH_URL).respond(200, text=load_fixture("search_form.html"))
    with pytest.raises(KindaiSyllabusError):
        await service.search_courses(course_name="X", year_level="小学1年生")
    with pytest.raises(KindaiSyllabusError):
        await service.search_courses(course_name="X", faculty="架空の学部")


@respx.mock
async def test_search_future_year_is_rejected(service: SyllabusService) -> None:
    respx.get(SEARCH_URL).respond(200, text=load_fixture("search_form.html"))
    route = respx.post(SEARCH_URL)
    with pytest.raises(KindaiSyllabusError):
        await service.search_courses(query="X", academic_year=2010)
    assert not route.called


@respx.mock
async def test_search_empty_condition_is_rejected(service: SyllabusService) -> None:
    respx.get(SEARCH_URL).respond(200, text=load_fixture("search_form.html"))
    route = respx.post(SEARCH_URL)
    with pytest.raises(KindaiSyllabusError):
        await service.search_courses()
    assert not route.called
