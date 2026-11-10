"""HTML解析専用モジュール。

方針:
- 構造判断はIDではなく「見出しテキスト」に依拠する(実測でspanのid名と内容が
  食い違っている箇所がある。例: 検索結果の id=lblkamokuKbn は学科、
  id=lblkamokuName は教員名を持つ。詳細は docs/PHASE1_FINDINGS.md)。
- 期待する構造が無い場合はレイアウトエラーで失敗させ、壊れたデータを返さない。
- 取得できない項目は推測せず空にする。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional, Sequence

from bs4 import BeautifulSoup, Tag

from .errors import CourseNotFoundError, DetailLayoutError, SearchLayoutError
from .models import CourseDetail, CourseSummary, LessonPlanItem

SEARCH_URL = "https://syllabus.itp.kindai.ac.jp/customer/Form/sy01000.aspx"
DETAIL_URL_TEMPLATE = "https://syllabus.itp.kindai.ac.jp/customer/Form/SY01010.aspx?syllabusno={no}"

# 実測(2026-11)の検索結果テーブルgvListの10列。順序が公式画面と同じ。
_SEARCH_COLUMNS: Sequence[str] = (
    "学部",
    "学科",
    "科目名",
    "教員名",
    "開講年次",
    "単位",
    "開講期",
    "分野",
    "科目区分",
    "必修選択",
)

# 実測(2026-11)の詳細ページの項目名 -> モデル属性。
_DETAIL_FIELDS: dict[str, str] = {
    "科目名": "course_name",
    "シラバスNO": "syllabus_no",
    "担当教員": "_teachers_raw",
    "開講年次": "year_level",
    "単位": "credits_text",
    "開講期": "term",
    "分野": "field_area",
    "科目区分": "course_category",
    "必修選択の別": "requirement",
    "英文科目名": "english_name",
    "備考": "remarks",
    "授業概要": "summary",
    "授業形態": "class_format",
    "アクティブ・ラーニングの要素": "active_learning",
    "ICTを活用したアクティブ・ラーニング": "ict_active_learning",
    "使用言語": "language",
    "学修到達目標": "learning_goals",
    "ディプロマポリシーとの関連": "diploma_policy",
    "成績評価方法および基準": "evaluation",
    "試験・課題に対するフィードバック方法": "feedback",
    "教科書": "textbooks",
    "参考文献": "references",
    "関連科目": "related_courses",
    "授業評価アンケート実施方法": "survey_method",
    "研究室・メールアドレス": "office_contact",
    "オフィスアワー": "office_hours",
    "授業計画の内容及び時間外学修の内容・時間": "lesson_plan_raw",
    "ホームページ": "homepage",
    "実践的な教育内容": "practical_content",
}

# 必須チェック用: 全部が揃わない場合は構造変化としてエラーにする。
_DETAIL_REQUIRED: Sequence[str] = (
    "科目名",
    "シラバスNO",
    "担当教員",
    "開講期",
    "学修到達目標",
    "成績評価方法および基準",
    "授業計画の内容及び時間外学修の内容・時間",
)

_ERROR_TITLE = "共通エラー"


def _tag_text(node: Tag) -> str:
    """タグの本文テキスト(改行正規化・前後空白除去)。"""
    return node.get_text(" ").strip()


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    # 全角スペース(U+3000)は氏名の一部(例「大谷　雅之」)なので保持する。
    v = re.sub(r"[\t\n\r\f\v]+", " ", value)
    v = re.sub(r"[ ]{2,}", " ", v)
    # 海外の見た目上の空白(&ensp;等)は的可読性のため半角スペースへ置換。
    v = re.sub(r"[\u2000-\u200b]", " ", v)
    return v.strip()


def _clean_lines(value: str | None) -> str:
    """行構造を保持した正規化。授業計画など <br> 区切りのテキストに使う。"""
    if not value:
        return ""
    lines = [_clean(line) for line in value.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_search_form_options(html: str) -> dict[str, Any]:
    """検索フォーム(sy01000.aspx)から選択肢を読む。

    - 学部/ソートは select の value。
    - チェックボックス(cbNEZ_*, cbKKK_* 等)は label の表示名と name の対応で読む。
      未確認のコードは推測しないため、この関数が読めた値以外はエラーになる。
    """
    soup = BeautifulSoup(html, "html.parser")

    def read_options(node: Tag | None) -> list[tuple[str, str]]:
        if node is None:
            return []
        return [(opt.get("value", ""), _tag_text(opt)) for opt in node.find_all("option")]

    gakubu = soup.find("select", attrs={"name": "dropDownListGakubu"})
    sort = soup.find("select", attrs={"name": "dropDownSort"})
    faculties = read_options(gakubu)
    sorts = read_options(sort)
    if len(faculties) < 2:
        raise SearchLayoutError("検索フォームの学部選択肢(dropDownListGakubu)を解析できませんでした")

    checkbox_labels: dict[str, dict[str, str]] = {}
    for inp in soup.find_all("input", attrs={"type": "checkbox"}):
        name = inp.get("name") or ""
        m = re.match(r"^cb([A-Z]+)_", name)
        if not m:
            continue
        prefix = f"cb{m.group(1)}_"
        label = soup.find("label", attrs={"for": inp.get("id") or name})
        label_text = _tag_text(label) if label else ""
        if not label_text:
            continue
        checkbox_labels.setdefault(prefix, {})[label_text] = name

    return {
        "faculties": faculties,
        "sorts": sorts,
        "checkbox_labels": checkbox_labels,
    }



def parse_search_results(html: str) -> list[CourseSummary]:
    """検索結果ページ(gvList)を実測の10列構造で解析する。

    注意: id名と内容が食い違っているため、列は「並び順」で判断する。
    """
    soup = BeautifulSoup(html, "html.parser")

    if soup.title is not None and _ERROR_TITLE in _tag_text(soup.title):
        raise CourseNotFoundError("シラバス検索ページがエラー(共通エラー)を返しました")

    # ヘッダ行: 直下のthが並ぶ行で10列の見出しを検証(入れ子の親行は集計しない)
    header_ok = False
    for tr in soup.find_all("tr"):
        ths = tr.find_all("th", recursive=False)
        if len(ths) >= len(_SEARCH_COLUMNS):
            titles = [_tag_text(t) for t in ths[: len(_SEARCH_COLUMNS)]]
            if titles == list(_SEARCH_COLUMNS):
                header_ok = True
                break
    if not header_ok:
        raise SearchLayoutError("検索結果テーブルの見出しが解析時と一致しません(HTML構造変化の可能性)")

    items: list[CourseSummary] = []
    for tr in soup.find_all("tr"):
        # 直下セルのみで行を判断する(ラッパーのテーブル行を誤採取しないため)
        tds = tr.find_all("td", recursive=False)
        if len(tds) != len(_SEARCH_COLUMNS):
            continue
        link = tds[2].find("a", href=re.compile(r"syllabusopen\(\s*[\"']?[0-9A-Za-z]+"))
        if link is None:
            continue

        href = link.get("href", "")
        m = re.search(r"syllabusopen\(\s*[\"']?([0-9A-Za-z]+)", href)
        if not m:
            raise SearchLayoutError("シラバス番号が検索結果のリンクから読み取れませんでした")
        syllabus_no = m.group(1)
        ym = re.match(r"^(\d{2})", syllabus_no)
        if not ym:
            raise SearchLayoutError(f"シラバス番号から年度を読み取れません: {syllabus_no}")
        academic_year = 2000 + int(ym.group(1))

        cells = [_clean(td.get_text(" ")) for td in tds]
        # 行の列は実測順序: 学部, 学科, 科目名(リンク), 教員名, 開講年次, 単位, 開講期, 分野, 科目区分, 必修選択
        items.append(
            CourseSummary(
                syllabus_no=syllabus_no,
                academic_year=academic_year,
                faculty=cells[0],
                department=cells[1],
                course_name=cells[2],
                teachers=_split_names(cells[3]),
                year_level=cells[4],
                credits_text=cells[5],
                term=cells[6],
                field_area=cells[7],
                course_category=cells[8],
                requirement=cells[9],
            )
        )
    return items


def parse_detail(html: str, syllabus_no: str, url: str) -> CourseDetail:
    """詳細ページ(SY01010.aspx)を解析する。

    構造(実測): <th>項目名</th><td><span id="lblNaiyou_NN...">値</span></td> の並び。
    年度はページ上部の lblNendoSyllabus から読む。
    """
    soup = BeautifulSoup(html, "html.parser")

    title_text = _tag_text(soup.title) if soup.title is not None else ""
    if _ERROR_TITLE in title_text or not soup.find(id=re.compile(r"^pnlData")):
        raise CourseNotFoundError(f"シラバス番号 {syllabus_no} は公開データとして存在しません(共通エラー)")

    # 年度: "2026年度シラバス"
    year_text = ""
    nendo = soup.find(id=re.compile(r"^lblNendoSyllabus"))
    if nendo is not None:
        year_text = _tag_text(nendo)
    ym = re.search(r"(\d{4})年度", year_text)
    if not ym:
        raise DetailLayoutError(f"年度表示(lblNendoSyllabus)から年度を読み取れませんでした: {year_text!r}")
    academic_year = int(ym.group(1))

    # 項目名 -> 値
    values: dict[str, str] = {}
    seen: set[str] = set()
    lesson_plan_field = "授業計画の内容及び時間外学修の内容・時間"
    for th in soup.find_all("th"):
        field_name = _tag_text(th)
        if field_name not in _DETAIL_FIELDS:
            continue
        td = th.find_next_sibling("td")
        if td is None:
            continue
        # <br> は行区切りとして保存する(授業計画の構造化に必要)
        for br in td.find_all("br"):
            br.replace_with("\n")
        text = td.get_text(" ")
        if field_name == lesson_plan_field:
            value = _clean_lines(text)
        else:
            value = _clean(text)
        values[field_name] = value
        seen.add(field_name)

    missing = [f for f in _DETAIL_REQUIRED if f not in seen]
    if missing:
        raise DetailLayoutError(
            "詳細ページの必須項目が解析できませんでした(HTML構造変化の可能性): " + ", ".join(missing)
        )

    detail_no = values.get("シラバスNO", "")
    if detail_no != syllabus_no:
        # 誤った結果を返さないための検証
        raise DetailLayoutError(
            f"詳細ページのシラバスNOが一致しません: リクエスト={syllabus_no}, ページ={detail_no!r}"
        )

    academic_year_in_page = 2000 + int(re.match(r"^(\d{2})", detail_no).group(1))
    if academic_year_in_page != academic_year:
        # ページ上部とシラバス番号の年度が違う場合も誤データ防止のため失敗させる
        raise DetailLayoutError(
            f"年度の一致確認に失敗: lblNendoSyllabus={academic_year}, シラバス番号={academic_year_in_page}"
        )

    teachers = _split_names(values.get("担当教員", ""))

    lesson_plan_raw = values.get(lesson_plan_field, "")
    lesson_plan = parse_lesson_plan(lesson_plan_raw)

    return CourseDetail(
        syllabus_no=detail_no,
        academic_year=academic_year,
        faculty=values.get("学部", ""),  # 詳細ページには学部列が無いことがある(検索結果を優先)
        course_name=values.get("科目名", ""),
        teachers=teachers,
        year_level=values.get("開講年次", ""),
        credits_text=values.get("単位", ""),
        term=values.get("開講期", ""),
        field_area=values.get("分野", ""),
        course_category=values.get("科目区分", ""),
        requirement=values.get("必修選択の別", ""),
        english_name=values.get("英文科目名", ""),
        remarks=values.get("備考", ""),
        summary=values.get("授業概要", ""),
        class_format=values.get("授業形態", ""),
        active_learning=values.get("アクティブ・ラーニングの要素", ""),
        ict_active_learning=values.get("ICTを活用したアクティブ・ラーニング", ""),
        language=values.get("使用言語", ""),
        learning_goals=values.get("学修到達目標", ""),
        diploma_policy=values.get("ディプロマポリシーとの関連", ""),
        evaluation=values.get("成績評価方法および基準", ""),
        feedback=values.get("試験・課題に対するフィードバック方法", ""),
        textbooks=values.get("教科書", ""),
        references=values.get("参考文献", ""),
        related_courses=values.get("関連科目", ""),
        survey_method=values.get("授業評価アンケート実施方法", ""),
        office_contact=values.get("研究室・メールアドレス", ""),
        office_hours=values.get("オフィスアワー", ""),
        lesson_plan_raw=lesson_plan_raw,
        lesson_plan=lesson_plan,
        homepage=values.get("ホームページ", ""),
        practical_content=values.get("実践的な教育内容", ""),
        url=url,
        fetched_at=datetime.now(timezone.utc),
    )


def _split_names(raw: str) -> list[str]:
    """教員名の分割。

    実測(2026-11):
    - 単一教員は「大谷　雅之」(氏名内の全角スペース)。
    - 複数教員は「仲西　功，中村　真也，村田　和也,...」と全角コンマ区切り。
    区切りとして扱うのは実測に基づく「，」「、」「;」「；」のみ。
    半角カンマや中点「・」は氏名内に出現しうるので区切りにしない。
    """
    raw = raw.strip()
    if not raw:
        return []
    parts: list[str] = []
    for chunk in re.split(r"[，、;；]", raw):
        chunk = _clean(chunk)
        if chunk:
            parts.append(chunk)
    return parts or [raw]


def parse_lesson_plan(raw_text: str) -> list[LessonPlanItem] | None:
    """授業計画テキストの構造化(推測なし)。構造が異なるなら None を返す。

    実測の構造: 「第N回  経 テーマ<br>内容...<br>予習内容：...(30分)<br>
    復習内容：...(150分)<br><br>第N+1回...」
    """
    if not raw_text.strip():
        return None
    text = raw_text
    # 明白な構造(第\d+回)が無いなら解析失敗扱い(推測しない)
    if not re.search(r"第\s*\d+\s*回", text):
        return None

    # 回の開始位置で分割
    marks = list(re.finditer(r"(第\s*\d+\s*回)\s*", text))
    items: list[LessonPlanItem] = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        block = text[m.start() : end].strip()
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        first = re.match(r"(第\s*\d+\s*回)?\s*(.*)", lines[0])
        session_label = m.group(1).replace(" ", "")
        theme = _clean(first.group(2)) if first else ""
        content: list[str] = []
        preparation = ""
        review = ""
        for ln in lines[1:]:
            p = re.match(r"予習内容[：:]\s*(.*)", ln)
            r = re.match(r"復習内容[：:]\s*(.*)", ln)
            if p and not preparation:
                preparation = _clean(p.group(1))
            elif r and not review:
                review = _clean(r.group(1))
            else:
                content.append(_clean(ln))
        items.append(
            LessonPlanItem(
                session=session_label,
                theme=theme,
                content=content,
                preparation=preparation,
                review=review,
                raw=block,
            )
        )
    return items or None


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
