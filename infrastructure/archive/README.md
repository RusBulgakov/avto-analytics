# Архивный контур: Mac mini (полная история) + Neon (hot window)

## Зачем

Neon free tier ограничен **512 MB**. 2026-08-29 база упёрлась в лимит — все
пишущие workflow падали с `DiskFullError`. Данные проекта копятся бессрочно
(в этом суть аналитики), поэтому вместо удаления выбрана двухконтурная схема:

- **Neon** — «горячее окно»: всё, что kolesa показывал за последние `HOT_DAYS`
  (default 90) дней. Прод-фронт/бэк/парсеры работают только с ним, ничего в них
  менять не нужно.
- **Mac mini** (`kolesa_archive`, локальный Postgres 18, brew-сервис) — полная
  история: все объявления и вся price_history, когда-либо спарсенные,
  плюс данные из CSV-дампов прошлых архиваций (`archive-dumps/*.csv.gz`).

Архив только **накапливает**: локально строки никогда не удаляются.

## Компоненты

| Файл | Что делает |
|---|---|
| `install.sh [--run-now]` | Ставит/обновляет контур в launchd: копирует скрипты в `~/.local/share/kolesa-archive`, `DATABASE_URL` — в `~/.config/kolesa-archive/neon.env` (600), грузит агент `com.kolesa.archive-nightly`, удаляет старые `archive-sync`/`archive-prune`. `--run-now` — сразу прогнать через launchd. |
| `nightly.sh` | Точка входа launchd (ежедневно 03:30): синк (вс — full, иначе incr) + подрезка `DRY_RUN=0`. Итог → `~/Library/Logs/kolesa-archive/last-status`; при сбое — уведомление macOS. |
| `sync_neon_to_local.sh [full]` | Синк Neon → локальный архив. Без аргумента — инкрементально по watermark (`sync_state`), `full` — полная пересинхронизация listings/price_history. Справочники всегда целиком (upsert). |
| `prune_neon.sh` | Подрезка Neon: синк (`PRUNE_SYNC_MODE`, default full), затем удаляет из Neon только те listings, которые подтверждённо есть в архиве (id + last_seen_at не старше + счётчик price_history не меньше). Кандидаты: `last_seen_at` старше `HOT_DAYS` (90) **или** сверх бюджета `NEON_MAX_LISTINGS` (450k, самые давно не виденные, но не свежее `MIN_HOT_DAYS`=30). `DRY_RUN=1` по умолчанию. После удаления — `VACUUM ANALYZE`; если строк всё ещё больше бюджета — уведомление. |
| `neon_compact.sql` | Ручной runbook после КРУПНОЙ подрезки: DROP 4 вторичных индексов → REINDEX CONCURRENTLY раздутых → CREATE обратно. Возвращает файловое место (лимит Neon считает файлы). Гонять через direct-endpoint (без `-pooler`). |
| `common.sh` | Общие функции: поиск `DATABASE_URL`, `notify` (macOS). |
| `com.kolesa.archive-nightly.plist` | Шаблон launchd-агента (плейсхолдеры подставляет `install.sh`). |

Установка / обновление (после ЛЮБОЙ правки скриптов — launchd исполняет копии):

```bash
./infrastructure/archive/install.sh --run-now
cat ~/Library/Logs/kolesa-archive/last-status
```

Логи: `~/Library/Logs/kolesa-archive/{sync,prune,launchd-nightly}.log`, итог — `last-status`.

### Почему скрипты не запускаются прямо из репо

Репо лежит в `~/Documents`, а macOS (TCC) запрещает фоновым launchd-процессам
доступ к `~/Documents`, `~/Desktop`, `~/Downloads`. Первые агенты
(2026-08-29) указывали прямо в репо и каждую ночь падали с
`/bin/bash: ...: Operation not permitted` (exit 126) — молча, почти месяц.
Neon снова дорос до 512 MB, и 2026-09-20…25 все пишущие парсеры падали с
`DiskFullError`. Full Disk Access для `/bin/bash` сознательно не выдаём (это
открыло бы весь диск любому bash-скрипту) — вместо этого копии вне `~/Documents`.

### Лимит Neon = размер файлов

Обычный `VACUUM` после подрезки освобождает место ВНУТРИ файлов (новые строки
ложатся туда), но файлы не уменьшаются. Индексы с растущим ключом
(`price_history.id`, `recorded_at`, kolesa `external_id`) растут правым краем и
требуют новые страницы — поэтому у потолка вставки цен падали даже после
подрезки 148k объявлений. Лекарство — `neon_compact.sql` (2026-09-25:
кластер 512 → 363 MB; `listings_source_id_external_id_key` 47 → 13 MB).
Ежедневная подрезка режет понемногу, и освобождённые страницы индексов
переиспользуются — компакт нужен только после крупных разовых подрезок.

## Как восстановить строку из архива обратно в Neon

Архив — обычный Postgres: `psql -h localhost -d kolesa_archive`. Выгрузить
нужные строки `\copy (...) TO ...` и залить в Neon тем же `\copy` + upsert.

## Устойчивость

- Watermark сдвигается только после полностью успешного синка; при падении
  следующий запуск дотянет всё с прошлой отметки (плюс запас 3 дня).
- Prune никогда не удалит строку, которой нет в архиве или которая в архиве
  старее, чем в Neon («rejected» в логе).
- Подключение к Neon берётся из `.env` в корне репо (`DATABASE_URL`).
- Разовый полный бэкап на момент запуска контура:
  `archive-dumps/neon_full_2026-08-29.dump` (pg_dump -Fc).

## Известные особенности

- 2026-08-29 в Neon дропнуты индексы `idx_listings_first_seen` и
  `idx_listings_liveness` (32+10 MB, почти не использовались) — стопгэп ради
  места. Если понадобятся — `CREATE INDEX` заново, схема в
  `database/init_neon.sql` остаётся источником правды.
- Схема архива = снапшот схемы Neon на 2026-08-29. При миграциях схемы в
  проде повторяй их и на архиве (`psql -h localhost -d kolesa_archive`),
  иначе синк новых колонок упадёт (скрипт сверяет колонки по локальной схеме).
- **Отличие схемы архива от Neon:** у локальной `listings` НЕТ уникального
  констрейнта `(source_id, external_id)` (заменён обычным индексом
  `idx_listings_source_external`). Причина: одно и то же объявление kolesa
  может быть снято и выложено заново → в истории несколько строк с разными
  `id`, но одинаковым `external_id` (разные «жизни» объявления). При выборке
  «текущего» состояния — `ORDER BY last_seen_at DESC LIMIT 1`.
