# Changelog

BioLog プロジェクトの全変更履歴です。
形式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に従います。

---
## [Unreleased]

### Changed
- `biolog_api/write_repository.py` のUPDATE系構造化ログを、既存の `mask_pii()` 経路へ統一した。現在の値はIDと固定フィールド名だけだが、将来ログ項目が増えた場合も同じマスキング境界を通る。

### Deployment
- この変更は開発拠点（C）のみにあり、実行拠点（D）と公開拠点（P）には未同期。3拠点一致とは扱わず、デプロイも本変更履歴更新では行わない。

---
## [1.7.9] — 2026-08-29

### Changed
- `docs/CODE_REFERENCE.md` / `docs/CODE_REFERENCE.html` の構成図を、日本語文字幅で
  崩れていたASCIIアートから、レスポンシブなCSS表示に置き換え

### Fixed
- `SHA256.md` / `SHA256.html` / `SHA256SUMS.txt` を現在のファイル構成を基準に全面再生成
  - 旧ファイル名（`docs/コード解説.md`、`TERMS_OF_SERVICE.md`、`LICENSE`、
    `BioLog起動.bat` 等の日本語 `.bat`）への参照が残っていたのを解消し、現行の正式名
    （`docs/CODE_REFERENCE.md` / `.html`、`TERMS_OF_USE.md`、`LICENSE.md`、
    `DISCLAIMER.md`、`THIRD_PARTY_LICENSES.md`、`start_biolog.bat` 等）に基づく一覧へ更新
  - 開発（C）/実行（D）/公開（P）の3拠点・対象92ファイルでハッシュを再計算し、
    3拠点へ反映（`.gitignore` の既存の相違はそのまま継続記載）

---
## [1.7.8] — 2026-08-24

### Fixed
- **読み取りキャッシュの version 機構が失われていた退行を修正**
  - v1.5.7（コミット `951c844`「fix: 新規登録後の stale 表示と form 状態残留を修正」）で
    導入された `data_version` が、v1.6.0（コミット `5411324`「Release v1.6.0 refactor and
    test baseline」）の非破壊分割の際に消えていた
  - CHANGELOG・コミットメッセージ・コードコメント・テストのいずれにも再廃止の意図は
    確認できず、v1.6.0 の記載はむしろ「cache clear / rerun のタイミングは維持」だった
    ため、意図的な廃止ではなく退行と判定した
  - 同じ v1.5.7 のコミットに含まれていた「新規登録フォームの状態残留」の修正も
    同時に失われており、そちらは v1.7.6 で先に復元済み
  - v1.5.7 の意図を現在の分割後コードへ復元：`cache.py` に `current_data_version()` /
    `bump_data_version()` を追加し、`fetch_latest` / `fetch_range_data` の cache key へ
    `version` を追加、`clear_health_caches()` で世代を進める
  - 既存の per-function `.clear()` と `ttl=10` は削除せず併用する。
    `.clear()` はプロセス全体の破棄、`data_version` はセッション単位の世代管理、
    `ttl=10` は反映前の値を取得した場合の滞留時間の上限で、役割が異なる
  - `data_version` の初期値は `int(time.time())`。0 起点はセッション跨ぎでキャッシュキーが
    衝突するため（v1.5.5 で旧 version 機構を廃止した原因）、v1.5.7 と同じ方式を維持する
  - 呼び出し側は `views/summary.py` と `views/graph.py` のみ変更。API・DB スキーマ・
    公開 API 形式・書き込み経路は変更なし

### Added
- `tests/test_streamlit_cache_version.py`（7 件）を追加
  - 初期 version が時刻由来で 0 でないこと、書き込みが無ければ据え置かれること、
    `clear_health_caches()` で 1 進むこと、cache key に `version` が含まれること、
    `summary.py` / `graph.py` が現在の version を渡していること、
    「更新」「新規登録」「修正」「削除」の 4 経路が invalidate を呼ぶこと、
    `.clear()` と TTL が併存していること
- `README.md` の用語解説に「ディスク / メモリ」を追加

### Changed
- `README.md` の `Cache Invalidation` 節を現行実装（`.clear()` / `data_version` / TTL の
  三層）と実際の履歴（v1.5.5 廃止 → v1.5.7 再導入 → v1.6.0 で退行 → v1.7.8 で復元）に合わせて修正
- `README.md` の `Known Issues / Limitations` の `Resolved` に今回の退行修正を追記
- `README.md` の用語解説「キャッシュ」の項を、現行の三層構成の説明へ更新
- `CLAUDE.md` の「BioLog 固有の不変条件」にキャッシュ version 機構を追加

### Note

**`ttl=10` の導入履歴（記録漏れの補足）**

- `@st.cache_data(ttl=10)` は、**2026-07-27 のコミット `f6d2da8`**
  「Update BioLog stability, security, and diagnostics」で導入されている
- 当時の CHANGELOG への記録が漏れていたため、ここで履歴として補足する
  （**v1.7.8 で新規に導入したものではない**）
- v1.6.0 時点の `cache.py` は `@st.cache_data`（TTL 指定なし）だった
- v1.7.8 現在も三層 Cache Invalidation の 1 つとして使用しており、
  役割は「反映前の値を掴んでしまった場合の滞留時間の上限」

**設計文書の追随（2026-08-24）**

- `docs/CODE_REFERENCE.md` を現行の三層 Cache Invalidation へ更新。
  旧ルール「`session_state` にバージョン番号を持たせる方式は禁止」を削除し、
  「version 機構を単独で使わず、`.clear()` と `ttl=10` を含む三層構成を維持する」へ改めた
- `biolog_streamlit/仕様書.md` は **v1.5.5 時点の履歴スナップショット**であるため本文は保存し、
  冒頭に現行仕様ではない旨と現行の三層構成を注記した（ルール 9 にも参照を追加）
- `biolog_streamlit/README.md` の `Cache Invalidation` 節と `Resolved` 項が
  現行コードと矛盾していたため、現行仕様へ追随した
- ドキュメントのみの変更のため、製品バージョンは上げていない

**ドキュメント構造の整理（2026-08-24）**

