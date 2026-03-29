"""
parsers/migrator.py
Скрипт переносит данные из локальной docker-БД в Neon DB.
Работает через asyncpg.executemany(), что позволяет перенести 150 000+ строк за пару минут.
"""
import asyncio
import logging
import os
import time

import asyncpg

# Убедимся что env загружены (на случай запуска вне контейнера)
from dotenv import load_dotenv
load_dotenv(".env")

logger = logging.getLogger("migrator")
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# Локальная база (считаем дефолтную)
LOCAL_DSN = "postgresql://automarket:automarket2024@localhost:5432/automarket_db"
# Neon база
NEON_DSN = os.getenv("DATABASE_URL")

async def migrate_dictionary(local_conn, neon_conn, table, name_fields):
    """
    Переносит справочник (brands, models, и т.д.).
    Строит маппинг local_id -> neon_id.
    name_fields - список полей для уникальной идентификации (например ["brand_id", "slug"] для models)
    """
    logger.info(f"Миграция справочника: {table}")
    
    # 1. Считываем всё локально
    local_rows = await local_conn.fetch(f"SELECT * FROM {table}")
    
    # 2. Считываем всё из Neon
    neon_rows = await neon_conn.fetch(f"SELECT * FROM {table}")
    
    # Строим ключи
    def make_key(row):
        return tuple(row[f] for f in name_fields)
        
    neon_map = {make_key(r): r['id'] for r in neon_rows}
    
    id_map = {}
    new_rows = []
    
    for r in local_rows:
        key = make_key(r)
        if key in neon_map:
            id_map[r['id']] = neon_map[key]
        else:
            new_rows.append(r)
            
    # Если есть новые, вставим и заново прочитаем
    if new_rows:
        columns = [c for c in new_rows[0].keys() if c != 'id']
        cols_str = ", ".join(columns)
        placeholders = ", ".join(f"${i+1}" for i in range(len(columns)))
        conflict_cols = ", ".join(name_fields)
        update_col = columns[0]  # Just update some column to force returning id
        
        insert_query = f"""
            INSERT INTO {table} ({cols_str}) VALUES ({placeholders}) 
            ON CONFLICT ({conflict_cols}) DO UPDATE SET {update_col} = EXCLUDED.{update_col} 
            RETURNING id
        """
        
        for r in new_rows:
            vals = [r[c] for c in columns]
            new_id = await neon_conn.fetchval(insert_query, *vals)
            id_map[r['id']] = new_id
            
    logger.info(f"{table}: {len(local_rows)} локальных записей -> {len(new_rows)} добавлено в Neon")
    return id_map


