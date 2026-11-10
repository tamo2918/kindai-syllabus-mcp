"""検索・詳細取得の手順まとめ(キャッシュ優先ロジック)。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

from bs4 import BeautifulSoup

from .cache import SyllabusCache
from .client import KindaiSyllabusClient
from .errors import KindaiSyllabusError
from .models import CourseDetail, CourseSummary
from .parser import (
    DETAIL_URL_TEMPLATE,
    SEARCH_URL,
    parse_detail,
    parse_search_form_options,
    parse_search_results,
)

DEFAULT_DETAIL_TTL_HOURS = 24 * 30  # シラバス内容は年単位で変わるため既定は30日
DEFAULT_SEARCH_TTL_HOURS = 6.0

# 実測(2026-11)のチェックボックス群と、モデル上のフィルタへの対応
#   学年: cbNEZ_****, 開講期: cbKKK_****
# ラベルとvalueの対応はフォームHTMLから動的に読む(未確認の値を推測しない)。
_YEAR_LEVEL_PREFIX = "cbNEZ_"
_TERM_PREFIX = "cbKKK_"
_CHECKBOXES_RE = re.compile(r"^cb([A-Z]+)_")


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, "") or default)
    except ValueError:
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.environ.get(key, "") or default)
    except ValueError:
        return default


class SyllabusService:
    """MCPツールから使われる高レベルAPI。

    検索条件は実測・検証済みのものだけ扱う:
    - テキスト: 科目名(course_name) / 教員名(teacher) / キーワード(query)
    - 学部: フォームの選択肢から解決
    - 学年・開講期: フォームのチェックボックスのラベル→valueを動的解決
    """

    def __init__(
        self,
        client: KindaiSyllabusClient | None = None,
        cache: SyllabusCache | None = None,
    ) -> None:
        self.client = client or KindaiSyllabusClient(
            timeout=_env_float("KINDAI_SYLLABUS_TIMEOUT", 20.0),
            min_interval=_env_float("KINDAI_SYLLABUS_MIN_INTERVAL", 1.0),
        )
        self.cache = cache or SyllabusCache()
        self.detail_ttl = _env_float("KINDAI_SYLLABUS_DETAIL_TTL_HOURS", DEFAULT_DETAIL_TTL_HOURS) * 3600
        self.search_ttl = _env_float("KINDAI_SYLLABUS_SEARCH_TTL_HOURS", DEFAULT_SEARCH_TTL_HOURS) * 3600
        self._form_html: str | None = None
        self._form_options: dict[str, Any] | None = None

    async def aclose(self) -> None:
        await self.client.aclose()
        await self.cache.close()

    # ---- 詳細 ----

    async def get_course(self, syllabus_no: str, refresh: bool = False) -> CourseDetail:
        if not re.fullmatch(r"\d{2}[0-9A-Z]{8}", str(syllabus_no or "")):
            raise KindaiSyllabusError(
                f"シラバス番号の形式が不正です: {syllabus_no!r} (例: 2611N00215, 10文字)"
            )

        if not refresh:
            cached = await self.cache.get_detail(syllabus_no, ttl_seconds=self.detail_ttl)
            if cached is not None:
                return cached

        html = await self.client.fetch_detail(syllabus_no)
        url = DETAIL_URL_TEMPLATE.format(no=syllabus_no)
        detail = parse_detail(html, syllabus_no=syllabus_no, url=url)
        await self.cache.put_detail(detail)
        return detail

    # ---- 検索フォーム ----

    async def _ensure_form_html(self) -> str:
        if self._form_html is None:
            self._form_html = await self.client.fetch_search_form()
            self._form_options = None  # HTMLと一起性にする
        return self._form_html

    async def _search_form_options(self) -> dict[str, Any]:
        if self._form_options is None:
            html = await self._ensure_form_html()
            self._form_options = parse_search_form_options(html)
        return self._form_options

    async def list_faculties(self) -> list[dict[str, str]]:
        opts = await self._search_form_options()
        return [{"code": code, "label": label} for code, label in opts["faculties"] if code]

    # ---- 検索 ----

    async def search_courses(
        self,
        query: str | None = None,
        academic_year: int | None = None,
        faculty: str | None = None,
        teacher: str | None = None,
        course_name: str | None = None,
        year_level: str | None = None,
        term: str | None = None,
        page: int = 1,
        page_size: int = 20,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """公式検索を1リクエストで実行し、ページ指定はローカル分割で実現。

        実測(2026-11): 公式は検索結果を全件1応答で返す(page/postback無し)ため、
        page/page_size は結果のスライス。公式ページングではないことを note に明記する。
        処理前に条件の非空性を検証する(全項目None/空なら公式サイトに問い合わせない)。
        """
        conditions = (
            query, academic_year, faculty, teacher, course_name, year_level, term,
        )
        if all(v in (None, "") for v in conditions):
            raise KindaiSyllabusError(
                "検索条件が空です。query / course_name / teacher / faculty / year_level / term から指定してください"
            )
        if not (isinstance(page, int) or (isinstance(page, str) and page.isdigit())):
            raise KindaiSyllabusError("page は1以上の整数で指定してください")
        page = int(page)
        if page < 1:
            raise KindaiSyllabusError("page は1以上の整数で指定してください")
        try:
            page_size = int(page_size)
        except (TypeError, ValueError) as exc:
            raise KindaiSyllabusError("page_size は 1〜200 の整数で指定してください") from exc
        if not 1 <= page_size <= 200:
            raise KindaiSyllabusError("page_size は 1〜200 で指定してください")

        if academic_year is not None:
            # 公式検索フォームには年度の選択UIが実測されていない。
            # 年度はシラバス番号先頭2桁に反映される(例 2611N00215 → 2026)。
            current = 2000 + _env_int("KINDAI_SYLLABUS_CUR_YEAR_SUFFIX", 26)
            if int(academic_year) != current:
                raise KindaiSyllabusError(
                    f"指定年度({academic_year})は検索フォームの対象外か未確認です。"
                    f"現行年度({current})のみ検証済み。別年度はシラバス番号指定(get_course)を使用してください。"
                )

        options = await self._search_form_options()

        extra_fields: dict[str, str] = {}
        if year_level:
            extra_fields.update(self._resolve_checkboxes(year_level, _YEAR_LEVEL_PREFIX, options, "学年"))
        if term:
            extra_fields.update(self._resolve_checkboxes(term, _TERM_PREFIX, options, "開講期"))

        faculty_code = self._resolve_faculty(faculty, options)

        params_key = self._search_params_key(
            query=query,
            academic_year=academic_year,
            faculty=faculty_code,
            teacher=teacher,
            course_name=course_name,
            year_level=year_level or "",
            term=term or "",
        )

        # キャッシュ優先(短TTL)
        if not refresh:
            cached_items = await self.cache.get_search(params_key, ttl_seconds=self.search_ttl)
            if cached_items is not None:
                return self._paged_response(cached_items, page, page_size, cached=True)

        html = await self.client.search(
            faculty=faculty_code,
            course_name=course_name or None,
            teacher=teacher or None,
            keyword=query or None,
            extra_fields=extra_fields or None,
        )
        items = parse_search_results(html)
        await self.cache.put_search(params_key, academic_year, items)
        return self._paged_response(items, page, page_size, cached=False)

    # ---- 解析ヘルパ ----

    def _resolve_faculty(self, faculty: str | None, options: dict[str, Any]) -> str | None:
        if faculty in (None, "", "指定しない"):
            return None
        val = str(faculty).strip()
        faculties = dict(options["faculties"])
        if val in faculties:
            return val
        # 部分一致は解決済みラベルのみ。推測はしない。
        matches = [code for code, label in options["faculties"] if label and label in val]
        if len(matches) == 1:
            return matches[0]
        raise KindaiSyllabusError(
            f"学部を検証できませんでした: {faculty!r}。list_faculties() の code を指定してください"
        )

    def _resolve_checkboxes(
        self,
        labels_spec: str,
        prefix: str,
        options: dict[str, Any],
        filter_name: str,
    ) -> dict[str, str]:
        """ラベル(例「1年次」「前期」)からチェックボックスのフィールド名を解決。

        ラベル対応はフォームHTMLから毎回読むため、公式サイトの変更に応答可能。
        通らなかったラベルは検証済みリストを含むエラーで返す(推測しない)。
        """
        checkbox_map = options["checkbox_labels"][prefix]
        if not checkbox_map:
            raise KindaiSyllabusError(
                f"{filter_name}フィルタ({prefix}*)を検索フォームから読み取れませんでした"
            )
        result: dict[str, str] = {}
        invalid: list[str] = []
        for raw in re.split(r"[,、]+", str(labels_spec)):
            label = raw.strip()
            if not label:
                continue
            if label in checkbox_map:
                result[checkbox_map[label]] = "on"
            else:
                invalid.append(label)
        if invalid:
            valid = "、".join(sorted(checkbox_map))
            raise KindaiSyllabusError(
                f"{filter_name}フィルタが検証できませんでした: {', '.join(invalid)} (有効な値: {valid})"
            )
        if not result:
            raise KindaiSyllabusError(f"{filter_name}フィルタが空です")
        return result

    def _search_params_key(self, **kwargs: Any) -> str:
        payload = json.dumps(kwargs, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256((SEARCH_URL + payload).encode()).hexdigest()[:32]

    def _paged_response(
        self,
        items: list[CourseSummary],
        page: int,
        page_size: int,
        cached: bool,
    ) -> dict[str, Any]:
        start = (page - 1) * page_size
        end = start + page_size
        slice_items = items[start:end]
        return {
            "items": [json.loads(item.model_dump_json()) for item in slice_items],
            "total": len(items),
            "page": page,
            "page_size": page_size,
            "returned": len(slice_items),
            "has_more": end < len(items),
            "cached": cached,
            "source_url": SEARCH_URL,
            "note": "公式検索は全件を1応答で返す。page/page_size はローカル分割であり公式ページングではありません。",
        }


__all__ = ["SyllabusService"]
