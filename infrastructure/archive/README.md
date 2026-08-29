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
| `sync_neon_to_local.sh [full]` | Синк Neon → локальный архив. Без аргумента — инкрементально по watermark (`sync_state`), `full` — полная пересинхронизация listings/price_history. Справочники всегда целиком (upsert). |
| `prune_neon.sh` | Подрезка Neon: сначала `sync full`, затем удаляет из Neon только те listings старше `HOT_DAYS`, которые подтверждённо есть в архиве (id + last_seen_at не старше + счётчик price_history не меньше). `DRY_RUN=1` по умолчанию. После удаления — `VACUUM ANALYZE`. |
| `com.kolesa.archive-sync.plist` | launchd: ежедневный инкрементальный синк в 03:30. |
| `com.kolesa.archive-prune.plist` | launchd: еженедельная подрезка (вс 04:30, `DRY_RUN=0`, `HOT_DAYS=90`). |

Установка launchd-агентов (копии лежат в `~/Library/LaunchAgents/`):

```bash
cp infrastructure/archive/com.kolesa.archive-*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.kolesa.archive-sync.plist
launchctl load ~/Library/LaunchAgents/com.kolesa.archive-prune.plist
```

Логи: `~/Library/Logs/kolesa-archive/{sync,prune,launchd-*}.log`.

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