- **ルート `README.md` をプロジェクト全体の唯一の正本として明確化した**
- `biolog_streamlit/README.md` はルート README のほぼ全文複製（372 行）になっており、
  v1.7.6 / v1.7.7 / v1.7.8 の内容が追随していなかったため、
  **Streamlit フロントエンド固有の補助 README（57 行）へ整理**した。
  セットアップ・Docker 構成・Known Issues・用語解説・License 等はルート README への参照に置き換え、
  このディレクトリの責務（各ファイルの担当、`BIOLOG_API_URL`、`.streamlit/config.toml`）だけを残した
- `docs/CODE_REFERENCE.md` に残っていた旧パス（`biolog_streamlit/` 配下の `CLAUDE.md`）への参照 3 箇所を、
  現在の配置であるリポジトリ直下の `CLAUDE.md` へ修正した
- `CLAUDE.md` の「5.2 README.md」に、README 正本ルール
  （ルートが正本／サブディレクトリは固有の補足のみ／全文複製の並行維持を禁止）を追加した
- 製品コードは変更していないため、製品バージョンは上げていない

**旧 `CLAUDE.md` パス参照の完全解消（2026-08-24）**

- 履歴・アーカイブ文書に残っていた旧パス（`biolog_streamlit/` 配下の `CLAUDE.md`）への参照を修正した
  - `biolog_streamlit/Biolog_prompt.md`（3 箇所、C のみ・非公開のため D / P へは同期しない）
  - `biolog_streamlit/README.before-localhost-default-20260722.md`（2 箇所）
  - いずれも本文の当時の仕様・日付・履歴内容は変更せず、**参照パスだけ**を
    リポジトリ直下の `CLAUDE.md` へ直した。GitHub 非公開ファイルのため
    リンク切れになる Markdown リンクは作らず、コード表記にしている
- リポジトリ全体（`.git/` `__pycache__/` `.pytest_cache/` `data/` `data_backups/` を除く）を再検索し、
  旧パスへの参照が **0 件**であることを確認した
- `CLAUDE.md` に恒久ルールを追加：正本はリポジトリ直下のみで複製や参照を作らないこと、
  履歴文書を含め存在しない内部文書パスへの参照を残さないこと
- **追補**：C 側の解消後も開発（C）／実行（D）／公開（P）の 3 拠点を個別に再検索したところ、
  D と P の過去コピーに残存があったため、一回限りの例外として D / P を直接修正し、
  **3 拠点すべてで旧 `CLAUDE.md` パスへの参照を 0 件にした**
  - D / P の `biolog_streamlit/Biolog_prompt.md`（各 3 箇所）— C と同じ参照修正のみを適用。
    修正後は 3 拠点でハッシュが一致し、本文に差がないことを確認済み。
    この清掃を理由に `*prompt.md` を通常の同期対象へ変更してはいけない
  - P にのみ存在する `plans/git-publish-recovery-runbook.md`（1 箇所）—
    `git check-ignore` の確認コマンド例の引数を、現在の配置であるリポジトリ直下の
    `CLAUDE.md` へ修正。C / D との一致対象にはしない
  - 検索は `.gitignore` 対象を含め、`.git/` `__pycache__/` `.pytest_cache/` `data/`
    `data_backups/` のみ除外して実施
- 製品コードは変更していない

## [1.7.7] — 2026-08-24

### Added
- **`README.md` に「用語解説」セクションを追加**
  - README 本文に登場する専門用語を、Web 開発やプログラミングを専門としない読者でも
    README 単体で理解できるよう解説した
  - 8 カテゴリー・101 見出し構成
    （BioLog・アプリ構成 / Web・API・ネットワーク / Python・Streamlit /
    データベース・SQLite / Docker・実行環境 / データ・日時・ファイル形式 /
    セキュリティ / 開発・運用）
  - 各項目に「一般的な意味」と「BioLog では何に使っているか」を併記し、
    `Docker` と `Docker Compose`、`INSERT` / `UPDATE` / `UPSERT`、`UTC` と `JST`、
    `frontend` と `backend` のように混同しやすい用語は対比して説明した
  - `Queue` / `Worker` / 単一 Writer モデル / `UPSERT` / `request_id` と冪等性など、
    BioLog 固有の設計については実コードで挙動を確認したうえで記述した
  - 配置は `ドキュメント` 節と `License` 節の間

### Note
- ドキュメントのみの変更であり、製品コード・テスト・DB スキーマ・公開 API 形式は
  一切変更していない
- README 本文（機能説明・手順・仕様記述・Known Issues 等）も変更していない

## [1.7.6] — 2026-08-23

### Fixed
- **新規登録フォームの状態リセット**
  - 新規登録成功後に前回の入力内容がフォームへ残る問題を修正
  - 測定値だけでなく、ユーザー、日付、メモ、食事ログ、行動ログもリセット対象
  - リセットは登録成功時のみ。入力エラー・API エラー時は入力値を維持する
  - v1.5.7 で `clear_on_submit=True` により修正されていた挙動が、ビュー分割後のコードで
    退行していたもの。`clear_on_submit` は submit のたびに入力が消えるため再採用せず、
    削除タブの `clear_del_id` と同じ deferred-clear 方式で実装した
  - 実装：全ウィジェットへ明示的な Session State キーを付与し、登録成功時のみ
    `clear_create_form` を設定する。次 run のウィジェット生成前に
    `reset_create_form_state()` が該当キーを削除する
- **UPSERT 時の返却 ID**
  - 同一ユーザー・同一日付への再登録で、実在するレコード ID ではなく `id=0` が返る問題を修正
  - SQLite の `ON CONFLICT ... DO UPDATE` が UPDATE 経路に入ると INSERT が発生せず、
    書き込みごとに接続を作り直す本構成では `cursor.lastrowid` が 0 のままになる
  - UPSERT 後に `user_id` + `date` から実際のレコード ID を取得して返すよう変更
  - INSERT、UPSERT、`request_id` 重複のすべてで実在する正しい ID を返す
  - 同一ユーザー・同一日付の UPSERT 仕様、`request_id` UNIQUE による冪等性、
    同日ログの追記・重複排除、公開 API 形式、DB スキーマはいずれも変更なし

### Added
- 回帰テストを追加（147 件 → 160 件）
  - `tests/test_api_write_ids.py`：INSERT 時／同日 UPSERT 時／連続 UPSERT 時／
    `request_id` 重複時／worker 経由の返却 ID
  - `tests/test_streamlit_crud_flows.py`：実際の `render_create()` / `render_edit()` を
    Streamlit の AppTest で駆動し、登録成功後のリセット、入力エラー・API エラー時の入力保持、
    ユーザー切替時の日付選択、選択中レコード削除後の日付選択、
    日付往復後の PUT 対象 ID と送信内容の一致を検証
  - `tests/test_streamlit_form_state.py`：Session State キー定義のドリフト検知と
    `reset_create_form_state()` の単体テストを追加
