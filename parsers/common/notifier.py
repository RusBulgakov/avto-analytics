"""
parsers/common/notifier.py
Модуль для отправки уведомлений в Telegram.
"""
import os
import logging
import aiohttp

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

async def send_telegram_message(message: str) -> bool:
    """Отправляет сообщение в Telegram. Возвращает True, если успешно."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not set. Message not sent: %s", message)
        return False
        
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error("Failed to send Telegram message: HTTP %d - %s", response.status, text)
                    return False
                return True
    except Exception as e:
        logger.error("Error sending Telegram message: %s", e)
        return False

async def send_success(source: str, scanned: int, start_time, end_time, new_listings: int = 0) -> bool:
    """Форматирует и отправляет сообщение об успешном завершении парсера."""
    duration = end_time - start_time
    minutes, seconds = divmod(int(duration), 60)
    time_str = f"{minutes}м {seconds}с"
    
    msg = (
        f"🟢 <b>Парсер {source} завершен!</b>\n"
        f"⏱ Время работы: {time_str}\n"
        f"📊 Обработано/Спарсено: {scanned}\n"
        f"🆕 Новых объявлений (добавлено): {new_listings}"
    )
    return await send_telegram_message(msg)

async def send_error(source: str, error: Exception) -> bool:
    """Форматирует и отправляет сообщение об ошибке парсера."""
    error_type = type(error).__name__
    error_msg = str(error)
    # limit error message length
    if len(error_msg) > 500:
        error_msg = error_msg[:500] + "..."
        
    msg = (
        f"🔴 <b>Ошибка в парсере {source}!</b>\n"
        f"⚠ Тип: {error_type}\n"
        f"📝 Детали: <code>{error_msg}</code>"
    )
    return await send_telegram_message(msg)
