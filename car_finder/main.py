"""Точка входа: раз в день ищет машины и присылает подходящие в Telegram.

Запуск: python -m car_finder.main   (или просто ./run.sh)
"""
import logging
import sys

from . import config, feedback, scoring, storage, telegram_bot
from .auto_dev_client import AutoDevError, fetch_photos, search_cars

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("car_finder.main")


def format_caption(car: dict, matched_trim, price_info: dict, accident_status: str, is_rental_suspect: bool) -> str:
    lines = []
    trim_part = f" {car['trim']}" if car["trim"] else ""
    lines.append(f"{car['year']} {car['make']} {car['model']}{trim_part}")
    lines.append(f"Цена: ${car['price']:,}")
    lines.append(f"Пробег: {car['mileage']:,} миль")

    dealer_line = car["dealer_name"] or "Дилер не указан"
    if car["dealer_city"]:
        dealer_line += f", {car['dealer_city']}"
        if car["dealer_state"]:
            dealer_line += f" {car['dealer_state']}"
    lines.append(dealer_line)

    if car["url"]:
        lines.append(car["url"])
    if car["carfax_url"]:
        lines.append(f"Carfax: {car['carfax_url']}")

    notes = []
    delta = price_info.get("delta")
    if accident_status == "confirmed":
        notes.append("⚠️ В истории машины числится авария (данные Auto.dev).")
    elif accident_status == "suspected":
        notes.append(
            f"⚠️ Дешевле похожих на ${abs(delta):,} — проверить историю (возможна авария/salvage)."
        )
    elif delta is not None:
        if delta < 0:
            notes.append(f"Дешевле похожих на ${abs(delta):,}.")
        elif delta > 0:
            notes.append(f"Дороже похожих на ${delta:,}.")

    if is_rental_suspect:
        notes.append("⚠️ Похоже на бывшую прокатную/перекупную машину — базовая комплектация, большой пробег для года и/или много владельцев.")

    if notes:
        lines.append("")
        lines.extend(notes)

    return "\n".join(lines)


def run():
    if not config.AUTO_DEV_API_KEY:
        logger.error("В .env не задан AUTO_DEV_API_KEY — заполните файл .env и запустите снова.")
        sys.exit(1)
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        logger.error("В .env не заданы TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID.")
        sys.exit(1)

    with storage.connect() as conn:
        logger.info("Проверяю новые реакции 👍/👎 в Telegram...")
        feedback.poll_reactions(conn, config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID)
        prefs = feedback.load_preferences()

        logger.info("Ищу машины на Auto.dev (один поиск с пагинацией)...")
        try:
            pool = search_cars(config.AUTO_DEV_API_KEY)
        except AutoDevError as exc:
            logger.error("Ошибка Auto.dev API: %s", exc)
            sys.exit(1)
        logger.info("Найдено машин по базовым фильтрам: %d", len(pool))

        candidates = []
        for car in pool:
            matched_trim = scoring.match_interesting_trim(car)
            if not matched_trim:
                continue

            existing = storage.get_sent_car(conn, car["vin"])
            price_changed = existing is not None and existing["last_price"] != car["price"]
            already_sent_same_price = existing is not None and not price_changed
            if already_sent_same_price:
                continue

            price_info = scoring.price_comparison(car, pool)
            accident_status = scoring.accident_flag(car, price_info)
            is_rental_suspect = scoring.rental_heuristic(car, matched_trim)
            bonus = feedback.get_feedback_bonus(car, prefs)
            score = scoring.score_car(car, matched_trim, price_info, accident_status, bonus)

            candidates.append({
                "car": car,
                "matched_trim": matched_trim,
                "price_info": price_info,
                "accident_status": accident_status,
                "is_rental_suspect": is_rental_suspect,
                "price_changed": price_changed,
                "old_price": existing["last_price"] if existing else None,
                "score": score,
            })

        candidates.sort(key=lambda c: c["score"], reverse=True)

        limit = config.MAX_TEST_CARS if config.TEST_MODE else config.MAX_CARS_PER_RUN
        to_send = candidates[:limit]

        logger.info(
            "Подходящих новых/изменившихся машин: %d. Отправляю: %d%s",
            len(candidates), len(to_send), " (тестовый режим)" if config.TEST_MODE else "",
        )

        sent_count = 0
        for item in to_send:
            car = item["car"]
            if item["price_changed"]:
                text = (
                    f"Цена упала с ${item['old_price']:,} до ${car['price']:,}: "
                    f"{car['year']} {car['make']} {car['model']} {car['trim']}".strip()
                )
                if car["url"]:
                    text += f"\n{car['url']}"
                telegram_bot.send_text(config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, text)
                storage.mark_car_sent(conn, car)
                sent_count += 1
                continue

            caption = format_caption(car, item["matched_trim"], item["price_info"], item["accident_status"], item["is_rental_suspect"])

            photos = fetch_photos(config.AUTO_DEV_API_KEY, car["vin"]) or car["photos"]

            try:
                message_ids = telegram_bot.send_car_album(
                    config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, photos, caption
                )
            except Exception as exc:
                logger.error("Не удалось отправить машину VIN=%s: %s", car["vin"], exc)
                continue

            for mid in message_ids:
                storage.link_message_to_car(conn, mid, config.TELEGRAM_CHAT_ID, car["vin"])
            storage.mark_car_sent(conn, car)
            sent_count += 1

        logger.info("Готово. Отправлено сообщений: %d", sent_count)
        if config.TEST_MODE:
            logger.info(
                "Это тестовый режим (TEST_MODE=true в .env). "
                "Когда всё устроит — поставьте TEST_MODE=false и настройте расписание."
            )


if __name__ == "__main__":
    run()
