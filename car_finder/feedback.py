"""Чтение реакций 👍/👎 из Telegram и накопление истории вкуса пользователя."""
import json
import logging

from . import config, storage, telegram_bot

logger = logging.getLogger("car_finder.feedback")

FEEDBACK_PATH = config.DATA_DIR / "feedback.jsonl"

LIKE_EMOJIS = {"👍", "❤", "🔥", "👏"}
DISLIKE_EMOJIS = {"👎", "💩"}


def poll_reactions(conn, token: str, chat_id: str):
    """Проверяет новые реакции на ранее отправленные машины и дописывает feedback.jsonl."""
    last_offset = storage.get_meta(conn, "telegram_offset")
    offset = int(last_offset) + 1 if last_offset else None

    try:
        updates = telegram_bot.get_reaction_updates(token, offset=offset)
    except Exception as exc:
        logger.warning("Не удалось получить обновления из Telegram: %s", exc)
        return

    if not updates:
        return

    new_entries = []
    for update in updates:
        storage.set_meta(conn, "telegram_offset", str(update["update_id"]))

        reaction = update.get("message_reaction")
        if not reaction:
            continue
        if str(reaction.get("chat", {}).get("id")) != str(chat_id):
            continue

        message_id = reaction.get("message_id")
        car = storage.get_car_by_message(conn, message_id, chat_id)
        if not car:
            continue

        new_reactions = reaction.get("new_reaction", [])
        emojis = {r.get("emoji") for r in new_reactions if r.get("type") == "emoji"}

        if emojis & LIKE_EMOJIS:
            verdict = "like"
        elif emojis & DISLIKE_EMOJIS:
            verdict = "dislike"
        else:
            continue

        new_entries.append({
            "vin": car["vin"],
            "make": car["make"],
            "model": car["model"],
            "year": car["year"],
            "trim": car["trim"],
            "verdict": verdict,
        })

    if new_entries:
        with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
            for entry in new_entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info("Записано %d новых оценок в feedback.jsonl", len(new_entries))


def load_preferences() -> dict:
    """Читает feedback.jsonl и считает нетто-баллы по (марка, модель, комплектация).

    Возвращает словарь {(make, model, trim): счёт}, где счёт = лайки - дизлайки.
    """
    prefs = {}
    if not FEEDBACK_PATH.exists():
        return prefs

    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = (entry.get("make"), entry.get("model"), entry.get("trim"))
            delta = 1 if entry.get("verdict") == "like" else -1
            prefs[key] = prefs.get(key, 0) + delta

    return prefs


def get_feedback_bonus(car: dict, prefs: dict) -> int:
    """Ищет по машине точное совпадение, а если нет — по марке+модели."""
    exact_key = (car["make"], car["model"], car["trim"])
    if exact_key in prefs:
        return prefs[exact_key]

    total = 0
    for (make, model, _trim), score in prefs.items():
        if make == car["make"] and model == car["model"]:
            total += score
    return total
