"""Отбор "интересных" машин и оценка цены/рисков."""
import statistics
from typing import Optional

from . import config


def match_interesting_trim(car: dict) -> Optional[str]:
    """Ищет признак богатой комплектации в trim/options/описании.

    Возвращает найденное ключевое слово или None, если машина обычная.
    """
    keywords = config.INTERESTING_TRIM_KEYWORDS.get(car["make"], [])
    haystack = " ".join([
        car.get("trim") or "",
        car.get("options_text") or "",
        car.get("description") or "",
    ]).lower()
    for kw in keywords:
        if kw.strip() in haystack:
            return kw.strip()
    return None


def find_similar_cars(car: dict, pool: list) -> list:
    """Похожие машины: та же марка+модель, год ±1, пробег в разумных пределах."""
    similar = []
    for other in pool:
        if other["vin"] == car["vin"]:
            continue
        if other["make"] != car["make"] or other["model"] != car["model"]:
            continue
        if abs(other["year"] - car["year"]) > config.SIMILAR_YEAR_RANGE:
            continue
        if abs(other["mileage"] - car["mileage"]) > config.SIMILAR_MILEAGE_DELTA:
            continue
        similar.append(other)
    return similar


def price_comparison(car: dict, pool: list) -> dict:
    """Сравнивает цену машины с похожими. Возвращает словарь с результатом."""
    similar = find_similar_cars(car, pool)
    if len(similar) < 2:
        return {"similar_count": len(similar), "avg_price": None, "delta": None, "cheap_flag": False}

    avg_price = statistics.median(c["price"] for c in similar)
    delta = car["price"] - avg_price
    percent = (delta / avg_price) * 100 if avg_price else 0

    cheap_flag = (
        delta <= -config.PRICE_ANOMALY_MIN_DOLLARS
        and percent <= -config.PRICE_ANOMALY_MIN_PERCENT
    )

    return {
        "similar_count": len(similar),
        "avg_price": round(avg_price),
        "delta": round(delta),
        "percent": round(percent, 1),
        "cheap_flag": cheap_flag,
    }


def rental_heuristic(car: dict, matched_trim: Optional[str]) -> bool:
    """Грубая эвристика "похоже на бывшую прокатную машину"."""
    from datetime import date

    age_years = max(date.today().year - car["year"], 1)
    mileage_per_year = car["mileage"] / age_years

    base_trim = matched_trim is None
    high_mileage = mileage_per_year >= config.RENTAL_MILEAGE_PER_YEAR

    text = " ".join([
        car.get("description") or "",
        car.get("dealer_name") or "",
    ]).lower()
    keyword_hit = any(kw in text for kw in config.RENTAL_DESCRIPTION_KEYWORDS + config.RENTAL_DEALER_KEYWORDS)

    return keyword_hit or (base_trim and high_mileage)


def score_car(car: dict, matched_trim: Optional[str], price_info: dict, feedback_bonus: int) -> float:
    """Считает итоговый балл для сортировки — чем больше, тем выше в списке."""
    score = 0.0
    if matched_trim:
        score += 10
    if price_info.get("cheap_flag"):
        # Дешевле похожих — не обязательно плохо для покупателя, но рискованно,
        # поэтому не поднимаем балл сильно, просто помечаем в сообщении.
        score += 1
    elif price_info.get("delta") is not None and price_info["delta"] < 0:
        score += 3  # дешевле похожих, но без признаков риска — хороший вариант
    score += feedback_bonus * 2
    return score
