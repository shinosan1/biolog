# BioLog

> Personal & family health record tracker.
> Streamlit + FastAPI + SQLite, self-hosted, **localhost-only by default**.

![Top](docs/screenshots/01-top.png)

家族（自分・父・母など）の体温・血圧・脈拍・体重・体脂肪・食事ログ・行動ログを
日次で記録・可視化するための個人向けセルフホストアプリです。
SQLite ファイル 1 つで完結し、標準構成では外部サービスへ健康記録を送信しません。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE.md)
[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org)
[![Docker](https://img.shields.io/badge/docker-required-blue.svg)](https://www.docker.com)

---

## ⚠ Security Notice — Please Read First

標準ComposeはBiolog APIの`8766`とUIの`8501`を`127.0.0.1`だけに公開し、**同一PCからの利用**を前提としています。家族別の記録を管理できますが、家族の別端末からのLANアクセスは標準では有効になりません。
インターネット公開を想定していません。以下は **意図的に未実装** です：

- 認証（API キー / Basic 認証 / OAuth）**なし**
- ブラウザのクロスオリジンAPI利用（CORS許可なし）
- HTTPS / TLS **前提としていない**
- レート制限 **なし**

**標準のlocalhost限定を解除したまま、インターネットへ直接公開してはいけません。** LAN内の別端末から利用する場合も、ファイアウォール等で接続元を制限してください。クラウド VM 等で運用する場合は、Reverse proxy + 認証層（Cloudflare Access / Tailscale / Basic 認証等）を必ず前段に置いてください。

### データの保管場所

すべてのデータはローカルの SQLite ファイル（デフォルト `./data/biolog.db`）に保存されます。
標準構成では、健康記録を外部サーバへ送信しません。

---

## コード詳細・用語解説

BioLog の内部構造や専門用語を先に確認したい場合は、ここから確認できます。詳細版は各リンク先にあります。

- **コード詳細**: [docs/CODE_REFERENCE.md](docs/CODE_REFERENCE.md) — 現行コードの構成、処理フロー、主要モジュールの説明
- **用語解説**: [この README の用語解説](#用語解説) — BioLog 固有用語、Web/API、Python、SQLite、Docker などを初心者向けに説明
- **仕様書**: [biolog_streamlit/仕様書.md](biolog_streamlit/仕様書.md) — アーキテクチャ、データフロー、整合性モデル
- **操作説明書**: [biolog_streamlit/操作説明書.md](biolog_streamlit/操作説明書.md) — 画面操作と日常利用の手順
- **API リファレンス**: [biolog_api/skills.md](biolog_api/skills.md) — API と curl の利用例

### 主要コード構成

| 場所 | 役割 |
|---|---|
| `biolog_streamlit/` | 画面、入力フォーム、一覧、グラフ、CSV入出力UI |
| `biolog_api/api.py` | Streamlit から利用する FastAPI エンドポイント |
| `biolog_api/worker.py` | Queue から書き込み処理を受け取る単一 Writer ワーカー |
| `biolog_api/write_repository.py` | SQLite への登録・更新・削除・CSVインポート書き込み |
| `biolog_api/csv_import.py` | CSVの解析、検証、インポート用データへの変換 |
| `biolog_api/migrations/` | 新規DB・既存DBのスキーマ更新 |
| `tests/` | API、DB、UIロジック、CSV、migration等の回帰テスト |

### 先に知っておく用語

| 用語 | BioLogでの意味 |
|---|---|
| **Streamlit** | ブラウザに表示する画面部分 |
| **FastAPI** | UIからの要求を受け取り、読み書き処理へ渡すAPI部分 |
| **SQLite** | 健康記録を保存するローカルDB。標準では `./data/biolog.db` |
| **単一 Writer** | DBへの書き込みを1本のWorkerに集約して競合を避ける方式 |
| **UPSERT** | 同じユーザー・同じ日付がなければ追加、あれば更新する処理 |
| **migration** | 既存データを保ちながらDB構造を新しい版へ更新する仕組み |
| **冪等性 / request_id** | 同じ要求の再送で重複書き込みや巻き戻りを起こさないための仕組み |

詳しい説明は下部の [用語解説](#用語解説) を参照してください。

---

## 主な機能

- 家族メンバー（self / father / mother）ごとの健康データを日次記録
- 体温・脈拍・血圧（収縮期/拡張期）・体重・体脂肪率・筋肉量・基礎代謝
- 食事ログ / 行動ログ / メモ（長文可、一覧で expander 展開）
- 時系列グラフ（matplotlib、複数ユーザー比較）
- CSV エクスポート（UTF-8 BOM 付き、Excel 文字化けなし）
- CSV インポート（出力CSVの追加・更新による復元。実行前プレビュー付き）
- JST 基準の日付補完（Docker UTC 環境でも正しく動作）
- migration 機構（CREATE TABLE + ALTER 併存で新規/既存両環境対応）

### CSV インポート

「一覧」画面の「CSV インポート」でファイルを選び、「内容を解析」で予定件数とエラーを確認してから「インポートを実行」します。サイドバーのフィルターとは独立してCSV全体を扱います。更新前の状態を残す場合は、先に現在のデータをCSV出力してください。

- BioLogの出力列を持つUTF-8／BOM付きCSVに対応します（CSV本文5 MiB・5,000データ行まで、空行は除外）。
- 同じユーザー・対象日はCSVの状態で更新します。測定値の空欄はNULL、メモ・食事ログ・行動ログの空欄は空文字になり、ログは追記しません。CSVにないレコードは変更しません。
- 不正行や同一ユーザー・対象日の重複がある場合は取り込みません。実行途中のDBエラーでは全件ロールバックします。予定件数は実行時に再判定し、値が同じ行はスキップします。
- `id`・`記録日時`・`created_at`・`request_id`は取り込みません。既存の識別情報・記録日時を維持し、新規行の記録日時は取り込み時刻になります。
- 数式対策の先頭アポストロフィを戻す選択肢があります。元から同じ文字で始まる値とは区別できないため、その場合は選択を解除してください。旧データでも現行の文字数上限を超えるログは取り込めません。自動切り詰めは行いません。
- 通信タイムアウトでは書き込み結果が未確認となるため、一覧を更新して確認してください。自動再試行は行いません。

---

## ドキュメント

| ファイル | 内容 |
|---|---|
| [docs/CODE_REFERENCE.md](docs/CODE_REFERENCE.md) | **コード詳細・現行実装の解説** |
| [用語解説](#用語解説) | **README 内の技術用語・BioLog 固有用語の説明** |
| [biolog_streamlit/操作説明書.md](biolog_streamlit/操作説明書.md) | 画面操作手順 |
| [biolog_streamlit/仕様書.md](biolog_streamlit/仕様書.md) | アーキテクチャ・データフロー・整合性モデル |
| [biolog_api/skills.md](biolog_api/skills.md) | API リファレンス（curl 集） |
| [CHANGELOG.md](CHANGELOG.md) | バージョン履歴 |
| [LICENSE.md](LICENSE.md) | ライセンス（MIT License） |
| [PRIVACY_POLICY.md](PRIVACY_POLICY.md) | プライバシーポリシー |
| [TERMS_OF_USE.md](TERMS_OF_USE.md) | 利用規約 |
| [DISCLAIMER.md](DISCLAIMER.md) | 免責事項 |
| [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) | サードパーティライセンス |
| [SHA256SUMS.txt](SHA256SUMS.txt) | 公開対象ファイルの SHA-256 一覧（機械検証用） |
| [SHA256.md](SHA256.md) | SHA-256 一覧（閲覧用） |

---

## Screenshots

<table>
  <tr>
    <td><img src="docs/screenshots/02-graph.png" alt="Graph" width="400"/></td>
    <td><img src="docs/screenshots/03-list.png" alt="List" width="400"/></td>
  </tr>
  <tr>
    <td align="center">時系列グラフ</td>
    <td align="center">一覧 + 全文 expander</td>
  </tr>
</table>

> ※ スクリーンショットの数値はすべてダミーデータです

---

## System Requirements

- **Docker Desktop** または **Docker Engine + Compose v2**（必須）
- 動作確認 OS: **Windows 11 + Docker Desktop**
  - Linux / macOS は理論上動作するが **未検証**
- ディスク: 約 **1 GB**（image + DB）
- メモリ: 2 GB 程度で十分
- ブラウザ: モダンなもの（Chrome / Edge / Firefox / Safari）

### Docker image / build 時間の目安

| 項目 | 目安 |
|---|---|
| 初回 build | 3〜5 分（依存パッケージ download 時間込み） |
| 2 回目以降 | 数十秒（layer cache が効く） |
| image 合計サイズ | 約 800 MB〜1 GB（biolog-api + biolog-streamlit） |

依存は軽量（FastAPI / Streamlit / matplotlib / pandas / requests）。
GPU / CUDA / ML フレームワークは **使用しません**。

---

## Quick Start

> Docker と git の基本操作に慣れていることを前提とします。

### 1. Clone

```bash
git clone https://github.com/shinosan1/biolog.git
cd biolog
```

### 2. 環境変数（任意）

デフォルトでは `./data` ディレクトリに DB が作られます。
別の場所に置きたい場合のみ `.env` を作成：

```bash
cp .env.sample .env
# エディタで BIOLOG_DATA_DIR を編集
```

### 3. 起動

```bash
docker compose up -d --build
```

初回のみ image build に 3〜5 分かかります。

### 4. アクセス

ブラウザで http://localhost:8501

ヘルスチェック：
```bash
curl http://localhost:8766/api/health/health
# {"status":"ok","worker_alive":true,"database_ok":true,"queue":{"size":0,"max_size":100}}
```

### 5. 停止

```bash
docker compose down
```

DB ファイルは `${BIOLOG_DATA_DIR:-./data}/biolog.db` に永続化されているので、
`docker compose down` してもデータは残ります。

---

## Architecture

```
┌────────────────────┐    HTTP     ┌──────────────────┐
│ Streamlit (8501)   │ ──────────► │ FastAPI (8766)   │
│ - UI               │             │ - POST/PUT/DELETE│
│ - 読み取り cache   │             │ - GET (biocore)  │
└────────────────────┘             └──────┬───────────┘
                                          │ Queue
                                          ▼
                                  ┌──────────────────┐
                                  │ Worker (1 thread)│
                                  │ - 単一 Writer    │
                                  │ - UPSERT/UPDATE/ │
                                  │   DELETE         │
                                  └──────┬───────────┘
                                         │ db_manager
                                         ▼
                                  ┌──────────────────┐
                                  │ SQLite           │
                                  │ /data/biolog.db  │
                                  └──────────────────┘
```

詳細は [仕様書](biolog_streamlit/仕様書.md) を参照。

---

## Design Rationale

### Why SQLite?

| 観点 | 理由 |
|---|---|
| **デプロイ簡易性** | ファイル 1 つ。バックアップは `cp` だけ |
| **依存最小** | 別 DB サーバ不要、Docker compose が biolog-api + biolog-streamlit のみで完結 |
| **個人/家族規模で十分** | レコード数は年間数千件程度。リクエスト頻度も 1 秒に 1 件未満 |
| **WAL 不要設計** | Windows + NTFS bind mount で WAL モードが I/O エラーを誘発するため、`PRAGMA journal_mode=DELETE` を強制 |

### Concurrency Model（単一 Writer）

書き込みは **1 本の Worker スレッド** に集約しています：

```
HTTP Request → FastAPI → Queue → Worker (1) → db_manager → SQLite
```

これにより：
- `database is locked` エラーを **構造的に回避**
- リトライロジックを worker.py の 1 箇所に集約
- BEGIN IMMEDIATE / commit / rollback のトランザクション境界が明確

### Cache Invalidation

`@st.cache_data(ttl=10)` を読み取りキャッシュとして使用。書き込み成功時と
サイドバー「更新」で `clear_health_caches()` を呼び、次の 2 つを併用して invalidate する。

- `fetch_latest.clear()` / `fetch_range_data.clear()` — per-function、プロセス全体を破棄
- `st.session_state.data_version` の更新 — セッション単位でキャッシュキーの世代を進める

`data_version` の初期値は `int(time.time())`。0 起点にすると新しいセッションが
過去セッションのキャッシュキーに衝突するため、これを構造的に避けている。
TTL 10 秒は、書き込み直後にまだ反映前の値を取得してしまった場合の滞留時間の上限。

**履歴**：version 機構は初期値 0 によるセッション跨ぎの衝突が原因で v1.5.5 に一度廃止され、
初期値を `int(time.time())` に変えて v1.5.7 で再導入された。その後 v1.6.0 の
「非破壊分割」の際に廃止理由の記録なく失われていたため、v1.7.8 で復元している。

---

## Not For（このアプリは○○には向きません）

- ❌ **インターネット公開**（認証・TLS・レート制限なし）
- ❌ **同時 100+ ユーザー**（単一 Writer、SQLite ファイル）
- ❌ **数百万件のデータ**（SQLite で動くが、グラフ描画が重くなる）
- ❌ **リアルタイム性が必要なユースケース**（Eventual Consistency 設計、書き込みから表示まで数秒）
- ❌ **マルチテナント / 不特定多数のユーザー**（user_id は固定 3 種：self / father / mother）

## 2026-07-27 安定性・監査対応

- Worker内の各書き込みタスクを例外隔離し、レコード不在や不正タスクで
  単一Writerスレッド全体が停止しないようにした。
- Worker応答が30秒以内に返らない場合は、未処理の500ではなく503を返す。
- API healthはWorker生存、DB読取疎通、Queue使用量を返す。
  Docker Composeのhealthcheckは状態の可視化用であり、`unhealthy`だけでは
  コンテナは自動再起動されない。
- 一覧とCSVは、指定期間および選択ユーザーだけを対象とする。
  CSVは現在ページではなく指定範囲の全件を出力する。
- SQLiteは`journal_mode=DELETE`を維持し、有限のbusy timeoutと短い読取リトライを使う。
- APIはページング負値、不正日付、逆転期間、JSONオブジェクト以外、
  過大なテキストを拒否する。`preprocess.py`の既存の整数型補正は維持する。
- コンテナ時刻は`Asia/Tokyo`へ統一し、Streamlit利用統計を無効化した。
- CSVの文字列が`=`, `+`, `-`, `@`で始まる場合は、表計算ソフトで
  数式として実行されないよう無害化する。
- Linuxコンテナの追加capabilityはすべて破棄する。
- APIとStreamlitはUID/GID `10001`の非rootユーザーで実行する。
  `/data`のバインドマウントは運用反映前に書き込み権限を確認する。
- `constraints.txt`で、2026-07-27時点の動作中イメージから採取した
  推移依存パッケージの版を固定する。

Streamlitの`Cannot load Streamlit frontend code`は原因未確定である。
再発時は[NETWORK_ISSUE_DIAGNOSTICS.md](docs/NETWORK_ISSUE_DIAGNOSTICS.md)に従い、
Docker再起動前にブラウザ、HTTP、コンテナ、スリープ復帰の証拠を採取する。

これらが必要な場合は別のスタック（PostgreSQL + 認証付きフレームワーク等）を検討してください。

---

## Data Persistence

### デフォルト動作

```yaml
# docker-compose.yml
volumes:
  - ${BIOLOG_DATA_DIR:-./data}:/data
```

- 環境変数未設定なら、リポジトリ直下の `./data/` にバインドマウント
- 初回起動時に `./data/biolog.db` が **migration runner により自動生成**

### バックアップ

```bash
docker compose down                    # 安全のため停止
cp ./data/biolog.db ./backup/biolog_$(date +%Y%m%d).db
docker compose up -d
```

### 別の場所に置く

`.env` を作成：
```bash
# Windows 例
BIOLOG_DATA_DIR=D:/AI/biolog/data

# Linux 例
BIOLOG_DATA_DIR=/var/lib/biolog
```

---

## Known Issues / Limitations

正直に列挙します。

### Resolved（修正済み）
- ✅ セッション跨ぎで古いキャッシュが残る問題 → v1.5.5 で version 機構廃止、per-function clear に変更
- ✅ 深夜 0〜9 時 (JST) に登録すると date が前日になる → v1.5.0 で `jst_date()` 統一
- ✅ 新規環境で `health_records` テーブル不在で起動失敗 → v1.5.2 で `CREATE TABLE IF NOT EXISTS` 追加
- ✅ migration runner の手動実行忘れ → v1.5.3 で entrypoint.sh による自動化
- ✅ 新規登録成功後もフォームに前回の入力値が残る → v1.7.6 で修正（登録成功時のみリセット、エラー時は入力を維持）
- ✅ 同一ユーザー・同一日付の再登録で API が `id=0` を返す → v1.7.6 で修正（UPSERT 後に実レコード ID を取得）
- ✅ v1.5.7 のキャッシュ version 機構が v1.6.0 の分割で失われていた退行 → v1.7.8 で復元（per-function clear / TTL と併用）

### Open（既知の未解決）
- ⚠ **migration_lock の stale 残存**：コンテナ強制終了で finally が走らないとロックが残る。手動 `DELETE FROM migration_lock WHERE id = 1` で復旧
- ⚠ **runner.py の lock 競合時 exit 0 仕様**：lock 残存時 runner は何もせず exit 0 → schema 未整備のまま API が起動する可能性あり
- ⚠ **CHECK 制約未実装**：DB レベル制約は無し、Pydantic 層のみで範囲検証している（DB 直接編集時の弱点）
- ⚠ **`updated_at` カラム未実装**：UPDATE しても created_at は変わらない。監査ログ用途には不十分

### Untested / Unverified（未検証範囲）
- 🔍 **Linux / macOS での動作**：理論上動くはずだが、Windows 以外での動作確認は未実施
- 🔍 **大量データ（数万件以上）**：性能未測定、グラフ描画速度に影響する可能性
- 🔍 **長時間連続稼働**：数ヶ月レベルの常時稼働は未検証
- 🔍 **マルチアーキテクチャ image**：amd64 でのみ確認済み、arm64 未検証
- 🔍 **同一データに対する複数 Streamlit インスタンス**：cache が分離するため、別タブで編集 → 別タブで未反映の可能性

### Out of Scope（対応予定なし）
- ❌ マルチユーザー認証
- ❌ クラウド DB 対応
- ❌ モバイルアプリ
- ❌ 機械学習による予測

---

## Troubleshooting

### Streamlit が起動しない / SyntaxError
```bash
docker logs biolog-streamlit --tail 50
```
ファイル編集ミスが最有力。差し戻して再起動：
```bash
docker compose restart biolog-streamlit
```

### API ヘルスチェックが失敗
```bash
docker logs biolog-api --tail 50
curl http://localhost:8766/api/health/health
```

### 「Migration lock exists」で API が起動しない
```bash
docker exec biolog-api python -c "
import sqlite3
conn = sqlite3.connect('/data/biolog.db')
conn.execute('DELETE FROM migration_lock WHERE id = 1')
conn.commit()
conn.close()
print('Lock released')
"
docker compose restart biolog-api
```

### `database is locked` が頻発
- WAL モード残骸を確認：`./data/biolog.db-wal` / `./data/biolog.db-shm` ファイルがあれば削除
- WAL モードは `db_manager.py` で禁止しているが、過去に手動 PRAGMA を実行した場合は残ることがある

### 表示が古い
- サイドバー「更新」ボタンを押す
- ブラウザを完全リロード（Ctrl + F5）

### ポート競合
- biolog-api: 8766、biolog-streamlit: 8501
- 他で使用中なら `docker-compose.override.yml` で port を変更

---

## Roadmap（参考）

監査由来の未着手タスク：
- M1: `schemas.py` の date に `YYYY-MM-DD` 形式バリデータ追加
- M2: API queue.Empty を 504 Gateway Timeout で返却
- L1: biocore.py の `SELECT *` を明示列指定に置換

優先度は低く、現状で実害なし。

---

## 用語解説

この README に登場する用語のうち、Web 開発やプログラミングを専門にしていない方が
読むときに意味を調べる必要がありそうなものをまとめました。
「一般的な意味」と「BioLog では何に使っているか」の両方を書いています。

### BioLog・アプリ構成

#### BioLog

このアプリの名前。家族（自分・父・母）の健康記録を 1 日 1 件ずつ記録・表示する、
個人利用向けのアプリ。画面部分（Streamlit）と処理部分（FastAPI）と保存部分（SQLite）の
3 つを組み合わせて動く。

#### セルフホスト（self-hosted）

サービス提供会社のサーバではなく、利用者自身のパソコンやサーバでソフトを動かす形態。

BioLog は自分の PC 上で動かし、健康記録も自分の PC 内のファイルに保存する。
標準構成では、記録が外部のサーバへ送られることはない。

#### レコード（record）

データベースに保存される 1 件分のデータ。表計算ソフトでいう「1 行」にあたる。

BioLog では「1 人分・1 日分の健康記録」が 1 レコード。
`health_records` という名前のテーブル（表）に保存される。
同じ人・同じ日付のレコードは必ず 1 件だけになるよう設計されている。

#### user_id（self / father / mother）

どの家族メンバーの記録かを表す識別子。BioLog では `self`（自分）・`father`（父）・
`mother`（母）の 3 種類に固定されており、利用者が自由に追加することは想定していない。
画面上では「自分 / 父 / 母」と表示される。

#### 単一 Writer モデル

データベースへ**書き込む処理を 1 か所（1 本の処理の流れ）だけに絞る**設計のこと。
Writer は「書き込む人」の意味。

BioLog では、登録・修正・削除の要求が同時に来ても、必ず次の順番で 1 件ずつ処理される。

```
HTTP Request → FastAPI → Queue → Worker (1 スレッド) → db_manager → SQLite
```

複数の処理が同時に書き込もうとして起きる `database is locked` エラーを、
仕組みとして発生させないための設計。読み取り（一覧表示やグラフ）はこの流れを通らず、
`biocore` から直接読み出す。

#### Queue（キュー／待ち行列）

先に入れたものから順に取り出される、順番待ちの入れ物。レジの行列と同じ考え方。

BioLog では、FastAPI が受け取った書き込み要求をいったん Queue に入れ、
Worker が 1 件ずつ取り出して処理する。これにより書き込みの順序が保証される。
Queue が満杯（上限 100 件）のときは、待たせ続けずに「混雑中」を意味するエラー（503）を返す。
Roadmap にある `queue.Empty` は、待ち時間内に応答が取り出せなかったことを表す
Python 側の合図で、これを 504 として返す案が未着手タスクとして挙がっている。

#### Worker（ワーカー）

裏側で作業を担当する処理。BioLog の Worker は 1 本だけ動いていて、
Queue から書き込み要求を 1 件ずつ取り出し、SQLite への追加・更新・削除を実行する。

1 件の処理が失敗しても Worker 全体が止まらないよう、要求ごとにエラーを封じ込めている。
`database is locked` が出たときだけ、待ち時間を倍にしながら最大 5 回まで再試行する。

#### スレッド（thread）

1 つのプログラムの中で並行して動く処理の単位。複数のスレッドがあれば複数の作業を
同時進行できるが、その分だけ競合も起きやすくなる。

BioLog の Worker は **意図的に 1 スレッドだけ**にしてある（→ 単一 Writer モデル）。

#### db_manager

データベースへの接続を開き、トランザクションを開始し、
終わったら確定（commit）または取り消し（rollback）して接続を閉じる役割を持つ部品。
書き込み処理は必ずここを通る。

#### biocore

データベースからの**読み取り専用**の部品。一覧・グラフ・最新値の取得など、
`SELECT` にあたる処理だけを担当する。書き込みは行わない。

#### Eventual Consistency（結果整合性）

「今すぐ完全に一致していなくても、しばらくすれば一致する」という考え方の整合性モデル。

BioLog では、書き込みを Queue 経由で処理し、画面側も約 10 秒ごとに読み直す設計のため、
登録してから画面へ反映されるまで数秒かかることがある。
即座の反映が必須の用途には向かない、と README で明示しているのはこのため。

#### 冪等性（べきとうせい／idempotency）

**同じ操作を何回繰り返しても、結果が 1 回だけ実行したときと変わらない**という性質。
通信エラーで再送されたり、ボタンを二重に押されたりしても壊れないようにするための考え方。

BioLog では次項の `request_id` を使ってこれを実現している。

#### request_id

1 回の書き込み要求を識別するための ID。登録のたびに新しい値が作られ、リクエストに含まれる。

データベース側で「同じ `request_id` は 1 件しか保存できない」という制約
（→ UNIQUE 制約）を持たせてあるため、同じ要求が二重に届いても 2 件目の保存は失敗する。
BioLog はこの失敗をエラーにせず、**すでに保存済みのレコードの ID を返して成功として扱う**。
これにより、二重送信されても記録が二重に増えない（→ 冪等性）。

#### migration（マイグレーション）／migration runner

データベースの表の構造（テーブルや列）を、決められた手順で作成・変更する仕組み。
「移行」の意味。

BioLog では API コンテナの起動時に `entrypoint.sh` が migration runner を自動実行し、
`health_records` テーブルが無ければ作成、足りない列があれば追加する。
新しい環境でも既存の環境でも同じ手順で動くようになっている。

#### migration_lock / stale（ステイル）

migration を 2 か所から同時に実行してしまわないための「鍵」を記録する小さなテーブル。
処理が始まると鍵を置き、終わると消す。

`stale` は「古くなって使われていない」という意味。コンテナを強制終了すると
鍵を消す処理が走らず、鍵だけが残ってしまうことがある。これが README にある
「migration_lock の stale 残存」で、`DELETE FROM migration_lock WHERE id = 1` で手動解除する。

#### entrypoint.sh

コンテナが起動したときに最初に実行されるスクリプト（自動実行される手順書）。
BioLog の API コンテナでは、migration を実行してから API 本体を起動する役割を持つ。

#### マルチテナント

1 つのシステムを、互いに無関係な複数の利用者・組織で共用する方式。

BioLog は `self` / `father` / `mother` の 3 つに固定された家族用アプリであり、
不特定多数が同じシステムを共有する使い方は想定していない。

#### インスタンス

「実際に動いている 1 つ分」のこと。同じアプリを 2 つのブラウザタブで開けば、
Streamlit のインスタンスも 2 つ動いていることになる。

BioLog では各インスタンスが別々に読み取りキャッシュを持つため、
片方のタブで編集しても、もう片方へすぐには反映されない可能性がある。

---

### Web・API・ネットワーク

#### API（Application Programming Interface）

ソフトウェア同士が情報や機能をやり取りするための窓口と、その取り決めのこと。

BioLog では、画面を担当する Streamlit が直接 SQLite を操作するのではなく、
FastAPI で作られた API へ HTTP で要求を送り、API 側が登録・取得・修正・削除を行う。
こうすることで「画面表示の担当」と「データ処理の担当」を分離できる。

#### HTTP（HyperText Transfer Protocol）

ブラウザとサーバが情報をやり取りするときの共通のルール（通信規約）。
`http://localhost:8501` のように、アドレスの先頭に付いているのがこれ。

BioLog では Streamlit → FastAPI の呼び出しにも HTTP を使っている。

#### GET / POST / PUT / DELETE

HTTP で「何をしたいか」を表す動詞。BioLog では次のように使い分けている。

| 動詞 | 意味 | BioLog での用途 |
|---|---|---|
| GET | 取得する | 一覧・グラフ・1 件表示・ヘルスチェック |
| POST | 新規に送る | 新規登録（同じ人・同じ日付なら既存レコードを更新） |
| PUT | 置き換える | 既存レコードの修正 |
| DELETE | 削除する | レコードの削除 |

GET は読み取りなので `biocore` が直接処理し、POST / PUT / DELETE は
Queue と Worker を経由する。

#### JSON（JavaScript Object Notation）

データを `{"status":"ok","db":"/data/biolog.db"}` のように、
名前と値の組で表現する書式。人が読めて、プログラムでも扱いやすい。

BioLog の API はリクエストもレスポンスも JSON でやり取りする。
README のヘルスチェック例で表示されている文字列がこれ。

#### ステータスコード（500 / 503 / 504 など）

HTTP の応答に付く 3 桁の数字で、処理結果の種類を表す。200 番台は成功、
400 番台は要求側の誤り、500 番台はサーバ側の問題を意味する。

BioLog では、Worker が 30 秒以内に応答しない場合に「サーバが今は処理できない」を
意味する **503** を返す（原因不明の 500 を返さない）。
Roadmap にある **504 Gateway Timeout** は「待ち時間切れ」を表すコード。

#### localhost / 127.0.0.1

どちらも「今使っているこのコンピュータ自身」を指すアドレス。
外部のネットワークからは到達できない。

BioLog は標準で API（8766）と画面（8501）を `127.0.0.1` にだけ公開するため、
**同じ PC のブラウザからしか開けない**。これが README のセキュリティ上の前提になっている。

#### ポート（port）

1 台のコンピュータの中で、通信の宛先を区別するための番号。
同じアドレスでも番号が違えば別のプログラムにつながる。

BioLog は画面に **8501**、API に **8766** を使う。
他のソフトが同じ番号を使っていると「ポート競合」で起動できないため、
その場合は `docker-compose.override.yml` で番号を変更する。

#### 完全リロード（Ctrl + F5）

ブラウザが手元に保存している一時ファイルを無視して、
ページを最初から読み込み直す操作。通常の再読み込みでは古い内容が
表示され続けることがあるため、それを避けたいときに使う。

BioLog で「表示が古い」ときの対処として README が挙げている手段のひとつ。

#### LAN（Local Area Network）

家庭内や社内など、限られた範囲をつなぐネットワーク。

BioLog は標準では LAN 内の別端末からもアクセスできない設定になっている。
別端末から使う場合は設定変更が必要で、その際もファイアウォール等で
接続元を制限することが README で求められている。

#### curl（カール）

コマンドライン（黒い画面）から HTTP 要求を送るためのツール。
ブラウザを開かずに API の応答を確認できる。

README では `curl http://localhost:8766/api/health/health` で
API が正常かどうかを確認する例として使われている。

#### ヘルスチェック（health check）

サービスが正常に動いているかを定期的に確認する仕組み。

BioLog の API のヘルスチェックは、Worker が生きているか・データベースを読めるか（読取疎通）・
Queue がどれくらい詰まっているかを返す。
Docker Compose 側の `healthcheck` 設定でも 30 秒ごとに確認しているが、
**状態の見える化が目的**であり、`unhealthy` になってもコンテナは自動再起動されない。

#### frontend / backend（フロントエンド / バックエンド）

- **frontend**：利用者が直接見る・操作する側。BioLog では Streamlit の画面。
- **backend**：画面の裏でデータを処理・保存する側。BioLog では FastAPI と SQLite。

README の `Cannot load Streamlit frontend code` は、
ブラウザが Streamlit の画面用ファイルを読み込めなかったときに出るメッセージ。

#### UI（User Interface）

利用者とソフトの接点、つまり操作画面のこと。BioLog の UI は Streamlit が担当し、
グラフ・一覧・新規登録・修正削除の 4 つのタブで構成されている。

#### Reverse proxy（リバースプロキシ）／認証層

利用者とアプリの間に立ち、通信を中継する仕組み。中継の途中で「誰が使っているか」を
確認したり（認証層）、暗号化を担当したりできる。

README では、もしクラウド上で運用するなら BioLog を直接公開せず、
Cloudflare Access や Tailscale などの認証機能を必ず前段に置くよう求めている。
BioLog 自体に認証機能は無いため。

#### VM（Virtual Machine／仮想マシン）

1 台の物理的なコンピュータの中に作られた、仮想のコンピュータ。
クラウド事業者が貸し出すサーバの多くがこれにあたる。

---

### Python・Streamlit

#### Python（パイソン）

BioLog 全体で使っているプログラミング言語。README のバッジにある「Python 3.11」は、
使用しているバージョンを示す。

#### Streamlit（ストリームリット）

Python のコードだけで Web 画面を作れるライブラリ。
HTML や JavaScript を書かずに、入力欄・表・グラフを並べられる。

BioLog では画面全体（グラフ / 一覧 / 新規登録 / 修正・削除）を Streamlit で作り、
ポート 8501 で表示している。

#### FastAPI（ファストエーピーアイ）

Python で API を作るためのライブラリ。受け取ったデータの形式チェックを
自動で行える点が特徴。

BioLog ではポート 8766 で動き、登録・取得・修正・削除の窓口を提供する。

#### Pydantic（パイダンティック）

受け取ったデータが期待どおりの形か（数値か、文字数は多すぎないか、
値が許容範囲内かなど）を検証するための Python ライブラリ。FastAPI が内部で使っている。

BioLog では体温 34〜42 ℃、脈拍 30〜200 bpm といった範囲検証をこの層で行う。
README の「CHECK 制約未実装：DB レベル制約は無し、Pydantic 層のみで範囲検証している」は、
**データベース自体には範囲の制限を設けておらず、この Python 側の検証に頼っている**
という意味。

#### バリデーション（validation）／バリデータ

入力された値が正しい形式・正しい範囲かどうかを検査すること。検査を行う部品がバリデータ。

BioLog では `schemas.py` が担当する。Roadmap の
「`schemas.py` の date に `YYYY-MM-DD` 形式バリデータ追加」は、
日付の書式チェックを追加する未着手タスクを指す。

#### preprocess.py（前処理）

API が受け取ったデータを、検証に回す前に整える部品。「前処理」の意味。

BioLog では、`"120/80"` のような血圧の文字列を上下に分解したり、
`"1400.0"` を `1400` に直したり、`date` や `request_id` が空のときに補ったりする。

#### キャッシュ（cache）／`@st.cache_data` / invalidate（無効化）

一度取得した結果を一時的に覚えておき、次回は再取得せずに使い回す仕組み。表示が速くなる。

BioLog では読み取り結果を `@st.cache_data` で数秒間キャッシュする。
ただし登録・修正・削除に成功した直後は古い内容を見せないよう、
`fetch_latest.clear()` / `fetch_range_data.clear()` を呼んでキャッシュを
**捨てる（invalidate＝無効化する）**。README の「per-function に明示 invalidate」は、
関数ごとに個別に捨てる、という意味。
あわせて「version 機構」も使っている。これはキャッシュの目印に世代番号
（`data_version`）を混ぜておき、書き込みのたびに番号を 1 つ進める方式。
`.clear()` がプロセス全体のキャッシュを捨てるのに対し、こちらは
その利用者のセッションだけを新しい世代へ移すため、直後に別のセッションが
古い値を詰め直しても影響を受けない。番号の初期値には時刻を使う（→ UTC / JST）。

3 つの役割は次のとおり。

| 仕組み | 役割 |
|---|---|
| `.clear()` | 書き込み直後に、今あるキャッシュをすべて捨てる |
| `data_version` | セッションごとにキャッシュの世代を進め、古い世代を参照しない |
| `ttl=10` | 万一古い値を取得してしまっても、10 秒で自動的に期限切れにする |

#### セッション（session）／セッション跨ぎ

ブラウザでアプリを開いてから閉じるまでの、1 回の利用のまとまり。

「セッション跨ぎ」は、いったん閉じて開き直した別の利用のこと。
README にある過去の不具合は、開き直したあとに前回の古いキャッシュを
拾ってしまうというものだった（v1.5.5 で解消）。

#### expander（エクスパンダー）

Streamlit の折りたたみ表示部品。クリックすると隠れていた内容が開く。

BioLog では、一覧のメモ・食事ログ・行動ログが長くて表に収まらない場合に、
その部分だけ expander で全文を開けるようにしている。

#### 例外（exception）／例外隔離

プログラムの実行中に起きた異常のこと。放置するとプログラムが止まる。

BioLog では書き込みタスクごとに例外を受け止めて封じ込めており（例外隔離）、
1 件の異常で単一 Writer スレッド全体が停止しないようにしている。

#### `finally`

Python で「異常が起きても、必ず最後に実行する」処理を書くための構文。

README の「コンテナ強制終了で finally が走らない」は、
コンテナを強制的に落とすと、この後始末（migration_lock の削除）が
実行されないまま終わってしまう、という意味。

#### 終了コード（exit 0）

プログラムが終わるときに残す数値。慣例として **0 は正常終了**、
0 以外は異常終了を表し、後続の処理はこれを見て続行するか判断する。

README の「runner.py の lock 競合時 exit 0 仕様」は、
migration の鍵が残っていて何も実行できなかった場合でも
runner が「正常終了（0）」を返してしまうため、
表の構造が整っていないまま API が起動してしまう可能性がある、という指摘。

#### SyntaxError（構文エラー）

プログラムの書き方が文法的に間違っているときのエラー。実行前の段階で失敗する。

README では、Streamlit が起動しない場合の原因としてまず疑うべきものとして挙げている。

#### matplotlib / pandas / requests

BioLog が利用している Python のライブラリ。

- **matplotlib**：グラフを描画する。BioLog の時系列グラフに使用。
- **pandas**：表形式のデータを扱う。一覧表示や CSV 出力に使用。
- **requests**：HTTP 通信を行う。Streamlit から FastAPI を呼び出すときに使用。

#### 依存パッケージ／推移依存／constraints.txt（バージョン固定）

- **依存パッケージ**：アプリが動くために必要な、外部で作られた部品。
- **推移依存**：依存パッケージがさらに内部で必要としている部品。間接的な依存。
- **バージョン固定**：使う版を明示的に指定し、勝手に新しい版へ変わらないようにすること。

BioLog では `constraints.txt` に、2026-07-27 時点で実際に動いていたイメージから
採取した推移依存の版まで書き出して固定している。
これにより、再ビルドしても同じ組み合わせで動くことを保証している。

#### 利用統計（テレメトリ）

ソフトが「どう使われたか」の情報を、開発元へ自動送信する仕組み。
Streamlit にはこの機能が標準で備わっている。

BioLog では設定ファイルでこれを **無効化**しており、
利用状況が外部へ送られないようにしている。

#### GPU / CUDA / ML フレームワーク

- **GPU**：画像処理や機械学習の計算を高速に行う専用装置。
- **CUDA**：その GPU を計算に使うための開発基盤。
- **ML フレームワーク**：機械学習（Machine Learning）のためのライブラリ群。

いずれも BioLog では **使用していない**。README がこれを明記しているのは、
インストールが軽く済むことを示すため。

---

### データベース・SQLite

#### データベース（DB）

データを整理して保存し、後から検索・更新できるようにした仕組み。

#### SQL（Structured Query Language）

データベースに対して「取り出す」「追加する」「変える」「消す」と指示するための言語。
README に出てくる `DELETE FROM migration_lock WHERE id = 1` や `SELECT *` はこの言語の文。

#### SQLite（エスキューライト）

**ファイル 1 つがそのままデータベースになる**タイプの小規模データベース。
別途データベース専用のサーバを立てる必要がない。

BioLog では `./data/biolog.db` というファイル 1 つに全記録を保存する。
バックアップはこのファイルをコピーするだけで済み、
Docker で起動するコンテナも 2 つ（API と画面）だけで完結する。

#### テーブル／カラム／スキーマ

- **テーブル（表）**：同じ形のデータをまとめて入れる箱。BioLog では `health_records`。
- **カラム（列）**：テーブルの各項目。`user_id`、`date`、`created_at` など。
- **スキーマ**：テーブルとカラムの構造そのもの。「どんな表で、どんな項目があるか」の定義。

README の「schema 未整備のまま API が起動する可能性あり」は、
テーブルの構造が作られていない状態で API が動き出す恐れがある、という意味。

#### SELECT / INSERT / UPDATE / DELETE

SQL の基本操作。BioLog での役割は次のとおり。

| 命令 | 意味 | BioLog での担当 |
|---|---|---|
| SELECT | 取り出す | `biocore`（読み取り専用） |
| INSERT | 新しい行を追加する | Worker（新規登録時） |
| UPDATE | 既存の行を書き換える | Worker（修正時、および同じ人・同じ日付の再登録時） |
| DELETE | 行を消す | Worker（削除時） |

Roadmap の「`SELECT *` を明示列指定に置換」は、
「全部の列」を意味する `*` をやめて必要な列名を書き並べる、という改善案。

#### CREATE TABLE / ALTER TABLE / IF NOT EXISTS

テーブルの構造そのものを操作する SQL。

- **CREATE TABLE**：新しいテーブルを作る。
- **ALTER TABLE**：既存のテーブルに列を追加するなど、構造を変更する。
- **IF NOT EXISTS**：「まだ無い場合だけ作る」という指定。
  すでにある場合はエラーにせず何もしない。

BioLog の migration は `CREATE TABLE IF NOT EXISTS` と `ALTER TABLE` を併存させてある。
新しい環境では表ごと作られ、すでに動いている環境では足りない列だけが追加されるため、
どちらでも同じ手順で起動できる。

#### UPSERT（アップサート）

**UPDATE と INSERT を合わせた造語**。対象が存在しなければ追加（INSERT）し、
すでに存在すれば書き換える（UPDATE）という 1 つの操作。

BioLog では「1 人につき 1 日 1 件」という決まりを守るために使っている。
`UNIQUE(user_id, date)` で同じ人・同じ日付が重複しないようにしたうえで、
`ON CONFLICT(user_id, date) DO UPDATE` を指定することで、
**同じ人・同じ日付で再登録しても新しい行を増やさず、既存の行を更新する**。

このとき、入力されなかった測定値は既存の値をそのまま残し、
食事ログ・行動ログは既存にない行だけを追記する（同じ内容は重複させない）。

#### UNIQUE 制約 / CHECK 制約

データベース側で設定できる、値のルール。

- **UNIQUE**：同じ値が 2 件以上入らないようにする制約。
  BioLog では `(user_id, date)` の組と `request_id` に設定されている。
- **CHECK**：値が決められた条件を満たすかをデータベース側で検査する制約。
  BioLog では **未実装**で、範囲の検査は Pydantic 層だけで行っている
  （README の Known Issues に記載のとおり、データベースを直接編集した場合の弱点になる）。

#### トランザクション / BEGIN IMMEDIATE / commit / rollback

**一連の書き込みを「全部成功」か「全部なかったこと」のどちらかにまとめる仕組み**。
途中で失敗したまま中途半端に保存される事態を防ぐ。

- **BEGIN IMMEDIATE**：トランザクションの開始。BioLog ではこの形式を使い、
  開始時点で書き込み権を確保する。
- **commit（コミット）**：ここまでの変更を確定して保存する。
- **rollback（ロールバック）**：変更を取り消して開始前の状態へ戻す。

BioLog では `db_manager` がこの境界を管理しており、
どこで開始してどこで確定・取り消しをするかが 1 か所に集約されている。

#### ロック / `database is locked` / busy timeout / リトライ

- **ロック**：あるプログラムが書き込み中に、他からの書き込みを一時的に締め出す仕組み。
- **`database is locked`**：締め出されて書き込めなかったときの SQLite のエラー。
- **busy timeout**：締め出されている間、どれだけ待つかの上限時間。
- **リトライ（再試行）**：失敗した処理をもう一度試すこと。

BioLog は単一 Writer モデルによってこのエラーを構造的に避けているが、
念のため有限の busy timeout（無限に待たない）と、
`database is locked` のときだけ最大 5 回の短い再試行を用意している。

#### PRAGMA / journal_mode / WAL

- **PRAGMA**：SQLite の動作設定を切り替えるための特別な命令。
- **journal_mode**：書き込み途中の記録をどう残すかの方式。
- **WAL（Write-Ahead Logging）**：更新内容を別ファイル（`.db-wal` / `.db-shm`）へ
  先に書き出す高速な方式。

BioLog は **WAL を使わず** `PRAGMA journal_mode=DELETE` を強制している。
Windows の NTFS 上で Docker のバインドマウント越しに WAL を使うと
入出力エラーを誘発するため。過去に手動で WAL を有効化した名残として
`.db-wal` / `.db-shm` が残っている場合は、削除してよいと README に記載されている。

#### ページング（paging）

大量のデータを一度に返さず、一定件数ずつ区切って返すこと。
「何件目から何件分か」を指定する。

BioLog の API はこの指定に負の値が来た場合などを拒否する。
なお CSV 出力は現在表示中のページではなく、**指定期間の全件**を出力する。

---

### Docker・実行環境

#### Docker（ドッカー）

アプリを、必要なライブラリや設定ごと**ひとまとめの箱**にして動かす仕組み。
「自分の PC では動くのに他所では動かない」を防げる。

BioLog は Python やライブラリを個別にインストールする必要がなく、
Docker があれば起動できるようにしてある。

#### Docker Desktop / Docker Engine

同じ Docker を使うための、提供形態の違い。

- **Docker Desktop**：Windows / macOS 向けの、画面操作もできる一式パッケージ。
  Docker 本体と Compose がまとめて入る。
- **Docker Engine**：Linux 向けの本体部分。Compose は別途導入する。

BioLog はどちらでも動く。README が「Docker Desktop **または** Docker Engine + Compose v2」
と書いているのはこのため。

#### コンテナ（container）／イメージ（image）

- **イメージ**：アプリと必要な部品一式を固めた「型」。実行前の状態。
- **コンテナ**：イメージから作られて実際に動いている「実体」。

BioLog は `biolog-api` と `biolog-streamlit` の 2 つのコンテナで動く。
イメージの合計サイズは約 800 MB〜1 GB。

#### build（ビルド）／layer cache（レイヤーキャッシュ）

- **build**：イメージを組み立てる作業。ライブラリのダウンロードを含むため初回は時間がかかる。
- **layer cache**：build の途中結果を層（レイヤー）ごとに保存しておく仕組み。
  変更がない層は再利用されるため、2 回目以降は大幅に短くなる。

BioLog の初回 build は 3〜5 分、2 回目以降は数十秒が目安。

#### Docker Compose / `docker compose` / Compose v2 / docker-compose.yml

**Docker** が 1 つのコンテナを作って動かす仕組みであるのに対し、
**Docker Compose** は複数のコンテナの構成をファイルに書いておき、まとめて起動・停止する仕組み。

BioLog では `docker-compose.yml` に、API と画面の 2 コンテナ、公開するポート、
保存先、タイムゾーンなどをまとめて定義している。
**Compose v2** は現行世代の呼び方で、コマンドがハイフン付きの `docker-compose` ではなく
空白区切りの `docker compose` になっている。

#### `docker compose up` / `down` / `restart` / `logs` / `exec`

README に登場する主なコマンド。

| コマンド | 意味 |
|---|---|
| `docker compose up -d --build` | イメージを組み立て、コンテナを起動する。`-d` は画面を占有せず裏で動かす指定 |
| `docker compose down` | コンテナを停止して片付ける。データファイルは残る |
| `docker compose restart <名前>` | 指定したコンテナだけ再起動する |
| `docker logs <名前> --tail 50` | コンテナが出力した記録の末尾 50 行を表示する |
| `docker exec <名前> <コマンド>` | 動いているコンテナの中でコマンドを実行する |

#### docker-compose.override.yml

`docker-compose.yml` の設定を、元ファイルを書き換えずに上書きするための追加ファイル。

BioLog では、8501 や 8766 が他のソフトと競合した場合に、
このファイルでポート番号だけを変更する使い方を README で案内している。

#### ボリューム（volume）／バインドマウント（bind mount）

コンテナの中と外でファイルを共有する仕組み。
コンテナは消えても、外に置いたファイルは残る。

- **バインドマウント**：PC 上の特定のフォルダを、そのままコンテナ内の場所として見せる方式。

`docker-compose.yml` の `volumes:` がこの指定にあたる。
BioLog は `./data`（または `.env` で指定した場所）をコンテナ内の `/data` に
バインドマウントし、`biolog.db` をそこに保存する。
このため `docker compose down` してもデータは消えない（→ 永続化）。

#### 永続化（persistence）

プログラムを終了しても、データが消えずに残ること。

#### 環境変数 / `.env` / `.env.sample` / BIOLOG_DATA_DIR

- **環境変数**：プログラムの外側から与える設定値。コードを書き換えずに動作を変えられる。
- **`.env`**：その設定値をまとめて書いておくファイル。
- **`.env.sample`**：記入例のファイル。これをコピーして `.env` を作る。
- **BIOLOG_DATA_DIR**：BioLog のデータベースを置く場所を指定する環境変数。
  未設定ならリポジトリ直下の `./data` が使われる。

#### restart policy（自動再起動）／`unhealthy`

コンテナが停止したときに自動で起動し直す設定。

BioLog では設定されているが、**ヘルスチェックが `unhealthy`（異常）になっただけでは
再起動されない**点に注意が必要、と README に明記されている。

#### capability（ケーパビリティ）

Linux でプログラムに与える特別な権限を、細かく分けたもの。

BioLog では追加の capability をすべて破棄しており、
コンテナ内のプログラムが必要以上の権限を持たないようにしている。

#### UID / GID / 非 root ユーザー

- **UID / GID**：利用者とグループを識別する番号。
- **root**：何でもできる管理者ユーザー。

BioLog の API と画面は、root ではなく UID/GID が `10001` の専用ユーザーで動く。
万一の侵入時に被害を広げないための措置。
このため、`/data` のバインドマウント先にこのユーザーの書き込み権限があるかを
運用前に確認する必要がある。

#### amd64 / arm64 / マルチアーキテクチャ

CPU の設計方式の種類。**amd64** は一般的な Windows / Linux PC、
**arm64** は Apple Silicon の Mac や Raspberry Pi などで使われる。
**マルチアーキテクチャ image** は、どちらでも動くように作られたイメージのこと。

BioLog は amd64 でのみ動作確認済みで、arm64 は未検証。

#### NTFS / I/O

- **NTFS**：Windows で標準的に使われるファイルの管理方式。
- **I/O（Input/Output）**：入出力。ファイルの読み書きなど。

README の「Windows + NTFS bind mount で WAL モードが I/O エラーを誘発する」は、
この組み合わせでファイルの読み書きに失敗しやすかった、という意味。

#### ディスク / メモリ

- **ディスク**：電源を切っても消えない保存領域。ハードディスクや SSD のこと。
  ファイルやデータベースはここに残る。
- **メモリ**：プログラムが動いている間だけ使う作業机のような領域。
  電源を切ると内容は消える。広いほど同時にたくさんの処理を進められる。

README の System Requirements にある「ディスク: 約 1 GB」は、
Docker のイメージとデータベースを置くために必要な保存領域の目安。
「メモリ: 2 GB 程度で十分」は、API と画面の 2 つのコンテナを動かすのに
必要な作業領域の目安。BioLog は機械学習のような重い計算をしないため、
一般的な家庭用パソコンで足ります。

#### デプロイ（deploy）

作ったアプリを、実際に動く場所へ配置して使える状態にすること。

#### PostgreSQL / フレームワーク / スタック

- **PostgreSQL**：本格的な、サーバ型のデータベース。SQLite より大規模用途に向く。
- **フレームワーク**：アプリを作るための土台となる枠組み。
- **スタック**：組み合わせて使う技術一式。BioLog のスタックは
  「Streamlit + FastAPI + SQLite」。

README は、大人数での利用や認証が必要なら BioLog ではなく
別のスタックを検討するよう案内している。

---

### データ・日時・ファイル形式

#### 測定項目（収縮期／拡張期血圧・体脂肪率・筋肉量・基礎代謝）

BioLog が 1 日 1 件のレコードに記録する健康の数値。

- **収縮期血圧 / 拡張期血圧**：血圧の「上」と「下」。心臓が縮んで血を押し出した瞬間が
  収縮期（上）、力を抜いて広がったときが拡張期（下）。
- **体脂肪率**：体重に占める脂肪の割合（%）。
- **筋肉量**：体内の筋肉の重さ（kg）。
- **基礎代謝**：何もせずじっとしていても消費されるエネルギー量（kcal）。

いずれも入力は任意で、空欄のままにした項目は既存の値がそのまま残る。

#### UTC / JST

- **UTC（協定世界時）**：世界共通の基準時刻。
- **JST（日本標準時）**：日本の時刻。UTC より 9 時間進んでいる（UTC+9）。

Docker のコンテナは何も指定しないと UTC で動くため、
日本の深夜 0〜9 時に登録すると「前日」の日付として記録されてしまう問題があった。
BioLog は日付を JST 基準で決める処理（`jst_date()`）に統一し、
さらにコンテナの時刻設定（`Asia/Tokyo`）もそろえてこれを解消している。

#### `Asia/Tokyo`（タイムゾーン指定）

コンテナの時刻を日本時間に合わせるための設定値。
`docker-compose.yml` の環境変数で API と画面の両方に指定されている。

#### created_at / updated_at

- **created_at**：そのレコードが最初に作られた日時。BioLog では自動的に記録される。
- **updated_at**：最後に更新された日時。**BioLog では未実装**。

このため、レコードを修正しても `created_at` は変わらず、
「いつ変更されたか」は残らない。README が「監査ログ用途には不十分」としているのはこの点。

#### 監査ログ

誰がいつ何を変更したかを、後から追跡できるように残す記録。

#### CSV / UTF-8 / BOM

- **CSV**：値をカンマ区切りで並べた、表計算ソフトで開ける単純なファイル形式。
- **UTF-8**：世界中の文字を扱える文字コード（文字の表現方式）。
- **BOM（Byte Order Mark）**：ファイル先頭に付ける短い目印。

Excel は BOM が無い UTF-8 の CSV を開くと日本語が文字化けすることがあるため、
BioLog は **BOM 付き UTF-8** で CSV を出力し、そのまま Excel で開けるようにしている。

#### CSV の数式無害化

表計算ソフトは、セルの内容が `=` や `+` で始まると**計算式として実行**してしまう。
悪意ある文字列が CSV に混ざっていた場合、開いただけで意図しない動作をする恐れがある。

BioLog は `=` `+` `-` `@` で始まる文字列を、そのまま文字として扱われる形に変換してから
CSV へ書き出している。

#### ダミーデータ

説明や画面例のために用意した、実在しない仮のデータ。
README のスクリーンショットに写っている数値はすべてこれ。

---

### セキュリティ

#### 認証（authentication）

利用しようとしている相手が誰なのかを確認し、許可された人だけ通す仕組み。

**BioLog には認証機能がありません。** URL を開ければ誰でも全データを閲覧・変更できます。
これは「同じ PC からしか開けない」前提で、意図的に実装していないものです。

#### API キー / Basic 認証 / OAuth

認証のやり方の代表例。

- **API キー**：あらかじめ決めた秘密の文字列を要求に添えて本人確認する方式。
- **Basic 認証**：ブラウザがユーザー名とパスワードの入力を求める、最も単純な方式。
- **OAuth**：Google アカウントなど外部サービスの認証結果を借りる方式。

いずれも BioLog では未実装。

#### CORS（Cross-Origin Resource Sharing）／クロスオリジン／オリジン

**オリジン**とは「どのサイトから来たか」を表す、
アドレスの `http://localhost:8501` の部分（プロトコル・ホスト・ポートの組）のこと。

ブラウザは安全のため、あるオリジンのページから別オリジンの API を呼ぶことを
標準で禁止している。CORS はそれを例外的に許可するための仕組み。

BioLog は **CORS の許可設定を入れていない**ため、
他のサイトのページから BioLog の API を直接呼び出すことはできない。

#### HTTPS / TLS

- **TLS**：通信内容を暗号化し、途中で盗み見・改ざんされないようにする技術。
- **HTTPS**：HTTP に TLS を組み合わせたもの。アドレスが `https://` で始まる。

BioLog は同一 PC 内での利用を前提としているため HTTPS を前提としていない。
外部から使える場所に置く場合は、前段のリバースプロキシ側で用意する必要がある。

#### レート制限（rate limit）

短時間に大量の要求が来たときに、受付を制限する仕組み。
BioLog では未実装。

#### ファイアウォール

通信を許可・遮断して、接続元を制限する仕組み。

README では、LAN 内の別端末から BioLog を使う場合でも、
ファイアウォール等で接続元を絞ることを求めている。

#### Cloudflare Access / Tailscale

BioLog の前段に置く認証層の実例として README に挙げられているサービス。

- **Cloudflare Access**：アプリの手前で本人確認を行うサービス。
- **Tailscale**：離れた端末同士を、閉じた仮想的なネットワークで安全につなぐサービス。

---

### 開発・運用

#### Git（ギット）／GitHub（ギットハブ）／clone（クローン）

- **Git**：ファイルの変更履歴を記録・管理する仕組み。
- **GitHub**：Git で管理したものをインターネット上に置いて共有するサービス。
- **clone**：GitHub 上のものを自分の PC へ複製すること。

README の `git clone https://github.com/shinosan1/biolog.git` は、
BioLog 一式を自分の PC へ取得するコマンド。

#### リポジトリ（repository）

Git が管理している、プロジェクト 1 つ分のファイルと履歴のまとまり。「置き場」の意味。
README の「リポジトリ直下」は、この置き場の一番上の階層を指す。

#### Issues / Pull Request（PR）

GitHub 上でのやり取りの仕組み。

- **Issues**：不具合報告や要望を書き込む場所。
- **Pull Request**：自分が書いた変更を「取り込んでほしい」と提案する仕組み。

BioLog は個人プロジェクトのため Pull Request の対応保証はなく、
設計変更はまず Issues での議論を求めている。

#### CHANGELOG（変更履歴）／バージョン番号

- **CHANGELOG**：どの版で何を変えたかを記録したファイル。
- **バージョン番号**：`v1.5.5` のような版の番号。README の Known Issues にある
  「v1.5.5 で〜」という記述は、その版で修正されたことを示す。

#### MIT License

ソフトの利用条件を定めたライセンスのひとつ。著作権表示を残せば、
商用利用・改変・再配布を広く認める、制約の緩い形式。BioLog はこれを採用している。

#### Roadmap（ロードマップ）

今後の予定や未着手のタスクを並べたもの。
BioLog の Roadmap に挙がっている項目は優先度が低く、現状で実害はないと明記されている。
先頭の `M1` `M2` `L1` は、監査で付けられた項目の識別子（M は中程度、L は低い優先度）。

#### Claude Code

Anthropic 社が提供する、AI を使った開発支援ツール。
BioLog では設計の議論や実装の一部に併用したことが Acknowledgments に記載されている。

---

## License

[MIT License](LICENSE.md) © 2026 [shinosan1]

---

## Acknowledgments

- 設計議論・実装の一部は Claude Code (Anthropic) を併用しています
