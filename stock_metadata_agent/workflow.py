from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Literal, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field, field_validator

from stock_metadata_agent.geocoding import ReverseGeocodeResult, reverse_geocode_location
from generate_stock_metadata import (
    Metadata,
    build_adobe_category_map,
    load_csv_header,
    load_list_from_markdown,
    metadata_to_markdown,
    parse_metadata_file,
    validate_metadata_items,
    write_metadata_file,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
HELPER_NAME_PATTERNS = (
    "contact_sheet",
    "review_sheet",
    "shutterstock_upload_generated",
    "adobe_stock_upload_generated",
    "istock_metadata_generated",
)
EXIF_SCRIPT = Path(__file__).resolve().parent / "scripts" / "extract_exif_context.py"


class MetadataDraft(BaseModel):
    filename: str = Field(description="Exact original image filename, including extension.")
    created_date: str = Field(default="", description="YYYY-MM-DD or YYYY-MM-DD HH:MM when supported by EXIF.")
    country: str = Field(default="", description="Country only when EXIF GPS and visible context support it.")
    title: str = Field(description="Short factual stock title.")
    description: str = Field(description="One factual sentence grounded in the visible image.")
    keywords: list[str] = Field(min_length=8, max_length=49)
    shutterstock_categories: list[str] = Field(min_length=1, max_length=2)
    adobe_category: str
    editorial: Literal["yes", "no"] = "no"
    mature_content: Literal["yes", "no"] = "no"
    illustration: Literal["yes", "no"] = "no"
    releases: str = ""
    notes: str = ""

    @field_validator("keywords")
    @classmethod
    def clean_keywords(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for keyword in value:
            item = re.sub(r"\s+", " ", keyword.strip().lower()).strip(" ,;")
            if item and item not in seen:
                seen.add(item)
                cleaned.append(item)
        return cleaned[:49]


class WorkflowState(TypedDict, total=False):
    root: str
    image_dir: str
    metadata_dir: str
    output_dir: str
    model: str
    max_images: int | None
    include_processed: bool
    overwrite_metadata: bool
    overwrite_csv: bool
    update_ledger: bool
    reverse_geocode_editorial: bool
    reverse_geocode_cache: str
    authority_context: dict[str, object]
    processed: list[str]
    pending_images: list[str]
    current_image: str
    exif_context: dict[str, dict[str, object]]
    written_markdown: list[str]
    skipped_existing: list[str]
    exported_csvs: list[str]


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def read_processed_ledger(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError("processed_photos.txt must exist and be read before batch work.")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def iter_source_images(image_dir: Path) -> list[Path]:
    images: list[Path] = []
    for path in sorted(image_dir.iterdir(), key=lambda p: p.name.lower()):
        lower_name = path.name.lower()
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        if lower_name.startswith("_") or any(pattern in lower_name for pattern in HELPER_NAME_PATTERNS):
            continue
        images.append(path)
    return images


def prepare_workspace(state: WorkflowState) -> WorkflowState:
    root = Path(state["root"]).resolve()
    image_dir = Path(state["image_dir"]).resolve()
    metadata_dir = Path(state["metadata_dir"]).resolve()
    output_dir = Path(state["output_dir"]).resolve()
    metadata_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    load_dotenv(root / ".env")

    processed = read_processed_ledger(root / "processed_photos.txt")
    processed_names = {Path(item).name.lower() for item in processed}

    shutterstock_categories = load_list_from_markdown(root / "shutterstock_categories.md", bullet_prefix="- ")
    adobe_categories = load_list_from_markdown(root / "adobe_categories.md")
    authority_context = {
        "shutterstock_categories": shutterstock_categories,
        "adobe_categories": adobe_categories,
        "adobe_category_map": build_adobe_category_map(adobe_categories),
        "istock_header": load_csv_header(root / "iStockMetadataTemplate.csv"),
        "shutterstock_header": load_csv_header(root / "shutterstock_content_upload.csv"),
        "adobe_header": load_csv_header(root / "Sample_Adobe_Stock_CSV_upload.csv"),
    }

    source_images = iter_source_images(image_dir)
    if state.get("include_processed", False):
        pending = [str(path) for path in source_images]
    else:
        pending = [str(path) for path in source_images if path.name.lower() not in processed_names]
    if state.get("max_images"):
        pending = pending[: int(state["max_images"])]

    return {
        **state,
        "authority_context": authority_context,
        "processed": processed,
        "pending_images": pending,
        "written_markdown": [],
        "skipped_existing": [],
        "exported_csvs": [],
    }


def extract_exif_context(state: WorkflowState) -> WorkflowState:
    image_dir = Path(state["image_dir"]).resolve()
    output_dir = Path(state["output_dir"]).resolve()
    exif_json = output_dir / ".stock_metadata_exif_context.json"
    if not EXIF_SCRIPT.exists():
        raise FileNotFoundError(f"Missing EXIF helper: {EXIF_SCRIPT}")

    subprocess.run(
        [sys.executable, str(EXIF_SCRIPT), str(image_dir), "--output", str(exif_json)],
        check=True,
        cwd=state["root"],
    )
    rows = json.loads(exif_json.read_text(encoding="utf-8"))
    return {**state, "exif_context": {row["filename"]: row for row in rows}}


def select_next_image(state: WorkflowState) -> WorkflowState:
    pending = list(state.get("pending_images", []))
    if not pending:
        return {**state, "current_image": ""}
    current = pending.pop(0)
    return {**state, "current_image": current, "pending_images": pending}


def should_review_or_export(state: WorkflowState) -> str:
    return "export" if not state.get("current_image") else "review"


def image_to_data_url(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def normalise_created_date(value: str) -> str:
    value = value.strip()
    match = re.match(r"^(\d{4}):(\d{2}):(\d{2})(?:\s+(\d{2}):(\d{2}))?", value)
    if match:
        date = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        if match.group(4) and match.group(5):
            return f"{date} {match.group(4)}:{match.group(5)}"
        return date
    return value


def build_prompt(
    image_path: Path,
    exif: dict[str, object],
    authority_context: dict[str, object],
) -> str:
    suggested_date = normalise_created_date(str(exif.get("created_at", "")))
    return f"""
Create stock photo metadata for exactly this image file: {image_path.name}

Follow these hard rules:
- Base visual decisions only on this original image.
- Use EXIF before visual classification, but do not treat GPS as landmark proof.
- If GPS exists, country may use the EXIF country guess when the image does not contradict it.
- Include any justified location or landmark in both Description and Keywords.
- If location, species, brand, artwork, private property, or editorial risk is uncertain, stay generic.
- If Editorial is yes, Description must use Shutterstock dateline format and may use bracketed placeholders.
- Use one or two Shutterstock categories, exactly from the allowed list.
- Use one Adobe category, exactly from the allowed list.
- Keep Mature content and Illustration as no unless the visible image clearly requires otherwise.
- Leave Releases blank unless the user has provided known release names.
- Add "Taxon candidate: ..." in notes only for a plausible plant or animal ID that should be validated later.

EXIF context:
{json.dumps(exif, ensure_ascii=False, indent=2)}
Suggested created_date from EXIF: {suggested_date}

Allowed Shutterstock categories:
{", ".join(authority_context["shutterstock_categories"])}

Allowed Adobe categories:
{", ".join(authority_context["adobe_categories"])}
""".strip()


def draft_to_metadata(
    draft: MetadataDraft,
    image_path: Path,
    exif: dict[str, object],
    authority_context: dict[str, object],
    reverse_geocode_editorial: bool,
    reverse_geocode_cache: Path,
) -> Metadata:
    created_date = normalise_created_date(draft.created_date or str(exif.get("created_at", "")))
    meta = Metadata(
        filename=image_path.name,
        created_date=created_date,
        country=draft.country.strip(),
        title=draft.title.strip(),
        description=draft.description.strip(),
        keywords=draft.keywords,
        shutterstock_categories=[item.strip() for item in draft.shutterstock_categories],
        adobe_category=draft.adobe_category.strip(),
        editorial=draft.editorial,
        mature_content=draft.mature_content,
        illustration=draft.illustration,
        releases=draft.releases.strip(),
        notes=draft.notes.strip(),
    )
    meta = normalise_provider_categories(meta, authority_context)
    return normalise_editorial_metadata(meta, exif, reverse_geocode_editorial, reverse_geocode_cache)


def infer_shutterstock_categories(meta: Metadata) -> list[str]:
    combined = " ".join([meta.title, meta.description, " ".join(meta.keywords)]).lower()
    inferred: list[str] = []
    if any(term in combined for term in ["temple", "shrine", "buddhist", "religion", "torii", "buddha", "jizo"]):
        inferred.append("Religion")
    if any(term in combined for term in ["sign", "banner", "lettering", "writing", "inscription", "symbol"]):
        inferred.append("Signs/Symbols")
    if any(term in combined for term in ["visitor", "people", "person", "crowd"]):
        inferred.append("People")
    if any(term in combined for term in ["building", "architecture", "gate", "landmark", "facade", "hall", "statue"]):
        inferred.append("Buildings/Landmarks")
    if any(term in combined for term in ["garden", "park", "outdoor", "terrace", "sky", "landscape"]):
        inferred.append("Parks/Outdoor")
    return inferred or ["Miscellaneous"]


def normalise_provider_categories(meta: Metadata, authority_context: dict[str, object]) -> Metadata:
    shutterstock_allowed = set(authority_context["shutterstock_categories"])  # type: ignore[arg-type]
    adobe_allowed = set(authority_context["adobe_categories"])  # type: ignore[arg-type]

    shutterstock_categories = [
        category for category in meta.shutterstock_categories if category in shutterstock_allowed
    ]
    for category in infer_shutterstock_categories(meta):
        if category in shutterstock_allowed and category not in shutterstock_categories:
            shutterstock_categories.append(category)
    shutterstock_categories = shutterstock_categories[:2]

    adobe_category = meta.adobe_category
    if adobe_category not in adobe_allowed:
        if any(category == "Religion" for category in shutterstock_categories):
            adobe_category = "Culture and Religion"
        elif any(category == "People" for category in shutterstock_categories):
            adobe_category = "People"
        elif any(category == "Animals/Wildlife" for category in shutterstock_categories):
            adobe_category = "Animals"
        elif any(category == "Buildings/Landmarks" for category in shutterstock_categories):
            adobe_category = "Buildings and Architecture"
        elif any(category in {"Nature", "Parks/Outdoor"} for category in shutterstock_categories):
            adobe_category = "Landscapes"
        else:
            adobe_category = "Travel" if "Travel" in adobe_allowed else next(iter(adobe_allowed))

    return Metadata(
        filename=meta.filename,
        created_date=meta.created_date,
        country=meta.country,
        title=meta.title,
        description=meta.description,
        keywords=meta.keywords,
        shutterstock_categories=shutterstock_categories,
        adobe_category=adobe_category,
        editorial=meta.editorial,
        mature_content=meta.mature_content,
        illustration=meta.illustration,
        releases=meta.releases,
        notes=meta.notes,
    )


def created_date_to_dateline_date(created_date: str) -> str:
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", created_date.strip())
    if not match:
        return "[Month Day, Year]"
    month_names = [
        "",
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    month = int(match.group(2))
    if month < 1 or month > 12:
        return "[Month Day, Year]"
    return f"{month_names[month]} {int(match.group(3))}, {match.group(1)}"


def is_placeholder(value: str) -> bool:
    return bool(re.fullmatch(r"\[[^\]]+\]", value.strip()))


def coerce_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def get_reverse_geocode_for_editorial(
    exif: dict[str, object],
    enabled: bool,
    cache_path: Path,
) -> ReverseGeocodeResult | None:
    if not enabled:
        return None
    latitude = coerce_float(exif.get("latitude"))
    longitude = coerce_float(exif.get("longitude"))
    if latitude is None or longitude is None:
        return None

    result = reverse_geocode_location(latitude, longitude, cache_path)
    if result:
        exif.setdefault("city_guess", result.city)
        exif.setdefault("state_guess", result.state)
        exif.setdefault("reverse_geocode_country", result.country)
        exif.setdefault("reverse_geocode_source", result.source)
    return result


def infer_city_for_dateline(
    meta: Metadata,
    exif: dict[str, object],
    reverse_geocode: ReverseGeocodeResult | None,
) -> str:
    combined = " ".join([meta.title, meta.description, " ".join(meta.keywords)]).lower()
    if "bangkok" in combined:
        return "Bangkok"
    if exif.get("country_guess") == "Thailand" and "wat arun" in combined:
        return "Bangkok"
    city_guess = str(exif.get("city_guess", "")).strip()
    if city_guess:
        return city_guess
    if reverse_geocode and reverse_geocode.city:
        return reverse_geocode.city
    return "[City]"


def parse_editorial_dateline(description: str) -> tuple[str, str, str, str] | None:
    match = re.match(
        r"^(?P<city>\[[^\]]+\]|[^,:]+), (?P<country>\[[^\]]+\]|[^:]+?) - "
        r"(?P<date>\[[^\]]+\]|[A-Z][a-z]+ \d{1,2}, \d{4}): (?P<sentence>.+\S)$",
        description.strip(),
    )
    if not match:
        return None
    return (
        match.group("city").strip(),
        match.group("country").strip(),
        match.group("date").strip(),
        match.group("sentence").strip(),
    )


def strip_existing_dateline(description: str) -> str:
    value = description.strip()
    if ":" in value:
        return value.split(":", 1)[1].strip()
    value = re.sub(r"^\[[^\]]+\]\s*", "", value).strip()
    value = re.sub(r"^[A-Z][A-Za-z\s/,]+\s+-\s+", "", value).strip()
    return value or description.strip()


def normalise_editorial_metadata(
    meta: Metadata,
    exif: dict[str, object],
    reverse_geocode_editorial: bool,
    reverse_geocode_cache: Path,
) -> Metadata:
    if meta.editorial != "yes":
        return meta

    existing = parse_editorial_dateline(meta.description)
    existing_city = existing[0] if existing else ""
    existing_country = existing[1] if existing else ""
    reverse_geocode = get_reverse_geocode_for_editorial(exif, reverse_geocode_editorial, reverse_geocode_cache)

    city = existing_city if existing_city and not is_placeholder(existing_city) else infer_city_for_dateline(meta, exif, reverse_geocode)
    country = (
        existing_country
        if existing_country and not is_placeholder(existing_country)
        else meta.country
        or str(exif.get("country_guess", "")).strip()
        or (reverse_geocode.country if reverse_geocode else "")
        or "[Country]"
    )
    date_text = existing[2] if existing and not is_placeholder(existing[2]) else created_date_to_dateline_date(meta.created_date)
    factual_sentence = existing[3] if existing else strip_existing_dateline(meta.description)
    description = f"{city}, {country} - {date_text}: {factual_sentence}"
    return Metadata(**{**meta.__dict__, "description": description})


def review_image_with_openai(state: WorkflowState) -> WorkflowState:
    image_path = Path(state["current_image"])
    metadata_dir = Path(state["metadata_dir"]).resolve()
    md_path = metadata_dir / f"{image_path.stem}.md"
    if md_path.exists() and not state.get("overwrite_metadata", False):
        skipped = list(state.get("skipped_existing", [])) + [str(md_path)]
        return {**state, "skipped_existing": skipped}

    exif = state.get("exif_context", {}).get(image_path.name, {"filename": image_path.name})
    llm = ChatOpenAI(model=state["model"], temperature=0)
    structured_llm = llm.with_structured_output(MetadataDraft)
    draft = structured_llm.invoke(
        [
            SystemMessage(
                content=(
                    "You are a conservative stock-photo metadata editor. "
                    "Return only metadata supported by the image, EXIF context, and provider authorities."
                )
            ),
            HumanMessage(
                content=[
                    {"type": "text", "text": build_prompt(image_path, exif, state["authority_context"])},
                    {"type": "image_url", "image_url": {"url": image_to_data_url(image_path)}},
                ]
            ),
        ]
    )
    if not isinstance(draft, MetadataDraft):
        draft = MetadataDraft.model_validate(draft)
    if draft.filename != image_path.name:
        raise ValueError(f"OpenAI returned filename {draft.filename!r}, expected {image_path.name!r}.")

    meta = draft_to_metadata(
        draft,
        image_path,
        exif,
        state["authority_context"],
        state.get("reverse_geocode_editorial", True),
        Path(state["reverse_geocode_cache"]),
    )
    write_metadata_file(md_path, metadata_to_markdown(meta), overwrite=True)
    parse_metadata_file(md_path)
    written = list(state.get("written_markdown", [])) + [str(md_path)]
    return {**state, "written_markdown": written}


def validate_and_export(state: WorkflowState) -> WorkflowState:
    image_dir = Path(state["image_dir"]).resolve()
    metadata_dir = Path(state["metadata_dir"]).resolve()
    output_dir = Path(state["output_dir"]).resolve()
    authority = state["authority_context"]
    source_filenames = {path.name for path in iter_source_images(image_dir)}
    items: list[Metadata] = []
    for path in sorted(metadata_dir.glob("*.md"), key=lambda p: p.name.lower()):
        item = parse_metadata_file(path)
        if (image_dir / item.filename).exists():
            items.append(item)
    if not items:
        raise RuntimeError(f"No metadata markdown files found for source images in {metadata_dir}.")
    validate_metadata_items(
        items=items,
        image_dir=image_dir,
        source_filenames=source_filenames,
        shutterstock_categories=authority["shutterstock_categories"],  # type: ignore[arg-type]
        adobe_categories=authority["adobe_categories"],  # type: ignore[arg-type]
        adobe_category_map=authority["adobe_category_map"],  # type: ignore[arg-type]
    )
    command = [
        sys.executable,
        "generate_stock_metadata.py",
        str(image_dir),
        "--metadata-dir",
        str(metadata_dir),
        "--output-dir",
        str(output_dir),
    ]
    if state.get("overwrite_csv"):
        command.append("--overwrite-csv")
    subprocess.run(command, check=True, cwd=state["root"])
    return {
        **state,
        "exported_csvs": [
            str(output_dir / "shutterstock_upload_generated.csv"),
            str(output_dir / "adobe_stock_upload_generated.csv"),
            str(output_dir / "istock_metadata_generated.csv"),
        ],
    }


def update_processed_ledger(state: WorkflowState) -> WorkflowState:
    if not state.get("update_ledger", True):
        return state
    root = Path(state["root"]).resolve()
    ledger_path = root / "processed_photos.txt"
    processed = read_processed_ledger(ledger_path)
    processed_set = set(processed)
    completed_names = [
        Path(path).name
        for path in list(state.get("written_markdown", [])) + list(state.get("skipped_existing", []))
    ]
    # Markdown paths become stems, so map them back to source image names from the validated current batch.
    image_dir = Path(state["image_dir"]).resolve()
    completed_images = []
    for md_path in list(state.get("written_markdown", [])) + list(state.get("skipped_existing", [])):
        md_stem = Path(md_path).stem.lower()
        for image in iter_source_images(image_dir):
            if image.stem.lower() == md_stem:
                completed_images.append(image.name)
                break
    additions = [name for name in completed_images if name not in processed_set]
    if additions:
        with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
            for name in additions:
                handle.write(f"{name}\n")
    return state


def build_graph():
    graph = StateGraph(WorkflowState)
    graph.add_node("prepare", prepare_workspace)
    graph.add_node("extract_exif", extract_exif_context)
    graph.add_node("select_next", select_next_image)
    graph.add_node("review_image", review_image_with_openai)
    graph.add_node("validate_export", validate_and_export)
    graph.add_node("update_ledger", update_processed_ledger)
    graph.set_entry_point("prepare")
    graph.add_edge("prepare", "extract_exif")
    graph.add_edge("extract_exif", "select_next")
    graph.add_conditional_edges("select_next", should_review_or_export, {"review": "review_image", "export": "validate_export"})
    graph.add_edge("review_image", "select_next")
    graph.add_edge("validate_export", "update_ledger")
    graph.add_edge("update_ledger", END)
    return graph.compile()


def parse_args(default_model: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the OpenAI + LangGraph stock metadata workflow.")
    parser.add_argument("image_dir", help="Batch folder containing original images.")
    parser.add_argument("--metadata-dir", help="Markdown output folder. Defaults to image_dir.")
    parser.add_argument("--output-dir", help="CSV output folder. Defaults to image_dir.")
    parser.add_argument("--model", default=default_model)
    parser.add_argument("--max-images", type=int, help="Limit images for a test run.")
    parser.add_argument("--include-processed", action="store_true", help="Include images already listed in processed_photos.txt.")
    parser.add_argument("--overwrite-metadata", action="store_true")
    parser.add_argument("--overwrite-csv", action="store_true")
    parser.add_argument("--no-update-ledger", action="store_true")
    parser.add_argument(
        "--no-reverse-geocode",
        action="store_true",
        help="Disable automatic GPS reverse geocoding for editorial datelines.",
    )
    return parser.parse_args()


def main() -> int:
    root = Path.cwd().resolve()
    load_dotenv(root / ".env")
    default_model = os.environ.get("OPENAI_VISION_MODEL") or os.environ.get("OPENAI_MODEL") or "gpt-5.4"
    args = parse_args(default_model)
    image_dir = (root / args.image_dir).resolve()
    metadata_dir = (root / (args.metadata_dir or args.image_dir)).resolve()
    output_dir = (root / (args.output_dir or args.image_dir)).resolve()
    reverse_geocode_cache = root / ".cache" / "reverse_geocode_cache.json"
    final_state = build_graph().invoke(
        {
            "root": str(root),
            "image_dir": str(image_dir),
            "metadata_dir": str(metadata_dir),
            "output_dir": str(output_dir),
            "model": args.model,
            "max_images": args.max_images,
            "include_processed": args.include_processed,
            "overwrite_metadata": args.overwrite_metadata,
            "overwrite_csv": args.overwrite_csv,
            "update_ledger": not args.no_update_ledger,
            "reverse_geocode_editorial": not args.no_reverse_geocode,
            "reverse_geocode_cache": str(reverse_geocode_cache),
        }
    )
    print(f"metadata written: {len(final_state.get('written_markdown', []))}")
    print(f"existing metadata reused: {len(final_state.get('skipped_existing', []))}")
    for csv_path in final_state.get("exported_csvs", []):
        print(f"exported: {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