- プロジェクト運用ルールをリポジトリ直下の `CLAUDE.md` として追加
  - 3 拠点（開発 C / 実行 D / 公開 P）の同期手順、モデル分担、不変条件、
    ドキュメント・ハッシュの更新順序を記載
  - 既存 `.gitignore` の `CLAUDE.md` パターンにより GitHub へは公開しない

### Note
- `time_utils` は `biolog_api` と `biolog_streamlit` の両方に同名モジュールが存在し、
  `tests/conftest.py` の `sys.path` 順では API 側が先に解決される。今回追加した
  Streamlit のフローテストは `tests/test_created_at_timezone.py` と同じフィクスチャ方式で
  `sys.modules` / `sys.path` を退避・復元する。製品コード側の構成は変更していない

## [1.7.5] — 2026-08-15

### Changed
- 登録API（`POST /api/health/record`）で、整数項目（脈拍、基礎代謝、収縮期血圧、
  拡張期血圧）に数値として解釈できない値が指定された場合、その項目を`null`として
  破棄せず、リクエスト全体を422で拒否するよう変更
  - 従来は不正な値が無かったことにされ、同じリクエスト内の他の項目だけが
    保存されていたため、送信側が入力ミスに気付けなかった
  - 不正な項目名をすべて列挙して返す（例: `Invalid number format: pulse, bmr`）
  - エラーログには項目名と例外型のみを記録し、値は出力しない
  - `72.9`→`72`、`"1400.0"`→`1400`のfloat→int補正、`null`の維持、血圧文字列
    （`"120/80"`、`"120－80mmHg"`等）の分解、`request_id`・`date`の欠損補完は変更なし
  - Streamlitの新規登録画面は送信前に`payloads.py`で数値化と範囲検証を行うため、
    画面操作による通常利用への影響はない
  - `spec.md`の「範囲外の値や、数字として解釈できない値は登録できません」という
    記述に実装を一致させる変更でもある

### Fixed
- 整数項目に`"inf"`、`"-inf"`、`"Infinity"`、`"1e309"`のような値が指定された場合に
  500が返る問題を修正し、422で拒否するよう変更
  - これらは`float()`までは成功し、`int()`で`OverflowError`になる
  - `OverflowError`は`ValueError`の派生ではないため、従来の
    `except (ValueError, TypeError)`から漏れてAPI層まで到達していた
  - Pythonの`json.loads`は`Infinity`・`NaN`リテラルを受理するため、
    JSONボディ経由でも到達しうる経路だった
  - `"nan"`は`int()`で`ValueError`になるため従来も422だったが、あわせて固定

### Added
- 上記のリグレッションテストを追加
  - `preprocess`層: 整数4項目 × 不正値14種（`float()`失敗、`OverflowError`、
    `NaN`）の拒否、複数項目が不正な場合に全項目名が列挙されること、
    float→int補正と`null`維持が変わらないこと
  - エンドポイント層: `"abc"`・`"inf"`・`"1e309"`で422が返りdetailに項目名が
    含まれること、正常なfloat値がQueueまで整数で到達すること

## [1.7.4] — 2026-08-13

### Changed
- 数値入力欄の視認性を改善
  - Streamlit標準の「Press Enter to submit form」案内が入力欄へ重なって
    入力値が読めなくなる問題を解消し、案内を数値入力欄でのみ非表示へ変更
    （メモ・食事ログ・行動ログのテキスト入力では従来どおり表示）
  - 入力値を通常時・フォーカス時とも明るい文字色と等幅数字で表示し、
    プレースホルダーは入力値より暗くして区別
  - 対象は修正・削除画面の体重、体温、収縮期血圧、拡張期血圧、脈拍、体脂肪率、
    基礎代謝、筋肉量、削除するレコードID、および一覧のページ番号
  - 表示のみの変更であり、入力操作、＋／－ボタン、Tab移動、Enterによる
    フォーム送信、登録・更新・削除処理、バリデーションは変更なし

### Added
- 数値入力欄のスタイルを1箇所へ集約する`biolog_streamlit/ui_style.py`を追加
  - 定数スタイルのみを`st.html()`で注入し、値の埋め込みは行わない
- `st.html`の使用箇所を`ui_style.py`に限定する回帰テストと、
  スタイル注入がアプリ入口から1回だけ行われることを確認する回帰テストを追加

## [1.7.3] — 2026-08-13

### Added
- BioLog起動、BioLog再ビルド起動、BioLog停止のバッチファイルを追加

## [1.7.2] — 2026-08-01

### Changed
- 一覧と削除確認の表を、PyArrowを使うStreamlitテーブルから、値をHTML
  エスケープする共通HTMLレンダラーへ変更
  - 一覧の約10秒ごとの自動更新、ページ送り、CSV、長文の全文表示は維持
  - 対話的な列ソートとセル選択は使用不可

### Fixed
- StreamlitプロセスがPyArrowのPandas変換中にSIGSEGV（終了コード139）で
  異常終了し、ブラウザに`Cannot load Streamlit frontend code`が表示される問題を回避
- phase 7aのコンテナTZ統一後に作成したレコードの記録日時が、一覧・CSV・
  削除確認で実際より9時間先に表示される問題を修正
  - `id <= 146`は従来どおりUTCからJSTへ変換し、`id >= 147`は保存済みJSTを維持
  - 修正前に出力したCSVとは、`id >= 147`の記録日時が9時間異なる

### Diagnostics
- `PYTHONFAULTHANDLER=1`を恒久的に有効化し、ネイティブクラッシュ時の
  Pythonスタックをコンテナログへ記録
- 修正後も7日間は再起動・`die`イベント・画面初期化回数を監視する
  - 再発ゼロは症状消失の確認であり、根本原因の確定とは扱わない

## [1.7.1] — 2026-07-27

### Fixed
- `requirements-test.txt`からAPI・Streamlit両サービスの依存関係を導入する際に
  発生していた`packaging`のバージョン競合を解消
- 両サービスの`constraints.txt`に同一パッケージの異なるバージョンが
  固定された場合に検出する回帰テストを追加

