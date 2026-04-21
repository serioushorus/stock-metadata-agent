from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_USER_AGENT = "stock-metadata-agent/0.1 local reverse-geocoder"
_LAST_REQUEST_AT = 0.0


@dataclass(frozen=True)
class ReverseGeocodeResult:
    city: str = ""
    state: str = ""
    country: str = ""
    source: str = "nominatim"


def reverse_geocode_location(
    latitude: float,
    longitude: float,
    cache_path: Path,
    timeout_seconds: float = 5.0,
) -> ReverseGeocodeResult | None:
    cache = _load_cache(cache_path)
    key = _cache_key(latitude, longitude)
    cached = cache.get(key)
    if isinstance(cached, dict):
        return _result_from_mapping(cached)

    payload = _fetch_nominatim(latitude, longitude, timeout_seconds)
    if payload is None:
        return None

    result = _parse_nominatim(payload)
    cache[key] = asdict(result)
    _write_cache(cache_path, cache)
    return result


def _cache_key(latitude: float, longitude: float) -> str:
    return f"{latitude:.5f},{longitude:.5f}"


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _result_from_mapping(value: dict[str, Any]) -> ReverseGeocodeResult | None:
    try:
        return ReverseGeocodeResult(
            city=str(value.get("city", "") or ""),
            state=str(value.get("state", "") or ""),
            country=str(value.get("country", "") or ""),
            source=str(value.get("source", "") or "nominatim"),
        )
    except (TypeError, ValueError):
        return None


def _fetch_nominatim(latitude: float, longitude: float, timeout_seconds: float) -> dict[str, Any] | None:
    global _LAST_REQUEST_AT

    elapsed = time.monotonic() - _LAST_REQUEST_AT
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)

    query = urllib.parse.urlencode(
        {
            "format": "jsonv2",
            "lat": f"{latitude:.7f}",
            "lon": f"{longitude:.7f}",
            "zoom": "18",
            "addressdetails": "1",
        }
    )
    request = urllib.request.Request(
        f"{NOMINATIM_URL}?{query}",
        headers={
            "Accept": "application/json",
            "Accept-Language": "en",
            "User-Agent": os.environ.get("STOCK_METADATA_GEOCODER_USER_AGENT", DEFAULT_USER_AGENT),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            _LAST_REQUEST_AT = time.monotonic()
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _parse_nominatim(payload: dict[str, Any]) -> ReverseGeocodeResult:
    address = payload.get("address")
    if not isinstance(address, dict):
        address = {}

    city = _first_text(address, ["city", "town", "municipality", "village"])
    state = _first_text(address, ["state", "province", "region"])
    country = _first_text(address, ["country"])
    return ReverseGeocodeResult(city=city, state=state, country=country, source="nominatim")


def _first_text(address: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = address.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
