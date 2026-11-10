# セットアップ / 運用メモ

## 実行方法

```sh
uv run --project /home/tatsuki/projects/kindai-syllabus-mcp kindai-syllabus-mcp
```

stdio MCPサーバー。初回起動時にuvがvenvを整備してから起動する。

## MCPクライアントへの登録

### OpenCode (`~/.config/opencode/opencode.json`)

```json
{
  "mcp": {
    "kindai-syllabus": {
      "type": "local",
      "command": ["uv", "run", "--project", "/home/tatsuki/projects/kindai-syllabus-mcp", "kindai-syllabus-mcp"],
      "enabled": true
    }
  }
}
```

セッションのツール一覧に `kindai-syllabus` (get_course / search_courses / list_faculties) が現れれば接続成功。

### Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.kindai-syllabus]
command = "uv"
args = ["run", "--project", "/home/tatsuki/projects/kindai-syllabus-mcp", "kindai-syllabus-mcp"]
```

### Hermes

HermesはDockerスタック(homelabのhermes-personal / hermes-company)で稼働しており、
ホストのuvパスがコンテナ内から見えないため未登録。
本体がMCPに対応している場合の手順:
`uvx --from /home/tatsuki/projects/kindai-syllabus-mcp kindai-syllabus-mcp`
をコンテナから参照可能な位置に置くか、ホストのStreamable HTTP化
(server.run(transport="streamable-http") + localhostポート)が必要。

## 環境変数

| 変数 | 既定 | 意味 |
|---|---|---|
| `KINDAI_SYLLABUS_DB` | `~/.cache/kindai-syllabus-mcp/cache.sqlite3` | SQLiteキャッシュの保存先 |
| `KINDAI_SYLLABUS_TIMEOUT` | `20.0` | HTTPタイムアウト秒 |
| `KINDAI_SYLLABUS_MIN_INTERVAL` | `1.0` | 公式サイトへの送信最小間隔秒 |
| `KINDAI_SYLLABUS_DETAIL_TTL_HOURS` | `720` (30日) | 詳細キャッシュの鮮期限 |
| `KINDAI_SYLLABUS_SEARCH_TTL_HOURS` | `6` | 検索結果キャッシュの鮮期限 |
| `KINDAI_SYLLABUS_CUR_YEAR_SUFFIX` | `2026年度→26` | 検索時に受付可能な年度 |

## テストとスモーク

```sh
# オフラインのユニットテスト(実サイト通信なし)
uv run pytest

# 実サイト突き合わせ(詳細1 + 検索1 + フォーム1の3リクエスト)
uv run python scripts/smoke_live.py

# stdio MCPとしての疎通(tools/list + tools/call)
uv run python scripts/smoke_mcp_stdio.py
```

## トラブルシュート

- **HTML構造変化**: `SearchLayoutError` / `DetailLayoutError` が出たら公式ページの
  構造が変わった可能性。解析を`tests/fixtures`の実物スナップショットと比較して更新する。
- **検索がエラーJSONを返す**: 検証済み条件のみ対応。`list_faculties()` で学部コード、
  学年/開講期はフォームのラベル表記(例「1～4年次」「前期」)。
- **キャッシュが古い**: `refresh=True` で強制再取得。
- 旧プロセスが残っている場合(`ps aux | grep kindai-syllabus`)はkillすると
  MCPクライアントが次回要求時に再起動する。

## 更新運用

- ソース変更 → `uv run pytest` → スモーク → コミット。
- ソースは `/home/tatsuki/projects/kindai-syllabus-mcp`(dev用, Git管理)。
- homelabコンソールへは `homelab.app.json` 経由で登録(常駐プロセスなし・stdio)。