## [1.7.0] — 2026-07-27

長時間運用時の可用性、書き込み経路の耐障害性、一覧・CSVの正確性、
API入力境界、Docker運用およびプライバシー保護を強化したリリース。

### Added
- Workerスレッド、DB読取疎通、Queue使用量を確認するAPI healthcheckを追加
- API・Streamlit両コンテナにDocker healthcheckを追加
  - Composeの`unhealthy`は状態可視化用であり、自動再起動機構ではない
- Network issue再発時にDocker再起動前の証拠を採取する
  `NETWORK_ISSUE_DIAGNOSTICS.md`を追加
- Worker耐障害性、healthcheck、一覧フィルター、SQLite読取リトライ、
  API境界の回帰テストを追加
- API・Streamlitの推移依存バージョンを固定する`constraints.txt`を追加
- DB、env、キャッシュ、内部バックアップ等をDocker build contextから除外する
  `.dockerignore`を追加

### Changed
- 同日の食事ログと行動ログを全置換せず、完全一致する項目の重複を避けて改行追記するよう変更（メモとPUT編集は従来どおり置換）
- 健康記録の登録条件を緩和し、計測値がなくても食事ログ・行動ログ・メモのいずれかがあれば登録可能に変更
- 作成APIで`memo: null`を受理し、保存時は従来どおり空文字として扱うよう変更
- 一覧を選択ユーザー・指定期間のデータだけに限定
  - 20件単位のページ表示は維持
  - CSVは現在ページではなく、選択ユーザー・指定期間の全件を出力
  - ユーザー未選択時に全件表示へフォールバックしない
- SQLiteの`journal_mode=DELETE`を維持したまま、有限の接続待機と短い読取リトライを追加
- APIの`limit`を1～500、`offset`を0～10000に制限
- 日付形式、実在日、期間の前後関係、JSONオブジェクト、文字列長の検証を強化
- コンテナのタイムゾーンを`Asia/Tokyo`へ統一
- API・StreamlitをUID/GID 10001の非rootユーザーで実行
- Streamlitの利用統計送信を無効化

### Fixed

- 作成・編集フォームで`session_state`と`value`を二重指定して表示されるStreamlit警告を解消
- 編集フォームでAPI更新後も固定ウィジェットキーの古い測定値が表示される問題を修正
- 存在しないレコードの更新・削除等で単一Writerスレッドが恒久停止する問題を修正
- Workerが応答しない場合に`queue.Empty`が未捕捉500になる問題を修正し、
  明示的な503応答へ変更
- Workerのレコード不在を404、入力不正を422として安全に返すよう修正
- 複数ユーザー選択時に選択外ユーザーの健康データが一覧・CSVへ混入する問題を修正
- 一覧のCSVファイル名と実際の対象期間・内容が一致しない問題を修正
- `limit=-1`でSQLiteの件数上限を回避できる問題を修正
- 不正JSONやJSON配列で未処理エラーになる問題を修正
- `views/graph.py`に残っていたデバッグ出力を削除

### Security
- CSV内の`=`, `+`, `-`, `@`で始まる文字列を無害化し、
  表計算ソフトでの数式実行を防止
- 両コンテナのLinux capabilityをすべて削除
- API health応答からDB絶対パスを削除
- Workerの例外ログとレスポンスを固定文言・例外種別へ変更し、
  入力値や内部パスの露出を抑制

### Known Issues
- Streamlitの`Cannot load Streamlit frontend code`が長時間運用や日跨ぎ後に
  表示される問題の根本原因は未確定
  - `st.fragment`、`st.tabs`、Streamlitバージョンは推測で変更していない
  - 再発時は`NETWORK_ISSUE_DIAGNOSTICS.md`に従い、
    Docker再起動前にブラウザ・HTTP・コンテナ・スリープ復帰情報を採取する
- Docker DesktopのWindowsバインドマウントでは`/data`がLinux側で
  `root:root`かつ広い権限に見える。ホスト側のNTFS権限で保護する
- `records/range`は現時点で件数上限を持たず、データ増加時は取得負荷が線形に増える

## [1.6.0] — 2026-06-25

リファクタリング、テスト基盤追加、表示順整理のリリース。

### Added
- **pytest 最小テスト基盤を追加**
  - `requirements-test.txt` を追加し、テスト依存を本番 requirements から分離
  - `tests/` 配下に Streamlit payload / form field / formatter、API preprocess / schemas、write repository / biocore の回帰テストを追加
  - テスト用 DB は `tmp_path` 配下の一時 SQLite を使用し、`data/biolog.db` を指した場合は失敗する安全策を追加

### Changed
- **Streamlit アプリを非破壊分割**
  - 既存起動入口 `biolog_streamlit/streamlit_app.py` は薄いエントリポイントとして維持
  - API client、cache、formatter、chart、form field、payload、各 view を分離
  - UI 文言、API URL、payload 形式、cache clear / rerun のタイミングは維持
- **新規登録 / 修正フォームの重複を整理**
  - 測定項目定義を `form_fields.py` に集約
  - Streamlit 描画を `form_components.py`、payload 作成を `payloads.py` に分離
  - create/update payload の `None` / 空文字 / `0` / `0.0` / date / request_id の扱いは従来互換
- **API 書き込み SQL を `write_repository.py` に分離**
  - `worker.py` は Queue / retry / logging / operation dispatch に集中
  - `get_connection(write=True)`、transaction、commit/rollback、retry、HTTP response は変更なし
  - `biocore.py` の SELECT カラム定義と row-to-dict helper を共通化（`SELECT *` の互換箇所は維持）
- **ホーム / フォーム / グラフの表示順を整理**
  - ホーム metric: 体重 → 体温 → 収縮期血圧 → 拡張期血圧 → 脈拍
  - 新規登録 / 修正フォーム: 左側に 体重・体温・収縮期血圧・拡張期血圧、右側に 脈拍・体脂肪率・基礎代謝・筋肉量
  - グラフ: 体重 → 体温 → 血圧 → 脈拍

### 残タスク（監査由来）
- M1: `schemas.py` の `date` に `YYYY-MM-DD` 形式バリデータ追加
- M2: `api.py` の `result_q.get(timeout=30)` で `queue.Empty` を捕捉して 504 Gateway Timeout を返却
- L1: `biocore.py:110` の `SELECT *` を明示列指定に置換
- 既知の運用課題: `migration_lock` 残存時の手動 `DELETE FROM migration_lock WHERE id = 1`

