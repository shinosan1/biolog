# BioLog — プロジェクト機能まとめ

## 1. アーキテクチャ概要

```
Streamlit (8501)
    │  HTTP (requests)
    ▼
FastAPI / api.py (8766)
    │  書き込み: Queue (maxsize=100) 経由のみ
    │  読み取り: biocore.py → db_manager 直接 SELECT
    ▼
Worker (1スレッド固定)
    │
    ▼
write_repository.py
    │  INSERT / UPDATE / DELETE SQL
    │
    ▼
db_manager.py  ← DB への唯一の入口
    │
    ▼
biolog.db (health_records テーブル)
```

### 絶対ルール

| # | ルール |
|---|---|
| 1 | SQLite 書き込みは **Worker のみ**。FastAPI・Streamlit から直接 INSERT/UPDATE/DELETE 禁止 |
| 2 | `sqlite3.connect()` は `db_manager.py` 以外で呼ばない |
| 3 | `PRAGMA journal_mode=WAL` 禁止（Windows NTFS バインドマウント非互換）。必ず `DELETE` |
| 4 | Worker スレッドは **1本のみ**（並列禁止） |
| 5 | Queue は **global singleton 1個のみ** |
| 6 | `write_repository.py` は FastAPI / Queue / worker loop を import しない。SQL 実行のみ |

---

### 1-1. 現在の主要モジュール構成

#### API 側

| ファイル | 責務 |
|---|---|
| `api.py` | FastAPI endpoint、HTTP error 変換、worker 起動 |
| `queue_manager.py` | 書き込み Queue singleton |
| `worker.py` | Queue 消費、retry、operation dispatch、worker log |
| `write_repository.py` | `health_records` の INSERT / UPDATE / DELETE SQL |
| `biocore.py` | 読み取り専用 SELECT |
| `db_manager.py` | SQLite connection / transaction 境界 |
| `schemas.py` | Pydantic validation |
| `preprocess.py` | request_id/date 補完、整数系型補正、blood_pressure 分解 |

#### Streamlit 側

| ファイル | 責務 |
|---|---|
| `streamlit_app.py` | 起動入口、sidebar、tab 呼び出し |
| `api_client.py` | HTTP GET / POST / PUT / DELETE |
| `cache.py` | `@st.cache_data` 付き取得関数と cache clear |
| `charts.py` | Matplotlib グラフ描画 |
| `form_fields.py` | 測定項目定義と表示順 / layout group |
| `form_components.py` | Streamlit 入力部品の共通描画 |
| `payloads.py` | create/update payload 作成 |
| `views/*.py` | summary / graph / list / create / edit の各画面 |

---

## 2. DB スキーマ（health_records テーブル）

```sql
CREATE TABLE IF NOT EXISTS health_records (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id   TEXT    NOT NULL UNIQUE,              -- 冪等性キー (UUID)
    date         TEXT    NOT NULL,
    user_id      TEXT    NOT NULL,
    temperature  REAL,   -- 34.0 〜 42.0 ℃
    pulse        INTEGER, -- 30 〜 200 bpm
    systolic_bp  INTEGER, -- 50 〜 250 mmHg
    diastolic_bp INTEGER, -- 30 〜 150 mmHg
    weight       REAL,   -- 0 < x < 300 kg
    body_fat     REAL,   -- 0 〜 100 %
    muscle_mass  REAL,   -- 0 < x < 200 kg
    bmr          INTEGER, -- 0 < x < 5000 kcal
    meal_detail  TEXT,   -- 食事ログ（長文可、UI で expander 展開）
    activity_log TEXT,   -- 行動ログ（長文可、UI で expander 展開）
    memo         TEXT    NOT NULL DEFAULT '',
    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
```

- `request_id` UNIQUE → 同一 UUID での二重 INSERT は **成功扱い**（冪等）
- 計測値はすべて NULL 許容。ただし POST 時は **1フィールド以上の入力必須**

---

## 3. API エンドポイント一覧

ベース URL: `http://localhost:8766`（コンテナ外から）/ `http://biolog-api:8766`（コンテナ間通信）

### 3-1. ヘルスチェック

```
GET /api/health/health
```

レスポンス例:
```json
{"status": "ok", "db": "/data/biolog.db"}
```

---

### 3-2. 健康記録の登録

```
POST /api/health/record
Content-Type: application/json
```

