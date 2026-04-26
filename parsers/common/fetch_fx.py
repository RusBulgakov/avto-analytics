"""
parsers/common/fetch_fx.py — daily fetch USD/KZT (+ EUR/RUB/CNY) с National Bank
of Kazakhstan API. Хранит в `fx_history` таблице.

Используется analytics endpoint /forecast чтобы:
  1. Конвертировать historical price_kzt → price_usd per week
  2. OLS regression на price_usd (отделяет тренд цены от тренда KZT)
  3. Forecast price_usd → конвертировать обратно в KZT по current rate

NBK API: https://nationalbank.kz/rss/get_rates.cfm?fdate=DD.MM.YYYY → XML.
Cron: ежедневно в 06:00 UTC (08:00 Алматы — после publication NBK).
"""
import asyncio
import logging
import os
import re
from datetime import date, timedelta

from curl_cffi import requests

from parsers.common.db import db_conn

logger = logging.getLogger("fetch_fx")

NBK_URL = "https://nationalbank.kz/rss/get_rates.cfm"


async def _fetch_one_date(session, d: date) -> dict | None:
    """Возвращает {USD, EUR, RUB, CNY} → KZT rate для одной даты, или None при ошибке."""
    url = f"{NBK_URL}?fdate={d.strftime('%d.%m.%Y')}"
    try:
        r = await asyncio.wait_for(session.get(url, timeout=15), timeout=20)
        if r.status_code != 200:
            return None
        rates = {}
        for m in re.finditer(
            r'<item>\s*<fullname>[^<]*</fullname>\s*<title>(\w+)</title>'
            r'\s*<description>([\d.]+)</description>',
            r.text,
        ):
            rates[m.group(1)] = float(m.group(2))
        return rates
    except Exception as e:
        logger.warning("NBK fetch failed for %s: %s", d, e)
        return None


async def fetch_recent(days: int = 7) -> int:
    """
    Догружает последние N дней (default 7) из NBK. Дубли отбрасываются ON CONFLICT.
    Возвращает число новых записей.
    """
    today = date.today()
    dates_to_check = [today - timedelta(days=i) for i in range(0, days)]

    inserted = 0
    async with db_conn() as conn:
        # Узнаём какие даты уже есть
        existing = await conn.fetch(
            "SELECT rate_date FROM fx_history WHERE rate_date >= $1",
            dates_to_check[-1],
        )
        existing_set = {r["rate_date"] for r in existing}
        todo = [d for d in dates_to_check if d not in existing_set]

        if not todo:
            logger.info("All %d recent dates already in fx_history — nothing to fetch", days)
            return 0

        logger.info("Fetching %d missing dates from NBK", len(todo))

        async with requests.AsyncSession(impersonate="chrome") as session:
            for d in todo:
                rates = await _fetch_one_date(session, d)
                if not rates:
                    continue
                usd = rates.get("USD")
                if usd is None or usd < 100 or usd > 1000:
                    logger.warning("Suspicious USD rate %r for %s — skipping", usd, d)
                    continue
                try:
                    await conn.execute(
                        """
                        INSERT INTO fx_history (rate_date, usd_kzt, eur_kzt, rub_kzt, cny_kzt)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (rate_date) DO NOTHING
                        """,
                        d, usd, rates.get("EUR"), rates.get("RUB"), rates.get("CNY"),
                    )
                    inserted += 1
                except Exception as e:
                    logger.warning("Insert fail for %s: %s", d, e)
                await asyncio.sleep(0.4)

    logger.info("✓ Inserted %d new fx rates", inserted)
    return inserted


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    days_back = int(os.getenv("FX_BACKFILL_DAYS", "7"))
    n = asyncio.run(fetch_recent(days=days_back))
    print(f"Done. Inserted: {n}")
