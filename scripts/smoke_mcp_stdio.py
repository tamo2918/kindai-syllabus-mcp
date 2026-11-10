"""MCP stdio接続の疎通スモーク(手動実行用・pytestには含めない)。

SDK v2 の Client を自サーバー(stdout/stdin)へ繋いで、
tools/list と tools/call を実際に行う。実通信は get_course 1回のみ。

    uv run python scripts/smoke_mcp_stdio.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import Client, StdioServerParameters

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


async def main() -> int:
    params = StdioServerParameters(
        command=os.environ.get("KINDAI_MCP_SMOKE_CMD", "uv"),
        args=["run", "kindai-syllabus-mcp"],
        cwd=PROJECT_ROOT,
        # キャッシュをテスト用に分離(実データを汚さない)
        env={"KINDAI_SYLLABUS_DB": os.path.join(PROJECT_ROOT, "data", "smoke-mcp-cache.sqlite3")},
    )
    failures = 0
    async with Client(params) as client:
        tools = await client.session.list_tools()
        names = [t.name for t in tools.tools]
        print("[tools/list]", names)
        if not {"get_course", "search_courses", "list_faculties"} <= set(names):
            failures += 1

        # 実通信: 既知のシラバス番号
        result = await client.call_tool("get_course", {"syllabus_no": "2611N00215"})
        text = result.content[0].text
        payload = json.loads(text)
        print("[get_course]", payload.get("course_name"), "| source:", payload.get("source_url"))
        if payload.get("course_name") != "アプリケーション開発実習１":
            failures += 1
        if not payload.get("source_url", "").endswith("SY01010.aspx?syllabusno=2611N00215"):
            failures += 1

        # エラー系(通信なしでフォーマット判定)
        result = await client.call_tool("get_course", {"syllabus_no": "AB"})
        payload = json.loads(result.content[0].text)
        print("[get_course invalid]", payload)
        if "error" not in payload:
            failures += 1

        # list_faculties(実通信)
        result = await client.call_tool("list_faculties", {})
        payload = json.loads(result.content[0].text)
        codes = [i["code"] for i in payload["items"]]
        print("[list_faculties]", f"n={len(codes)}", "111" in codes)
        if "111" not in codes:
            failures += 1

        # search(実通信・キャッシュ書き込みを伴う経路)
        result = await client.call_tool(
            "search_courses", {"course_name": "データサイエンス", "page_size": 3}
        )
        payload = json.loads(result.content[0].text)
        print("[search]", f"total={payload.get('total')}", "returned=", payload.get("returned"))
        if "error" in payload or not payload.get("items"):
            failures += 1
    print("FAILURES:", failures)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