---

## [1.5.7] — 2026-05-29

### Fixed
- **新規登録後にサマリーカード / グラフ / 一覧に前日データが残る不具合**
  - 原因：`fetch_*.clear()` 方式では Eventual Consistency ラグ等で stale な fetch がキャッシュされる場合があった
  - 対応：`@st.cache_data` の cache key に `version: int` 引数を追加し、書き込み成功時に `st.session_state.data_version += 1` で明示 invalidate する方式に変更
- **新規登録フォームに前回入力値が残る不具合**
  - `with st.form("create_form")` に `clear_on_submit=True` を追加し、submit 後に全フィールドを自動リセット

### Changed
- `fetch_latest(uid)` → `fetch_latest(uid, version)`、`fetch_range_data(start, end)` → `fetch_range_data(start, end, version)`
- 全 4 箇所（「更新」ボタン / 新規登録 / 編集 / 削除）の `fetch_latest.clear()` / `fetch_range_data.clear()` を `st.session_state.data_version += 1` に置換
- `session_state.data_version` の初期値を **`int(time.time())`** にし、v1.5.5 で fix した「翌日跨ぎ cache 衝突」問題が再発しないように保証
- 新規登録成功時のメッセージを「登録を受け付けました（反映には数秒かかる場合があります）」から「**登録しました。最新データを更新しています。**」に変更（version 機構で即時反映されるため）

### Note
- v1.5.5 で廃止した version 引数方式を再導入する形になるが、初期値を `int(time.time())` にすることで「新セッションで `version=0` リセット → 過去 cache `(uid, 0)` に衝突」という v1.5.5 当時の問題は構造的に発生しない

---

## [1.5.6] — 2026-05-26

### Fixed
- **公開準備：API リファレンス（`biolog_api/skills.md`）に `meal_detail` / `activity_log` の記述漏れを補完**
  - DB スキーマ表、リクエストフィールド表、レスポンス例、返却辞書キー、curl 例の各箇所に追記
  - コード（worker.py / biocore.py / schemas.py / migrate_001 / Streamlit UI）側は対応済みだったが、ドキュメント側のみ追従漏れだった

### Changed
- `README.md` / `biolog_streamlit/README.md` の冒頭サマリーに「食事ログ」を追加（行動ログのみ言及だったのを修正）

### Removed
- StreamlitAPIException 再発防止のため、`session_state["del_id"]` 直接代入を deferred-clear パターンに変更（既に v1.5.5 で実装、本エントリで明文化）

---

## [1.5.5] — 2026-05-25

### Fixed
- **キャッシュのセッション跨ぎ staleness を構造的に解消**
  - 症状：登録 → 更新後、新しいブラウザセッションでトップ画面が古い値に戻る
  - 原因：`@st.cache_data` がプロセス global、`session_state.latest_version` が新セッションで `0` にリセットされて過去キャッシュキーに衝突
  - 修正：version 機構を完全廃止し、書き込み成功時に `fetch_latest.clear()` / `fetch_range_data.clear()` で per-function invalidate

### Changed
- `fetch_latest(uid)` / `fetch_range_data(start, end)` から `version` 引数を削除
- `st.session_state.range_version` / `latest_version` を完全削除
- サマリーカード・グラフ・一覧の呼び出し側から `version` 引数を削除
- 「更新」ボタン・新規登録成功・編集成功・削除成功の各箇所で `+= 1` を `fetch_latest.clear()` + `fetch_range_data.clear()` に置換
- 削除タブの cache invalidation 欠落も同時解消

---

## [1.5.4] — 2026-05-25

### Added
- **H4: API ログの PII マスク（軽量実装）**
  - `biolog_api/log_utils.py` を新規作成
  - `mask_pii(text)` 関数：6 種の regex で `user_id` / `request_id` / email / UUID をマスク
  - JSON 形式（`"user_id": "self"`）と key=value 形式（`user_id=self`）の両方に対応
  - UUID は 8-4-4-4-12 形式 + 32 文字 hex（ハイフン無し圧縮形）も対象

### Changed
- `api.py` POST 内 local `log()` の print 行に `mask_pii(json.dumps(...))` を適用
- `worker.py` `_log()` の print 行に `mask_pii(json.dumps(...))` を適用
- 健康数値（temperature / weight 等）はマスク対象外（読み続けられる）

---

## [1.5.3] — 2026-05-25

### Added
- **H3: migration runner の Docker 起動時自動実行化**
  - `biolog_api/entrypoint.sh` を新規作成
  - `set -e` + `python migrations/runner.py` → `exec uvicorn api:app` の直列実行
  - フェーズログ（`[entrypoint] running migrations...` / `[entrypoint] migrations complete, starting API...`）
  - migration 失敗時は exit 1 で API 起動を阻止

### Changed
- `biolog_api/Dockerfile` を `CMD ["uvicorn", ...]` から `ENTRYPOINT ["./entrypoint.sh"]` に変更
- `RUN chmod +x entrypoint.sh` を追加（Windows file system 由来の executable bit 喪失対策）

### Known Limitation
- runner.py の lock 競合時 exit 0 仕様は維持（S1 採用）。stale lock 残存時は schema 未整備のまま API が起動する可能性あり。手動 `DELETE FROM migration_lock WHERE id = 1` で復旧

---

## [1.5.2] — 2026-05-25

### Added
- **H2: `migrate_001_init.py` に `CREATE TABLE IF NOT EXISTS health_records` を追加**
  - 16 カラム + `request_id` UNIQUE + `created_at` DEFAULT `datetime('now','localtime')`
  - 新規環境（DB ファイル未作成）でもテーブルが自動生成されて API 起動可能に
  - 既存 ALTER TABLE 群（`ADD COLUMN request_id` / `meal_detail` / `activity_log`）は **環境差吸収のため併存維持**
  - CREATE と ALTER は冗長ではなく「二重互換構造」として削除・統合禁止
- CHECK 制約は省略（既存 DB との不整合を最小化、互換最優先）

---

## [1.5.1] — 2026-05-25

### Fixed
- **H1: Streamlit 起動ブロッカー修正（最優先）**
  - `streamlit_app.py:76-78` に存在した orphan な `except Exception` ブロックを削除
  - 前回の truncate 関数追加時に旧 `api_get()` の generic except 節が切り離されて残存していた
  - `SyntaxError: invalid syntax` で Streamlit アプリ起動不可だった状態を解消

