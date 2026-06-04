# Kolesa Liveness Sweep — Implementation Plan (Phase 0 + Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать kolesa точный детектор «продано» и полный охват, который реально работает на бесплатном GHA: курсор-резюмируемый проход по всем активным объявлениям, который пингует URL и ставит `closed_at` на `404` / освежает `last_seen_at` на `200`.

**Architecture:** Один time-boxed воркер `parsers/kolesa/liveness.py` в цикле тянет батчи активных kolesa-listing'ов, упорядоченных по `last_checked_at NULLS FIRST` (дольше всех не проверенные — первыми), GET'ит каждый URL, классифицирует (alive / closed / transient) и применяет к БД. Резюмируемость — через персистентный `last_checked_at` (без offset'ов). Расписание каждые ~6ч; за сутки несколько прогонов перекрывают весь активный набор. Bootstrap = просто дать ему несколько прогонов вычистить накопленный бэклог 157k.

**Tech Stack:** Python 3.11, asyncio, curl_cffi (Chrome impersonation), asyncpg + Neon (statement_cache_size=0), pytest (вводится этим планом), GitHub Actions.

**Scope:** Только Phase 0 (схема) + Phase 1 (liveness + bootstrap + workflow) из спеки `docs/superpowers/specs/2026-06-04-kolesa-stable-parser-design.md`. Phase 2 (discovery early-stop) и Phase 3 (cycle-tracker, ретайр deep-parse) — отдельные планы. Price-refresh во время liveness **отложен** в Phase 2 (нужен FX для `price_usd`); MVP даёт coverage + sold-detection.

---

## File Structure

| Файл | Ответственность |
|---|---|
| `database/migrations/001_liveness_last_checked_at.sql` (create) | Миграция: колонка `listings.last_checked_at` + индекс liveness. Запускается вручную в Neon SQL Editor. |
| `database/init.sql` (modify) | Схема-контракт: та же колонка + индекс в DDL для свежих инсталляций. |
| `parsers/kolesa/liveness_classify.py` (create) | **Чистая** функция `classify_listing(status, body, external_id) -> str`. Импортирует только `re`. Тестируется без сети/БД. |
| `parsers/kolesa/liveness.py` (create) | Воркер: выборка батча, HTTP-проверка, применение вердикта, time-box цикл, `__main__`. |
| `tests/test_liveness_classify.py` (create) | Unit-тесты классификатора (alive / 404 / soft-404 / transient). |
| `parsers/requirements.txt` (modify) | Добавить `pytest`. |
| `.github/workflows/kolesa_liveness.yml` (create) | Расписание + ручной запуск воркера. |
| `README.md`, `CHANGELOG.md` (modify) | Документация (правило CLAUDE.md). |
| `.claudemetrics/backlog.json` (modify) | Обновить статус `t-0004` (поглощён), добавить задачи Phase 2/3. |

**Публичный интерфейс (зафиксирован, используется в нескольких задачах):**
- `parsers/kolesa/liveness_classify.py`:
  - константы `ALIVE = "alive"`, `CLOSED = "closed"`, `TRANSIENT = "transient"`
  - `classify_listing(status_code: int, body: str | None, external_id: str) -> str`
- `parsers/kolesa/liveness.py`:
  - `async select_liveness_batch(pool, source_id: int, limit: int) -> list[asyncpg.Record]`
  - `async apply_verdict(pool, listing_id, verdict: str, dry_run: bool) -> None`
  - `async run_liveness(dry_run: bool = False) -> dict`

---

## Task 1: Схема — `last_checked_at` + индекс

**Files:**
- Create: `database/migrations/001_liveness_last_checked_at.sql`
- Modify: `database/init.sql:92` (после строки `closed_at`), `database/init.sql:107` (после `idx_listings_first_seen`)

- [ ] **Step 1: Написать миграцию**

Create `database/migrations/001_liveness_last_checked_at.sql`:

```sql
-- 001_liveness_last_checked_at.sql
-- Liveness sweep: курсор "когда объявление в последний раз пинговали по URL".
-- Отличается от last_seen_at (когда последний раз ВИДЕЛИ живым).
-- Запустить вручную в Neon SQL Editor. Idempotent.

ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ DEFAULT NULL;

-- Выбирать "дольше всех не проверенные среди активных" дёшево.
-- NULLS FIRST → новые (ещё не проверенные) идут в голову очереди.
CREATE INDEX IF NOT EXISTS idx_listings_liveness
    ON listings (source_id, last_checked_at NULLS FIRST)
    WHERE is_active;
```

- [ ] **Step 2: Отразить в `init.sql` (DDL-контракт)**

Modify `database/init.sql` — добавить колонку сразу после строки `closed_at TIMESTAMPTZ, ...` (строка 92):

```sql
    closed_at           TIMESTAMPTZ,               -- когда объявление исчезло (продано)
    last_checked_at     TIMESTAMPTZ DEFAULT NULL,  -- liveness: когда последний раз пинговали URL
```

И добавить индекс сразу после `CREATE INDEX idx_listings_first_seen ...` (строка 107):

```sql
CREATE INDEX idx_listings_first_seen ON listings(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_liveness ON listings (source_id, last_checked_at NULLS FIRST) WHERE is_active;
```

- [ ] **Step 3: Применить миграцию к Neon**

Запустить содержимое `database/migrations/001_liveness_last_checked_at.sql` в Neon SQL Editor (или `psql "$DATABASE_URL" -f database/migrations/001_liveness_last_checked_at.sql`).

- [ ] **Step 4: Проверить, что колонка и индекс на месте**

Run (psql или Neon):
```sql
SELECT column_name FROM information_schema.columns
 WHERE table_name='listings' AND column_name='last_checked_at';
SELECT indexname FROM pg_indexes WHERE indexname='idx_listings_liveness';
```
Expected: обе строки возвращаются (1 row каждая).

- [ ] **Step 5: Commit**

```bash
git add database/migrations/001_liveness_last_checked_at.sql database/init.sql
git commit -m "feat(db): add listings.last_checked_at + liveness index"
```

---

## Task 2: Чистый классификатор + pytest (TDD)

**Files:**
- Modify: `parsers/requirements.txt`
- Create: `tests/test_liveness_classify.py`
- Create: `parsers/kolesa/liveness_classify.py`

- [ ] **Step 1: Добавить pytest в зависимости**

Append to `parsers/requirements.txt` (новой строкой):
```
pytest>=8.0
```

- [ ] **Step 2: Убедиться, что импорт пакета лёгкий**

Run:
```bash
cat parsers/__init__.py parsers/kolesa/__init__.py
```
Expected: оба пустые (или без тяжёлых импортов). Тест импортирует `parsers.kolesa.liveness_classify`, поэтому `parsers/common/__init__.py` (который тянет aiohttp) НЕ должен затрагиваться. Если `parsers/kolesa/__init__.py` импортирует `parser`/`alive_check` — оставь как есть, классификатор всё равно изолирован в своём модуле.

- [ ] **Step 3: Написать падающий тест**

Create `tests/test_liveness_classify.py`:

```python
"""Unit-тесты классификатора liveness — чистая логика, без сети/БД."""
from parsers.kolesa.liveness_classify import classify_listing, ALIVE, CLOSED, TRANSIENT

# Реальные маркеры со страниц kolesa /a/show/{id} (см. спеку §1):
# живой лист → <title> с "№{id}" и "цена ...₸", canonical на /a/show/{id}.
ALIVE_BODY = (
    '<html><head><title>Продажа ВАЗ (Lada) Kalina 2013 года в Актобе - '
    '№221153415: цена 3250000₸. Купить — Колёса</title>'
    '<link rel="canonical" href="https://kolesa.kz/a/show/221153415"/></head></html>'
)
# 404-страница kolesa возвращает дженерик-главную: общий title, без №id/canonical.
DEAD_BODY = (
    '<html><head><title>Колёса — продажа авто в Казахстане. Весь авторынок '
    'Казахстана на одном сайте</title></head><body>страница не найдена</body></html>'
)

def test_404_is_closed():
    assert classify_listing(404, DEAD_BODY, "217539026") == CLOSED

def test_410_is_closed():
    assert classify_listing(410, "", "217539026") == CLOSED

def test_200_with_listing_markers_is_alive():
    assert classify_listing(200, ALIVE_BODY, "221153415") == ALIVE

def test_200_soft404_without_markers_is_closed():
    # 200, но тело — дженерик-главная без №id/canonical → soft-404 → closed
    assert classify_listing(200, DEAD_BODY, "221153415") == CLOSED

def test_200_wrong_id_is_closed():
    # 200 с маркерами ДРУГОГО объявления (редирект на похожее) → не наш лист
    assert classify_listing(200, ALIVE_BODY, "999999999") == CLOSED

def test_5xx_is_transient():
    assert classify_listing(503, "", "221153415") == TRANSIENT

def test_network_error_is_transient():
    # -1 = network/timeout (см. liveness._check_one)
    assert classify_listing(-1, None, "221153415") == TRANSIENT

def test_429_is_transient():
    # rate-limit — НЕ закрываем, перечекаем
    assert classify_listing(429, "", "221153415") == TRANSIENT
```

- [ ] **Step 4: Запустить тест — убедиться, что падает**

Run: `PYTHONPATH=. pytest tests/test_liveness_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'parsers.kolesa.liveness_classify'`.

- [ ] **Step 5: Реализовать классификатор**

Create `parsers/kolesa/liveness_classify.py`:

```python
"""Чистый классификатор ответа kolesa /a/show/{id} — alive / closed / transient.

Без сети и БД, чтобы юнит-тестировать в любом окружении.
Сигнал (см. спеку §1, провалидировано на реальных страницах):
  - Живой лист: HTTP 200 И тело содержит canonical/title именно ЭТОГО объявления
    (`/a/show/{external_id}` в canonical, либо `№{external_id}` в <title>).
  - 404/410, либо 200 без маркеров этого листа (kolesa отдаёт дженерик-главную) → closed.
  - 5xx / 429 / -1 (сеть/таймаут) → transient (НЕ закрываем).
"""
import re

ALIVE = "alive"
CLOSED = "closed"
TRANSIENT = "transient"

# Транзиентные коды: сеть/таймаут (-1), rate-limit (429), серверные 5xx.
_TRANSIENT_CODES = {-1, 429, 500, 502, 503, 504}


def classify_listing(status_code: int, body: str | None, external_id: str) -> str:
    if status_code in _TRANSIENT_CODES:
        return TRANSIENT
    if status_code in (404, 410):
        return CLOSED
    if status_code == 200 and body and _is_listing_page(body, external_id):
        return ALIVE
    # Любой иной 200 (soft-404 / редирект на главную / чужой лист) или прочие коды → closed.
    if status_code == 200:
        return CLOSED
    # Неожиданный код (403/451/3xx и т.п.) — безопаснее не закрывать.
    return TRANSIENT


def _is_listing_page(body: str, external_id: str) -> bool:
    """True, если тело — страница именно объявления external_id."""
    eid = re.escape(external_id)
    if re.search(rf'/a/show/{eid}\b', body):       # canonical/og:url на себя
        return True
    if re.search(rf'№\s*{eid}\b', body):            # <title> ... №{id}: цена ...
        return True
    return False
```

- [ ] **Step 6: Запустить тест — убедиться, что проходит**

Run: `PYTHONPATH=. pytest tests/test_liveness_classify.py -v`
Expected: PASS (8 passed).

- [ ] **Step 7: Commit**

```bash
git add parsers/requirements.txt tests/test_liveness_classify.py parsers/kolesa/liveness_classify.py
git commit -m "feat(kolesa): pure liveness classifier + pytest unit tests"
```

---

## Task 3: Воркер liveness — выборка, проверка, применение

**Files:**
- Create: `parsers/kolesa/liveness.py`

- [ ] **Step 1: Написать модуль воркера**

Create `parsers/kolesa/liveness.py`:

```python
"""parsers/kolesa/liveness.py — liveness sweep активных kolesa-объявлений.

Тянет батчи активных listing'ов (дольше всех не проверенные первыми по
last_checked_at NULLS FIRST), GET'ит listing_url, и:
  - ALIVE   → last_seen_at=now(), last_checked_at=now(), closed_at=NULL
  - CLOSED  → is_active=FALSE, closed_at=now(), last_checked_at=now()  ← «продано»
  - TRANSIENT → last_checked_at=now() (не блокируем голову очереди, перечек в след. цикле)

Резюмируемость — через персистентный last_checked_at (никаких offset'ов).
Time-boxed: крутит батчи пока не выйдет LIVENESS_TIME_BUDGET_MIN или не опустеет очередь.
Запускается отдельным workflow (kolesa_liveness.yml).
"""
import asyncio
import logging
import os
import random
import time

from curl_cffi import requests

from parsers.common.db import get_pool
from parsers.common.http_client import USER_AGENTS
from parsers.kolesa.liveness_classify import classify_listing, ALIVE, CLOSED, TRANSIENT

logger = logging.getLogger("liveness.kolesa")

BATCH = int(os.getenv("LIVENESS_BATCH", "500"))
CONCURRENCY = int(os.getenv("LIVENESS_CONCURRENCY", "2"))
DELAY_MIN = float(os.getenv("LIVENESS_DELAY_MIN", "1.2"))
DELAY_MAX = float(os.getenv("LIVENESS_DELAY_MAX", "2.5"))
TIME_BUDGET_MIN = float(os.getenv("LIVENESS_TIME_BUDGET_MIN", "300"))
DRY_RUN = os.getenv("LIVENESS_DRY_RUN", "0") == "1"
TIMEOUT = 20


async def select_liveness_batch(pool, source_id: int, limit: int):
    async with pool.acquire() as c:
        return await c.fetch(
            """
            SELECT id, external_id, listing_url
            FROM listings
            WHERE source_id = $1 AND is_active = TRUE AND listing_url IS NOT NULL
            ORDER BY last_checked_at NULLS FIRST
            LIMIT $2
            """,
            source_id, limit,
        )


async def apply_verdict(pool, listing_id, verdict: str, dry_run: bool) -> None:
    if dry_run:
        return
    async with pool.acquire() as c:
        if verdict == ALIVE:
            await c.execute(
                "UPDATE listings SET last_seen_at=NOW(), last_checked_at=NOW(), "
                "closed_at=NULL WHERE id=$1", listing_id)
        elif verdict == CLOSED:
            await c.execute(
                "UPDATE listings SET is_active=FALSE, closed_at=NOW(), "
                "last_checked_at=NOW() WHERE id=$1", listing_id)
        else:  # TRANSIENT — только сдвигаем курсор, состояние не трогаем
            await c.execute(
                "UPDATE listings SET last_checked_at=NOW() WHERE id=$1", listing_id)


async def _check_one(session, url: str, external_id: str) -> str:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    try:
        resp = await asyncio.wait_for(
            session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True),
            timeout=TIMEOUT + 5,
        )
        return classify_listing(resp.status_code, resp.text, external_id)
    except Exception as e:
        logger.debug("check failed for %s: %s", url, e)
        return classify_listing(-1, None, external_id)  # → TRANSIENT


async def _worker(q: asyncio.Queue, session, pool, totals: dict) -> None:
    while True:
        try:
            row = q.get_nowait()
        except asyncio.QueueEmpty:
            return
        verdict = await _check_one(session, row["listing_url"], str(row["external_id"]))
        try:
            await apply_verdict(pool, row["id"], verdict, DRY_RUN)
        except Exception as e:
            logger.warning("apply failed for %s: %s", row["id"], e)
            totals["errors"] += 1
        totals[verdict] += 1
        totals["checked"] += 1
        await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        q.task_done()


async def run_liveness(dry_run: bool = DRY_RUN) -> dict:
    pool = await get_pool()
    async with pool.acquire() as c:
        source_id = await c.fetchval("SELECT id FROM sources WHERE name='kolesa'")
    if source_id is None:
        raise RuntimeError("kolesa source not found")

    totals = {ALIVE: 0, CLOSED: 0, TRANSIENT: 0, "checked": 0, "errors": 0}
    deadline = time.monotonic() + TIME_BUDGET_MIN * 60
    logger.info("liveness start: budget=%.0fmin batch=%d concurrency=%d dry_run=%s",
                TIME_BUDGET_MIN, BATCH, CONCURRENCY, dry_run)

    async with requests.AsyncSession(impersonate="chrome") as session:
        while time.monotonic() < deadline:
            rows = await select_liveness_batch(pool, source_id, BATCH)
            if not rows:
                logger.info("queue drained — all active listings checked")
                break
            q: asyncio.Queue = asyncio.Queue()
            for r in rows:
                q.put_nowait(r)
            await asyncio.gather(*[_worker(q, session, pool, totals)
                                   for _ in range(CONCURRENCY)])
            logger.info("progress: checked=%d alive=%d closed=%d transient=%d",
                        totals["checked"], totals[ALIVE], totals[CLOSED], totals[TRANSIENT])
    return totals


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    start = time.time()
    stats = asyncio.run(run_liveness())
    elapsed = time.time() - start
    print(f"Liveness done in {elapsed:.0f}s {'[DRY-RUN] ' if DRY_RUN else ''}"
          f"checked={stats['checked']} alive={stats['alive']} "
          f"closed={stats['closed']} transient={stats['transient']} errors={stats['errors']}")
```

- [ ] **Step 2: Проверить компиляцию**

Run: `python -m py_compile parsers/kolesa/liveness.py parsers/kolesa/liveness_classify.py`
Expected: без вывода (успех).

- [ ] **Step 3: Прогнать unit-тесты ещё раз (регресс)**

Run: `PYTHONPATH=. pytest tests/test_liveness_classify.py -v`
Expected: PASS (8 passed).

- [ ] **Step 4: Commit**

```bash
git add parsers/kolesa/liveness.py
git commit -m "feat(kolesa): liveness sweep worker (cursor-resumable, time-boxed)"
```

---

## Task 4: Dry-run валидация против прода (обязательно перед записью)

**Files:** нет (валидация). Зависит от применённой миграции (Task 1) и установленных зависимостей.

- [ ] **Step 1: Установить зависимости парсеров (если ещё нет)**

Run: `pip install -r parsers/requirements.txt`
Expected: curl_cffi, asyncpg, python-dotenv, pytest установлены.

- [ ] **Step 2: Прогнать малый dry-run на проде**

Run:
```bash
DATABASE_URL="<neon pooler url>" LIVENESS_DRY_RUN=1 LIVENESS_BATCH=200 \
  LIVENESS_TIME_BUDGET_MIN=8 python -m parsers.kolesa.liveness
```
Expected: лог `progress: checked=... alive=... closed=... transient=...`, в конце `[DRY-RUN]`. Ни одной записи в БД (dry-run).

- [ ] **Step 3: Сверить вердикты с ожиданием**

Проверка глазами (правило CLAUDE.md про bulk-операции): на выборке «дольше всех не проверенных» доля `closed` должна быть в районе ~15%+ (проба из спеки), `alive` — большинство, `transient` — единицы. Если `closed` подозрительно высок (>60%) — СТОП: вероятен soft-404 false-positive или анти-бот challenge, отдающий не-листинг 200. Разобраться до записи.

- [ ] **Step 4: Точечная проверка одного известного мёртвого URL**

Run:
```bash
curl -s -o /dev/null -w "%{http_code}\n" -A "Mozilla/5.0" https://kolesa.kz/a/show/217539026
```
Expected: `404`. (Контрольный известный «мертвец» из спеки — классификатор должен дать CLOSED.)

- [ ] **Step 5: Commit** (нечего коммитить — это валидация; зафиксировать вывод в PR-описании/заметке)

---

## Task 5: Workflow `kolesa_liveness.yml`

**Files:**
- Create: `.github/workflows/kolesa_liveness.yml`

- [ ] **Step 1: Написать workflow**

Create `.github/workflows/kolesa_liveness.yml`:

```yaml
name: Kolesa Liveness Sweep

# Курсор-резюмируемый проход по активным kolesa-объявлениям: пингует URL,
# ставит closed_at на 404 (продано), освежает last_seen_at на 200.
# Каждый прогон time-boxed (300 мин), несколько прогонов/сутки перекрывают
# весь активный набор. Резюмируемость — через last_checked_at в БД.

on:
  schedule:
    - cron: '15 1,7,13,19 * * *'   # 4×/сутки, со сдвигом от kolesa_full/daily/alive
  workflow_dispatch:
    inputs:
      dry_run:
        description: 'Dry-run (не писать в БД)'
        required: false
        default: '0'
      time_budget_min:
        description: 'Бюджет времени на прогон, мин'
        required: false
        default: '300'

concurrency:
  group: kolesa-liveness
  cancel-in-progress: false   # не убиваем — ждём в очереди

env:
  PYTHONPATH: ${{ github.workspace }}

jobs:
  liveness:
    name: Liveness sweep (kolesa)
    runs-on: ubuntu-latest
    timeout-minutes: 330       # < 6ч hard-cap; воркер сам выходит на 300
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
          cache-dependency-path: parsers/requirements.txt
      - name: Install dependencies
        run: pip install -r parsers/requirements.txt
      - name: Run liveness sweep
        run: python -m parsers.kolesa.liveness
        env:
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          LIVENESS_DRY_RUN: ${{ github.event.inputs.dry_run || '0' }}
          LIVENESS_TIME_BUDGET_MIN: ${{ github.event.inputs.time_budget_min || '300' }}
          LIVENESS_BATCH: '500'
          LIVENESS_CONCURRENCY: '2'
          LIVENESS_DELAY_MIN: '1.2'
          LIVENESS_DELAY_MAX: '2.5'
```

- [ ] **Step 2: Провалидировать YAML**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/kolesa_liveness.yml'))"`
Expected: без ошибок.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/kolesa_liveness.yml
git commit -m "ci(kolesa): liveness sweep workflow (4x/day, time-boxed, resumable)"
```

---

## Task 6: Bootstrap — вычистить бэклог 157k, затем включить расписание

**Files:** нет (операционная задача). Делать ПОСЛЕ успешного dry-run (Task 4).

- [ ] **Step 1: Боевой запуск вручную (без dry-run), маленький бюджет — первый «настоящий» батч**

GitHub → Actions → **Kolesa Liveness Sweep** → Run workflow → `dry_run=0`, `time_budget_min=30`.
Expected: прогон завершается ✅; в логе `closed=N` > 0.

- [ ] **Step 2: Подтвердить, что «продажи» наконец проставляются**

Run (psql/Neon):
```sql
SELECT count(*) FILTER (WHERE closed_at > now() - interval '1 hour') AS closed_last_hour
FROM listings WHERE source_id = (SELECT id FROM sources WHERE name='kolesa');
```
Expected: `closed_last_hour` > 0 — сигнал «продано» снова живой (был 0 за 30 дней).

- [ ] **Step 3: Прогнать bootstrap до перекрытия всего бэклога**

Запустить workflow вручную несколько раз (или дождаться расписания) с `time_budget_min=300`, пока не «протухших» почти не останется. Контроль:
```sql
SELECT count(*) FILTER (WHERE last_checked_at IS NULL) AS never_checked,
       count(*) FILTER (WHERE last_checked_at < now() - interval '36 hours') AS stale_checked
FROM listings WHERE source_id=(SELECT id FROM sources WHERE name='kolesa') AND is_active;
```
Expected (после bootstrap): `never_checked` → 0; `stale_checked` мал и держится низким за счёт расписания.

- [ ] **Step 4: Зафиксировать реальный dead-rate**

```sql
SELECT count(*) FILTER (WHERE closed_at > now() - interval '3 days') AS closed_3d
FROM listings WHERE source_id=(SELECT id FROM sources WHERE name='kolesa');
```
Записать число (ожидаем десятки тысяч закрытых фантомов). Сообщить владельцу: «активных» закономерно упало — аналитика выправлена, это не регресс.

---

## Task 7: Документация + backlog

**Files:**
- Modify: `README.md` (§Известные особенности / §Workflows / §Схема БД)
- Modify: `CHANGELOG.md`
- Modify: `/Users/ruslanbulgakov/Documents/personal/Колеса/.claudemetrics/backlog.json`

- [ ] **Step 1: README — добавить liveness в §GitHub Actions Workflows**

В `README.md`, в секцию workflows, добавить блок (рядом с alive_check):

```markdown
### `kolesa_liveness.yml` — детектор «продано» (liveness sweep)

Курсор-резюмируемый проход по ВСЕМ активным kolesa-объявлениям (порядок —
`last_checked_at NULLS FIRST`). GET listing_url: `200`+маркеры листа →
`last_seen_at=now()`; `404/410`/soft-404 → `is_active=FALSE, closed_at=now()`
(момент продажи); `5xx/сеть` → не трогаем. Time-boxed 300 мин, 4×/сутки
(`15 1,7,13,19 UTC`), ~2 req/s. Резюмируемость через `listings.last_checked_at`.
Поглощает роль `alive_check` (тот только реанимировал inactive).
```

И в §Схема БД добавить `last_checked_at` к колонкам `listings`.

- [ ] **Step 2: CHANGELOG — запись сверху**

Добавить в `CHANGELOG.md` сразу под `---` шапкой новую запись:

```markdown
## 2026-06-XX — Kolesa liveness sweep: детектор «продано» + полный охват (<sha>)

### Added
- **`parsers/kolesa/liveness.py`** + `liveness_classify.py` — курсор-резюмируемый
  liveness-проход по активным объявлениям; `404`→`closed_at` (продано), `200`→
  освежение `last_seen_at`. Pure-классификатор покрыт pytest.
- **`listings.last_checked_at`** + индекс `idx_listings_liveness` (миграция 001).
- **`.github/workflows/kolesa_liveness.yml`** — 4×/сутки, time-boxed 300 мин, resumable.

### Fixed
- Сигнал «продано» был мёртв >30 дней (deactivate под `success()`, а
  kolesa_full всегда отменялся по таймауту). Liveness ставит `closed_at` напрямую.

### Impact
- «Активных» kolesa закономерно снизилось (закрыты фантомы, накопленные с ~21 апр).
  Аналитика скорости продажи восстановлена. Это починка, не регресс.
```

- [ ] **Step 3: Обновить ClaudeMetrics backlog**

В `/Users/ruslanbulgakov/Documents/personal/Колеса/.claudemetrics/backlog.json`:
- `t-0004` (resumable checkpoints): `status` → `"done"`, в `notes` указать «поглощён liveness-first дизайном (Phase 1)».
- Добавить `t-0016` (Phase 2: discovery early-stop + newest-first + retire deep-parse) и `t-0017` (Phase 3: cycle-tracker + price-refresh during liveness + safety-deactivate). Поднять верхний `updatedAt`. Сохранить валидный JSON.

- [ ] **Step 4: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs(kolesa): document liveness sweep (workflow, schema, changelog)"
```
(backlog.json в основном чекауте — закоммитить отдельно при желании.)

---

## Self-Review (выполнено автором плана)

**Spec coverage:** Phase 0 (схема last_checked_at) → Task 1. Phase 1 liveness sweep (выборка по курсору, классификация 200/404/soft-404/transient, time-box, resumable) → Tasks 2-3. Анти-бот rate ~2 req/s, «не закрывать на неоднозначности» → классификатор TRANSIENT + apply_verdict. Bootstrap → Task 6. Workflow/matrix-волны → упрощено до single-job × расписание (Task 5) — даёт суточное перекрытие без риска параллелизма; sharding оставлен на потом (открытый вопрос спеки про каденцию). Поглощение alive_check, ретайр deep-parse → отмечены как Phase 2/3 (вне scope), `alive_check.yml` пока не трогаем (не мешает). Price-refresh → явно отложен (Phase 2, нужен FX). Документация/метрики → Task 7.

**Placeholder scan:** код приведён полностью в каждом шаге; команд с ожидаемым выводом — да; `<neon pooler url>` и `<sha>` — намеренные подстановки секрета/хэша, не код-плейсхолдеры.

**Type consistency:** `classify_listing(status_code, body, external_id)` и константы `ALIVE/CLOSED/TRANSIENT` едины в Tasks 2-3; `select_liveness_batch`/`apply_verdict`/`run_liveness` совпадают между объявлением (File Structure) и реализацией (Task 3); env-имена (`LIVENESS_*`) совпадают между воркером и workflow.
```
