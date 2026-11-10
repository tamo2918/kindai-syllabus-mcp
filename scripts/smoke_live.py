"""実サイトとの突き合わせスモーク(手動実行用・pytestには含めない)。

実通信が発生するため、通常は行わない。公式サイトへの負荷を抑えるため
1回の実行で3リクエスト(詳細1・検索1・フォーム1)に制限している。

    uv run python scripts/smoke_live.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from kindai_syllabus_mcp.cache import SyllabusCache  # noqa: E402
from kindai_syllabus_mcp.client import KindaiSyllabusClient  # noqa: E402
from kindai_syllabus_mcp.service import SyllabusService  # noqa: E402


async def main() -> int:
    cache = SyllabusCache(db_path=os.environ.get(
        "KINDAI_SYLLABUS_DB",
        os.path.join(os.path.dirname(__file__), "..", "data", "smoke-cache.sqlite3"),
    ))
    svc = SyllabusService(
        client=KindaiSyllabusClient(
            timeout=20.0,
            min_interval=max(1.0, float(os.environ.get("KINDAI_SYLLABUS_MIN_INTERVAL", "1"))),
        ),
        cache=cache,
    )
    failures = 0
    try:
        # 1) 既知のシラバス番号から詳細取得 (公式例: 2611N00215)
        detail = await svc.get_course("2611N00215", refresh=True)
        checks = {
            "syllabus_no": detail.syllabus_no == "2611N00215",
            "academic_year": detail.academic_year == 2026,
            "course_name": detail.course_name == "アプリケーション開発実習１",
            "evaluation": bool(detail.evaluation),
            "lesson_plan": bool(detail.lesson_plan and len(detail.lesson_plan) >= 6),
            "prep_review": bool(detail.lesson_plan and detail.lesson_plan[0].preparation and detail.lesson_plan[0].review),
            "source_url": detail.url.endswith("SY01010.aspx?syllabusno=2611N00215"),
        }
        print("[detail]", json.dumps(checks, ensure_ascii=False))
        if not all(checks.values()):
            failures += 1
        print("  fetched_at:", detail.fetched_at.isoformat())
        print("  name:", detail.course_name, "| teachers:", detail.teachers, "| credits:", detail.credits_text)

        # 2) 検索 (確認済み条件: 科目名/教員名/キーワード/学部)
        search = await svc.search_courses(course_name="データサイエンス", page=1, page_size=5, refresh=True)
        checks2 = {
            "has_items": len(search["items"]) > 0,
            "source_url": search["source_url"].endswith("sy01000.aspx"),
        }
        print("[search]", json.dumps(checks2, ensure_ascii=False), "total=", search["total"])
        if search["items"]:
            first = search["items"][0]
            print("  first:", first["syllabus_no"], first["course_name"], first["teachers"])
        if not all(checks2.values()):
            failures += 1

        # 3) 学部コード一覧
        faculties = await svc.list_faculties()
        codes = [f["code"] for f in faculties]
        checks3 = {"111" in codes and "Z11" in codes}
        print("[faculties]", f"n={len(faculties)} ok={checks3}")
        if not all(checks3):
            failures += 1
    finally:
        await svc.aclose()
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
