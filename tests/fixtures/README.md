# tests/fixtures

公式サイト(https://syllabus.itp.kindai.ac.jp)の**構造検証用の小さな切り出し**です。

- `search_form.html`: 検索フォームの全HTML(現行年度のフォーム構造)
- `search_results.html`: 検索結果ページから最初の12行だけを残し、`__VIEWSTATE`等の
  状態トークンをプレースホルダ(`__STATE__` / `__EV__`)へ置き換えた縮小版
- `detail_web.html` / `detail_eng.html`: 2科目の詳細ページ(公開データそのまま)
- `error.html`: 不正ID時の共通エラーページ

**表現目的の再配布ではありません。** HTML構造が変わった際に
`SearchLayoutError` / `DetailLayoutError` を正しく発生させるための単体テスト
(オフライン)用の最小スナップショットです。コース内容の二次配布を求めるときは
本リポジトリではなく公式シラバスを参照してください。
