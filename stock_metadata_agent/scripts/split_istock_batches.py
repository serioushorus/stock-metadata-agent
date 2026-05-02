from __future__ import annotations

import argparse
import csv
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
BATCH_DIR_RE = re.compile(r"^batch_\d{3}$")


@dataclass(frozen=True)
class UploadKind:
    name: str
    source_csv_names: tuple[str, ...]
    batch_csv_name: str


UPLOAD_KINDS = (
    UploadKind(
        name="commercial",
        source_csv_names=(
            "istock_metadata_commercial_generated_all.csv",
            "istock_metadata_commercial_generated.csv",
        ),
        batch_csv_name="istock_metadata_commercial_generated.csv",
    ),
    UploadKind(
        name="editorial",
        source_csv_names=(
            "istock_metadata_editorial_generated_all.csv",
            "istock_metadata_editorial_generated.csv",
        ),
        batch_csv_name="istock_metadata_editorial_generated.csv",
    ),
)


def is_batch_dir(path: Path) -> bool:
    return path.is_dir() and bool(BATCH_DIR_RE.fullmatch(path.name))


def find_source_csv(upload_dir: Path, kind: UploadKind) -> Path | None:
    for name in kind.source_csv_names:
        path = upload_dir / name
        if path.exists():
            return path
    return None


def source_csvs_in_dir(upload_dir: Path) -> list[tuple[UploadKind, Path]]:
    sources: list[tuple[UploadKind, Path]] = []
    for kind in UPLOAD_KINDS:
        path = find_source_csv(upload_dir, kind)
        if path:
            sources.append((kind, path))
    return sources


def discover_upload_dirs(root: Path) -> list[Path]:
    if source_csvs_in_dir(root):
        return [root]

    directories: set[Path] = set()
    for kind in UPLOAD_KINDS:
        for csv_name in kind.source_csv_names:
            for csv_path in root.rglob(csv_name):
                if any(BATCH_DIR_RE.fullmatch(part) for part in csv_path.parts):
                    continue
                directories.add(csv_path.parent)
    return sorted(directories, key=lambda path: str(path).lower())


def discover_upload_sources(root: Path) -> list[tuple[Path, UploadKind, Path]]:
    sources: list[tuple[Path, UploadKind, Path]] = []
    for upload_dir in discover_upload_dirs(root):
        for kind, csv_path in source_csvs_in_dir(upload_dir):
            sources.append((upload_dir, kind, csv_path))
    return sorted(sources, key=lambda item: (str(item[0]).lower(), item[1].name))


def source_pairs(upload_dir: Path) -> dict[str, tuple[Path, Path]]:
    pairs: dict[str, tuple[Path, Path]] = {}
    for image_path in upload_dir.rglob("*"):
        if not image_path.is_file() or image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        md_path = image_path.with_suffix(".md")
        if not md_path.exists():
            raise SystemExit(f"Missing metadata for {image_path}")
        key = image_path.name
        if key in pairs:
            raise SystemExit(f"Duplicate image filename in upload tree: {key}")
        pairs[key] = (image_path, md_path)
    return pairs


def filename_column(header: list[str], csv_path: Path) -> str:
    for column in header:
        if column.strip().lower() in {"file name", "filename"}:
            return column
    raise SystemExit(f"Missing file name column: {csv_path}")


def read_source_csv(path: Path) -> tuple[list[str], list[dict[str, str]], str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"Missing CSV header: {path}")
        header = reader.fieldnames
        rows = list(reader)
    return header, rows, filename_column(header, path)


def move_pair(image_path: Path, md_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    image_target = target_dir / image_path.name
    md_target = target_dir / md_path.name
    if image_path.resolve() != image_target.resolve():
        if image_target.exists():
            raise SystemExit(f"Destination image already exists: {image_target}")
        shutil.move(str(image_path), str(image_target))
    if md_path.resolve() != md_target.resolve():
        if md_target.exists():
            raise SystemExit(f"Destination metadata already exists: {md_target}")
        shutil.move(str(md_path), str(md_target))


def write_batch_csv(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def remove_stale_csvs(upload_dir: Path, kind: UploadKind, batch_count: int) -> None:
    for stale_dir in sorted(upload_dir.glob("batch_*"), key=lambda path: path.name):
        if not is_batch_dir(stale_dir):
            continue
        match = re.fullmatch(r"batch_(\d{3})", stale_dir.name)
        if match and int(match.group(1)) <= batch_count:
            continue
        stale_csv = stale_dir / kind.batch_csv_name
        if stale_csv.exists():
            stale_csv.unlink()
        if not any(stale_dir.iterdir()):
            shutil.rmtree(stale_dir)


def split_upload_dir(upload_dir: Path, kind: UploadKind, source_csv: Path, max_images: int) -> int:
    header, rows, filename_key = read_source_csv(source_csv)
    pairs = source_pairs(upload_dir)
    missing = [row.get(filename_key, "") for row in rows if row.get(filename_key, "") not in pairs]
    if missing:
        raise SystemExit(f"{upload_dir}: {source_csv.name} references missing images: {missing[:10]}")

    batch_count = math.ceil(len(rows) / max_images) if rows else 0
    for index, start in enumerate(range(0, len(rows), max_images), start=1):
        batch_rows = rows[start : start + max_images]
        target_dir = upload_dir / f"batch_{index:03d}"
        for row in batch_rows:
            filename = row[filename_key]
            image_path, md_path = pairs[filename]
            move_pair(image_path, md_path, target_dir)
            pairs[filename] = (target_dir / image_path.name, target_dir / md_path.name)
        write_batch_csv(target_dir / kind.batch_csv_name, header, batch_rows)

    remove_stale_csvs(upload_dir, kind, batch_count)

    print(f"{upload_dir}")
    print(f"kind: {kind.name}")
    print(f"source csv: {source_csv.name}")
    print(f"{kind.name} rows: {len(rows)}")
    print(f"batches: {batch_count}")
    for index in range(1, batch_count + 1):
        batch_dir = upload_dir / f"batch_{index:03d}"
        image_count = sum(
            1 for path in batch_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        )
        print(f"{batch_dir.name}: {image_count}")
    return batch_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Split one or more iStock commercial or editorial upload folders into "
            "numbered batches that respect the per-upload image limit."
        )
    )
    parser.add_argument(
        "path",
        help="A commercial/editorial folder, or a parent folder to scan for iStock CSV files.",
    )
    parser.add_argument(
        "max_images_positional",
        nargs="?",
        type=int,
        help="Maximum images per batch. Kept for compatibility with the original CLI.",
    )
    parser.add_argument("--max-images", type=int, default=None, help="Maximum images per batch. Defaults to 100.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.path).resolve()
    max_images = args.max_images or args.max_images_positional or 100
    if max_images < 1:
        raise SystemExit("max-images must be at least 1")

    sources = discover_upload_sources(root)
    if not sources:
        raise SystemExit(f"No iStock commercial or editorial CSV files found under: {root}")

    for upload_dir, kind, source_csv in sources:
        split_upload_dir(upload_dir, kind, source_csv, max_images)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