---

## [1.5.0] — 2026-05-25

### Added
- **date 補完の JST 統一（深夜帯ズレ修正）**
  - `biolog_api/time_utils.py` を新規作成
    - `JST = timezone(timedelta(hours=9))`
    - `now_jst()` / `to_jst(dt)` / `jst_date()`
  - Docker コンテナの TZ が UTC でも JST 基準で date を確定

### Fixed
- `preprocess.py` の date 補完を `datetime.date.today().isoformat()` → `jst_date()` に変更
  - 深夜 0:00〜9:00（JST）に date 省略で POST すると前日扱いになる不具合を修正
- `streamlit_app.py` の新規登録フォーム日付初期値を `date.today()` → `datetime.now(JST).date()` に統一

### Note
- 本変更は WORKDIR=/app でのフラット import 構成を前提（`from time_utils import jst_date`）

---

## [1.4.5] — 2026-05-25

### Changed
- **一覧タブの長文セルを列別 truncate + expander 詳細展開に変更**
  - `_LIMITS` 列別上限（メモ 40 / 食事ログ 80 / 行動ログ 200）を導入
  - `_safe_str()` / `truncate()` / `is_truncated()` ヘルパー関数を追加
  - `st.dataframe` 直下に行別 expander 一覧を表示（`_LIMITS` を超えるセルのみ）
  - expander ラベル：`対象日 / ユーザー / 列名` で識別容易
  - full データは `disp.at[idx, col]` ベースの真実データ参照に統一
  - CSV ダウンロードは従来通り全文（変更なし）

---

## [1.4.4] — 2026-05-08

### Changed
- 一覧タブの `created_at` 表示を `time_utils.to_jst()` ベースへ統一
  （JST 表示責務を UI 側ではなく `time_utils` に集約）
- priority 列に 基礎代謝(kcal)・体脂肪率(%)・筋肉量(kg) を追加

---

## [1.4.3] — 2026-05-08

### Changed
- 一覧タブの列名を日本語化（体重(kg)・体温(℃)・収縮期血圧・記録日時 など）
- 表示列順を整理（ID・ユーザー・記録日時を左固定、健康指標を優先表示）
- `created_at` を一覧表示に追加し `YYYY-MM-DD HH:MM` 形式にフォーマット
- CSV ダウンロードも日本語列名・並び替え済みで出力

---

## [1.4.2] — 2026-05-07

### Changed
- 修正フォームの選択方式を ID 手入力から「ユーザー選択 → 日付 selectbox」に変更
  - 登録済み日付のみ選択肢に表示（`GET /api/health/records` から日付一覧を取得）
  - `GET /api/health/record/day` で既存値を取得してフォーム全フィールドにプリフィル
  - 更新 URL を `edit_id` から取得レコードの `id` フィールドに変更

---

## [1.4.1] — 2026-05-07

### Added
- `GET /api/health/record/day?user_id=self&date=2026-05-07` エンドポイントを追加
  - `user_id` + `date` でレコードを1件取得（編集用途）
  - 存在しない場合は 404 を返す
  - `biocore.get_record_by_user_date()` を新規追加（`SELECT *` で将来カラム追加に追従）

---

## [1.4.0] — 2026-05-07

### Added
- `biolog_streamlit/time_utils.py` を新規作成（UTC→JST 変換ユーティリティ）
  - `to_jst(dt)` 関数: `str` / `datetime` の両方を受け付け、スペース区切りも対応
  - 削除プレビューの `created_at` を JST（Asia/Tokyo）に変換して表示

### Fixed
- 修正・削除タブで memo フィールドが更新されないバグを修正
  - `api.py`: `exclude_none=True` → `exclude_unset=True`（UI が明示的に送ったフィールドのみ payload 化）
  - `worker.py`: UPDATE に型チェック付きホワイトリスト `ALLOWED_FIELDS` を導入。`None` はスキップ、`memo` は `"" ` も上書き対象
  - `streamlit_app.py`: `if edit_memo:` を `body["memo"] = edit_memo or ""` に変更し、常に memo を送信
  - 修正フォームの memo 欄に現在値をプリフィル
  - 更新成功後に `st.rerun()` + version++ を追加
- `api.py` lifespan の重複削除 + UNIQUE INDEX 挿入順序を整理
  - DROP 旧 INDEX → DELETE 重複行（MAX(id) 残し）→ CREATE UNIQUE INDEX の順序に統一
  - `(user_id, date)` 重複がある状態でも起動時に UNIQUE INDEX 作成が成功するよう保証

### Changed
- サマリーカードの表示順を変更（体重→体温→脈拍→収縮期血圧→拡張期血圧）
- グラフタブの表示順をサマリーカードと統一（体重→体温→脈拍→血圧）

---

## [1.3.9] — 2026-05-06

### Added
- タブ2「一覧」に CSV ダウンロードボタンを追加
  - 現在表示中のデータを `biolog_{開始日}_{終了日}.csv` でダウンロード
  - Excel で日本語が文字化けしないよう UTF-8 BOM 付きで出力

---

## [1.3.8] — 2026-05-06

### Changed
- API 呼び出しに `@st.cache_data` を適用し Streamlit 再実行の副作用を抑制
  - `fetch_range_data(start, end, version)` / `fetch_latest(uid, version)` ラッパーを追加
  - `range_version` / `latest_version` を session_state で管理（version はキャッシュ無効化トリガー）
  - サイドバーに「更新」ボタンを追加（version++ で即時再取得）
  - 登録成功後も version++ してキャッシュを無効化
  - 登録成功メッセージを「登録を受け付けました（反映には数秒かかる場合があります）」に変更
  - 常時注記「データは非同期で反映されます」を追加

---

## [1.3.7] — 2026-05-06

### Fixed
- グラフが重複して表示される問題を修正
  - 原因: Streamlit の再描画でスクリプトが複数回実行され `st.pyplot()` が積み重なっていた
    （デバッグログで同じ描画ブロックが1回のロードで3回実行されることを確認）
  - 修正: `st.pyplot(fig, clear_figure=True)` に変更（Streamlit が figure を自動クリア）
  - データ処理・groupby・xticks は変更なし

---

## [1.3.6] — 2026-05-06

