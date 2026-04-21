#!/usr/bin/env python3
"""
Read per-image metadata markdown files, enrich them with pyinaturalist taxon
validation, and export provider-specific CSV files.

Workflow:
1. Read existing metadata .md files.
2. Validate and, when possible, enrich taxon candidates using pyinaturalist.
3. Export:
   - Shutterstock CSV
   - Adobe Stock CSV

Notes:
    Taxon candidates are read from `Notes` entries prefixed with `Taxon candidate:`.

Typical usage:
    python generate_stock_metadata.py 260327

Requirements:
    pip install pyinaturalist

Environment:
Optional:
    A local .env file in the project root is loaded automatically.
    pyinaturalist is optional but enables taxon validation for animal and plant subjects.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    from PIL import Image
    from PIL.ExifTags import GPSTAGS, TAGS
except ImportError:  # pragma: no cover - validated at runtime
    Image = None  # type: ignore[assignment]
    GPSTAGS = {}  # type: ignore[assignment]
    TAGS = {}  # type: ignore[assignment]

try:
    from pyinaturalist import ClientSession
    from pyinaturalist.v1.taxa import get_taxa, get_taxa_autocomplete
except ImportError:  # pragma: no cover - validated at runtime
    ClientSession = None  # type: ignore[assignment]
    get_taxa = None  # type: ignore[assignment]
    get_taxa_autocomplete = None  # type: ignore[assignment]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ[key] = value


load_dotenv(Path.cwd() / ".env")


DEFAULT_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_BOOLEAN_FLAGS = {"yes", "no"}
EDITORIAL_DESCRIPTION_PATTERN = re.compile(
    r"^(?:\[[^\]]+\]|[^,:]+), (?:\[[^\]]+\]|[^:]+?) - "
    r"(?:\[[^\]]+\]|[A-Z][a-z]+ \d{1,2}, \d{4}): .+\S$"
)


@dataclass
class Metadata:
    filename: str
    created_date: str
    country: str
    title: str
    description: str
    keywords: list[str]
    shutterstock_categories: list[str]
    adobe_category: str
    editorial: str
    mature_content: str
    illustration: str
    releases: str
    notes: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Read existing metadata markdown files, enrich them with pyinaturalist, "
            "and build Shutterstock and Adobe CSV exports from those markdown files."
        )
    )
    parser.add_argument("image_dir", help="Directory containing image files.")
    parser.add_argument(
        "--metadata-dir",
        help="Directory for per-image metadata markdown files. Defaults to image_dir.",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory for output CSV files. Defaults to image_dir.",
    )
    parser.add_argument(
        "--overwrite-csv",
        action="store_true",
        help="Overwrite existing CSV files.",
    )
    parser.add_argument(
        "--max-keywords",
        type=int,
        default=49,
        help="Maximum number of keywords to keep when rewriting enriched metadata.",
    )
    parser.add_argument(
        "--extensions",
        nargs="*",
        default=sorted(DEFAULT_EXTENSIONS),
        help="Image extensions to include. Default: .jpg .jpeg .png .webp",
    )
    return parser.parse_args()


def load_list_from_markdown(path: Path, bullet_prefix: str | None = None) -> list[str]:
    items: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if bullet_prefix:
            if line.startswith(bullet_prefix):
                items.append(line[len(bullet_prefix) :].strip())
        else:
            items.append(line.lstrip("- ").strip())
    return [item for item in items if item]


def load_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ValueError(f"{path} is empty") from exc
    if not header:
        raise ValueError(f"{path} does not contain a header row")
    return header


def build_adobe_category_map(categories: list[str]) -> dict[str, int]:
    return {name: idx for idx, name in enumerate(categories, start=1)}


def normalize_keywords(keywords: Iterable[str], max_keywords: int) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        value = re.sub(r"\s+", " ", keyword.strip().lower()).strip(" ,;")
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
        if len(cleaned) >= max_keywords:
            break
    return cleaned


def normalize_taxon_candidate(candidate: str) -> str:
    candidate = re.sub(r"\([^)]*\)", " ", candidate)
    return re.sub(r"\s+", " ", candidate.strip(" .;:,"))


def get_pyinaturalist_session() -> object | None:
    if ClientSession is None:
        return None

    cache_root = Path(
        os.environ.get("PYINATURALIST_CACHE_DIR", Path.cwd() / ".pyinaturalist_cache")
    ).expanduser()
    cache_root.mkdir(parents=True, exist_ok=True)
    return ClientSession(
        cache_file=str(cache_root / "api_requests.db"),
        ratelimit_path=str(cache_root / "api_ratelimit.db"),
        lock_path=str(cache_root / "api_ratelimit.lock"),
    )


def validate_taxon_candidate(candidate: str) -> dict | None:
    if not candidate:
        return None
    session = get_pyinaturalist_session()
    if get_taxa_autocomplete is None or session is None:
        return None

    query = normalize_taxon_candidate(candidate)
    def search(**params: object) -> list[dict]:
        try:
            response = get_taxa_autocomplete(session=session, **params)
        except Exception:
            return []
        return list(response.get("results") or [])

    results = search(q=query, is_active=True)
    if not results and " " in query and get_taxa is not None:
        first_token = query.split()[0]
        try:
            response = get_taxa(
                q=first_token,
                all_names=True,
                is_active=True,
                per_page=10,
                session=session,
            )
            results = list(response.get("results") or [])
        except Exception:
            results = []

    if not results:
        return None

    query_lc = query.lower()
    for result in results:
        name = str(result.get("name", "")).strip()
        matched_term = str(result.get("matched_term", "")).strip()
        common_name = str(result.get("preferred_common_name", "")).strip()
        if (
            name.lower() == query_lc
            or matched_term.lower() == query_lc
            or common_name.lower() == query_lc
        ):
            return result

    return None


def choose_taxon_result(
    taxon_candidate: str,
    validated_candidate: dict | None,
) -> tuple[dict | None, str]:
    if validated_candidate:
        candidate_name = str((validated_candidate or {}).get("name", taxon_candidate)).strip()
        taxon_rank = str((validated_candidate or {}).get("rank", "")).strip().lower()
        return validated_candidate, f"Taxon validated with pyinaturalist: {candidate_name} ({taxon_rank})."
    return None, ""


def get_taxon_candidate(meta: Metadata) -> str:
    note_match = re.search(
        r"taxon candidate\s*:\s*(.+?)(?=\.\s|;\s| taxon validated\b| taxon candidate not confirmed\b| pyinaturalist unavailable\b|$)",
        meta.notes,
        re.IGNORECASE,
    )
    if note_match:
        return normalize_taxon_candidate(note_match.group(1))

    return ""


def enrich_metadata_with_taxon(meta: Metadata, max_keywords: int) -> Metadata:
    candidate = get_taxon_candidate(meta)
    if not candidate:
        return meta
    if get_taxa_autocomplete is None:
        notes = meta.notes
        if "pyinaturalist unavailable; taxon validation skipped." not in notes:
            notes = f"{notes} pyinaturalist unavailable; taxon validation skipped.".strip()
        return Metadata(
            filename=meta.filename,
            created_date=meta.created_date,
            country=meta.country,
            title=meta.title,
            description=meta.description,
            keywords=meta.keywords,
            shutterstock_categories=meta.shutterstock_categories,
            adobe_category=meta.adobe_category,
            editorial=meta.editorial,
            mature_content=meta.mature_content,
            illustration=meta.illustration,
            releases=meta.releases,
            notes=notes,
        )

    validated_candidate = validate_taxon_candidate(candidate)
    taxon_result, taxon_validation_note = choose_taxon_result(candidate, validated_candidate)
    if not taxon_result:
        if candidate and "Taxon candidate not confirmed:" not in meta.notes:
            note = f"{meta.notes} Taxon candidate not confirmed: {candidate}."
            return Metadata(**{**meta.__dict__, "notes": note.strip()})
        return meta

    taxon_name = str(taxon_result.get("name", "")).strip()
    taxon_rank = str(taxon_result.get("rank", "")).strip().lower()
    common_name = str(taxon_result.get("preferred_common_name", "")).strip()
    if common_name and common_name.lower() not in {kw.lower() for kw in meta.keywords}:
        keyword_candidates = [common_name] + meta.keywords
    else:
        keyword_candidates = list(meta.keywords)
    if taxon_name and taxon_name.lower() not in {kw.lower() for kw in keyword_candidates}:
        if taxon_rank in {"species", "subspecies"}:
            keyword_candidates = [taxon_name] + keyword_candidates
        elif taxon_rank in {"genus", "family"}:
            keyword_candidates = keyword_candidates + [taxon_name]

    notes = meta.notes
    if taxon_validation_note and taxon_validation_note not in notes:
        notes = f"{notes} {taxon_validation_note}".strip()

    return Metadata(
        filename=meta.filename,
        created_date=meta.created_date,
        country=meta.country,
        title=meta.title,
        description=meta.description,
        keywords=normalize_keywords(keyword_candidates, max_keywords),
        shutterstock_categories=meta.shutterstock_categories,
        adobe_category=meta.adobe_category,
        editorial=meta.editorial,
        mature_content=meta.mature_content,
        illustration=meta.illustration,
        releases=meta.releases,
        notes=notes,
    )


def metadata_to_markdown(meta: Metadata) -> str:
    lines = [
        "# Metadata",
        "",
        f"- Filename: `{meta.filename}`",
        f"- Created date: {meta.created_date}",
        f"- Country: {meta.country}",
        f"- Title: {meta.title}",
        f"- Description: {meta.description}",
        f"- Keywords: {', '.join(meta.keywords)}",
        f"- Shutterstock Categories: {', '.join(meta.shutterstock_categories)}",
        f"- Adobe Category: {meta.adobe_category}",
        f"- Editorial: {meta.editorial}",
        f"- Mature content: {meta.mature_content}",
        f"- Illustration: {meta.illustration}",
        f"- Releases: {meta.releases}",
        f"- Notes: {meta.notes}",
        "",
    ]
    return "\n".join(lines)


def write_metadata_file(path: Path, content: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        return
    path.write_text(content, encoding="utf-8")


def parse_metadata_file(path: Path) -> Metadata:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        if ":" not in line:
            continue
        key, value = line[2:].split(":", 1)
        values[key.strip()] = value.strip()

    filename = values.get("Filename", "").strip("`")
    created_date = values.get("Created date", "")
    country = values.get("Country", "")
    title = values.get("Title", "")
    description = values.get("Description", "")
    keywords = normalize_keywords(values.get("Keywords", "").split(","), 49)
    shutterstock_field = values.get("Shutterstock Categories", values.get("Category", ""))
    shutterstock_categories = [item.strip() for item in shutterstock_field.split(",") if item.strip()]
    adobe_category = values.get("Adobe Category", values.get("Category", ""))
    editorial = values.get("Editorial", "no").lower()
    mature_content = values.get("Mature content", "no").lower()
    illustration = values.get("Illustration", values.get("illustration", "no")).lower()
    releases = values.get("Releases", "")
    notes = values.get("Notes", "")

    if not filename:
        raise ValueError(f"{path.name}: missing Filename")
    if not title:
        raise ValueError(f"{path.name}: missing Title")
    if not description:
        raise ValueError(f"{path.name}: missing Description")
    if not shutterstock_categories:
        raise ValueError(f"{path.name}: missing Shutterstock Categories")
    if not adobe_category:
        raise ValueError(f"{path.name}: missing Adobe Category")

    return Metadata(
        filename=filename,
        created_date=created_date,
        country=country,
        title=title,
        description=description,
        keywords=keywords,
        shutterstock_categories=shutterstock_categories,
        adobe_category=adobe_category,
        editorial=editorial,
        mature_content=mature_content,
        illustration=illustration,
        releases=releases,
        notes=notes,
    )


def _coerce_exif_rational(value: object) -> float:
    if isinstance(value, tuple) and len(value) == 2:
        numerator, denominator = value
        return float(numerator) / float(denominator)
    return float(value)


def _dms_to_decimal(dms: tuple[object, object, object], ref: str) -> float:
    degrees = _coerce_exif_rational(dms[0])
    minutes = _coerce_exif_rational(dms[1])
    seconds = _coerce_exif_rational(dms[2])
    decimal = degrees + minutes / 60.0 + seconds / 3600.0
    if ref in {"S", "W"}:
        decimal = -decimal
    return decimal


def extract_image_gps(path: Path) -> tuple[float, float] | None:
    if Image is None:
        return None
    try:
        info = Image.open(path)._getexif() or {}
    except Exception:
        return None

    gps_info: dict[str, object] | None = None
    for tag, value in info.items():
        if TAGS.get(tag, tag) != "GPSInfo":
            continue
        gps_info = {str(GPSTAGS.get(t, t)): v for t, v in value.items()}
        break

    if not gps_info:
        return None
    latitude = gps_info.get("GPSLatitude")
    latitude_ref = str(gps_info.get("GPSLatitudeRef", "N"))
    longitude = gps_info.get("GPSLongitude")
    longitude_ref = str(gps_info.get("GPSLongitudeRef", "E"))
    if not latitude or not longitude:
        return None

    return (
        _dms_to_decimal(latitude, latitude_ref),  # type: ignore[arg-type]
        _dms_to_decimal(longitude, longitude_ref),  # type: ignore[arg-type]
    )


def guess_country_from_gps(latitude: float, longitude: float) -> str | None:
    # Conservative coarse country boxes for this workflow's common travel batches.
    country_boxes = [
        ("Taiwan", (21.5, 26.5, 119.0, 122.5)),
        ("South Korea", (33.0, 39.5, 124.0, 132.0)),
        ("Japan", (24.0, 46.5, 122.0, 146.5)),
        ("Thailand", (5.0, 21.0, 97.0, 106.5)),
    ]
    for country, (lat_min, lat_max, lon_min, lon_max) in country_boxes:
        if lat_min <= latitude <= lat_max and lon_min <= longitude <= lon_max:
            return country
    return None


def validate_metadata_items(
    items: list[Metadata],
    image_dir: Path,
    source_filenames: set[str],
    shutterstock_categories: list[str],
    adobe_categories: list[str],
    adobe_category_map: dict[str, int],
) -> None:
    image_datetime_pattern = re.compile(
        r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}(?: [+-]\d{2}:\d{2})?)?$|^\d{2}/\d{2}/\d{4}(?: \d{2}:\d{2}(?: [+-]\d{2}:\d{2})?)?$"
    )
    seen_filenames: set[str] = set()
    for item in items:
        if item.filename in seen_filenames:
            raise ValueError(f"duplicate metadata filename: {item.filename}")
        seen_filenames.add(item.filename)

        if item.filename not in source_filenames:
            raise ValueError(f"metadata filename does not match a source image: {item.filename}")

        if not 1 <= len(item.shutterstock_categories) <= 2:
            raise ValueError(
                f"{item.filename}: Shutterstock requires one or two categories; "
                f"found {len(item.shutterstock_categories)}."
            )

        invalid_ss = [cat for cat in item.shutterstock_categories if cat not in shutterstock_categories]
        if invalid_ss:
            raise ValueError(f"{item.filename}: invalid Shutterstock categories: {invalid_ss}")

        if item.adobe_category not in adobe_categories:
            raise ValueError(f"{item.filename}: invalid Adobe category: {item.adobe_category}")
        if item.adobe_category not in adobe_category_map:
            raise ValueError(f"{item.filename}: Adobe category missing from numeric map: {item.adobe_category}")
        if item.editorial not in ALLOWED_BOOLEAN_FLAGS:
            raise ValueError(
                f"{item.filename}: Editorial must be 'yes' or 'no', got {item.editorial!r}."
            )
        if item.mature_content not in ALLOWED_BOOLEAN_FLAGS:
            raise ValueError(
                f"{item.filename}: Mature content must be 'yes' or 'no', got {item.mature_content!r}."
            )
        if item.illustration not in ALLOWED_BOOLEAN_FLAGS:
            raise ValueError(
                f"{item.filename}: Illustration must be 'yes' or 'no', got {item.illustration!r}."
            )
        if item.editorial == "yes" and not EDITORIAL_DESCRIPTION_PATTERN.fullmatch(item.description):
            raise ValueError(
                f"{item.filename}: editorial Description must use dateline format "
                "('CITY, STATE/COUNTRY - MONTH DAY, YEAR: factual sentence.') "
                "and may use bracketed placeholders for unknown facts."
            )
        if item.created_date and not image_datetime_pattern.fullmatch(item.created_date):
            raise ValueError(
                f"{item.filename}: invalid Created date format: {item.created_date!r}. "
                "Use YYYY-MM-DD or MM/DD/YYYY, optionally with time as HH:MM and timezone as +/-HH:MM."
            )
        gps = extract_image_gps(image_dir / item.filename)
        if gps and item.country:
            gps_country = guess_country_from_gps(gps[0], gps[1])
            if gps_country and gps_country != item.country:
                raise ValueError(
                    f"{item.filename}: Country {item.country!r} conflicts with EXIF GPS "
                    f"({gps[0]:.6f}, {gps[1]:.6f}) which resolves conservatively to {gps_country!r}."
                )


def write_shutterstock_csv(path: Path, items: list[Metadata], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists. Use --overwrite-csv to replace it.")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "Filename",
                "Description",
                "Keywords",
                "Categories",
                "Editorial",
                "Mature content",
                "illustration",
            ]
        )
        for item in items:
            writer.writerow(
                [
                    item.filename,
                    item.description,
                    ", ".join(item.keywords),
                    ",".join(item.shutterstock_categories),
                    item.editorial,
                    item.mature_content,
                    item.illustration,
                ]
            )


def write_adobe_csv(
    path: Path,
    items: list[Metadata],
    adobe_category_map: dict[str, int],
    overwrite: bool,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists. Use --overwrite-csv to replace it.")
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Filename", "Title", "Keywords", "Category", "Releases"])
        for item in items:
            category_id = adobe_category_map[item.adobe_category]
            writer.writerow(
                [
                    item.filename,
                    item.title,
                    ", ".join(item.keywords),
                    str(category_id),
                    item.releases,
                ]
            )


def write_istock_csv(path: Path, items: list[Metadata], header: list[str], overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists. Use --overwrite-csv to replace it.")
    # iStock rejects a BOM-prefixed header and then reports every "file name" as blank.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for item in items:
            writer.writerow(
                [
                    item.filename,
                    item.created_date,
                    item.description,
                    item.country,
                    item.title,
                    ", ".join(item.keywords),
                ]
            )


def build_csvs_from_metadata(
    image_dir: Path,
    metadata_dir: Path,
    output_dir: Path,
    shutterstock_categories: list[str],
    adobe_categories: list[str],
    adobe_category_map: dict[str, int],
    istock_header: list[str],
    extensions: set[str],
    max_keywords: int,
    overwrite_csv: bool,
) -> tuple[Path, Path, Path, int]:
    items: list[Metadata] = []
    source_filenames = {
        path.name
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in extensions
    }
    source_stems = {
        path.stem.lower(): path.name
        for path in image_dir.iterdir()
        if path.is_file() and path.suffix.lower() in extensions
    }
    for md_path in sorted(metadata_dir.glob("*.md"), key=lambda p: p.name.lower()):
        source_name = source_stems.get(md_path.stem.lower())
        if not source_name:
            continue
        item = enrich_metadata_with_taxon(parse_metadata_file(md_path), max_keywords=max_keywords)
        write_metadata_file(md_path, metadata_to_markdown(item), overwrite=True)
        if item.filename != source_name:
            raise ValueError(
                f"{md_path.name}: Filename field {item.filename!r} does not match source image {source_name!r}"
            )
        items.append(item)

    if not items:
        raise SystemExit(f"No metadata .md files found in {metadata_dir}")

    validate_metadata_items(
        items=items,
        image_dir=image_dir,
        source_filenames=source_filenames,
        shutterstock_categories=shutterstock_categories,
        adobe_categories=adobe_categories,
        adobe_category_map=adobe_category_map,
    )

    shutterstock_csv = output_dir / "shutterstock_upload_generated.csv"
    adobe_csv = output_dir / "adobe_stock_upload_generated.csv"
    istock_csv = output_dir / "istock_metadata_generated.csv"
    write_shutterstock_csv(shutterstock_csv, items, overwrite_csv)
    write_adobe_csv(adobe_csv, items, adobe_category_map, overwrite_csv)
    write_istock_csv(istock_csv, items, istock_header, overwrite_csv)
    return shutterstock_csv, adobe_csv, istock_csv, len(items)


def main() -> int:
    args = parse_args()
    root = Path.cwd()
    image_dir = (root / args.image_dir).resolve()
    metadata_dir = (root / (args.metadata_dir or args.image_dir)).resolve()
    output_dir = (root / (args.output_dir or args.image_dir)).resolve()
    metadata_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    shutterstock_categories = load_list_from_markdown(root / "shutterstock_categories.md", bullet_prefix="- ")
    adobe_categories = load_list_from_markdown(root / "adobe_categories.md")
    adobe_category_map = build_adobe_category_map(adobe_categories)
    istock_header = load_csv_header(root / "iStockMetadataTemplate.csv")

    shutterstock_csv, adobe_csv, istock_csv, count = build_csvs_from_metadata(
        image_dir=image_dir,
        metadata_dir=metadata_dir,
        output_dir=output_dir,
        shutterstock_categories=shutterstock_categories,
        adobe_categories=adobe_categories,
        adobe_category_map=adobe_category_map,
        istock_header=istock_header,
        extensions={ext.lower() if ext.startswith(".") else f".{ext.lower()}" for ext in args.extensions},
        max_keywords=args.max_keywords,
        overwrite_csv=args.overwrite_csv,
    )
    print(f"generated {count} metadata files into CSV exports")
    print(f"shutterstock csv: {shutterstock_csv}")
    print(f"adobe csv: {adobe_csv}")
    print(f"istock csv: {istock_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
