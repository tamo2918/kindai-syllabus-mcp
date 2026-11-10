"""検索結果・フォーム解析のテスト(オフライン)。"""

from __future__ import annotations

import pytest

from kindai_syllabus_mcp.errors import CourseNotFoundError, SearchLayoutError
from kindai_syllabus_mcp.parser import parse_search_form_options, parse_search_results

from .conftest import load_fixture


def test_search_result_rows_are_parsed_in_official_order() -> None:
    items = parse_search_results(load_fixture("search_results.html"))
    # トリミング済みフィクスチャ: 12行 保持
    assert len(items) >= 10
    first = items[0]
    # 実測1行目: Communicative English 1A（再）
    assert first.syllabus_no == "2611100030"
    assert first.academic_year == 2026
    assert first.faculty == "法学部"
    assert first.department == "（平成20年度以降）法律学科"
    assert first.course_name == "Communicative English 1A（再）"
    assert first.teachers == ["テリー　アンダーソン"]
    assert first.year_level == "1～4年次"
    assert first.credits_text == "1単位"
    assert first.term == "半期"
    assert first.course_category == "外国語科目"
    assert first.requirement == "必修科目"


def test_search_row_ids_extracted_from_javascript_link() -> None:
    items = parse_search_results(load_fixture("search_results.html"))
    ids = [it.syllabus_no for it in items]
    assert ids[:3] == ["2611100030", "2611100031", "2611100055"]


def test_multi_teachers_split_by_full_width_comma() -> None:
    # 実測: データサイエンス演習の担当は「仲西　功，中村　真也，...」の全角コンマ区切り
    from kindai_syllabus_mcp.parser import _split_names

    assert _split_names("仲西　功，中村　真也，村田　和也") == [
        "仲西　功",
        "中村　真也",
        "村田　和也",
    ]
    # 単一教員(氏名内の全角スペースは保持)
    assert _split_names("大谷　雅之") == ["大谷　雅之"]
    # 中点・半角カンマは氏名内の可能性があるため区切らない(推測しない)
    assert _split_names("テリー・アンダーソン") == ["テリー・アンダーソン"]


def test_search_results_error_page_is_rejected() -> None:
    with pytest.raises(CourseNotFoundError):
        parse_search_results(load_fixture("error.html"))


def test_search_results_header_change_is_detected() -> None:
    html = load_fixture("search_results.html")
    # 公式見出しの「開講期」を「開講学期」に変えた擬似改変 → 検出可能エラーに。
    assert html.count("開講期") >= 1
    broken = html.replace(">開講期<", ">開講学期<", 1)
    with pytest.raises(SearchLayoutError):
        parse_search_results(broken)


def test_search_results_missing_grid_is_detected() -> None:
    html = "<html><body><p>no table here</p></body></html>"
    with pytest.raises(SearchLayoutError):
        parse_search_results(html)


def test_search_form_options_are_parsed() -> None:
    opts = parse_search_form_options(load_fixture("search_form.html"))
    faculties = dict(opts["faculties"])
    assert faculties["111"] == "法学部"
    assert faculties["Z11"] == "共通教養"
    sorts = dict(opts["sorts"])
    assert sorts["002"] == "学科順"

    # 実測のチェックボックスラベル対応(動的読み取り)
    year_levels = opts["checkbox_labels"]["cbNEZ_"]
    assert year_levels["1年次"] == "cbNEZ_0010"
    assert year_levels["1～4年次"] == "cbNEZ_0090"
    terms = opts["checkbox_labels"]["cbKKK_"]
    assert terms["前期"] == "cbKKK_009"
    assert terms["通年"] == "cbKKK_011"
    assert terms["2セメスター"] == "cbKKK_002"


def test_search_form_corruption_is_detected() -> None:
    html = load_fixture("search_form.html")
    broken = html.replace('name="dropDownListGakubu"', 'name="dropDownListGakubuX"')
    with pytest.raises(SearchLayoutError):
        parse_search_form_options(broken)