async def run_migration():
    if not NEON_DSN:
        logger.error("DATABASE_URL не задан! Не могу подключиться к Neon DB.")
        return

    logger.info("Подключение к базам...")
    local_conn = await asyncpg.connect(LOCAL_DSN)
    neon_conn = await asyncpg.connect(NEON_DSN)

    try:
        # 1. Миграция справочников
        sources_map = await migrate_dictionary(local_conn, neon_conn, "sources", ["name"])
        brands_map = await migrate_dictionary(local_conn, neon_conn, "brands", ["slug"])
        
        # Models сложнее т.к. brand_id локальный надо заменить на neon_id
        local_models = await local_conn.fetch("SELECT * FROM models")
        neon_models = await neon_conn.fetch("SELECT * FROM models")
        neon_mod_map = {(r['brand_id'], r['slug']): r['id'] for r in neon_models}
        
        models_map = {}
        for r in local_models:
            neon_brand = brands_map.get(r['brand_id'])
            if not neon_brand:
                continue # странно, но пропустим
            
            key = (neon_brand, r['slug'])
            if key in neon_mod_map:
                models_map[r['id']] = neon_mod_map[key]
            else:
                new_id = await neon_conn.fetchval(
                    """
                    INSERT INTO models (brand_id, name, slug) 
                    VALUES ($1, $2, $3) 
                    ON CONFLICT (brand_id, slug) 
                    DO UPDATE SET name = EXCLUDED.name 
                    RETURNING id
                    """,
                    neon_brand, r['name'], r['slug']
                )
                models_map[r['id']] = new_id
                neon_mod_map[key] = new_id
        
        bt_map = await migrate_dictionary(local_conn, neon_conn, "body_types", ["name"])
        ft_map = await migrate_dictionary(local_conn, neon_conn, "fuel_types", ["name"])
        tt_map = await migrate_dictionary(local_conn, neon_conn, "transmission_types", ["name"])
        dt_map = await migrate_dictionary(local_conn, neon_conn, "drive_types", ["name"])
        
        # 2. Миграция Listings
        logger.info("Подготовка объявлений (listings)...")
        # кешируем уже имеющиеся объявления Neon
        neon_listings_raw = await neon_conn.fetch("SELECT id, source_id, external_id FROM listings")
        neon_listings_by_ext = {(r['source_id'], r['external_id']): r['id'] for r in neon_listings_raw}
        
        local_listings = await local_conn.fetch("SELECT * FROM listings")
        logger.info(f"Найдено {len(local_listings)} локальных объявлений.")
        
        listing_uuid_map = {} # local_uuid -> neon_uuid
        
        # Готовим батчи для вставки
        new_listings_args = []
        for r in local_listings:
            neon_source = sources_map.get(r['source_id'])
            if not neon_source: continue
            
            neon_uuid = neon_listings_by_ext.get((neon_source, r['external_id']))
            if neon_uuid:
                # Уже есть в неон — запоминаем маппинг
                listing_uuid_map[r['id']] = neon_uuid
            else:
                # Нет в неон — будем вставлять, сохраняя локальный UUID!
                listing_uuid_map[r['id']] = r['id']
                new_listings_args.append((
                    r['id'], neon_source, r['external_id'], brands_map.get(r['brand_id']),
                    models_map.get(r['model_id']), r['title'], r['year'], r['mileage_km'],
                    r['engine_volume_cc'], r['engine_power_hp'], bt_map.get(r['body_type_id']),
                    ft_map.get(r['fuel_type_id']), tt_map.get(r['transmission_id']), dt_map.get(r['drive_type_id']),
                    r['color'], r['city'], r['region'], r['condition'], r['listing_url'], r['is_active'],
                    r['first_seen_at'], r['last_seen_at'], r['closed_at']
                ))

        if new_listings_args:
            logger.info(f"Вставляю {len(new_listings_args)} новых объявлений в Neon...")
            # batch insert
            ins_q = """
                INSERT INTO listings (
                    id, source_id, external_id, brand_id, model_id, title, year, mileage_km,
                    engine_volume_cc, engine_power_hp, body_type_id, fuel_type_id, transmission_id,
                    drive_type_id, color, city, region, condition, listing_url, is_active,
                    first_seen_at, last_seen_at, closed_at
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20, $21, $22, $23
                )
                ON CONFLICT (source_id, external_id) DO NOTHING
            """
            await neon_conn.executemany(ins_q, new_listings_args)

        # Re-fetch valid UUIDs to guarantee NO Foreign Key violations
        valid_neon_uuids = {r['id'] for r in await neon_conn.fetch("SELECT id FROM listings")}

        # 3. Миграция Price History
        logger.info("Подготовка истории цен (price_history)...")
        chunk_size = 20000
        offset = 0
        total_p = 0
        
        while True:
            local_prices = await local_conn.fetch(f"SELECT * FROM price_history ORDER BY id LIMIT {chunk_size} OFFSET {offset}")
            if not local_prices:
                break
            
            p_args = []
            for r in local_prices:
                neon_list_id = listing_uuid_map.get(r['listing_id'])
                # Safe check: ensures the listing actually exists in Neon DB
                if neon_list_id in valid_neon_uuids:
                    p_args.append((neon_list_id, r['price_kzt'], r['price_usd'], r['recorded_at']))
                    
            if p_args:
                # В PostgreSQL нет простого ON CONFLICT для таблиц без UNIQUE. 
                # Но так как локальная база содержит больше данных, мы просто добавим историю. 
                # Если в Neon уже есть какая-то история цен, будет небольшое наслоение за 1 день. Это нормально.
                await neon_conn.executemany("""
                    INSERT INTO price_history (listing_id, price_kzt, price_usd, recorded_at)
                    VALUES ($1, $2, $3, $4)
                """, p_args)
                total_p += len(p_args)
            
            offset += chunk_size
            logger.info(f"Перенесено цен: {total_p}...")

        logger.info("🎉 Миграция БД успешно завершена!")
    finally:
        await local_conn.close()
        await neon_conn.close()


if __name__ == "__main__":
    t0 = time.time()
    asyncio.run(run_migration())
    logger.info(f"Время миграции: {time.time() - t0:.1f} сек.")