#### リクエスト JSON（`HealthRecordCreate`）

| フィールド | 型 | 必須 | 説明 |
|---|---|---|---|
| `user_id` | string | **必須** | `"self"` / `"father"` / `"mother"` |
| `request_id` | string | 省略可 | UUID。省略時は自動生成。**冪等キー** |
| `date` | string | 省略可 | `"YYYY-MM-DD"` 形式。省略時は今日 |
| `temperature` | float | ※1 | 体温 (34.0〜42.0 ℃) |
| `pulse` | int | ※1 | 脈拍 (30〜200 bpm) |
| `systolic_bp` | int | ※1 | 収縮期血圧 (50〜250 mmHg) |
| `diastolic_bp` | int | ※1 | 拡張期血圧 (30〜150 mmHg) |
| `weight` | float | ※1 | 体重 (0〜300 kg) |
| `body_fat` | float | ※1 | 体脂肪率 (0〜100 %) |
| `muscle_mass` | float | ※1 | 筋肉量 (0〜200 kg) |
| `bmr` | int | ※1 | 基礎代謝 (0〜5000 kcal) |
| `meal_detail` | string | 省略可 | 食事ログ（長文可、`null` 許容） |
| `activity_log` | string | 省略可 | 行動ログ（長文可、`null` 許容） |
| `memo` | string / null | 省略可 | メモ（`null` 許容。保存時は空文字として扱う） |

※1: 計測値は全て省略可。計測値、`meal_detail`、`activity_log`、`memo` のうち、
**最低1つに有効な値が必須**。全て省略、`null`、空文字、空白のみの場合は 422 エラー。

同一ユーザー・同一日付へ POST した場合、`meal_detail` と `activity_log` は既存内容へ
改行区切りで追記されます。完全一致する改行単位の項目は重複追加されません。
`memo` は最新の非空値で置換されます。PUT による編集は各項目を全文置換します。

リクエスト例:
```json
{
  "user_id": "self",
  "date": "2026-05-06",
  "temperature": 36.5,
  "pulse": 72,
  "systolic_bp": 120,
  "diastolic_bp": 80,
  "weight": 65.2,
  "memo": "朝食後",
  "meal_detail": "朝: 食パン1枚、ヨーグルト、コーヒー / 昼: 鶏胸肉サラダ",
  "activity_log": "散歩 30 分、階段昇降 5 回"
}
```

レスポンス例（201 Created）:
```json
{"message": "登録完了", "id": 1}
```

冪等レスポンス（同一 `request_id` を再送した場合）:
```json
{"message": "登録完了", "idempotent": true}
```

バリデーションエラー（422）:
```json
{
  "detail": [
    {"loc": ["body", "temperature"], "msg": "temperature must be between 34.0 and 42.0 °C"}
  ]
}
```

---

### 3-3. 健康記録の更新

```
PUT /api/health/record/{record_id}
Content-Type: application/json
```

#### リクエスト JSON（`HealthRecordUpdate`）

更新したいフィールドのみ送信。全フィールド省略可（`null` / 省略で変更なし）。

```json
{
  "systolic_bp": 118,
  "diastolic_bp": 76,
  "memo": "再測定"
}
```

レスポンス例（200 OK）:
```json
{"message": "更新完了", "id": 3, "updated": 1}
```

レコードが存在しない場合（404）:
```json
{"detail": "Record 99 not found"}
```

---

### 3-4. 健康記録の削除

```
DELETE /api/health/record/{record_id}
```

レスポンス例（200 OK）:
```json
{"message": "削除完了", "id": 3, "deleted": 1}
```

---

### 3-5. 記録一覧の取得（ページング）

```
GET /api/health/records?user_id=self&limit=20&offset=0
```

| クエリパラメータ | 型 | 省略時 | 説明 |
|---|---|---|---|
| `user_id` | string | 全ユーザー | `"self"` / `"father"` / `"mother"` |
| `limit` | int | 20 | 取得件数（最大 500） |
| `offset` | int | 0 | スキップ件数（最大 10000） |

レスポンス例（200 OK）:
```json
[
  {
    "id": 1,
    "request_id": "550e8400-e29b-41d4-a716-446655440000",
    "date": "2026-05-06",
    "user_id": "self",
    "temperature": 36.5,
    "pulse": 72,
    "systolic_bp": 120,
    "diastolic_bp": 80,
    "weight": 65.2,
    "body_fat": null,
    "muscle_mass": null,
    "bmr": null,
    "meal_detail": "朝: 食パン1枚、ヨーグルト、コーヒー",
    "activity_log": "散歩 30 分",
    "memo": "朝食後",
    "created_at": "2026-05-06 09:00:00"
  }
]
```

