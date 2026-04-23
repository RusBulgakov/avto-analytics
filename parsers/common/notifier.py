"""
parsers/common/notifier.py
Модуль для отправки уведомлений в Telegram.
"""
import os
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


def _creds() -> tuple[Optional[str], Optional[str]]:
    """Читает креды в момент вызова — чтобы load_dotenv() успел отработать."""
    return os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")


async def send_telegram_message(message: str) -> bool:
    """Отправляет сообщение в Telegram. Возвращает True, если успешно."""
    token, chat_id = _creds()
    if not token or not chat_id:
        logger.warning("Telegram credentials not set. Message not sent: %s", message)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

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


async def send_telegram_message_with_id(message: str) -> Optional[int]:
    """
    Как send_telegram_message, но возвращает message_id отправленного сообщения
    (нужен для последующего edit через edit_telegram_message). None при ошибке.
    """
    token, chat_id = _creds()
    if not token or not chat_id:
        logger.warning("Telegram credentials not set. Message not sent: %s", message)
        return None

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status != 200:
                    text = await response.text()
                    logger.error("Failed to send Telegram message: HTTP %d - %s", response.status, text)
                    return None
                data = await response.json()
                return data.get("result", {}).get("message_id")
    except Exception as e:
        logger.error("Error sending Telegram message: %s", e)
        return None


async def edit_telegram_message(message_id: int, new_text: str) -> bool:
    """
    Редактирует ранее отправленное сообщение через editMessageText.
    Если Telegram вернул "message is not modified" — это не ошибка, возвращаем True.
    """
    token, chat_id = _creds()
    if not token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": new_text,
        "parse_mode": "HTML",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as response:
                if response.status == 200:
                    return True
                text = await response.text()
                # "message is not modified" — безобидно, текст совпал
                if "message is not modified" in text:
                    return True
                logger.warning("Failed to edit Telegram message %d: HTTP %d - %s",
                               message_id, response.status, text)
                return False
    except Exception as e:
        logger.warning("Error editing Telegram message %d: %s", message_id, e)
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
