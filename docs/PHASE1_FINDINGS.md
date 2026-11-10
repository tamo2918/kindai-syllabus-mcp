公式サイト通信解析結果 (Phase 1)

日付: 2026-11-10
検証者: エージェント(GLM-5.3-Flash Free / opencode)
URL: https://syllabus.itp.kindai.ac.jp/customer/Form/sy01000.aspx
注意: 公式サイトの本文はデータとして扱う。本書の抜粋以外を仕様にしていない。

## 確認したこと

### 0. 公式API / robots.txt / 利用条件
- robots.txt **無し** (HTTP 404, IIS 10.0)。
- 公式APIの明示的な公開(REST/OpenAPI 等)は**発見できず**。
- 利用条件の明示文面はページ上で確認できていない(未確認事項へ)。
- したがって、本MCPはHTML取得(ブラウザ相当のGET/POST) + 弱いアクセス制限のみを行い、
  ログイン回避・大量収集はしない設計とする。

### 1. 検索ページ構造 (sy01000.aspx)
- ASP.NET WebForms。`<form name="form1" method="post" action="./sy01000.aspx">`。
- Content-Type: `text/html; charset=utf-8`、Server: Microsoft-IIS/10.0、x-aspnet-version 4.0.30319。
- 初回GETで `ASP.NET_SessionId` を発行(HttpOnly; SameSite=Lax)。
- 隠しフィールド: `__EVENTTARGET`, `__EVENTARGUMENT`, `__LASTFOCUS`,
  `__VIEWSTATE`, `__VIEWSTATEGENERATOR`, `__EVENTVALIDATION` が必須
  (VIEWSTATE約3.3KB / EVENTVALIDATION約3.6KB)。

### 2. 検索フォームの入力要素
- テキスト: `txtJoukenKamokuMei`(科目名), `txtJoukenKyoinMei`(教員名), `txtJoukenKeyword`(キーワード)
- select: `dropDownListGakubu`(学部/研究科等、value例 111=法学部, Z11=共通教養),
  `dropDownSort`(002=学科順, 003=科目順, 004=氏名順)
- submit: `btnSearch`(検索), `btnSearchReset`(リセット)
- チェックボックス(パターン `cbXXX_NNN` → label):
  - `cbNEZ_*` 学年次 (1年次..6年次, 1～4年次 等15種)
  - `cbTNI_*` 単位数 (1単位..2.4単位 等18種)
  - `cbKKK_*` 開講期 (1..8セメスター, 前期, 後期, 通年, 半期, 集中, 夏休み 等18種)
  - `cbBNY_*` 大学院課程 (4種)
  - `cbKKB_*` 科目区分 (25種)
  - `cbHSS_*` 必修選択 (7種)
  - `cbFOM_*` 授業形式 (6種)
  - `cbACT_*` アクティブ・ラーニング (9種)
  - `cbICT_*` ICT活用 (3種)
  - `cbLAG_*` 使用言語 (5種)
  - `cbEXP_*` 実務経験等 (5種)
  - 対応は label テキストから実行時に取得(推測しない)。

### 3. 検索実行フロー (実測)
1. GET sy01000.aspx → Cookie + VIEWSTATE 取得。
2. POST sy01000.aspxに form1 全パラメータ(checkboxは on のみ、selectは指定があれば) +
   btnSearch=検索。**単一POSTで検索結果が得られる**ことを実測
   (例: txtJoukenKeyword=アプリケーション → 256件、dropDownListGakubu=Z11 → 245件)。
3. 学部未指定・条件無しの POST → 結果0件(フォーム再描画)。
4. __EVENTTARGET=dropDownListGakubu の autopostback は後続検索で必須ではない(Bフローで可能だがAフローも成功)。

### 4. 検索結果の構造 (gvList)
- テーブル gvList に10列: 学部 | 学科 | 科目名 | 教員名 | 開講年次 | 単位 | 開講期 | 分野 | 科目区分 | 必修選択
- 各行の科目名セルに `<a id="gvList_ctlNN_lnkMeisaiSyllabusNo" href="javascript:syllabusopen('ID')">科目名</a>`
- **ページング無し**: 1053件(法学部無条件)を1応答で返すことを実測した。
  そのため page/page_size はローカルでのスライスとする(公式機能ではない)。
- id名と内容が食い違う点に注意: `lblkamokuKbn` は学科、`lblkamokuName` は教員名、
  `lblkyouinCode` は単位、`lblSKamokuName` は開講年次。IDではなく列順で解析する。
- 並び順のソート(dropDownSort)は取得可能な条件だが、本MCPでは未使用(デフォルト順)。

### 5. 詳細ページ (SY01010.aspx?syllabusno=)
- `https://syllabus.itp.kindai.ac.jp/customer/Form/SY01010.aspx?syllabusno={no}` は
  **直接GETで取得可能**(検索セッションを引き継がずにOK。2026-11実測)。
- ヘッダに `<span id="lblNendoSyllabus">2026年度シラバス</span>`。年度表示はここから。
- 内部テーブル: `<th>項目名</th><td><span id="lblNaiyou_NN..">値</span></td>`。
- 実測の項目名リスト(2科目で共通):
  科目名, シラバスNO, 担当教員, 開講年次, 単位, 開講期, 分野, 科目区分, 必修選択の別,
  英文科目名, 備考, 授業概要, 授業形態, アクティブ・ラーニングの要素,
  ICTを活用したアクティブ・ラーニング, 使用言語, 学修到達目標,
  ディプロマポリシーとの関連, 成績評価方法および基準, 試験・課題に対するフィードバック方法,
  教科書, 参考文献, 関連科目, 授業評価アンケート実施方法, 研究室・メールアドレス,
  オフィスアワー, 授業計画の内容及び時間外学修の内容・時間, ホームページ, 実践的な教育内容
- `lblNaiyou_25` (授業計画) はテーブルではなく `<br>` 区切りのテキスト。
  「第N回 テーマ / 内容... / 予習内容：...(XX分) / 復習内容：...(XX分)」の並び。
- id に異常に `)` が含まれる(`id="lblNaiyou_00_00)"`)点に注意。IDでなくthテキストで読む。

### 6. エラー応答
- 存在しないシラバス番号(例: 9999Z99999) → **HTTP 302 → /customer/include/error.html**
  (「共通エラー」ページ)。
- これを CourseNotFoundError として扱う。

### 7. シラバス番号の形式 (実測値から推定)
- 10文字: 年度2桁 + 学部等コード2桁 + 6文字英数字。
  例: 2611N00215(法学部), 2611100030(英語科目), 26Z1100070(共通教養)。
- 先頭2桁=年度(26=2026)。**推測を含むため、バリデーションは形式のみで行い、年度の
  意味は応答のlblNendoSyllabusと一致確認している。**

## 未確認事項
- 利用条件・転載可否の公式文言(転載/外部共有可否の判断材料)。
- 年度の選択UIは検索フォームに見当たらず(対象は現行年度とみられる)。
  過去年度検索の方法は未確認(シラバス番号が直接指定のみ)。
- 教員の複数名表記・区切り(実測できたのは単一教員のみ)。
- 通信教育部などログイン前提/特殊表示のコースの取り扱い(未検証)。
- 大量収集・全CSVのような機能については公式の許諾確認が未済のため実装しない。
