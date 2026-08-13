"""Обращение к Auto.dev Vehicle Listings API.

Параметры запроса (zip/distance/vehicle.make/vehicle.year/retailListing.price/
retailListing.miles) взяты из официальной документации (docs.auto.dev).
На случай, если какое-то название всё же окажется неверным (например,
документация поменяется), запрос "самолечится": при ошибке 400 про
неизвестный параметр он убирается и запрос повторяется (см.
_extract_invalid_param/_remember_bad_param) — фильтрация по году/цене/
пробегу всё равно дублируется на нашей стороне в search_cars().

Названия полей в *ответе* API (структура data[].vehicle.*/retailListing.*)
подтверждены документацией только частично (vin/year/make/price и общая
форма ответа) — если какое-то поле у машины не заполняется (например,
всегда пустое фото), сырой ответ первой страницы каждого прогона
сохраняется в data/last_api_response.json — нужно заглянуть в этот файл
и поправить одну функцию parse_listing() ниже.
"""
import json
import logging
import re
from datetime import date
from typing import Any, Optional

import requests

from . import config

logger = logging.getLogger("car_finder.auto_dev")

BASE_URL = "https://api.auto.dev/listings"
PHOTOS_URL = "https://api.auto.dev/photos/{vin}"

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
        BAD_PARAMS_PATH.write_text(json.dumps(sorted(bad_params)), encoding="utf-8")
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

    # Диапазоны года/цены/пробега — по документации Auto.dev задаются через
    # тире (например vehicle.year=2019-2027), а не отдельными _min/_max.
    # Верхнюю границу года берём с запасом на пару лет вперёд (в продаже уже
    # бывают машины следующих модельных годов).
    year_upper = date.today().year + 2

    optional_params = {
        "vehicle.year": f"{config.SEARCH_YEAR_MIN}-{year_upper}",
        "retailListing.price": f"0-{config.SEARCH_PRICE_MAX}",
        "retailListing.miles": f"0-{config.SEARCH_MILEAGE_MAX}",
    }
    bad_params = _load_bad_params()

    def build_params(page: int) -> dict:
        p = {
            "zip": config.SEARCH_ZIP,
            "distance": config.SEARCH_DISTANCE,
            "vehicle.make": ",".join(config.SEARCH_MAKES),
            "page": page,
            "limit": 20,  # максимум на тарифе Starter — выше он всё равно обрежёт
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
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except (OSError, UnicodeError):
                pass  # это только отладочный файл, из-за него не стоит падать
            first_page_saved = True

        items = payload.get("data") if isinstance(payload, dict) else payload
        if not items:
            break
        all_items.extend(items)

        has_next = bool(_get_path(payload, "links.next")) if isinstance(payload, dict) else False
        if not has_next:
            break

    return all_items


def parse_listing(raw: dict) -> Optional[dict]:
    """Превращает "сырой" объект машины из API в понятный словарь.

    Названия полей подтверждены реальными примерами ответа из документации
    Auto.dev: вложенная структура {"vehicle": {...}, "retailListing": {...},
    "history": {...}}. Эта API не отдаёт ни текстового описания дилера, ни
    списка опций, ни нескольких фото — только одно retailListing.primaryImage.
    """
    vin = _first(raw, ["vehicle.vin", "vin"])
    if not vin:
        return None

    year = _first(raw, ["vehicle.year"])
    make = _first(raw, ["vehicle.make"])
    model = _first(raw, ["vehicle.model"])
    # Некоторые поля Auto.dev иногда присылает не строкой (например, trim
    # числом) — на всякий случай всегда приводим текстовые поля к str().
    trim = str(_first(raw, ["vehicle.trim"]) or "")
    make = str(make) if make is not None else None
    model = str(model) if model is not None else None

    exterior_color = str(_first(raw, ["vehicle.exteriorColor"]) or "")
    interior_color = str(_first(raw, ["vehicle.interiorColor"]) or "")
    engine = str(_first(raw, ["vehicle.engine"]) or "")
    drivetrain = str(_first(raw, ["vehicle.drivetrain"]) or "")

    price = _first(raw, ["retailListing.price"])
    mileage = _first(raw, ["retailListing.miles"])

    dealer_name = str(_first(raw, ["retailListing.dealer"]) or "")
    dealer_city = str(_first(raw, ["retailListing.city"]) or "")
    dealer_state = str(_first(raw, ["retailListing.state"]) or "")

    url = str(_first(raw, ["retailListing.vdp"]) or "")
    carfax_url = str(_first(raw, ["retailListing.carfaxUrl"]) or "")

    primary_image = _first(raw, ["retailListing.primaryImage"])
    photos = [primary_image] if isinstance(primary_image, str) and primary_image else []

    accidents = _first(raw, ["history.accidents"])
    owner_count = _first(raw, ["history.ownerCount"])

    try:
        year = int(year) if year is not None else None
        price = int(float(price)) if price is not None else None
        mileage = int(float(mileage)) if mileage is not None else None
        owner_count = int(owner_count) if owner_count is not None else None
    except (TypeError, ValueError):
        pass

    if year is None or price is None or price <= 0 or mileage is None or not make or not model:
        return None

    return {
        "vin": vin,
        "year": year,
        "make": make,
        "model": model,
        "trim": trim,
        "exterior_color": exterior_color,
        "interior_color": interior_color,
        "engine": engine,
        "drivetrain": drivetrain,
        "price": price,
        "mileage": mileage,
        "dealer_name": dealer_name,
        "dealer_city": dealer_city,
        "dealer_state": dealer_state,
        "url": url,
        "carfax_url": carfax_url,
        "accidents": accidents,
        "owner_count": owner_count,
        "description": "",
        "options_text": "",
        "photos": photos,
    }


def fetch_photos(api_key: str, vin: str, limit: int = 8) -> list:
    """Запрашивает несколько фото машины по VIN через отдельный Auto.dev
    Vehicle Photos API. Вызывается только для машин, которые реально
    отправляем в Telegram (не для всех найденных), чтобы не тратить лишние
    запросы к API. Если фото нет или запрос не удался — возвращает [].
    """
    try:
        resp = requests.get(
            PHOTOS_URL.format(vin=vin),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("Не удалось получить фото для VIN=%s: %s", vin, exc)
        return []

    if resp.status_code != 200:
        return []

    payload = resp.json()
    try:
        debug_dir = config.DATA_DIR / "photos_debug"
        debug_dir.mkdir(exist_ok=True)
        (debug_dir / f"{vin}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:
        pass

    photos = _first(payload, ["data.retail"])
    if not isinstance(photos, list):
        return []
    return [p for p in photos if isinstance(p, str)][:limit]


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
