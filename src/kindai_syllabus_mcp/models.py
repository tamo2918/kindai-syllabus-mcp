"""データモデル。

検索結果と詳細取得で同じデータモデルを利用する:
- 検索結果: CourseSummary (骨格)
- 詳細取得: CourseDetail (= CourseSummary の骨格 + 詳細項目)

取得できない項目は推測せず空文字にする。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class CourseSummary(BaseModel):
    """検索結果1行分。詳細ページでも同名目のデータとして保持する部分。

    2026年11月時点の検索結果テーブル(gvList)の10列から作る。
    """

    syllabus_no: str = Field(description="シラバス番号 (例: 2611N00215)")
    academic_year: int = Field(description="年度 (シラバス番号先頭2桁。2611N00215なら2026)")
    faculty: str = Field(default="", description="学部")
    department: str = Field(default="", description="学科")
    course_name: str = Field(default="", description="科目名")
    teachers: list[str] = Field(default_factory=list, description="担当教員")
    year_level: str = Field(default="", description="開講年次 (公式表記そのまま)")
    credits_text: str = Field(default="", description="単位 (例「1単位」。数値は公式表記しない)")
    term: str = Field(default="", description="開講期 (例「前期」「1セメスター」)")
    field_area: str = Field(default="", description="分野")
    course_category: str = Field(default="", description="科目区分")
    requirement: str = Field(default="", description="必修選択の別")


class LessonPlanItem(BaseModel):
    """授業計画の1回分。

    公式の授業計画は「第N回 + テーマ / 内容行 / 予習内容 / 復習内容」のテキスト。
    テキスト解析の成否に関係なく原文(raw)を必ず保持して推測を防ぐ。
    """

    session: str = Field(description="回 (例「第1回」。特定できれば原文そのまま)")
    theme: str = Field(default="", description="テーマ")
    content: list[str] = Field(default_factory=list, description="内容行(テーマ以降の説明行)")
    preparation: str = Field(default="", description="予習内容")
    review: str = Field(default="", description="復習内容")
    raw: str = Field(default="", description="当該回の原文")


class CourseDetail(CourseSummary):
    """詳細ページ取得結果。SY01010.aspx の項目名(2026-11実測)に対応。"""

    english_name: str = Field(default="", description="英文科目名")
    remarks: str = Field(default="", description="備考")
    summary: str = Field(default="", description="授業概要")
    class_format: str = Field(default="", description="授業形態")
    active_learning: str = Field(default="", description="アクティブ・ラーニングの要素")
    ict_active_learning: str = Field(default="", description="ICTを活用したアクティブ・ラーニング")
    language: str = Field(default="", description="使用言語")
    learning_goals: str = Field(default="", description="学修到達目標")
    diploma_policy: str = Field(default="", description="ディプロマポリシーとの関連")
    evaluation: str = Field(default="", description="成績評価方法および基準")
    feedback: str = Field(default="", description="試験・課題に対するフィードバック方法")
    textbooks: str = Field(default="", description="教科書")
    references: str = Field(default="", description="参考文献")
    related_courses: str = Field(default="", description="関連科目")
    survey_method: str = Field(default="", description="授業評価アンケート実施方法")
    office_contact: str = Field(default="", description="研究室・メールアドレス")
    office_hours: str = Field(default="", description="オフィスアワー")
    lesson_plan_raw: str = Field(default="", description="授業計画の原文(未解析のままの文字列)")
    lesson_plan: Optional[list[LessonPlanItem]] = Field(
        default=None, description="授業計画の構造化(None=構造化できなかった)"
    )
    homepage: str = Field(default="", description="ホームページ")
    practical_content: str = Field(default="", description="実践的な教育内容")
    url: str = Field(default="", description="公式詳細URL")
    fetched_at: datetime = Field(description="取得日時(UTC)")
    cached: bool = Field(default=False, description="キャッシュから返したか")


class SearchOptions(BaseModel):
    """検索フォームから読み取った選択肢。コードは公式 select の value そのまま。"""

    faculties: list[tuple[str, str]] = Field(default_factory=list, description="(code, 学部名)")
    sorts: list[tuple[str, str]] = Field(default_factory=list, description="(code, ソート名)")
