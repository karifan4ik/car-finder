"""Обращение к Auto.dev Vehicle Listings API.

ВАЖНО: этот файл написан "защищённо" — он умеет читать данные машины
из разных возможных вариантов названий полей в ответе API, потому что
на момент написания кода не было доступа к живой документации из
песочницы разработки. Сырой ответ первой страницы каждого прогона
сохраняется в data/last_api_response.json — если какое-то поле у машины
не заполняется (например, всегда пустой пробег), нужно заглянуть в этот
файл и поправить одну функцию parse_listing() ниже.
"""
import json
import logging
import re
from typing import Any, Optional

import requests

from . import config

logger = logging.getLogger("car_finder.auto_dev")

BASE_URL = "https://api.auto.dev/listings"

BAD_PARAMS_PATH = config.DATA_DIR / "auto_dev_bad_params.json"


class AutoDevError(RuntimeError):
    pass


def _load_bad_params() -> set:
    """Названия параметров запроса, про которые Auto.dev уже сказал
    "такого параметра нет" — чтобы больше их не отправлять и не тратить
    впустую запросы к API.
    """
    if not BAD_PARAMS_PATH.exists():
        return set()
    try:
        return set(json.loads(BAD_PARAMS_PATH.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def _remember_bad_param(name: str, bad_params: set):
    bad_params.add(name)
    try:
        BAD_PARAMS_PATH.write_text(json.dumps(sorted(bad_params)))
    except OSError:
        pass


def _extract_invalid_param(error_text: str, known_param_names) -> Optional[str]:
    """Пытается вытащить название "неправильного" параметра из текста ошибки API."""
    match = re.search(r"parameter[^:]*:\s*([A-Za-z0-9_]+)", error_text, re.IGNORECASE)
    if match and match.group(1) in known_param_names:
        return match.group(1)
    for name in known_param_names:
        if name in error_text:
            return name
    return None


def _get_path(obj: dict, path: str) -> Optional[Any]:
    """Достаёт значение по пути вида 'vehicle.vin'."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _first(obj: dict, paths: list) -> Optional[Any]:
    for path in paths:
        val = _get_path(obj, path)
        if val not in (None, ""):
            return val
    return None


def fetch_raw_pages(api_key: str, max_pages: int = None) -> list:
    """Делает один поиск с пагинацией. Возвращает список "сырых" объектов машин."""
    if not api_key:
        raise AutoDevError("Не задан AUTO_DEV_API_KEY в файле .env")

    max_pages = max_pages or config.MAX_API_PAGES
    headers = {"Authorization": f"Bearer {api_key}"}
    optional_params = {
        "year_min": config.SEARCH_YEAR_MIN,
        "price_max": config.SEARCH_PRICE_MAX,
        "mileage_max": config.SEARCH_MILEAGE_MAX,
    }
    bad_params = _load_bad_params()

    def build_params(page: int) -> dict:
        p = {
            "zip": config.SEARCH_ZIP,
            "distance": config.SEARCH_DISTANCE,
            "make": ",".join(config.SEARCH_MAKES),
            "page": page,
        }
        for name, value in optional_params.items():
            if name not in bad_params:
                p[name] = value
        return p

    all_items = []
    first_page_saved = False
    for page in range(1, max_pages + 1):
        # Год/цена/пробег дублируются нашим фильтром в search_cars(), поэтому
        # если API не примет какой-то из этих параметров — просто перестаём
        # его отправлять и пробуем снова, вместо того чтобы останавливать агента.
        for attempt in range(len(optional_params) + 1):
            params = build_params(page)
            resp = requests.get(BASE_URL, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                break
            if resp.status_code == 400:
                bad_name = _extract_invalid_param(resp.text, optional_params.keys())
                if bad_name and bad_name not in bad_params:
                    logger.warning(
                        "Auto.dev не принимает параметр '%s' — убираю его и пробую снова.", bad_name
                    )
                    _remember_bad_param(bad_name, bad_params)
                    continue
            raise AutoDevError(
                f"Auto.dev API вернул ошибку {resp.status_code}: {resp.text[:500]}"
            )
        else:
            raise AutoDevError("Auto.dev API постоянно отклоняет параметры запроса.")

        payload = resp.json()

        if not first_page_saved:
            try:
                (config.DATA_DIR / "last_api_response.json").write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False)
                )
            except OSError:
                pass
            first_page_saved = True

        items = payload.get("data") if isinstance(payload, dict) else payload
        if not items:
            break
        all_items.extend(items)

        has_next = bool(_get_path(payload, "links.next")) if isinstance(payload, dict) else False
        if not has_next and len(items) < 1:
            break
        if not has_next:
            # Нет явного признака следующей страницы — на всякий случай
            # останавливаемся, если страница вернула мало записей.
            if len(items) < 5:
                break

    return all_items


def parse_listing(raw: dict) -> Optional[dict]:
    """Превращает "сырой" объект машины из API в понятный словарь.

    Пробует несколько вариантов расположения полей, т.к. это либо
    плоский объект, либо вложенный ({"vehicle": {...}, "retailListing": {...}}).
    """
    vin = _first(raw, ["vehicle.vin", "vin", "VIN"])
    if not vin:
        return None

    year = _first(raw, ["vehicle.year", "year"])
    make = _first(raw, ["vehicle.make", "make"])
    model = _first(raw, ["vehicle.model", "model"])
    trim = _first(raw, ["vehicle.trim", "trim"]) or ""

    price = _first(raw, ["retailListing.price", "price", "listPrice"])
    mileage = _first(raw, ["retailListing.mileage", "mileage", "odometer"])

    dealer_name = _first(raw, ["retailListing.dealerName", "retailListing.dealer.name", "dealerName", "dealer.name"]) or ""
    dealer_city = _first(raw, ["retailListing.dealerCity", "retailListing.dealer.city", "dealerCity", "dealer.city"]) or ""
    dealer_state = _first(raw, ["retailListing.dealerState", "retailListing.dealer.state", "dealerState", "dealer.state"]) or ""

    url = _first(raw, ["retailListing.vdpUrl", "retailListing.clickoffUrl", "retailListing.url", "vdpUrl", "clickoffUrl", "url"]) or ""

    description = _first(raw, ["retailListing.description", "description"]) or ""

    options = _first(raw, ["retailListing.options", "options", "vehicle.options"])
    if isinstance(options, list):
        options_text = " ".join(str(o) for o in options)
    elif isinstance(options, str):
        options_text = options
    else:
        options_text = ""

    photos = _first(raw, ["retailListing.photoUrls", "retailListing.photos", "photoUrls", "photos", "vehicle.photoUrls"])
    if not isinstance(photos, list):
        photos = []
    photos = [p for p in photos if isinstance(p, str)]

    try:
        year = int(year) if year is not None else None
        price = int(float(price)) if price is not None else None
        mileage = int(float(mileage)) if mileage is not None else None
    except (TypeError, ValueError):
        pass

    if year is None or price is None or mileage is None or not make or not model:
        return None

    return {
        "vin": vin,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "price": price,
        "mileage": mileage,
        "dealer_name": dealer_name,
        "dealer_city": dealer_city,
        "dealer_state": dealer_state,
        "url": url,
        "description": description,
        "options_text": options_text,
        "photos": photos,
    }


def search_cars(api_key: str) -> list:
    """Один поиск с пагинацией + фильтрация на нашей стороне (на случай,
    если серверные фильтры на API назывались иначе, чем мы предположили).
    """
    raw_items = fetch_raw_pages(api_key)
    cars = []
    for raw in raw_items:
        car = parse_listing(raw)
        if car is None:
            continue
        if car["make"] not in config.SEARCH_MAKES:
            continue
        if car["year"] < config.SEARCH_YEAR_MIN:
            continue
        if car["mileage"] > config.SEARCH_MILEAGE_MAX:
            continue
        if car["price"] > config.SEARCH_PRICE_MAX:
            continue
        cars.append(car)
    return cars