### Fixed
- X 軸ティック密集問題を解決（DayLocator → set_xticks に変更）
  - `DayLocator(interval=1)` はデータのない日にも毎日ティックを打つため廃止
  - `ax.set_xticks(sorted(df["date"].unique()))` でデータが実在する日付だけにティックを固定
  - `udf["date"].dt.date` 変換を削除し datetime64 のまま matplotlib に渡す
  - 対象: 血圧・体温・脈拍・体重の全グラフ

---

## [1.3.5] — 2026-05-06

### Changed
- データ集約責務を描画関数の外（DataFrame 読み込み直後）に集約
  - `df.sort_values("date").groupby(["user_id", "date"], as_index=False).last()` で
    全ユーザー・全メトリクスの「1日1点」を一括確立
  - `_plot_metric()` と血圧グラフから per-user groupby を削除（前集約済みのため不要）
  - `drop_duplicates` / `FuncFormatter(_jp_date)` の使用を廃止
  - `print("after_groupby:", len(df))` で集約後件数を確認可能

---

## [1.3.4] — 2026-05-06

### Fixed
- X 軸ラベル重複を DayLocator で強制排除
  - `udf["date"] = pd.to_datetime(udf["date"]).dt.date` で date 型にフラット化
  - `AutoDateLocator` → `DayLocator(interval=1)` に変更（1日=1ティック固定）
  - `st.pyplot` 直後に `"Labels fixed with DateFormatter"` デバッグログを追加
  - 対象: 血圧・体温・脈拍・体重の全グラフ

---

## [1.3.3] — 2026-05-06

### Fixed
- X 軸の日付ラベル重複問題を根本解決
  - `pd.to_datetime(df["date"]).dt.normalize()` で時刻成分を除去し、日付集約を確実に実行
  - `groupby("date").last().reset_index()` の順序を統一（dropna を後置）
  - `FuncFormatter(_jp_date)` → `mdates.DateFormatter("%m-%d")` に変更してラベル二重化を防止
  - `AutoDateLocator()` でデータ量に応じた自動間隔調整

---

## [1.3.2] — 2026-05-06

### Fixed
- X 軸の日付ラベルが重複して表示される問題を修正
  - `drop_duplicates` を `groupby("date").last()` に変更し、同日複数レコードを最新値1件に集約
  - `AutoDateLocator(minticks=3, maxticks=10)` を追加し、FuncFormatter 使用時のティック重複を防止
  - 対象: 血圧・体温・脈拍・体重の全グラフ

---

## [1.3.1] — 2026-05-06

### Fixed
- 同一日付のデータが複数回描画される問題を修正
  - 各グラフ描画前に `plt.clf()` を追加してキャンバスをクリア
  - `drop_duplicates(subset=['user_id', 'date', col])` で重複データを排除
  - デバッグログ（`print("DEBUG: ... data count = N")`）を追加（`docker logs -f biolog-streamlit` で確認可）

---

## [1.3.0] — 2026-05-06

### Changed
- 描画エンジンを Plotly から Matplotlib + Seaborn に移行
  - `st.pyplot()` による静止画像出力でモバイルのピンチズーム問題を根本解決
  - `japanize-matplotlib` で日本語フォントを自動適用（Dockerfile 変更不要）
  - X 軸日付を「2026年5月6日」形式の日本語表記に変更
  - `dark_background` スタイルで Streamlit ダークモードとデザインを統一
  - 血圧グラフに `axhline` で収縮期 120 / 拡張期 80 の参考線を維持

### Removed
- Plotly (`plotly==5.24.1`) を requirements.txt から削除
- v1.2.2〜v1.2.9 で実装した CSS シールド / JS ガードパネル / touch-action ハックを全削除
  （静止画像化により不要になったため）

---

## [1.2.9] — 2026-05-06

### Changed
- JS による動的透明ガードパネルを実装
  - `.stPlotlyChart` の上に `z-index: 99999` の透明 `<div>` を動的生成してグラフへのタッチを物理遮断
  - ガード自身は `touch-action: pan-y` を持ち縦スクロールは通す
  - `setInterval` で 1 秒ごとにスキャンし Streamlit の再描画後も自動適用

---

## [1.2.8] — 2026-05-06

### Fixed
- iOS/Android でグラフをピンチするとズームが発生する問題を根本解決
  - 原因: `pointer-events` / `::before` はコンポジタースレッドより上位レイヤーのみに作用し、
    ブラウザネイティブのピンチジェスチャーを止められていなかった

### Changed
- CSS を `touch-action: pan-x pan-y !important` に変更（コンポジタースレッドに直接ピンチ禁止を指示）
- JS `touchstart` / `touchmove` を `passive: false` で登録し、2本指タッチを `preventDefault()` でキャンセル
- MutationObserver により動的追加グラフにも自動適用
- 効果がなかった `::before` シールドと `position: relative` ルールを削除

---

## [1.2.7] — 2026-05-06

### Changed
- CSS 擬似要素（`::before`）による透明シールドをグラフ上に配置
  - 指が触れる先が Plotly ではなく透明な膜になり、あらゆるイベントを物理的に遮断
  - iOS (Safari/Chrome) および Android でのピンチズーム・誤タップを 100% 封鎖
  - 既存の `pointer-events: none !important` と `staticPlot: true` も継続

---

## [1.2.6] — 2026-05-06

### Changed
- グラフエリアに CSS `pointer-events: none` を適用し、iOS/Android のスクロール競合を完全解消
  - `.stPlotlyChart` コンテナを DOM レベルでタッチ・マウスイベント透過状態にする
  - iPhone (Safari/Chrome) および Android でグラフ上をスワイプしてもページスクロールが阻害されない
  - JS 側の `staticPlot` / `fixedrange` / `dragmode=False` との組み合わせで二重に封鎖

---

## [1.2.5] — 2026-05-06

### Changed
- Plotly グラフに `staticPlot: true` を追加し、JS インタラクションを根本から無効化
  - ドラッグ・ズーム・ホバー・クリック等の全イベントを物理的に封鎖
  - グラフは完全な静止画像として扱われる
  - 既存の `fixedrange=True` / `dragmode=False` / `doubleClick=False` は維持
  - 対象: 血圧・体温・脈拍・体重の全グラフ

---

## [1.2.4] — 2026-05-06

