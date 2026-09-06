# BioLog Mobile PWA v1 実装プラン

## Summary
- 既存の Streamlit/API/SQLite/Docker 版は一切変更せず、`biolog_pwa/` に完全独立の静的 PWA を追加する。
- 配布は GitHub Pages 前提。Android/iPhone はブラウザからアクセスして「ホーム画面に追加」する。
- v1 は 1人用で `user_id = "self"` 固定。データは端末内 IndexedDB に保存し、JSON export/import でバックアップする。
- グラフや同期は v2 以降に回し、v1 は入力・履歴・編集・削除・バックアップに集中する。

## Key Changes
- `biolog_pwa/` に vanilla HTML/CSS/JavaScript の静的アプリを追加する。
- GitHub Pages 対応のため、`manifest` / `service-worker` / CSS / JS / icons はすべて `./` 始まりの相対パスで参照し、`/xxx` の絶対パスは禁止する。
- Service worker 登録は `./service-worker.js` を使い、scope も `./` 前提にする。
- PWA 構成を追加する:
  - `index.html`
  - `styles.css`
  - `app.js`
  - `manifest.webmanifest`
  - `service-worker.js`
  - `icons/`
- `service-worker.js` は `CACHE_NAME` にバージョン番号を含め、`activate` 時に古い cache を削除する。
- IndexedDB に `health_records` store を作る。
- store の主キーは `id` とし、`autoIncrement` を使う。
- `request_id` は import/export と重複判定用の業務IDとして扱う。
- `request_id` index と `date_user` index を作る。
- `date_user` は `${user_id}::${date}` 形式で保存する。
- 保存時は `date_user` で既存レコードを探し、存在すれば更新、なければ追加する。
- 今日の日付は端末ローカルタイムで `YYYY-MM-DD` を生成する。`toISOString().slice(0,10)` は使わない。
- レコード項目は既存 BioLog 互換にする:
  - `id`, `request_id`, `date`, `date_user`, `user_id`
  - `temperature`, `pulse`, `systolic_bp`, `diastolic_bp`
  - `weight`, `body_fat`, `muscle_mass`, `bmr`
  - `meal_detail`, `activity_log`, `memo`
  - `created_at`, `updated_at`
- 入力項目順は既存 Streamlit に合わせる:
  - 体重、体温、収縮期血圧、拡張期血圧、脈拍、体脂肪率、基礎代謝、筋肉量、食事ログ、行動ログ、メモ
- validation は既存 API schema と同じ範囲にする。
- 新規保存時、空入力の数値項目は保存しない。`0` / `0.0` は値として保持する。
- 既存レコード編集時、空欄の項目は既存値を保持する。空欄による値削除 UI は v1 では作らない。
- 画面は次の 3 つにする:
  - 今日: 今日の日付の記録を入力/更新
  - 履歴: 日付降順一覧、編集、削除
  - バックアップ: JSON export/import、全削除
- Export JSON は `app`, `version`, `exported_at`, `records` を持つ形式にする。
- Export ファイル名は `biolog-mobile-backup-YYYY-MM-DD.json` にする。
- Import 時は `app` / `version` / `records` の存在を確認し、不正形式なら取り込まずエラー表示する。
- `records` が配列でない場合も取り込まない。
- Import は `date_user` 優先で upsert する。
- 全削除は `confirm` を出し、確認された場合のみ実行する。

## Test Plan
- ローカル静的サーバーで確認する:
  - `python -m http.server 8080 -d biolog_pwa`
- 手動確認:
  - Android Chrome でホーム画面追加できる
  - iPhone Safari でホーム画面追加できる
  - オフラインでも起動できる
  - 今日の入力、更新、履歴表示、編集、削除ができる
  - JSON export/import 後に同じデータが復元される
  - 不正 JSON import でデータが変更されずエラー表示される
  - 全削除は確認後のみ実行される
  - GitHub Pages のリポジトリ名付き URL でも CSS/JS/manifest/SW/icons が壊れない
- JavaScript の軽量テストを追加する:
  - validation 範囲
  - ローカル日付生成
  - 空入力を保存しない
  - `0` / `0.0` を保持する
  - 編集時の空欄は既存値を保持する
  - `date_user` upsert
  - export/import 形式
  - 不正 import の拒否
- 既存テストは維持する:
  - `python -m pytest -q`

## Assumptions
- v1 は 1人用で `user_id = "self"` 固定。
- App Store / Google Play 配布は対象外。
- ログイン、暗号化、通知、同期、グラフ、家族3人切り替え、PC版への自動取り込みは v2 以降。
- 端末紛失や機種変更への対策は v1 では JSON export/import で対応する。
