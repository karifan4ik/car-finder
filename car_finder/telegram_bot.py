"""Отправка сообщений в Telegram и чтение реакций (👍/👎) на них."""
import logging

import requests

logger = logging.getLogger("car_finder.telegram")

API_ROOT = "https://api.telegram.org/bot{token}/{method}"


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, **kwargs):
    url = API_ROOT.format(token=token, method=method)
    resp = requests.post(url, timeout=30, **kwargs)
    data = resp.json()
    if not data.get("ok"):
        raise TelegramError(f"Telegram API {method} вернул ошибку: {data}")
    return data["result"]


def send_car_album(token: str, chat_id: str, photos: list, caption: str) -> list:
    """Отправляет альбом фото (2-10 шт.) с подписью на первом фото.

    Если фото нет или только одно — отправляет обычным сообщением/фото.
    Возвращает список id отправленных сообщений (для отслеживания реакций).
    """
    photos = photos[:8]

    if len(photos) == 0:
        result = _call(
            token, "sendMessage",
            json={"chat_id": chat_id, "text": caption, "disable_web_page_preview": True},
        )
        return [result["message_id"]]

    if len(photos) == 1:
        result = _call(
            token, "sendPhoto",
            json={"chat_id": chat_id, "photo": photos[0], "caption": caption},
        )
        return [result["message_id"]]

    media = [{"type": "photo", "media": url} for url in photos]
    media[0]["caption"] = caption
    results = _call(token, "sendMediaGroup", json={"chat_id": chat_id, "media": media})
    return [item["message_id"] for item in results]


def send_text(token: str, chat_id: str, text: str):
    _call(token, "sendMessage", json={"chat_id": chat_id, "text": text})


def get_reaction_updates(token: str, offset: int = None) -> list:
    """Забирает новые события, включая реакции (message_reaction).

    По умолчанию Telegram не присылает события реакций, пока явно не
    попросишь через allowed_updates.
    """
    payload = {
        "timeout": 0,
        "allowed_updates": ["message", "message_reaction"],
    }
    if offset is not None:
        payload["offset"] = offset
    return _call(token, "getUpdates", json=payload)
