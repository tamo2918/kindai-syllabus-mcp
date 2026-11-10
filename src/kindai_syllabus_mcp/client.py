"""公式サイトとのHTTP通信。

- httpx + BeautifulSoup4。Playwrightは使わない(HTTP方式で実現できている間は)。
- 送信間隔の下限(rate limit)・タイムアウトを設ける。
- 読み取り専用: 送るのは検索フォームの送信(GET/POST)のみ。ログインはしない。
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any, Mapping

import httpx
from bs4 import BeautifulSoup

from .errors import CourseNotFoundError, UpstreamResponseError
from .parser import DETAIL_URL_TEMPLATE, SEARCH_URL

DEFAULT_TIMEOUT = 20.0
DEFAULT_MIN_INTERVAL = 1.0  # 秒。公式サイトの負荷を抑える下限間隔

USER_AGENT = "kindai-syllabus-mcp/0.1 (+https://kindai.ac.jp syllabus read-only cache MCP)"

_ERROR_REDIRECT = "/customer/include/error.html"


class KindaiSyllabusClient:
    """近畿大学シラバスの読み取りクライアント(非同期)。

    検索フローは実測に基づく:
    1. GET  sy01000.aspx (フォーム取得、Cookie/ViewState取得)
    2. POST sy01000.aspx (btnSearch; 必要な隠しパラメータを引き回す)
    事前のautopostback(学部変更)無しでも検索は通る(2026-11実測)。
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        user_agent: str = USER_AGENT,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._timeout = timeout
        self._min_interval = min_interval
        self._owned = http is None
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "User-Agent": user_agent,
                "Accept-Language": "ja,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            follow_redirects=False,
        )
        self._lock = asyncio.Lock()
        self._last_request_monotonic: float | None = None

    async def aclose(self) -> None:
        if self._owned:
            await self._http.aclose()

    # ---- 通信基本 ----

    async def _throttle(self) -> None:
        """全リクエスト間に下限間隔を設ける(公式サイトの負荷軽減)。"""
        async with self._lock:
            if self._last_request_monotonic is not None and self._min_interval > 0:
                elapsed = time.monotonic() - self._last_request_monotonic
                wait = self._min_interval - elapsed
                if wait > 0:
                    await asyncio.sleep(wait)
            self._last_request_monotonic = time.monotonic()

    async def get(self, url: str) -> httpx.Response:
        await self._throttle()
        try:
            resp = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise UpstreamResponseError(f"GETに失敗: {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise UpstreamResponseError(f"HTTP {resp.status_code}: {url}")
        return resp

    async def post_form(self, url: str, data: Mapping[str, Any]) -> httpx.Response:
        await self._throttle()
        try:
            resp = await self._http.post(
                url,
                data={k: v for k, v in data.items() if v is not None},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            raise UpstreamResponseError(f"POSTに失敗: {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise UpstreamResponseError(f"HTTP {resp.status_code}: {url}")
        return resp

    # ---- 検索 ----

    async def fetch_search_form(self) -> str:
        """検索フォームHTML(隠しパラメータ含む)。"""
        resp = await self.get(SEARCH_URL)
        return resp.text

    async def search(
        self,
        faculty: str | None = None,
        course_name: str | None = None,
        teacher: str | None = None,
        keyword: str | None = None,
        sort: str | None = None,
        extra_fields: Mapping[str, str] | None = None,
    ) -> str:
        """検索を1回実行して結果HTMLを返す。

        - faculty: 学部selectのvalue(例 '111')。条件があるときだけ送る。
        - sort: dropDownSortのvalue。
        - extra_fields: cbHSS_001 のような checkbox や検証済みの追加条件。
        """
        form_html = await self.fetch_search_form()
        fields = _collect_form_fields(form_html)
        fields["__EVENTTARGET"] = ""
        fields["__EVENTARGUMENT"] = ""
        fields["__LASTFOCUS"] = ""
        if faculty:
            fields["dropDownListGakubu"] = faculty
        if sort:
            fields["dropDownSort"] = sort
        if course_name:
            fields["txtJoukenKamokuMei"] = course_name
        if teacher:
            fields["txtJoukenKyoinMei"] = teacher
        if keyword:
            fields["txtJoukenKeyword"] = keyword
        if extra_fields:
            fields.update(extra_fields)
        fields["btnSearch"] = "検索"
        fields.pop("btnSearchReset", None)

        resp = await self.post_form(SEARCH_URL, fields)
        html = resp.text
        if "共通エラー" in html:
            raise UpstreamResponseError("検索処理が共通エラーを返しました(条件・構成を見直してください)")
        return html

    # ---- 詳細 ----

    async def fetch_detail(self, syllabus_no: str) -> str:
        """詳細ページHTML。不正ID(実測: 302→共通エラー)は CourseNotFoundError。"""
        if not re.fullmatch(r"\d{2}[0-9A-Z]{8}", syllabus_no):
            # 実測: 10文字 = 年度2桁 + 学部等コード2桁 + 6文字英数字
            # 例: 2611N00215 / 2611100030 / 26Z1100070
            raise CourseNotFoundError(
                f"シラバス番号の形式が不正です: {syllabus_no!r} (例: 2611N00215)"
            )
        url = DETAIL_URL_TEMPLATE.format(no=syllabus_no)
        resp = await self.get(url)
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("location", "")
            if _ERROR_REDIRECT in location:
                raise CourseNotFoundError(
                    f"シラバス番号 {syllabus_no} は公開データとして存在しません(共通エラーへの誘導)"
                )
            raise UpstreamResponseError(f"想定外のリダイレクト: {location}")
        html = resp.text
        if "共通エラー" in html:
            raise CourseNotFoundError(f"シラバス番号 {syllabus_no} は存在しません(共通エラー)")
        if f"syllabusno={syllabus_no}" not in html:
            raise UpstreamResponseError("詳細ページ応答に要求したシラバス番号が現れませんでした")
        return html


def _collect_form_fields(html: str) -> dict[str, str]:
    """ASP.NETフォームの隠し・テキストパラメータ収集(__VIEWSTATE等を引き回す)。"""
    soup = BeautifulSoup(html, "html.parser")
    fields: dict[str, str] = {}
    for inp in soup.find_all("input"):
        type_ = (inp.get("type") or "").lower()
        name = inp.get("name")
        if not name or type_ in ("submit", "image", "checkbox", "button", "file"):
            continue
        value = inp.get("value", "") or ""
        fields[name] = value
    return fields
