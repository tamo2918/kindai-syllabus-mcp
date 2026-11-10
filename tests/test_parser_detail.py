"""詳細ページ(SY01010)解析のテスト(オフライン)。"""

from __future__ import annotations

import pytest

from kindai_syllabus_mcp.errors import CourseNotFoundError, DetailLayoutError
from kindai_syllabus_mcp.parser import DETAIL_URL_TEMPLATE, parse_detail, parse_lesson_plan

from .conftest import load_fixture

DETAIL_URL = DETAIL_URL_TEMPLATE.format(no="2611N00215")


def test_detail_fields_are_mapped_by_th_text() -> None:
    detail = parse_detail(load_fixture("detail_web.html"), "2611N00215", DETAIL_URL)
    # 実測値
    assert detail.syllabus_no == "2611N00215"
    assert detail.academic_year == 2026
    assert detail.course_name == "アプリケーション開発実習１"
    assert detail.teachers == ["大谷　雅之"]
    assert detail.year_level == "1年次"
    assert detail.credits_text == "1単位"
    assert detail.term == "後期"
    assert detail.course_category == "専門科目"
    assert detail.requirement == "必修科目"
    assert detail.english_name == "Application Development Practicum 1"
    assert detail.summary.startswith("本授業では、Appleのプログラミング言語 Swift")
    assert detail.class_format == "メディア授業（全授業回）"
    assert detail.language == "日本語"
    assert detail.learning_goals.startswith("この科目の学修到達目標")
    assert detail.evaluation.startswith("基礎演習課題")
    assert detail.feedback != ""
    assert detail.textbooks != ""
    assert "Develop in Swift Fundamentals" in detail.references
    assert detail.office_contact.startswith("大谷講師室（E館2階E-233）")
    assert detail.url == DETAIL_URL


def test_detail_lesson_plan_is_structured() -> None:
    detail = parse_detail(load_fixture("detail_web.html"), "2611N00215", DETAIL_URL)
    assert detail.lesson_plan is not None
    plan = detail.lesson_plan
    assert len(plan) >= 6  # 実測で10数回分ある
    first = plan[0]
    assert first.session == "第1回"
    assert first.theme == "ガイダンス・開発環境の構築"
    assert "授業の目的と進め方、アプリケーション開発の全体像を理解する。" in first.content
    assert first.preparation.startswith("授業計画をよく確認すること")
    assert first.review.startswith("理解が不十分だった内容を復習")
    # 原文を必ず保持(推測しない方針)
    assert first.raw.startswith("第1回")
    # 全ての項目に回が入る
    for item in plan:
        assert item.session.startswith("第")


def test_detail_english_course_lesson_plan() -> None:
    detail = parse_detail(load_fixture("detail_eng.html"), "2611100030", DETAIL_URL_TEMPLATE.format(no="2611100030"))
    assert detail.syllabus_no == "2611100030"
    assert detail.lesson_plan is not None
    assert detail.lesson_plan[0].theme != ""
    # 英語科目: 使用言語・科目区分が読める
    assert detail.language != ""


def test_invalid_syllabusno_flow_is_parse_error_page() -> None:
    with pytest.raises(CourseNotFoundError):
        parse_detail(load_fixture("error.html"), "9999Z99999", "https://example.invalid")


def test_detail_structural_change_is_not_silently_accepted() -> None:
    html = load_fixture("detail_web.html")
    # 必須項目(成績評価方法および基準)の見出しが変更された状態 → 誤データではなくエラー
    broken = html.replace("成績評価方法および基準", "成績評価基準", 1)
    with pytest.raises(DetailLayoutError):
        parse_detail(broken, "2611N00215", DETAIL_URL)


def test_detail_syllabusno_mismatch_is_rejected() -> None:
    # request 2611N00215 だがページ側が別番号 → 誤返却を防ぐ
    html = load_fixture("detail_web.html").replace("2611N00215", "2611N00999")
    with pytest.raises(DetailLayoutError):
        parse_detail(html, "2611N00215", DETAIL_URL)


def test_lesson_plan_unparseable_structure_returns_none() -> None:
    # 「第N回」が無い形式は構造化せず None (原文は残す)
    assert parse_lesson_plan("集中講義で実施します。") is None
    assert parse_lesson_plan("") is None