---

### 3-6. 日付範囲で取得（グラフ用）

```
GET /api/health/records/range?start=2026-04-01&end=2026-05-06&user_id=father
```

| クエリパラメータ | 型 | 必須 | 説明 |
|---|---|---|---|
| `start` | string | **必須** | 開始日 `"YYYY-MM-DD"` （以上） |
| `end` | string | **必須** | 終了日 `"YYYY-MM-DD"` （以下、start と同日も含む） |
| `user_id` | string | 省略可 | 省略時は全ユーザー |

結果は `date ASC` 順（グラフ描画向け）。

---

### 3-7. ユーザーの最新記録を1件取得

```
GET /api/health/records/latest/{user_id}
```

レスポンス例（200 OK）: 3-5 と同じ構造の単一オブジェクト。

レコードなし（404）:
```json
{"detail": "No records for user_id=mother"}
```

---

## 4. biocore.py — Python から直接データを取得する

`biocore` は **読み取り専用** のクエリ集。`db_manager.get_connection(read=True)` 経由でのみ DB にアクセスする。

### 4-1. 一覧取得（ページング）

```python
from biocore import get_health_records

# 全ユーザー、最新20件
records = get_health_records(limit=20, offset=0)

# 父のデータ、2ページ目
records = get_health_records(user_id="father", limit=20, offset=20)
```

制約:
- `limit` > 500 → `ValueError`
- `offset` > 10000 → `ValueError`
- 結果は `date DESC, id DESC` 順

---

### 4-2. 日付範囲取得（グラフ・集計用）

```python
from biocore import get_health_records_by_date_range

# 自分の過去30日分
records = get_health_records_by_date_range(
    start_date="2026-04-06",
    end_date="2026-05-06",
    user_id="self",
)

# 全員の指定期間
records = get_health_records_by_date_range(
    start_date="2026-01-01",
    end_date="2026-05-06",
)
```

結果は `date ASC, id ASC` 順（時系列グラフに使いやすい）。

---

### 4-3. 最新1件取得

```python
from biocore import get_latest_record

record = get_latest_record("mother")
if record:
    print(record["systolic_bp"], record["diastolic_bp"])
else:
    print("データなし")
```

---

### 4-4. 返却される辞書のキー一覧

```python
{
    "id":           int,
    "request_id":   str,       # UUID
    "date":         str,       # "YYYY-MM-DD"
    "user_id":      str,       # "self" / "father" / "mother"
    "temperature":  float | None,
    "pulse":        int   | None,
    "systolic_bp":  int   | None,
    "diastolic_bp": int   | None,
    "weight":       float | None,
    "body_fat":     float | None,
    "muscle_mass":  float | None,
    "bmr":          int   | None,
    "meal_detail":  str   | None,  # 食事ログ（長文可）
    "activity_log": str   | None,  # 行動ログ（長文可）
    "memo":         str,          # リクエストの null は保存時に空文字として扱う
    "created_at":   str,       # "YYYY-MM-DD HH:MM:SS"
}
```

---

## 5. Worker の構造化ログ

Worker は標準出力に JSON 形式でログを出す。

```json
{"ts": "2026-05-06T09:00:00+00:00", "op": "insert", "request_id": "550e...", "queue_size": 0, "retry": 0, "status": "success", "id": 1}
{"ts": "2026-05-06T09:00:01+00:00", "op": "insert", "request_id": "550e...", "queue_size": 0, "retry": 0, "status": "success", "idempotent": true}
{"ts": "2026-05-06T09:00:02+00:00", "op": "insert", "request_id": "abc1...", "queue_size": 3, "retry": 2, "status": "retry", "error": "database is locked"}
```

確認コマンド:
```powershell
docker logs biolog-api --follow
```

---

## 5-1. UI 表示順

### ホーム（直近データ）

各ユーザーカードの metric 表示順:

1. 体重
2. 体温
3. 収縮期血圧
4. 拡張期血圧
5. 脈拍

### 新規登録 / 修正フォーム

