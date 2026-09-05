# BioLog コード解説

ファイルごとに「何を担当し、どう動くか」をまとめた開発者向けの注釈書です。

- 対象: BioLog v1.7.5 相当（リポジトリ確認日 2026-08-15）
  - ただし「4.4 cache.py」と「2. 設計上の絶対ルール」のルール 9 は、
    v1.7.8 の三層 Cache Invalidation へ追随更新済み（2026-08-24）
- 「何ができるか」は [spec.md](spec.md)、「守るべき制約」はリポジトリ直下の `CLAUDE.md`（開発リポジトリのみ・非公開）を参照してください。本書はその2つの**間を埋める、コードの動作説明**です。

---

## 目次

1. [全体構成](#1-全体構成)
2. [設計上の絶対ルールと、それを守っているコード](#2-設計上の絶対ルールとそれを守っているコード)
3. [biolog_api — 書き込みと読み取りのAPI](#3-biolog_api--書き込みと読み取りのapi)
4. [biolog_streamlit — 画面](#4-biolog_streamlit--画面)
5. [データモデル](#5-データモデル)
6. [1件の登録を最初から最後まで追う](#6-1件の登録を最初から最後まで追う)
7. [tests — 何を守っているテストか](#7-tests--何を守っているテストか)
8. [起動と運用](#8-起動と運用)
9. [コードを読むときの注意点](#9-コードを読むときの注意点)

---

## 1. 全体構成

### コンテナは2つ、DBはファイル1つ

| 順序 | コンポーネント | 接続・役割 |
|---:|---|---|
| 1 | **`biolog-streamlit :8501`** | 閲覧・登録・修正を行うUI。HTTPでAPIへ接続 |
| 2 | **`biolog-api :8766`** | FastAPIによる読み取り・書き込みAPI |
| 3 | **`Queue(maxsize=100)`** | 書き込み要求を受け付けてworkerへ渡す |
| 4 | **worker スレッド × 1** | 書き込み処理を1本に直列化 |
| 5 | **`db_manager` → SQLite** | 共有DB `/data/biolog.db`へ保存 |

どちらのポートも `127.0.0.1` にバインドされており、同じ PC からのみ接続できます。

### 書き込みと読み取りで経路が違う

これが BioLog の設計の中心です。

| 種別 | 経路 | 実行スレッド |
|---|---|---|
| **書き込み**（登録・更新・削除） | API → Queue → **worker 1本** → `db_manager` → SQLite | worker スレッド |
| **読み取り**（一覧・グラフ・最新値） | API → `biocore` → `db_manager` → SQLite | リクエストのスレッド |

SQLite は同時書き込みに弱いため、**書き込みを1本のスレッドに直列化**しています。読み取りは並行して構いません。

### 依存関係

```
biolog_api/
  api.py ──┬─ preprocess.py ─ time_utils.py
           ├─ schemas.py
           ├─ queue_manager.py
           ├─ worker.py ─ write_repository.py ─┐
           ├─ biocore.py ───────────────────────┼─ db_manager.py ─ SQLite
           └─ log_utils.py                      ┘
  migrations/runner.py ─ versions/migrate_001_init.py（隔離接続。db_manager を使わない唯一の例外）

biolog_streamlit/
  streamlit_app.py ─┬─ views/summary.py ──── cache.py ──┐
                    ├─ views/graph.py ────── charts.py  ├─ api_client.py ─ HTTP
                    ├─ views/list_view.py ─┬ safe_table.py
                    │                      └ formatters.py, time_utils.py
                    ├─ views/create.py ────┬ form_components.py ─ form_state.py
                    └─ views/edit.py ──────┴ payloads.py ─ form_fields.py
                    └─ ui_style.py
```

---

## 2. 設計上の絶対ルールと、それを守っているコード

設計上の絶対ルールは10個あります（開発ルールの正本はリポジトリ直下の `CLAUDE.md`。開発リポジトリのみ・非公開）。**どのコードがそれを担保しているか**を対応させます。

| # | ルール | 実装上の担保 |
|---|---|---|
| 1 | 書き込み経路は1本 | `api.py:_enqueue_and_wait()` 以外に書き込み入口が無い |
| 2 | `sqlite3.connect()` は `db_manager.py` 以外で呼ばない | 例外は `migrations/runner.py` のみ（起動時に直列実行されるため競合しない） |
| 3 | `journal_mode=WAL` 禁止 | `db_manager.py` で `PRAGMA journal_mode=DELETE` を毎回設定 |
| 4 | worker は daemon 1本 | `api.py:_start_worker()` が `daemon=True` で1本だけ生成 |
| 5 | Queue は singleton 1個 | `queue_manager.py` にモジュールレベルの `_write_queue` 1個 |
| 6 | エンドポイント内でDB直接操作をしない | GET は全て `biocore` 経由。`api.py` に SQL は1行も無い |
| 7 | Streamlit から DB へ直接アクセスしない | `api_client.py` の HTTP のみ。`sqlite3` を import していない |
| 8 | `lifespan` に migration を書かない | `entrypoint.sh` が `runner.py` → `uvicorn` の順に直列実行 |
| 9 | キャッシュ無効化は `.clear()` + `data_version` + TTL の三層 | `cache.py:clear_health_caches()` が `.clear()` と `bump_data_version()` を両方呼ぶ |
| 10 | ログに PII を生で出さない | `log_utils.mask_pii()` を `api.py` と `worker.py` の全ログが通る |

**WAL 禁止の理由**は Windows の NTFS バインドマウントで I/O エラーになるためです。トラブル時に `.db-wal` / `.db-shm` が残っていないか確認する運用は、この制約から来ています。

---

## 3. biolog_api — 書き込みと読み取りのAPI

### 3.1 api.py — エンドポイントの定義（263行）

#### lifespan：worker の起動と停止

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    _worker_thread = _start_worker()          # daemon スレッド1本
    signal.signal(signal.SIGTERM, _handle_sigterm)
    yield
    _stop_worker(_worker_thread)              # None を積んで join(timeout=10)
```

停止は **`None` を Queue に積む**ことで通知します（sentinel 方式）。`worker_loop` は `None` を受け取るとループを抜けます。`SIGTERM` ハンドラも同じ処理を呼ぶので、`docker stop` でも安全に止まります。

#### `_enqueue_and_wait(operation, payload)` — 書き込みの唯一の入口

```python
result_q = SyncQueue()                        # このリクエスト専用の返信箱
task = {"operation":…, "request_id":…, "payload":…, "result_queue": result_q}
if q.full(): → 503 "Write queue is full"
q.put(task)
result = result_q.get(timeout=30)             # ← ここで待つ
```

リクエストごとに**返信用の Queue を作って task に同梱**し、worker がそこへ結果を投げ返します。これで「どのリクエストの結果か」を取り違えません。

worker から返る `error_kind` を HTTP ステータスへ変換します。

| `error_kind` | HTTP |
|---|---|
| `not_found` | 404 |
| `validation` | 422 |
| その他（`database` / `internal`） | 500 |
| Queue 満杯 / 30秒応答なし | 503 |

#### `POST /api/health/record` — 登録

このエンドポイントだけ**リクエストボディを Pydantic で直接受け取らず、生の JSON を読みます**。

```python
raw = await request.json()          # 生のまま受ける
preprocessed = pp.preprocess_record(raw)   # ← 先に正規化する必要がある
record = HealthRecordCreate(**preprocessed)  # その後で検証
```

理由は、`request_id` や `date` の欠損補完、`blood_pressure` 文字列の分解を**検証より前**に行う必要があるためです。Pydantic を先に通すと `extra="forbid"` で `blood_pressure` が弾かれてしまいます。

処理の各段階で構造化ログを出します（すべて `mask_pii` を通過）。

```
REQ_START → API_IN → API_ENRICH → PREPROCESS → UNKNOWN_KEYS
→ VALIDATION → API_PAYLOAD_KEYS → API_PAYLOAD_BEFORE_QUEUE → DB_WRITE → REQ_END
```

出力するのは**キー名だけで、値は出しません**。健康値がログに残らないようにするためです。

#### その他のエンドポイント

| メソッド | パス | 実装 |
|---|---|---|
| GET | `/api/health/health` | worker 生存 + DB 疎通 + Queue 空き状況 |
| POST | `/api/health/record` | Queue 経由で insert |
| PUT | `/api/health/record/{id}` | Queue 経由で update |
| DELETE | `/api/health/record/{id}` | Queue 経由で delete |
| GET | `/api/health/record/day` | `biocore.get_record_by_user_date` |
| GET | `/api/health/record/{id}` | `biocore.get_record_by_id` |
| GET | `/api/health/records` | 一覧（limit 1〜500, offset 0〜10000） |
| GET | `/api/health/records/range` | 期間指定 |
| GET | `/api/health/records/latest/{user_id}` | 最新1件 |

> **ルート定義順が意味を持ちます。** `/api/health/record/day` は `/api/health/record/{record_id}` より**前**に定義されています。逆にすると `"day"` が `record_id` として解釈され、常に 422 になります。並び替えないでください。

`/records/range` の日付検証は厳密です。

```python
start_date = date.fromisoformat(start)
if start_date.isoformat() != start:   # "2026-8-1" のようなゼロ埋め無しを弾く
    → 422
if start_date > end_date:             # 逆転を弾く
    → 422
```

#### ヘルスチェックの判定

```python
worker_alive and database_ok  → queue.full() なら "degraded"、そうでなければ "ok"
どちらか欠ける                → "unhealthy"
```

`docker-compose.yml` のヘルスチェックは `status == "ok"` のみを成功とみなします。`degraded` はコンテナ的には異常扱いです。

---

### 3.2 queue_manager.py — たった7行の要（7行）

```python
_write_queue: Queue = Queue(maxsize=100)
def get_queue() -> Queue: return _write_queue
```

モジュールレベルの変数なので、同一プロセス内では**必ず同じ1個**が返ります。`maxsize=100` に達すると API が 503 を返し、worker が止まっていることを検知できます。

---

### 3.3 worker.py — 書き込みを直列化するスレッド（139行）

#### メインループ

```python
while True:
    task = q.get()
    if task is None: break            # 停止指示
    try:
        result = _execute_with_retry(task, q)
        result_queue.put({"status": "success", **result})
    except sqlite3.OperationalError as e: → "database"
    except ValueError as e:               → "not found" を含むなら "not_found"、他は "validation"
    except Exception as e:                → "internal"
    finally:
        q.task_done()
```

**重要な性質: 1件の失敗で worker は死にません。** すべての例外を捕まえて結果 Queue にエラーを返し、次のタスクへ進みます。`tests/test_worker_resilience.py` がこれを検証しています（存在しないIDの更新・削除の後に、次の insert が通ること）。

#### エラーメッセージを外に出さない

```python
public_messages = {
    "not_found":  "Record not found",
    "validation": "Invalid write request",
    "database":   "Database operation failed",
    "internal":   "Worker operation failed",
}
```

クライアントには**この4種類の固定文言しか返しません**。例外の実メッセージ（テーブル名・パス・SQL断片を含みうる）はログにのみ残り、例外の型名だけが記録されます。

#### ロック時の再試行

```python
max_retry = 5, delay = 0.1 → 0.2 → 0.4 → 0.8（指数バックオフ）
if "database is locked" not in str(e): raise    # ロック以外は即座に投げ直す
```

再試行するのは**ロック競合だけ**です。型エラーや制約違反を5回繰り返しても無駄なので、即座に失敗させます。

---

### 3.4 write_repository.py — SQL を書く唯一の場所（書き込み側・152行）

#### `insert_record()` は insert ではなく **upsert**

```sql
INSERT INTO health_records (…) VALUES (…)
ON CONFLICT(user_id, date) DO UPDATE SET
    request_id   = excluded.request_id,
    temperature  = COALESCE(excluded.temperature, health_records.temperature),
    …
    meal_detail  = COALESCE(NULLIF(excluded.meal_detail, ''), health_records.meal_detail),
    memo         = COALESCE(NULLIF(excluded.memo, ''), health_records.memo)
```

同じ「ユーザー×日付」が既にあれば **UPDATE に化けます**（`uidx_hr_user_date` の UNIQUE 制約が引き金）。

**値の保護のしかたが数値とテキストで違います。**

| 種別 | SQL | 意味 |
|---|---|---|
| 数値8項目 | `COALESCE(excluded.X, 既存.X)` | **NULL なら既存値を残す** |
| テキスト3項目 | `COALESCE(NULLIF(excluded.X, ''), 既存.X)` | **NULL または空文字なら既存値を残す** |

つまり、体重だけ送信すれば他の項目は消えません。空文字を送っても既存のメモは消えません。**API 経由で値を消す手段は無い**、というのが現在の仕様です。

#### `_merge_log_entries()` — ログは上書きではなく追記

登録前に既存の `meal_detail` / `activity_log` を SELECT し、**行単位で重複を除いて追記**します。

```python
既存 = {"朝食: パン", "昼食: そば"}
新規 = "昼食: そば\n夕食: カレー"
結果 = "朝食: パン\n昼食: そば\n夕食: カレー"    # 「昼食: そば」は重複なので足さない
```

- 改行コードは `\r\n` `\r` を `\n` に正規化してから比較
- 比較は `strip()` 済みの文字列で行うが、**追記される行は元の形のまま**
- 部分一致は別行として扱う（「そば」と「昼食: そば」は別物）

**同じ日に何度も登録すると、食事ログと行動ログは積み上がっていきます。** 数値は上書き、ログは追記、という非対称な設計です。

#### 冪等性（request_id 衝突）

```python
except sqlite3.IntegrityError as e:
    if "request_id" in str(e).lower():
        row = SELECT id FROM health_records WHERE request_id = ?
        return {"idempotent": True, "id": row[0]}
    raise
```

`request_id` は UNIQUE です。ネットワーク再送などで同じ `request_id` が二度届いても、**新しい行を作らず既存の id を返します**。それ以外の `IntegrityError` はそのまま投げ直します。

#### `update_record()` — ホワイトリスト方式

```python
_ALLOWED = {"temperature": float, "pulse": int, …, "meal_detail": str}
for k, v in payload.items():
    if k in _ALLOWED and v is not None:
        fields[k] = _ALLOWED[k](v)     # 型変換。失敗は ValueError
if not fields: raise ValueError("No fields to update")
```

- `_ALLOWED` に無いキーは**黙って無視**されます。`date` や `user_id` は含まれないので、**更新で日付や人を変えることはできません**
- `None` は「更新しない」の意味なのでスキップ
- 更新対象が0件なら `ValueError` → 422
- `rowcount == 0`（ID が存在しない）なら `ValueError("… not found")` → 404
- SET 句は `_ALLOWED` のキーからのみ組み立てるため、キー名が SQL に混入する経路はありません（値は必ずプレースホルダ）

#### `delete_record()`

ID 指定で1行削除。`rowcount == 0` なら `ValueError("Record N not found")` → 404。

---

### 3.5 biocore.py — SQL を書く唯一の場所（読み取り側・128行）

#### 読み取り専用の再試行

```python
def _execute_read(query, params=(), *, one=False):
    delays = (0.1, 0.2)
    for attempt in range(3):
        try:
            with get_connection(read=True) as conn: …
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower() or attempt == 2: raise
            time.sleep(delays[attempt])
```

**最大3回**（初回＋2回の再試行）。合計待ち時間は 0.3 秒以内です。worker 側（最大5回・指数バックオフ）より軽く設定されており、読み取りが画面を長く待たせないようになっています。ロック以外のエラーは即座に投げます。

#### クエリ一覧

| 関数 | 並び順 | 備考 |
|---|---|---|
| `check_database()` | — | `SELECT 1` の疎通確認のみ |
| `get_health_records()` | `date DESC, id DESC` | limit/offset を**関数内でも再検証** |
| `get_health_records_by_date_range()` | `date ASC, id ASC` | グラフ用に古い順 |
| `get_record_by_id()` | — | 1件 |
| `get_record_by_user_date()` | — | 1件 |
| `get_latest_record()` | `date DESC, id DESC LIMIT 1` | サマリーカード用 |

`limit` / `offset` の範囲チェックは FastAPI の `Query(ge=…, le=…)` と `biocore` の両方にあります。**API を経由しない呼び出しでも守られる**ようにするための二重化です。

> `get_record_by_user_date()` だけ `SELECT *` を使っています（他は `HEALTH_RECORD_COLUMNS` を明示）。列を追加したとき、この関数だけ返却内容が自動的に増えます。

---

### 3.6 db_manager.py — DB接続の唯一の入口（43行）

```python
DATABASE_PATH = os.getenv("DATABASE_PATH")
if not DATABASE_PATH: raise RuntimeError("DATABASE_PATH is not set")
```

**import された時点で環境変数が無ければ即座に落ちます。** 設定漏れのまま中途半端に動くことを防ぎます。

```python
@contextmanager
def get_connection(*, read=False, write=False):
    if read == write: raise ValueError("Specify exactly one of read=True or write=True")
```

`read` と `write` を**必ずどちらか一方**指定させます。両方 True も両方 False もエラーです。呼び出し側が意図を明示せざるを得ない設計です。

| 設定 | 値 | 理由 |
|---|---|---|
| `timeout` | 1.0 秒 | 接続時のロック待ち |
| `isolation_level` | `None` | 自動コミット。トランザクションは明示的に張る |
| `text_factory` | `str` | 日本語の文字化け防止 |
| `row_factory` | `sqlite3.Row` | 列名でアクセス可能に |
| `PRAGMA journal_mode` | **DELETE** | WAL は Windows バインドマウントで壊れる |
| `PRAGMA busy_timeout` | 1000 ms | ロック時の待機 |
| `PRAGMA foreign_keys` | ON | — |

書き込み時のみ **`BEGIN IMMEDIATE`** を発行します。読み取りロックから書き込みロックへの昇格時に起きるデッドロックを避けるため、**最初から書き込みロックを取ります**。成功で `commit()`、例外で `rollback()`、いずれにせよ `finally` で `close()`。

---

### 3.7 schemas.py — Pydantic による入力検証（199行）

```python
model_config = ConfigDict(extra="forbid")   # 未知のキーは 422
```

#### 検証範囲

| 項目 | 範囲 |
|---|---|
| `temperature` | 34.0 〜 42.0 |
| `pulse` | 30 〜 200 |
| `systolic_bp` | 50 〜 250 |
| `diastolic_bp` | 30 〜 150 |
| `weight` | 0 < v < 300 |
| `body_fat` | 0.0 〜 100.0 |
| `muscle_mass` | 0 < v < 200 |
| `bmr` | 0 < v < 5000 |
| `user_id` | `self` / `father` / `mother` のみ |
| `date` | 実在する `YYYY-MM-DD`（`isoformat()` との往復一致で検証） |

テキスト長の上限は `meal_detail` 10000 / `activity_log` **20000** / `memo` 10000 文字。行動ログだけ倍あります。

#### `at_least_one_health_value` — 空レコードの拒否

```python
@model_validator(mode="after")
def at_least_one_health_value(self):
    has_measurement = 数値8項目のいずれかが not None
    has_text_log = テキスト3項目のいずれかが strip() して非空
    if not has_measurement and not has_text_log: raise ValueError(…)
```

数値が全部 None かつテキストが全部空なら登録できません。

#### `HealthRecordUpdate` は Create と別物

- `request_id` / `date` / `user_id` を**持ちません**。したがって PUT で日付や人を変更できません
- `exclude_unset=True` で `model_dump()` されるため、**送信されなかった項目は payload に現れません**（`write_repository` 側の「更新しない」判定と噛み合っています）

> **層の役割分担**（ファイル冒頭のコメントより）: API 層のバリデーションは UX 目的で、422 を即座に返すためのもの。DB の CHECK 制約は最終防衛ラインで、絶対条件のみ。
> なお現在の `migrate_001_init.py` に数値レンジの CHECK 制約はありません（NOT NULL と UNIQUE のみ）。数値範囲の担保は実質 API 層のみです。書き込み経路が worker 1本に限定されているため実用上は問題になりませんが、DB を直接操作する場合は範囲が守られない点に注意してください。

---

### 3.8 preprocess.py — 構文の正規化だけを行う層（50行）

冒頭のコメントで**許される変換が3種類に限定**されています。

```
1. 型補正       float → int
2. 構造補完     UUID / date の欠損補完
3. 構文クリーンアップ  BP 文字列の分解
これ以外（意味変換・カテゴリ化・単位変換・推論）は別層に追加すること
```

#### 1. 欠損補完

```python
if not data.get("request_id"): data["request_id"] = str(uuid.uuid4())
if not data.get("date"):       data["date"] = jst_date()     # JST の今日
```

日付は**必ず JST 基準**です。コンテナの TZ に関わらず `time_utils.JST`（UTC+9 固定）で計算します。

#### 2. 型補正

```python
invalid_fields = []
for field in ("pulse", "bmr", "systolic_bp", "diastolic_bp"):
    v = data.get(field)
    if v is not None:
        try:
            data[field] = int(float(v))
        except (ValueError, TypeError, OverflowError):
            invalid_fields.append(field)
if invalid_fields:
    raise ValueError("Invalid number format: " + ", ".join(invalid_fields))
```

整数フィールドに `72.0` や `"1400.0"` のような float が来ても通します。

**数値として解釈できない値は `ValueError` になり、`api.create_record` が 422 に変換します。** 不正な項目名はすべて列挙されます（例: `Invalid number format: pulse, bmr`）。`None` は「未入力」として維持され、エラーにはなりません。

> **`OverflowError` を個別に捕捉している理由:** `"inf"` `"-inf"` `"Infinity"` `"1e309"` は `float()` までは成功し、`int()` で `OverflowError` になります。`OverflowError` は `ValueError` の派生ではない（基底は `ArithmeticError`）ため、この3つ目を書かないと API 層の `except ValueError` も素通りして **500 になります**。Python の `json.loads` は `Infinity` / `NaN` リテラルを受理するので、JSON ボディ経由で実際に到達しうる経路です。なお `"nan"` は `int()` で `ValueError` になります。

> 以前は変換失敗時に `data[field] = None` として黙って値を捨てていました。その場合、体重と脈拍を送って脈拍だけが不正だと、**脈拍が無かったことにされて体重だけが保存**されていました。入力ミスに気付けないため、422 で全体を拒否する方式に変更しています。

#### 3. 血圧文字列の分解

```python
bp = data.pop("blood_pressure", None)
bp = re.sub(r'[－–—-]', '/', bp)        # 各種ハイフンを / に統一
bp = re.sub(r'[^\d/\s]', '', bp)        # 数字・/・空白以外を除去（"mmHg" が消える）
parts = re.split(r'[/ ]+', bp)
data.setdefault("systolic_bp",  int(float(parts[0])))
data.setdefault("diastolic_bp", int(float(parts[1])))
```

`"110/75"` `"110－75"` `"110/75mmHg"` `"110 75"` に対応します。

- 区切りは `[/ ]+` なので、`"110//75"` のように区切り文字が連続していても2要素に分かれ、正しく変換されます
- **`pop`** しているので `blood_pressure` キーは消え、`extra="forbid"` に引っかかりません
- **`setdefault`** なので、`systolic_bp` が明示的に指定されていればそちらが優先されます

**有効な2つの数値へ変換できない場合は、例外にせず黙って無視します。**（要素数が2でない、または数値変換に失敗した場合）。整数項目の型変換失敗が 422 になるのとは扱いが異なります。詳細と例外は第9章の注記を参照してください。

`meal_detail` / `activity_log` は**一切触らずに通過**します（コメントで「変換・結合禁止」と明記）。結合は `write_repository` の責務です。

---

### 3.9 time_utils.py / log_utils.py

#### time_utils.py（17行）

```python
JST = timezone(timedelta(hours=9))     # zoneinfo ではなく固定オフセット
def jst_date() -> str: return now_jst().date().isoformat()
```

日本には夏時間が無いため固定オフセットで十分です。Streamlit 側の `time_utils.py` は `ZoneInfo("Asia/Tokyo")` を使っており、**API 側と実装が違います**（結果は同じ）。

#### log_utils.py（26行）

`mask_pii(text)` が以下を `****` に置換します。

| 対象 | パターン |
|---|---|
| `user_id` | JSON形式 `"user_id": "…"` と `user_id=…` の両方 |
| `request_id` | 同上 |
| UUID | `8-4-4-4-12` の16進 |
| 32桁の16進 | ハッシュ想定 |
| メールアドレス | `***@***` |

`api.py` の `log()` と `worker.py` の `_log()` は**全出力がこれを通ります**。ただし**マスクしているのは識別子であって、健康値そのものは元々ログに出していません**（キー名のみ出力する設計）。`tests/test_security_boundaries.py` がこれを検証しています。

---

### 3.10 migrations/ — スキーマ管理

#### runner.py（126行）

```
_acquire_lock()  → migration_lock テーブルに1行 INSERT（多重実行の防止）
_get_applied()   → schema_migrations テーブルから適用済みIDを取得
_load_versions() → versions/migrate_*.py を番号順に動的 import
pending だけを BEGIN IMMEDIATE → run(conn) → INSERT schema_migrations → commit
_release_lock()  → finally で必ず解放
```

- **ロックが残ると次回以降スキップされます。** その場合はメッセージ通り `DELETE FROM migration_lock WHERE id = 1` を手動実行します（`CLAUDE.md` のデバッグチェックリストにも項目があります）
- 各マイグレーションは**1件ずつコミット**されます。3件目で失敗しても1〜2件目は適用済みのまま残ります
- `sqlite3.connect()` を直接呼ぶ、`db_manager` を通さない唯一の場所です。起動時に `uvicorn` より前に直列実行されるため、worker と競合しません

#### versions/migrate_001_init.py（56行）

3つのブロックに分かれています。

| ブロック | 内容 | 意図 |
|---|---|---|
| `_DDL_CREATE` | `CREATE TABLE IF NOT EXISTS health_records` | 新規環境用 |
| `_DDL_MIGRATE` | `ALTER TABLE … ADD COLUMN`（3列） | 旧 DB 用。`duplicate column name` は握りつぶす |
| `_DDL_INDEXES` | インデックス2本 | 両方の環境で必要 |

> ファイル内のコメントに「**CREATE TABLE と ALTER TABLE は環境差吸収のため両方残す（削除・統合禁止）**」と明記されています。冗長に見えても消さないでください。

作られるインデックス:

```sql
CREATE INDEX        idx_hr_user_date  ON health_records(user_id, date DESC)  -- 検索用
CREATE UNIQUE INDEX uidx_hr_user_date ON health_records(user_id, date)       -- 1日1件の保証
```

**`uidx_hr_user_date` が `ON CONFLICT(user_id, date)` の対象**であり、upsert が成立する根拠です。

`created_at` の既定値は `datetime('now','localtime')` で、**コンテナの TZ 設定に依存します**。これが次項の `LEGACY_UTC_MAX_RECORD_ID` の原因です。

---

## 4. biolog_streamlit — 画面

### 4.1 streamlit_app.py — 入口（90行）

Streamlit は**操作のたびにスクリプト全体を上から再実行**します。この構造を理解していないとコードが読めません。

```python
st.set_page_config(…)
inject_number_input_styles()        # CSS 注入（1回だけ）
with st.sidebar:  … フィルター・更新ボタン・ヘルスチェック
render_summary()                    # サマリーカード
tab_graph, tab_list, tab_create, tab_edit = st.tabs([…])
with tab_graph: render_graph(selected_users, date_start, date_end)
with tab_list:  render_list(…)
with tab_create: render_create()
with tab_edit:  render_edit()
```

> **4つのタブは毎回すべて実行されます。** タブは表示の切り替えであって、遅延実行ではありません。したがって「一覧タブを開いていなくても一覧のAPI呼び出しは走る」ことになります。

サイドバーの「更新」ボタンは `clear_health_caches()` → `st.rerun()` の順で、キャッシュを捨ててから再描画します。

> **注記:** ヘルスチェックボタンは `st.success(f"OK — {r.get('db','')}")` を表示しますが、現在の API のレスポンスに `db` キーはありません（返るのは `status` / `worker_alive` / `database_ok` / `queue`）。そのため常に「OK — 」と空欄で表示されます。API 疎通の確認としては機能しています。

> **注記:** 開始日の既定は `date.today()`（システムのタイムゾーン）、終了日は `datetime.now(JST).date()` と実装が異なります。コンテナは `TZ=Asia/Tokyo` なので実運用では一致します。

---

### 4.2 config.py — 設定と定数（11行）

```python
API_BASE = os.getenv("BIOLOG_API_URL", "http://localhost:8766")
LEGACY_UTC_MAX_RECORD_ID = 146
USER_LABELS = {"self": "自分", "father": "父", "mother": "母"}
USER_COLORS = {"self": "#1f77b4", "father": "#2ca02c", "mother": "#d62728"}
```

**`LEGACY_UTC_MAX_RECORD_ID = 146` は歴史的な境界値です。**

- phase 7a でコンテナの TZ を `Asia/Tokyo` に変更した
- `created_at` の既定値は `datetime('now','localtime')`
- したがって **ID 146 以前は naive な UTC 文字列、147 以降は naive な JST 文字列**として保存されている
- タイムゾーン情報が文字列に含まれていないため、**ID で判別するしかない**

この定数を変えると過去データの表示時刻が9時間ずれます。

---

### 4.3 api_client.py — HTTP クライアント（83行）

#### 接続先の制限（重要な安全機構）

```python
_LOCAL_API_HOSTS = {"localhost", "127.0.0.1", "::1", "biolog-api"}

def _validated_api_base(value):
    parsed = urlparse(value)
    if parsed.scheme != "http" or (parsed.hostname or "").lower() not in _LOCAL_API_HOSTS:
        raise ValueError("BIOLOG_API_URL must point to the local Biolog API")

_API_BASE = _validated_api_base(API_BASE)      # ← モジュール import 時に実行
```

**環境変数で外部URLを指定しても、モジュールの読み込み時点で例外になりアプリが起動しません。** 健康データが外部へ送られる経路を設定ミスや改変で作れないようにする仕組みです。

```python
_SESSION.trust_env = False
```

`HTTP_PROXY` / `HTTPS_PROXY` などの環境変数を**無視**します。プロキシ経由で外部へ抜けることを防ぎます。`tests/test_security_boundaries.py` が両方を検証しています。

#### エラーの扱い

```python
class ApiClientError(Exception):
    def __init__(self, message, status_code=None): …
```

HTTP エラー時は**レスポンス JSON の `detail`** を取り出してメッセージにします（FastAPI の `HTTPException(detail=…)` がそのまま画面に出る経路）。

タイムアウトは GET 10秒、POST/PUT/DELETE 30秒。書き込みは Queue 待ちがあるため長めです。

> **注記:** `api_post` / `api_put` / `api_delete` には `except Exception` の受けがありますが、**`api_get` には HTTPError の受けしかありません**。API が停止しているときの `ConnectionError` は `ApiClientError` に変換されず、呼び出し側の `except ApiClientError` を素通りします。API 停止時、書き込み操作は整形されたエラー表示になり、読み取りは Streamlit の例外画面になる、という差が出ます。

---

### 4.4 cache.py — 読み取りキャッシュ（49行）

```python
def current_data_version() -> int:
    if _DATA_VERSION_KEY not in st.session_state:
        st.session_state[_DATA_VERSION_KEY] = int(time.time())
    return st.session_state[_DATA_VERSION_KEY]

def bump_data_version() -> int:
    st.session_state[_DATA_VERSION_KEY] = current_data_version() + 1
    return st.session_state[_DATA_VERSION_KEY]

@st.cache_data(ttl=10)
def fetch_range_data(start, end, version): …
@st.cache_data(ttl=10)
def fetch_latest(uid, version): …

def clear_health_caches():
    fetch_latest.clear()
    fetch_range_data.clear()
    bump_data_version()
```

**キャッシュ無効化は三層構成**です（ルール9）。1つでは足りないため、3つを併用します。

| 層 | 粒度 | 役割 |
|---|---|---|
| `fetch_*.clear()` | プロセス全体 | 書き込み直後に、今あるキャッシュをすべて捨てる |
| `data_version` | セッション単位 | キャッシュキーの世代を進め、古い世代を参照しない |
| `ttl=10` | 時間 | 反映前の値を掴んでしまった場合の滞留時間を10秒で打ち切る |

**読み取り側**は `version` をキャッシュキーの一部として渡します。関数本体では使いません。

```python
# views/summary.py
latest = fetch_latest(uid, current_data_version())
# views/graph.py
data = fetch_range_data(str(date_start), str(date_end), current_data_version())
```

**書き込み側**は既存の `clear_health_caches()` を呼ぶだけです。サイドバーの「更新」・新規登録・修正・削除の4経路がこれを呼び、キャッシュ破棄と世代更新が同時に起きます。増分処理を `clear_health_caches()` の中に置いてあるため、呼び出し側は変更不要です。

`data_version` の初期値に `int(time.time())` を使うのは、`0` 起点だと新しいセッションが過去セッションのキャッシュキー `(uid, 0)` に衝突して古い値を再表示するためです（v1.5.5 で旧 version 機構を廃止した原因）。

> **version 機構を単独で使ってはいけません。** `.clear()` と `ttl=10` を含む現在の三層構成を維持してください。この機構は v1.5.7 で導入された後、v1.6.0 の非破壊分割の際に廃止理由の記録なく失われ、v1.7.8 で復元された経緯があります。回帰テストは `tests/test_streamlit_cache_version.py`。

> **一覧タブはこのキャッシュを使いません。** `list_view.py` は `api_get` を直接呼びます。理由は次項。

---

### 4.5 views/summary.py — 上部のサマリーカード（27行）

3列に「自分・父・母」を並べ、各人の `fetch_latest(uid)` を表示します。

```python
st.metric("体重", f"{latest['weight']:.1f} kg" if latest.get("weight") is not None else "—")
```

値が無い項目は `—`。`latest` そのものが None（記録なし）なら「データなし」。

**最新1件のレコードの値をそのまま出すため、その日に体重だけ記録していれば体温は `—` になります。** 過去の値で埋めることはしません。

---

### 4.6 views/graph.py + charts.py — グラフ

#### graph.py（39行）

```python
data = fetch_range_data(str(date_start), str(date_end))     # キャッシュ経由
df = pd.DataFrame(data)
df["date"] = pd.to_datetime(df["date"]).dt.normalize()
df = df[df["user_id"].isin(selected_users)]
df = df.sort_values("date").groupby(["user_id", "date"], as_index=False).last()
```

`groupby(...).last()` は、同一ユーザー・同一日付が複数あった場合に**最後の1件だけを残す**保険です（UNIQUE 制約があるため通常は発生しません）。

描画は体重・体温・血圧・脈拍の4種類。

#### charts.py（96行）

```python
import japanize_matplotlib      # import するだけで日本語フォントが有効になる
plt.style.use("dark_background")
```

- ユーザーごとに `USER_COLORS` の固定色で描き分け
- 血圧グラフのみ**収縮期を実線・拡張期を破線**にし、`axhline` で **120 / 80 の目安線**を引く
- 小数表示が必要な項目（体重・体温・体脂肪率・筋肉量）は `FuncFormatter` で小数第1位に固定
- `ax.set_xticks(all_dates)` は **df 全体の日付**を目盛りにします。表示中のユーザーに値が無い日も目盛りとして現れます
- データが1件も無ければ `st.info("…のデータがありません")` を出して図を描きません
- `plt.clf()` / `plt.close(fig)` / `clear_figure=True` で figure を都度破棄（再実行のたびに図が増えるのを防ぐ）

---

### 4.7 views/list_view.py — 一覧とCSV（151行）

#### 10秒ごとの自動更新

```python
@st.fragment(run_every="10s")
def render_list(selected_users, date_start, date_end): …
```

`st.fragment` は**この関数だけを再実行**します。ページ全体の再実行ではないので、他タブの入力途中の内容が消えません。

キャッシュを使わず `api_get` を直接呼ぶのは、10秒ごとに動く fragment が**キャッシュではなく実データを取りに行く**必要があるためです。

#### 表示の組み立て

```
records → _filter_records()（選択ユーザーで絞る）
       → sort_values(["date","id"], ascending=[False,False])
       → ページング（page_size = 20）
       → _prepare_display()（日本語列名・列順・JST変換）
       → 長文の省略（メモ40 / 食事ログ80 / 行動ログ200文字）
       → render_safe_table()
       → 省略された分だけ expander で全文表示
```

`_prepare_display()` は `created_at` を `to_jst(値, record_id=id)` で変換します。前述の ID 146 境界がここで効きます。

#### CSV出力の2つの工夫

```python
def _sanitize_csv_value(value):
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
```

**CSV インジェクション（数式インジェクション）対策**です。`=1+1` や `=cmd|...` で始まるセルを Excel が数式として実行してしまうのを防ぐため、先頭に `'` を付けます。

```python
csv = disp_csv.to_csv(index=False, encoding="utf-8-sig")
```

**BOM 付き UTF-8**。Excel で開いたときに文字化けしないようにするためです。

> CSV に出力されるのは**ページングされる前の全件**（選択ユーザー × 指定期間）です。画面に見えている20件だけではありません。

---

### 4.8 safe_table.py — XSS の境界（48行）

```python
def dataframe_to_safe_html(df):
    display_df = df.astype(object).where(pd.notna(df), "")
    table_html = display_df.to_html(index=False, escape=True, …)
    return f'{_TABLE_STYLE}<div class="biolog-table-wrap">{table_html}</div>'

def render_safe_table(df):
    st.markdown(dataframe_to_safe_html(df), unsafe_allow_html=True)
```

**アプリ全体で `unsafe_allow_html=True` を使うのはここだけです。**

安全性は次の2点で担保されています。

1. `escape=True` により、セルの値・列名がすべて HTML エスケープされる
2. ラッパー部分は定数のみで、ユーザー値を文字列補間しない

コード内のコメントにも「table_html is the only non-constant HTML inserted here」と明記されています。`tests/test_streamlit_refresh_policy.py` が「`unsafe_allow_html` が他所に増えていないこと」を回帰テストとして検証しています。

`white-space: pre-wrap` により、メモ内の改行がそのまま表示されます。

---

### 4.9 入力フォーム群

登録・修正フォームは4ファイルに分かれています。

| ファイル | 責務 |
|---|---|
| `form_fields.py` | 項目の定義（**唯一の出典**） |
| `form_components.py` | ウィジェットの描画と session_state の同期 |
| `form_state.py` | 3方向マージのアルゴリズム（Streamlit 非依存） |
| `payloads.py` | 送信ボディの組み立てと検証 |

#### form_fields.py（28行）

```python
@dataclass(frozen=True)
class NumberField:
    name, label, min_value, max_value, step, cast, fmt, create_group, edit_group
```

`create_group` / `edit_group` は `"left"` / `"right"` で、**2列レイアウトのどちらに置くか**を指定します。

> コメントに「Keep this order identical to the create/edit form display order.」とあり、`tests/test_streamlit_payloads.py` の `test_form_fields_order_and_layout_groups_match_existing_forms` が順序とグループを固定しています。並べ替えるとテストが落ちます。

#### form_components.py（120行）— 登録と修正でウィジェットが違う

```python
def _create_measurement_input(field, key):
    return st.text_input(field.label, value="", key=f"{key}_text")   # ← 登録は text_input
```

**登録フォームは `number_input` ではなく `text_input` を使います。** `number_input` は未入力状態を保てず `min_value` に落ちてしまうため、「入力していない」と「最小値を入力した」を区別する目的です。文字列で受け取り、`payloads.py` 側で数値化と範囲検証を行います。

修正フォームは `number_input` を使いますが、値の渡し方が繊細です。

```python
if key not in st.session_state:
    kwargs["value"] = value          # 初回だけ既定値を渡す
elif st.session_state[key] is None:
    kwargs["value"] = None           # 空のままを維持
# それ以外は value を渡さない（session_state の値が使われる）
```

コメントにある通り、ここで `session_state` のキーを削除すると、実ブラウザで Streamlit がウィジェットを `min_value` で作り直してしまいます。**空欄が勝手に最小値になる不具合**への対処です。

#### form_state.py（53行）— 3方向マージ

修正画面は10秒ごとに API の値を取り直します。そのとき「入力途中の値」を消さないためのアルゴリズムです。

```python
merge_measurement_values(field_names, api_values, previous_api_values, widget_values)
```

3つを突き合わせます。

- `api_values`: いま API から返ってきた値
- `previous_api_values`: 前回同期したときの API の値（ベースライン）
- `widget_values`: 画面で編集中の値

| 条件 | 採用する値 | 備考 |
|---|---|---|
| ベースラインが無い（初回） | API 値 | 全項目 |
| ウィジェットが未生成 | API 値 | — |
| API が前回から変わっていない | **ウィジェット値** | ユーザーの編集を保持 |
| ウィジェット値がベースラインまたは現 API 値と同じ | API 値 | 実質編集していない |
| 上記以外（両方変わった） | **ウィジェット値** ＋ **競合として記録** | 入力を優先し警告 |

```python
def _same_value(left, right) -> bool:
    return type(left) is type(right) and left == right
```

**型まで一致を要求します。** `1`（int）と `1.0`（float）は別物、`None` と `0` も別物として扱われます。`0 == False` のような Python の緩い比較で誤判定しないための措置で、`tests/test_streamlit_form_state.py` が検証しています。

競合が出ると `edit.py` が警告と「競合項目を最新値に置換」ボタンを出し、押すと `accept_latest_measurements()` が**競合した項目だけ** API 値で上書きします。

このモジュールは Streamlit に依存しない純粋関数なので、単体テストが容易です。

#### payloads.py（56行）

```python
def _add_measurements(body, values):
    for field in MEASUREMENT_FIELDS:
        value = values.get(field.name)
        if value is None or (isinstance(value, str) and not value.strip()): continue
        validate_range = isinstance(value, str)          # ← 文字列のときだけ範囲検証
        converted = field.cast(value)                    # 失敗 → ValueError（日本語メッセージ）
        if validate_range and 範囲外: raise ValueError(…)
        body[field.name] = converted
```

**範囲検証は値が文字列のときだけ**行います。登録フォーム（`text_input`）は文字列なので検証され、修正フォーム（`number_input`）は既に min/max で制限済みなので再検証しません。

```python
body["memo"] = memo or ""
body["meal_detail"] = meal_detail or ""
body["activity_log"] = activity_log or ""
```

テキストは**常に送ります**（空なら空文字）。サーバ側の `NULLIF(…, '')` により、空文字は「既存を残す」と解釈されます。

---

### 4.10 views/create.py — 新規登録（54行）

```python
with st.form("create_form"):
    ユーザー選択・日付・測定値・メモ・食事ログ・行動ログ
    submitted = st.form_submit_button("登録")

if submitted:
    body = build_create_payload(…)     # ValueError → st.error して return
    result = api_post("/api/health/record", body)
    st.success("登録を受け付けました（反映には数秒かかる場合があります）")
    clear_health_caches()
    st.rerun()
```

`st.form` を使うことで、**送信ボタンを押すまで再実行が起きません**（入力中に毎回スクリプトが走らない）。

「反映には数秒かかる場合があります」という文言は、Queue 経由で worker が直列に書き込む実装を踏まえたものです。

**ただし、これは fire-and-forget の非同期書き込みではありません。** `_enqueue_and_wait` が結果を最大30秒待つため、**API は DB 書き込みの完了を待ってから応答します**。

```
Streamlit → API → Queue投入 → workerがDB書き込み → result_queueへ結果
                     ↑                                    │
                     └──── APIは結果を待つ（最大30秒）────┘
                                    ↓
                            HTTPレスポンス
```

したがってレスポンスが返った時点で worker の処理は成功しています。この文言は「保存が後回しになる」という意味ではなく、**Queue の滞留やロック再試行によって応答までに時間がかかりうる**ことを示すものと読むのが実装に即しています。

> 表示文言と実装にはわずかなずれがあります。「受け付けました」は非同期処理を連想させますが、実際には保存完了後に表示されます。不具合ではありません。文言を変える場合の対象は `views/create.py` の1箇所です。

日付の既定値は `datetime.now(JST).date()`。

---

### 4.11 views/edit.py — 修正と削除（166行）

#### 修正の流れ

```
ユーザー選択
 → GET /records?user_id=…&limit=500 で登録済み日付一覧を作る
 → 日付を選択
 → GET /record/day?user_id=…&date=… で該当レコードを取得
 → sync_edit_measurement_state()  ← ウィジェット生成の「前」に session_state を整える
 → 競合があれば警告＋置換ボタン
 → st.form で編集
 → PUT /record/{id}
```

```python
edit_key_prefix = f"edit_{edit_user}_{edit_date}"
```

**キー名にユーザーと日付を含めます。** 別のレコードを選ぶと別の session_state キーになるため、前のレコードの入力が混ざりません。

日付一覧は `limit=500` で取得します。**501件目以降の日付は編集リストに出てきません。**

#### 削除の流れ

```python
if st.session_state.get("clear_del_id"):        # 前回の削除後にフラグが立っている
    st.session_state["del_id"] = None           # 入力欄をリセット
    del st.session_state["clear_del_id"]

delete_id = st.number_input("削除するレコード ID", min_value=1, step=1, value=None, key="del_id")
```

Streamlit ではウィジェット生成後に自分の `session_state` を書き換えられないため、**「次回の実行の冒頭でリセットする」フラグ方式**を使っています。削除成功時に `clear_del_id = True` を立て、`st.rerun()` します。

削除は3段構えです。

1. ID を入力すると `GET /record/{id}` でプレビューを表示（`request_id` は伏せる）
2. 確認チェックボックスを入れるまで「削除実行」ボタンは `disabled`
3. `DELETE /record/{id}`

存在しない ID なら「ID N のレコードは存在しません」と表示します。

---

### 4.12 ui_style.py — CSS注入（52行）

```python
def inject_number_input_styles() -> None:
    st.html(_NUMBER_INPUT_STYLE)
```

`st.number_input` が入力欄に重ねて描画する「Press Enter to submit form」の案内が、列幅の狭い修正画面で数値と重なって読めなくなる問題への対処です。

- 案内の非表示は **`number_input` 配下に限定**（メモ・食事ログのテキスト入力では従来どおり表示）
- `[data-testid="stNumberInput"]` と `.stNumberInput` の**両方を併記**し、Streamlit 側の名称変更に備えている
- ステップボタンには手を入れない
- 万一セレクタが効かなくなっても「案内が再表示されるだけ」で機能は壊れない

**定数のみを注入し、値を埋め込みません。** `tests/test_streamlit_refresh_policy.py` が「`st.html` の使用箇所はこのモジュールだけ」「注入はアプリ入口から1回だけ」を検証しています。

---

## 5. データモデル

### health_records テーブル

| 列 | 型 | 制約 | 備考 |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| `request_id` | TEXT | NOT NULL **UNIQUE** | 冪等性の鍵 |
| `date` | TEXT | NOT NULL | `YYYY-MM-DD`（対象日） |
| `user_id` | TEXT | NOT NULL | `self` / `father` / `mother` |
| `temperature` | REAL | | 体温 |
| `pulse` | INTEGER | | 脈拍 |
| `systolic_bp` | INTEGER | | 収縮期血圧 |
| `diastolic_bp` | INTEGER | | 拡張期血圧 |
| `weight` | REAL | | 体重 |
| `body_fat` | REAL | | 体脂肪率 |
| `muscle_mass` | REAL | | 筋肉量 |
| `bmr` | INTEGER | | 基礎代謝 |
| `meal_detail` | TEXT | | 食事ログ（**追記される**） |
| `activity_log` | TEXT | | 行動ログ（**追記される**） |
| `memo` | TEXT | NOT NULL DEFAULT '' | メモ |
| `created_at` | TEXT | NOT NULL DEFAULT `datetime('now','localtime')` | **TZ依存。ID146が境界** |

インデックス:

```sql
idx_hr_user_date   (user_id, date DESC)   -- 検索の高速化
uidx_hr_user_date  UNIQUE (user_id, date) -- 1人1日1件の保証 ＋ upsert の対象
```

補助テーブル: `schema_migrations`（適用済みマイグレーション）、`migration_lock`（多重実行防止）

### 押さえるべき性質

- **`created_at` は「レコードが作られた時刻」であって、upsert で更新されません。** 同じ日に追記しても初回の時刻のままです
- **`date` は対象日**であり、記録操作をした日ではありません
- `updated_at` に相当する列はありません

---

## 6. 1件の登録を最初から最後まで追う

「体重 62.5 kg、行動ログ『散歩30分』を登録」する場合の全経路です。

```
① views/create.py
   st.form_submit_button("登録") が押される

② payloads.build_create_payload()
   {"request_id": "<uuid4>", "user_id": "self", "date": "2026-08-15",
    "memo": "", "weight": 62.5, "meal_detail": "", "activity_log": "散歩30分"}
   weight は text_input の文字列 "62.5" → float(62.5) に変換され、範囲(0.1〜299.9)を検証

③ api_client.api_post("/api/health/record", body)
   POST http://biolog-api:8766/api/health/record（timeout 30秒）

④ api.create_record()
   raw = await request.json()
   ログ: REQ_START → API_IN

⑤ preprocess.preprocess_record(raw)
   request_id / date は既にあるので補完なし
   blood_pressure キーは無いので分解なし
   ログ: PREPROCESS

⑥ schemas.HealthRecordCreate(**preprocessed)
   extra="forbid" で未知キー検査、weight の範囲検査、
   at_least_one_health_value で「何か入っている」ことを確認
   失敗すれば ここで 422、ログ: VALIDATION status=error

⑦ api._enqueue_and_wait("insert", payload)
   専用の result_queue を作って Queue へ put
   Queue が満杯なら 503
   result_queue.get(timeout=30) でブロック

⑧ worker.worker_loop() が task を取得
   _execute_with_retry() → _execute_once() → insert_record(payload)

⑨ write_repository.insert_record()
   db_manager.get_connection(write=True)
     → PRAGMA journal_mode=DELETE / busy_timeout=1000 / foreign_keys=ON
     → BEGIN IMMEDIATE
   既存の (self, 2026-08-15) を SELECT
     あれば _merge_log_entries() で activity_log を追記マージ
   INSERT … ON CONFLICT(user_id, date) DO UPDATE
     数値は COALESCE、テキストは COALESCE(NULLIF(…,''))
   commit → close
   返り値 {"id": 123}
   （request_id が衝突していたら {"idempotent": True, "id": 既存id}）

⑩ worker が result_queue に {"status":"success","id":123} を put
   ログ: op=insert status=success（mask_pii 適用済み）

⑪ api が受け取り {"message":"登録完了","request_id":…,"status":"success","id":123} を 201 で返す
   ログ: REQ_END

⑫ views/create.py
   st.success("登録を受け付けました…")
   clear_health_caches()   ← fetch_latest / fetch_range_data のキャッシュを破棄
   st.rerun()              ← 画面を再描画。サマリーとグラフに新しい値が出る
```

**ロック競合が起きた場合**は ⑧ で最大5回、0.1→0.2→0.4→0.8 秒の間隔で再試行します。それでも駄目なら `database` エラーとして 500 が返ります。

---

## 7. tests — 何を守っているテストか

`pytest` で実行します（`requirements-test.txt` に両サービスの依存が入っています）。

### conftest.py — 本番DBを絶対に触らない仕組み

```python
REAL_DB = (ROOT / "data" / "biolog.db").resolve()

@pytest.fixture
def temp_db_modules(tmp_path, monkeypatch):
    db_path = (tmp_path / "biolog_test.db").resolve()
    assert db_path != REAL_DB
    assert ROOT not in db_path.parents          # ← リポジトリ配下でないことも確認
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    …
    for name in ("db_manager", "write_repository", "biocore"):
        sys.modules.pop(name, None)             # ← 環境変数を読み直させる
```

`db_manager` は import 時に `DATABASE_PATH` を読むため、**モジュールキャッシュを捨ててから再 import** しないとテスト用DBに切り替わりません。二重の `assert` で本番DBを指していないことを確認しています。

### テストファイルの担当範囲

| ファイル | 守っているもの |
|---|---|
| `test_api_boundaries.py` | ページネーション上限、日付形式、不正JSON、期間の逆転 |
| `test_api_preprocess_schemas.py` | 欠損補完、血圧分解、既存BP優先、各値の範囲、`extra="forbid"` |
| `test_api_repository_biocore.py` | **upsert の値保護、ログの追記マージ、冪等性、更新・削除の not found** |
| `test_created_at_timezone.py` | **ID 146 境界の時刻変換**（旧UTC / 新JST / aware値 / ID欠損） |
| `test_healthcheck.py` | ヘルスチェックの状態判定、`check_database` が読み取り専用であること |
| `test_list_filters.py` | ユーザー絞り込み（**未選択時に全件へフォールバックしない**）、CSV数式の無害化 |
| `test_read_retry.py` | ロック時の再試行回数、ロック以外は再試行しないこと |
| `test_requirement_constraints.py` | 両サービスの依存バージョン固定が矛盾しないこと |
| `test_security_boundaries.py` | **CORS ミドルウェア不在**、ログに健康値が出ないこと、外部URL拒否、プロキシ無視 |
| `test_streamlit_form_state.py` | **3方向マージの全分岐**、空欄が最小値に落ちないこと |
| `test_streamlit_payloads.py` | ペイロード組み立て、型保持、0 と None の区別、項目順序の固定 |
| `test_streamlit_refresh_policy.py` | **`unsafe_allow_html` / `st.html` の使用箇所の限定**、fragment の維持 |
| `test_worker_resilience.py` | **worker が1件の失敗で死なないこと**、エラー種別のHTTP変換、タイムアウト503 |

**回帰テストとして「コードの書き方そのもの」を検査しているものがあります。** 例えば `test_security_boundaries.py` はソースを読んで CORS ミドルウェアが追加されていないことを確認し、`test_streamlit_refresh_policy.py` は `unsafe_allow_html` が `safe_table.py` 以外に現れていないことを確認します。**安全側の設計を後から崩さないための仕掛け**です。

---

## 8. 起動と運用

### docker-compose.yml

| 設定 | 値 | 意図 |
|---|---|---|
| ポート | `127.0.0.1:8766` / `127.0.0.1:8501` | **ループバックのみ**。LAN から見えない |
| `cap_drop` | `ALL` | Linux ケーパビリティを全放棄 |
| `volumes` | `${BIOLOG_DATA_DIR:-./data}:/data` | DB の置き場所を環境変数で差し替え可能 |
| `TZ` | `Asia/Tokyo` | `created_at` の既定値に影響（ID146境界の原因） |
| `restart` | `unless-stopped` | |
| `logging` | 10MB × 3ファイル | ログの無制限肥大を防ぐ |
| healthcheck | API は `status=="ok"`、Streamlit は `/_stcore/health` | |

両コンテナとも Dockerfile で **UID/GID 10001 の非 root ユーザー**を作って実行します。

### 起動順序

```
docker compose up
  └─ biolog-api
       └─ entrypoint.sh
            ├─ python migrations/runner.py     ← 先にマイグレーション
            └─ exec uvicorn api:app …          ← 完了後にAPI起動
  └─ biolog-streamlit（depends_on: biolog-api）
```

`depends_on` はコンテナの起動順のみを保証し、API の準備完了は待ちません。Streamlit が先に接続を試みてエラーになった場合は、画面を再読み込みすれば回復します。

### バッチファイル

| ファイル | 内容 |
|---|---|
| `start_biolog.bat` | `cd /d "%~dp0"` で自身の場所へ移動 → Docker 接続確認 → `docker compose up -d` → `/_stcore/health` を最大300秒ポーリング → ブラウザを開く |
| `rebuild_and_start_biolog.bat` | 上記に `--build` を付けて実行 |
| `stop_biolog.bat` | `docker compose down` |

**パスをハードコードしていない**ため、開発用の C: ドライブでも運用用の D: ドライブでも、コピーするだけで動きます。

---

## 9. コードを読むときの注意点

### 挙動として知っておくべきこと

| 項目 | 内容 |
|---|---|
| **値の保持と空欄** | POST は数値の NULL とテキストの空文字を既存値の保持として扱います。PUT は数値の NULL を無視し、テキストの空文字でメモ・食事ログ・行動ログを空にできます |
| **ログは積み上がる** | 同じ日に登録を繰り返すと、食事ログと行動ログは行単位で追記されます。数値は上書きです |
| **日付と人は変更不可** | `HealthRecordUpdate` に `date` / `user_id` がないため、PUT で移動できません。作り直しが必要です |
| **編集リストは500件まで** | `edit.py` が `limit=500` で日付一覧を取ります |
| **4タブは常に全部動く** | 見えていないタブの API 呼び出しも毎回走ります |
| **`created_at` は初回のみ** | upsert しても更新されません |
| **ID 146 の境界** | 過去データの時刻表示は `LEGACY_UTC_MAX_RECORD_ID` に依存します。変更すると9時間ずれます |

### 変更するときに触る場所

**測定項目を1つ増やす場合:**

1. `biolog_api/schemas.py` の `HealthRecordCreate` と `HealthRecordUpdate` の両方
2. `biolog_api/write_repository.py` の INSERT 文・`ON CONFLICT` 節・`_ALLOWED`
3. `biolog_api/biocore.py` の `HEALTH_RECORD_COLUMNS`
4. `biolog_api/migrations/versions/` に新しい `migrate_002_*.py` を追加（既存ファイルは編集しない）
5. `biolog_streamlit/form_fields.py` の `MEASUREMENT_FIELDS`（順序とグループに注意）
6. `biolog_streamlit/views/list_view.py` の列名マップと `priority`
7. 必要なら `biolog_streamlit/charts.py`、`views/summary.py`
8. `tests/test_streamlit_payloads.py` の順序テストの期待値

**やってはいけないこと:**

- `PRAGMA journal_mode=WAL` への変更
- `db_manager.py` を経由しない `sqlite3.connect()`
- worker の複数スレッド化、Queue の複数化
- `lifespan` へのマイグレーション処理の追加
- Streamlit からの DB 直接アクセス
- `unsafe_allow_html` / `st.html` の使用箇所を増やすこと
- ログへの健康値・識別子の生出力

いずれも回帰テストか `CLAUDE.md` のルールで明示的に禁止されています。

### 技術的な注記

以下はコードを読んで確認した事実です。現時点で不具合として観測されているものではありませんが、把握しておくと調査時に役立ちます。

- **`create_record` は `async def`** です。FastAPI では `async def` のエンドポイントはイベントループ上で直接実行されるため、`_enqueue_and_wait` の最大30秒のブロッキング待機がループを占有します。`update_record` / `delete_record` は同期 `def` なのでスレッドプールで動きます。単独利用では表面化しませんが、同時アクセス時は他のリクエスト（GET 含む）が待たされる構造です。
- **`api.py` の `from db_manager import get_connection`** は `api.py` 内で使われていません。ただし `biocore` 経由でも `db_manager` は読み込まれるため、`DATABASE_PATH` 未設定時の起動失敗という副作用は変わりません。
- **`preprocess.py` の `blood_pressure` は、有効な2つの数値へ変換できない場合に黙って無視されます。** 整数項目の型変換失敗が 422 になるのとは扱いが異なります。失敗経路は2種類あります。
  - **区切り後の要素数が2でない**場合（`"110"` は1個、`"110/75/60"` は3個）は `if len(parts) == 2:` に入らず、何もしません。
  - **要素数は2だが数値変換できない**場合（`"/75"` は `["", "75"]`）は `except (ValueError, TypeError): pass` で握りつぶします。
- **片方だけ変換できる場合、その片方は設定されます。** `"110/"` は `["110", ""]` となり、`setdefault` が順に評価されるため `systolic_bp` に 110 が入った後で2つ目が例外になり、`diastolic_bp` だけが未設定で進みます。
- **血圧分解側の `except` は `OverflowError` を捕捉していません。** 400桁の数字列のような入力は `float()` で `inf` になり `int()` で `OverflowError` を送出して 500 になります（記号は事前に除去されるため `"1e309"` 表記は到達しませんが、桁数だけで到達します）。整数項目側と同じ対応を入れるかは未決です。
- **数値レンジの CHECK 制約は DB にありません。** 範囲の担保は API 層（Pydantic）のみです。

---

## 関連資料

| ファイル | 内容 |
|---|---|
| [spec.md](spec.md) | 機能仕様書。「何ができるか」 |
| [slides.html](slides.html) | 構成スライド |
| `CLAUDE.md`（リポジトリ直下） | 開発ルールと BioLog 固有の不変条件（開発リポジトリのみ・非公開） |
| [biolog_streamlit/仕様書.md](../biolog_streamlit/仕様書.md) | 設計思想・データフロー |
| [biolog_streamlit/操作説明書.md](../biolog_streamlit/操作説明書.md) | 画面操作 |
| [biolog_api/skills.md](../biolog_api/skills.md) | API リファレンス・curl 集 |
| [README.md](../README.md) | セットアップと運用 |
| [CHANGELOG.md](../CHANGELOG.md) | 全変更履歴 |
| [NETWORK_ISSUE_DIAGNOSTICS.md](NETWORK_ISSUE_DIAGNOSTICS.md) | Streamlit の "Network issue" 調査手順 |
| `GITHUB_PUBLISHING_PROCEDURE.md` | 公開手順（開発リポジトリのみ・非公開） |