### Changed
- Plotly グラフを「見るだけのダッシュボード」として完全固定（v1.2.3 の強化版）
  - X・Y 軸を `fixedrange=True` で物理的に固定（軸ドラッグによるズーム不可）
  - ダブルクリックによるズームリセットを `doubleClick=False` で無効化
  - `dragmode="pan"` を `dragmode=False` に変更（ドラッグ操作を完全無効化）
  - 対象: 血圧・体温・脈拍・体重の全グラフ

---

## [1.2.3] — 2026-05-06

### Changed
- Plotly グラフの操作性改善（血圧・体温・脈拍・体重の全グラフに適用）
  - マウスホイールによる誤ズームを無効化（`scrollZoom: false`）— ホイールでページスクロール可能に
  - グラフ右上のモードバーを非表示（`displayModeBar: false`）
  - ドラッグ操作をズームからパン（移動）に変更（`dragmode: "pan"`）

---

## [1.2.2] — 2026-05-06

### Added
- サマリーカードをメイン画面最上部（グラフ・タブの上）に追加
  （自分・父・母の最新の収縮期/拡張期血圧・体温・脈拍を `st.metric` で3列横並び表示）
- データがないユーザーは「データなし」と優しく表示（`suppress_404=True` で 404 を事前吸収）
- グラフを `st.line_chart` から **Plotly** (`plotly.graph_objects`) に全面刷新
- ユーザー選択を `st.selectbox`（単一）から `st.multiselect`（複数可）に変更
  （デフォルト: 自分 / 選択しない場合は「選択してください」案内を表示）
- 選択した全ユーザーのデータを色分けして1グラフに重ね描き
  （自分: 青 `#1f77b4` / 父: 緑 `#2ca02c` / 母: 赤 `#d62728`）
- 血圧グラフに目標値の参考線を追加（収縮期 120 mmHg / 拡張期 80 mmHg — 点線）
- `_plot_metric()` ヘルパー関数を追加（体温・脈拍・体重グラフの共通描画ロジック）
- `biolog_streamlit/requirements.txt` に `plotly==5.24.1` を追加

### Changed
- グラフレイアウトを2列から縦1列に変更（複数ユーザー比較時の視認性向上）
- タブ2「一覧」: 単一ユーザー選択時のみ `user_id` フィルタを適用、複数または未選択は全員表示

---

## [1.2.1] — 2026-05-06

### Fixed
- `api.py` の lifespan 起動時、既存 DB に `(user_id, date)` 重複行がある場合に
  `CREATE UNIQUE INDEX` が失敗してコンテナが再起動ループに陥る `IntegrityError` を修正
- DDL 実行順序を「テーブル作成 → 重複クリーンアップ → インデックス作成」の3ステップに変更し、
  重複行を削除してからインデックスを作成することで確実に成功するようにした
- クリーンアップ件数を構造化ログ（`"event": "cleanup_duplicates"`）として標準出力に記録
  （重複がなければサイレント処理）

### Changed
- `api.py` の `_DDL` を `_DDL_TABLE` / `_CLEANUP_DUPLICATES` / `_DDL_INDEXES` の3定数に分割

---

## [1.2.0] — 2026-05-06

### Fixed
- **BUG-001**: 同一 `user_id` + `date` で複数回 POST すると重複行が増える問題を修正
- **BUG-002**: Streamlit の削除画面で存在しない ID を入力すると `404 Not Found` になる問題を修正
- **IMPROVEMENT-001**: 削除画面でレコード内容が確認できない問題を同時解消

### Added
- `worker.py` の INSERT を `ON CONFLICT(user_id, date) DO UPDATE SET` による UPSERT に変更
  （同一ユーザー・同一日付の再登録は上書き更新になる）
- `api.py` の DDL に `CREATE UNIQUE INDEX uidx_hr_user_date ON health_records(user_id, date)` を追加
- `biocore.py` に `get_record_by_id(record_id: int)` 関数を追加
- `api.py` に `GET /api/health/record/{record_id}` エンドポイントを追加
- Streamlit の削除タブにリアルタイムプレビュー表示を追加
  - ID 入力時に対象レコードの内容を `st.table()` で表示
  - 存在しない ID は「存在しません」警告を表示し、削除ボタン自体を非表示に
  - 削除成功後に `st.rerun()` でプレビューを自動クリア
- `streamlit_app.py` の `api_get()` に `suppress_404=True` オプションを追加
  （プレビュー取得時の 404 をエラー表示せず `None` で返す）

---

## [1.1.0] — 2026-05-05

### Added
- 初期リリース
- **アーキテクチャ**: `FastAPI → Queue → Worker(1スレッド) → db_manager → SQLite` の単一 Writer モデル
- **DB**: `health_records` テーブル新規作成（初期は他プロジェクトの SQLite ファイルに同居、後に独立 DB `biolog.db` へ移行）
- **対応ユーザー**: `self` / `father` / `mother`
- **計測項目**: 体温・脈拍・収縮期血圧・拡張期血圧・体重・体脂肪率・筋肉量・基礎代謝・メモ
- **Pydantic バリデーション**: 体温 34–42 ℃、脈拍 30–200 bpm、血圧上 50–250 / 下 30–150 mmHg
- **冪等性**: `request_id` UNIQUE 制約により重複リクエストを成功扱いで吸収
- **Worker リトライ**: `database is locked` のみ対象、指数バックオフ（最大5回）
- **Graceful Shutdown**: SIGTERM ハンドリング + Worker への `None` タスク送信
- **構造化ログ**: Worker の処理状況を JSON 形式で標準出力に記録
- **FastAPI エンドポイント**:
  - `GET  /api/health/health` — ヘルスチェック
  - `POST /api/health/record` — 登録（Queue 経由）
  - `PUT  /api/health/record/{id}` — 更新（Queue 経由）
  - `DELETE /api/health/record/{id}` — 削除（Queue 経由）
  - `GET  /api/health/records` — 一覧（直接 SELECT、ページング対応）
  - `GET  /api/health/records/range` — 日付範囲取得（グラフ用）
  - `GET  /api/health/records/latest/{user_id}` — 最新1件取得
- **Streamlit UI**: 4タブ構成（グラフ・一覧・新規登録・修正削除）
- **Docker Compose 統合**: `biolog-api`（ポート 8766）、`biolog-streamlit`（ポート 8501）
- **ドキュメント**: `biolog_api/skills.md`（API リファレンス・curl 集）、`CLAUDE.md`（設計ルール・既知バグ）