測定項目は `biolog_streamlit/form_fields.py` の `MEASUREMENT_FIELDS` で管理する。

| 左側 | 右側 |
|---|---|
| 体重 | 脈拍 |
| 体温 | 体脂肪率 |
| 収縮期血圧 | 基礎代謝 |
| 拡張期血圧 | 筋肉量 |

### グラフ

グラフタブの表示順:

1. 体重
2. 体温
3. 血圧（収縮期 / 拡張期を1グラフに統合）
4. 脈拍

---

## 6. Pydantic バリデーション範囲まとめ

| フィールド | 単位 | 下限 | 上限 | NULL 許容 |
|---|---|---|---|---|
| `temperature` | ℃ | 34.0 | 42.0 | ○ |
| `pulse` | bpm | 30 | 200 | ○ |
| `systolic_bp` | mmHg | 50 | 250 | ○ |
| `diastolic_bp` | mmHg | 30 | 150 | ○ |
| `weight` | kg | 0（超過） | 300（未満） | ○ |
| `body_fat` | % | 0.0 | 100.0 | ○ |
| `muscle_mass` | kg | 0（超過） | 200（未満） | ○ |
| `bmr` | kcal | 0（超過） | 5000（未満） | ○ |

範囲外の値は FastAPI が **422 Unprocessable Entity** を返し、Queue には積まれない。

---

## 7. トラブルシューティング

### コンテナが起動しない

```powershell
docker ps -a
docker logs biolog-api
docker logs biolog-streamlit
```

### DB パスが違う

```powershell
# ヘルスチェックで実際のパスを確認
curl http://localhost:8766/api/health/health
# → "db" フィールドが "/data/biolog.db" であること

# コンテナ内の DB ファイル位置を確認
docker exec biolog-api find / -name "biolog.db" 2>/dev/null
```

### WAL ファイルが残っている

```powershell
# ${BIOLOG_DATA_DIR} は docker-compose.yml の volume マウント先（デフォルト ./data）
# 存在してはいけないファイル
ls ${BIOLOG_DATA_DIR}\biolog.db-shm
ls ${BIOLOG_DATA_DIR}\biolog.db-wal

# 残っていれば削除（biolog-api 停止後）
Remove-Item "${BIOLOG_DATA_DIR}\biolog.db-shm" -Force
Remove-Item "${BIOLOG_DATA_DIR}\biolog.db-wal" -Force
```

### Queue が満杯（503）

Worker が停止しているか、書き込みが詰まっている。`docker logs biolog-api` でリトライ状況を確認する。`database is locked` が続く場合は、同じ DB ファイルに別 process（別ツール / 別 container）が並行アクセスしていないかを確認する。

---

## 8. テスト

開発用テスト依存:

```powershell
pip install -r requirements-test.txt
```

回帰テスト:

```powershell
python -m pytest -q
```

テスト方針:
- 実 DB `data/biolog.db` は読み書きしない
- repository / biocore テストは `tmp_path` 配下の一時 SQLite を使用
- `DATABASE_PATH` が実 DB を指す場合はテストを失敗させる
- request_id / date 補完などの変動値は `monkeypatch` で固定する

---

## 9. curl コマンド集

```powershell
# 登録（数値のみ）
curl -X POST http://localhost:8766/api/health/record `
  -H "Content-Type: application/json" `
  -d '{"user_id":"self","temperature":36.5,"pulse":72,"systolic_bp":120,"diastolic_bp":80}'

# 登録（食事ログ・行動ログ付き）
curl -X POST http://localhost:8766/api/health/record `
  -H "Content-Type: application/json" `
  -d '{"user_id":"self","weight":65.0,"meal_detail":"朝食: パン、卵","activity_log":"散歩 30 分"}'

# 一覧（自分、最新10件）
curl "http://localhost:8766/api/health/records?user_id=self&limit=10"

# 日付範囲（父、グラフ用）
curl "http://localhost:8766/api/health/records/range?start=2026-04-01&end=2026-05-06&user_id=father"

# 最新1件（母）
curl http://localhost:8766/api/health/records/latest/mother

# 更新（ID=3 の血圧を修正）
curl -X PUT http://localhost:8766/api/health/record/3 `
  -H "Content-Type: application/json" `
  -d '{"systolic_bp":118,"diastolic_bp":76}'

# 削除（ID=3）
curl -X DELETE http://localhost:8766/api/health/record/3
```
