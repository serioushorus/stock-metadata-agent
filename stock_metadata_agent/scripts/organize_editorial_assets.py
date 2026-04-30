#!/usr/bin/env python3
"""Move editorial-marked stock photo assets into per-batch editorial folders."""

from __future__ import annotations

import argparse
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


DATE_DIR_PATTERN = re.compile(r"^\d{6}(?:_\d+)?$")
EDITORIAL_PATTERN = re.compile(r"^\s*-\s*Editorial\s*:\s*(yes|true)\s*$", re.IGNORECASE | re.MULTILINE)
FILENAME_PATTERN = re.compile(r"^\s*-\s*Filename\s*:\s*`?([^`\r\n]+?)`?\s*$", re.IGNORECASE | re.MULTILINE)
SKIP_MD_PATTERN = re.compile(
    r"^(?:adobe_categories|shutterstock_categories|shutterstock_metadata_.*)\.md$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EditorialPair:
    folder: Path
    markdown: Path
    image: Path
    markdown_dest: Path
    image_dest: Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Find per-image markdown files marked 'Editorial: yes' or 'Editorial: true' "
            "inside date-named folders, then move each markdown file and its referenced "
            "image into that folder's editorial subfolder."
        )
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=".",
        help="Workspace root containing date folders. Defaults to the current directory.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform moves. Without this flag, only prints the planned changes.",
    )
    parser.add_argument(
        "--editorial-dir-name",
        default="editorial",
        help="Destination subfolder name to create inside each date folder.",
    )
    return parser.parse_args()


def iter_date_dirs(root: Path) -> list[Path]:
    return sorted(
        (path for path in root.iterdir() if path.is_dir() and DATE_DIR_PATTERN.match(path.name)),
        key=lambda path: path.name,
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def extract_filename(markdown_path: Path, text: str) -> str:
    match = FILENAME_PATTERN.search(text)
    if not match:
        raise ValueError(f"Editorial markdown is missing a Filename field: {markdown_path}")
    filename = match.group(1).strip()
    if not filename:
        raise ValueError(f"Editorial markdown has an empty Filename field: {markdown_path}")
    return filename


def collect_pairs(root: Path, editorial_dir_name: str) -> list[EditorialPair]:
    pairs: list[EditorialPair] = []
    for folder in iter_date_dirs(root):
        editorial_dir = folder / editorial_dir_name
        for markdown_path in sorted(folder.glob("*.md"), key=lambda path: path.name.lower()):
            if SKIP_MD_PATTERN.match(markdown_path.name):
                continue
            text = read_text(markdown_path)
            if not EDITORIAL_PATTERN.search(text):
                continue

            image_name = extract_filename(markdown_path, text)
            image_path = folder / image_name
            pairs.append(
                EditorialPair(
                    folder=folder,
                    markdown=markdown_path,
                    image=image_path,
                    markdown_dest=editorial_dir / markdown_path.name,
                    image_dest=editorial_dir / image_name,
                )
            )
    return pairs


def validate_pairs(pairs: list[EditorialPair]) -> list[str]:
    errors: list[str] = []
    seen_destinations: set[Path] = set()
    for pair in pairs:
        if not pair.image.is_file():
            errors.append(f"Missing image for {pair.markdown}: {pair.image.name}")
        for destination in (pair.markdown_dest, pair.image_dest):
            resolved = destination.resolve()
            if resolved in seen_destinations:
                errors.append(f"Duplicate destination in planned moves: {destination}")
            seen_destinations.add(resolved)
            if destination.exists():
                errors.append(f"Destination already exists: {destination}")
    return errors


def summarize(pairs: list[EditorialPair]) -> None:
    by_folder: dict[str, int] = {}
    for pair in pairs:
        by_folder[pair.folder.name] = by_folder.get(pair.folder.name, 0) + 1

    if not by_folder:
        print("No root-level editorial markdown files found in date folders.")
        return

    for folder_name in sorted(by_folder):
        print(f"{folder_name}: {by_folder[folder_name]} pair(s)")
    print(f"Total planned pairs: {len(pairs)}")


def move_pairs(pairs: list[EditorialPair]) -> None:
    for pair in pairs:
        pair.markdown_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(pair.image), str(pair.image_dest))
        shutil.move(str(pair.markdown), str(pair.markdown_dest))


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Root directory does not exist: {root}")

    pairs = collect_pairs(root, args.editorial_dir_name)
    summarize(pairs)

    errors = validate_pairs(pairs)
    if errors:
        print("\nErrors:")
        for error in errors:
            print(f"- {error}")
        return 1

    if not args.execute:
        print("\nDry run only. Re-run with --execute to move files.")
        return 0

    move_pairs(pairs)
    print("\nMoved editorial image/markdown pairs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
