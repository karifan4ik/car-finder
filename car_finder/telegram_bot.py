"""Отправка сообщений в Telegram и чтение реакций (👍/👎) на них."""
import logging
import re

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


def _extract_bad_media_index(error_message: str):
    """Из ошибки вида 'failed to send message #8 with the error message ...'
    достаёт номер фото в альбоме (1-based), которое Telegram не смог загрузить.
    """
    match = re.search(r"failed to send message #(\d+)", error_message)
    return int(match.group(1)) if match else None


def send_car_album(token: str, chat_id: str, photos: list, caption: str) -> list:
    """Отправляет альбом фото (2-10 шт.) с подписью на первом фото.

    Если фото нет или только одно — отправляет обычным сообщением/фото.
    Если Telegram не смог загрузить какое-то конкретное фото по ссылке
    (битая ссылка у дилера, защита от хотлинков и т.п.) — убирает именно
    его и пробует снова, а не отменяет отправку машины целиком.
    Возвращает список id отправленных сообщений (для отслеживания реакций).
    """
    photos = list(photos[:8])

    for _ in range(len(photos) + 1):
        if len(photos) == 0:
            result = _call(
                token, "sendMessage",
                json={"chat_id": chat_id, "text": caption, "disable_web_page_preview": True},
            )
            return [result["message_id"]]

        if len(photos) == 1:
            try:
                result = _call(
                    token, "sendPhoto",
                    json={"chat_id": chat_id, "photo": photos[0], "caption": caption},
                )
                return [result["message_id"]]
            except TelegramError as exc:
                logger.warning("Не удалось загрузить фото %s (%s) — отправляю без фото.", photos[0], exc)
                photos = []
                continue

        media = [{"type": "photo", "media": url} for url in photos]
        media[0]["caption"] = caption
        try:
            results = _call(token, "sendMediaGroup", json={"chat_id": chat_id, "media": media})
            return [item["message_id"] for item in results]
        except TelegramError as exc:
            bad_index = _extract_bad_media_index(str(exc))
            if bad_index is not None and 1 <= bad_index <= len(photos):
                logger.warning(
                    "Telegram не смог загрузить фото №%d (%s) — убираю его и пробую снова.",
                    bad_index, photos[bad_index - 1],
                )
                photos.pop(bad_index - 1)
                continue
            raise

    # На всякий случай, если фото так и не удалось подобрать — хотя бы текст.
    result = _call(
        token, "sendMessage",
        json={"chat_id": chat_id, "text": caption, "disable_web_page_preview": True},
    )
    return [result["message_id"]]


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
