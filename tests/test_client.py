"""クライアント(HTTP)のテスト。respxでネットワークを模擬。"""

from __future__ import annotations

import httpx
import pytest
import respx

from kindai_syllabus_mcp.client import KindaiSyllabusClient
from kindai_syllabus_mcp.errors import CourseNotFoundError, UpstreamResponseError

SEARCH_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/sy01000.aspx"
DETAIL_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/SY01010.aspx"


@pytest.fixture()
async def client():
    c = KindaiSyllabusClient(min_interval=0.0)
    try:
        yield c
    finally:
        await c.aclose()


@respx.mock
async def test_search_sends_form_state(client: KindaiSyllabusClient) -> None:
    from .conftest import load_fixture

    form_html = load_fixture("search_form.html")
    results_html = """<html><body>
      <table><tr><th>学部</th><th>学科</th><th>科目名</th><th>教員名</th><th>開講年次</th>
      <th>単位</th><th>開講期</th><th>分野</th><th>科目区分</th><th>必修選択</th></tr>
      <tr><td>法学部</td><td>法律学科</td><td><a href="javascript:syllabusopen('2611100030')">X</a></td>
      <td>教員A</td><td>1年次</td><td>1単位</td><td>前期</td><td></td><td>外国語科目</td><td>選択科目</td></tr>
      </table></body></html>"""

    route = respx.post(SEARCH_URL).respond(200, text=results_html)
    respx.get(SEARCH_URL).respond(200, text=form_html)

    html = await client.search(course_name="データサイエンス")
    assert "syllabusopen" in html

    assert route.called
    req = route.calls[0].request
    body = req.read().decode("utf-8")
    # ASP.NETの状態引き回しを含むこと
    assert "__VIEWSTATE=" in body
    assert "__EVENTVALIDATION=" in body
    assert "btnSearch=" in body
    assert "txtJoukenKamokuMei=" in body
    # リセットボタンは送らない
    assert "btnSearchReset" not in body


@respx.mock
async def test_detail_redirect_to_error_is_not_found(client: KindaiSyllabusClient) -> None:
    respx.get(DETAIL_URL).respond(
        302, headers={"location": "/customer/include/error.html"}
    )
    with pytest.raises(CourseNotFoundError):
        await client.fetch_detail("9999Z99999")


@respx.mock
async def test_detail_invalid_format_rejected_before_http(client: KindaiSyllabusClient) -> None:
    route = respx.get(DETAIL_URL)
    with pytest.raises(CourseNotFoundError):
        await client.fetch_detail("123!")
    assert not route.called


@respx.mock
async def test_unexpected_status_is_upstream_error(client: KindaiSyllabusClient) -> None:
    respx.get(SEARCH_URL).respond(500, text="boom")
    with pytest.raises(UpstreamResponseError):
        await client.fetch_search_form()
