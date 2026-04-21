#!/usr/bin/env python3
"""Extract per-image EXIF context for stock-photo review workflows.

This helper is designed for the stock-photo-metadata skill. Run it before opening
images so review can start with factual EXIF clues such as capture date and GPS.
It does not attempt network reverse geocoding. Instead, it reports coordinates,
a coarse country guess, and optional nearby landmarks from a local JSON database.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}

COUNTRY_BOXES = [
    ('Taiwan', (21.5, 25.5, 119.0, 122.5)),
    ('South Korea', (33.0, 39.5, 124.0, 132.0)),
    ('Japan', (24.0, 46.5, 123.0, 146.5)),
    ('Thailand', (5.0, 21.0, 97.0, 106.0)),
    ('United States', (24.0, 49.5, -125.0, -66.0)),
    ('Canada', (41.0, 84.0, -141.0, -52.0)),
    ('United Kingdom', (49.5, 59.0, -8.5, 2.5)),
    ('France', (41.0, 51.5, -5.5, 9.8)),
    ('Germany', (47.0, 55.5, 5.0, 16.0)),
    ('Italy', (35.0, 47.5, 6.0, 19.0)),
    ('Spain', (27.0, 44.5, -18.5, 4.5)),
    ('Australia', (-44.5, -10.0, 112.0, 154.5)),
    ('New Zealand', (-48.0, -33.0, 166.0, 179.5)),
]


@dataclass
class ExifContext:
    filename: str
    created_at: str
    has_gps: bool
    latitude: float | None
    longitude: float | None
    country_guess: str
    landmark_hint: str
    maps_url: str


@dataclass
class LandmarkPoint:
    name: str
    latitude: float
    longitude: float
    radius_km: float = 1.0
    city: str = ''
    country: str = ''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Extract EXIF context before stock-photo review.')
    parser.add_argument('image_dir', help='Directory containing source images.')
    parser.add_argument('--output', help='Optional path for JSON output.')
    parser.add_argument(
        '--landmark-db',
        help='Optional JSON file with known landmark points to compare against GPS coordinates.',
    )
    return parser.parse_args()


def get_exif(image_path: Path) -> dict:
    with Image.open(image_path) as image:
        raw = image.getexif()
    exif: dict = {}
    for tag_id, value in raw.items():
        tag = TAGS.get(tag_id, tag_id)
        if tag == 'GPSInfo':
            gps_raw = raw.get_ifd(tag_id) if hasattr(raw, 'get_ifd') else value
            gps_data = {}
            if hasattr(gps_raw, 'items'):
                for gps_tag_id, gps_value in gps_raw.items():
                    gps_data[GPSTAGS.get(gps_tag_id, gps_tag_id)] = gps_value
            exif[tag] = gps_data
        else:
            exif[tag] = value
    return exif


def dms_to_decimal(values, ref: str) -> float | None:
    if not isinstance(values, (tuple, list)) or len(values) != 3:
        return None

    def rational_to_float(item) -> float:
        if isinstance(item, tuple):
            numerator, denominator = item
        else:
            numerator = getattr(item, 'numerator', None)
            denominator = getattr(item, 'denominator', None)
            if numerator is None or denominator is None:
                return float(item)
        return float(numerator) / float(denominator)

    degrees = rational_to_float(values[0])
    minutes = rational_to_float(values[1])
    seconds = rational_to_float(values[2])
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in {'S', 'W'}:
        decimal *= -1
    return decimal


def extract_gps(exif: dict) -> tuple[float | None, float | None]:
    gps = exif.get('GPSInfo') or {}
    lat = dms_to_decimal(gps.get('GPSLatitude'), gps.get('GPSLatitudeRef', 'N'))
    lon = dms_to_decimal(gps.get('GPSLongitude'), gps.get('GPSLongitudeRef', 'E'))
    return lat, lon


def guess_country(latitude: float | None, longitude: float | None) -> str:
    if latitude is None or longitude is None:
        return ''
    for country, (lat_min, lat_max, lon_min, lon_max) in COUNTRY_BOXES:
        if lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max:
            return country
    return ''


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_landmarks(path: Path | None) -> list[LandmarkPoint]:
    if path is None or not path.exists():
        return []
    data = json.loads(path.read_text(encoding='utf-8'))
    items = data.get('landmarks', data)
    landmarks: list[LandmarkPoint] = []
    for item in items:
        landmarks.append(
            LandmarkPoint(
                name=item['name'],
                latitude=float(item['latitude']),
                longitude=float(item['longitude']),
                radius_km=float(item.get('radius_km', 1.0)),
                city=item.get('city', ''),
                country=item.get('country', ''),
            )
        )
    return landmarks


def nearest_landmark(latitude: float | None, longitude: float | None, landmarks: Iterable[LandmarkPoint]) -> str:
    if latitude is None or longitude is None:
        return ''
    best_name = ''
    best_distance = None
    for landmark in landmarks:
        distance = haversine_km(latitude, longitude, landmark.latitude, landmark.longitude)
        if distance <= landmark.radius_km and (best_distance is None or distance < best_distance):
            place = landmark.name
            if landmark.city:
                place = f'{place} ({landmark.city})'
            if landmark.country:
                place = f'{place}, {landmark.country}'
            best_name = f'{place} [{distance:.2f} km]'
            best_distance = distance
    return best_name


def build_maps_url(latitude: float | None, longitude: float | None) -> str:
    if latitude is None or longitude is None:
        return ''
    return f'https://www.openstreetmap.org/?mlat={latitude:.6f}&mlon={longitude:.6f}#map=17/{latitude:.6f}/{longitude:.6f}'


def iter_images(image_dir: Path) -> Iterable[Path]:
    for path in sorted(image_dir.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
            yield path


def main() -> int:
    args = parse_args()
    image_dir = Path(args.image_dir).expanduser().resolve()
    landmarks = load_landmarks(Path(args.landmark_db).expanduser().resolve() if args.landmark_db else None)

    rows: list[ExifContext] = []
    for image_path in iter_images(image_dir):
        exif = get_exif(image_path)
        created_at = str(exif.get('DateTimeOriginal') or exif.get('DateTime') or '')
        latitude, longitude = extract_gps(exif)
        rows.append(
            ExifContext(
                filename=image_path.name,
                created_at=created_at,
                has_gps=latitude is not None and longitude is not None,
                latitude=latitude,
                longitude=longitude,
                country_guess=guess_country(latitude, longitude),
                landmark_hint=nearest_landmark(latitude, longitude, landmarks),
                maps_url=build_maps_url(latitude, longitude),
            )
        )

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.write_text(
            json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
            encoding='utf-8',
        )

    print('filename\tcreated_at\thas_gps\tlatitude\tlongitude\tcountry_guess\tlandmark_hint\tmaps_url')
    for row in rows:
        print(
            '\t'.join(
                [
                    row.filename,
                    row.created_at,
                    'yes' if row.has_gps else 'no',
                    '' if row.latitude is None else f'{row.latitude:.6f}',
                    '' if row.longitude is None else f'{row.longitude:.6f}',
                    row.country_guess,
                    row.landmark_hint,
                    row.maps_url,
                ]
            )
        )
    return 0


if __name__ == '__main__':
    raise SystemExit(main())



