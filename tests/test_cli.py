import csv
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generate_stock_metadata import Metadata, build_csvs_from_metadata, metadata_to_markdown
from stock_metadata_agent.workflow import normalise_editorial_metadata


def make_local_tmp_dir() -> Path:
    path = ROOT / f"_test_tmp_{uuid.uuid4().hex}"
    path.mkdir()
    return path


def test_workflow_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "stock_metadata_agent" / "workflow.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--include-processed" in result.stdout
    assert "--no-reverse-geocode" in result.stdout
    assert "--review-mode" in result.stdout


def test_exporter_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "generate_stock_metadata.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--metadata-dir" in result.stdout


def test_istock_exports_are_split_by_editorial_status() -> None:
    tmp_path = make_local_tmp_dir()
    try:
        image_dir = tmp_path / "images"
        metadata_dir = tmp_path / "metadata"
        output_dir = tmp_path / "output"
        image_dir.mkdir()
        metadata_dir.mkdir()
        output_dir.mkdir()

        commercial = Metadata(
            filename="commercial.jpg",
            created_date="2026-04-21",
            country="Taiwan",
            title="Potted plant on balcony",
            description="Potted green plant growing on a balcony in soft daylight.",
            keywords=["plant", "balcony", "green", "leaves", "container", "home", "daylight", "growth"],
            shutterstock_categories=["Nature"],
            adobe_category="Plants and Flowers",
            editorial="no",
            mature_content="no",
            illustration="no",
            releases="",
            notes="",
        )
        editorial = Metadata(
            filename="editorial.jpg",
            created_date="2026-04-22",
            country="Taiwan",
            title="People walking near temple",
            description="Taipei, Taiwan - April 22, 2026: People walk near a temple entrance.",
            keywords=["temple", "people", "taipei", "taiwan", "travel", "entrance", "street", "editorial"],
            shutterstock_categories=["Buildings/Landmarks"],
            adobe_category="Travel",
            editorial="yes",
            mature_content="no",
            illustration="no",
            releases="",
            notes="",
        )
        for item in (commercial, editorial):
            (image_dir / item.filename).write_bytes(b"not a real jpeg")
            (metadata_dir / f"{Path(item.filename).stem}.md").write_text(metadata_to_markdown(item), encoding="utf-8")

        _, _, istock_csv, commercial_csv, editorial_csv, count = build_csvs_from_metadata(
            image_dir=image_dir,
            metadata_dir=metadata_dir,
            output_dir=output_dir,
            shutterstock_categories=["Nature", "Buildings/Landmarks"],
            adobe_categories=["Plants and Flowers", "Travel"],
            adobe_category_map={"Plants and Flowers": 14, "Travel": 21},
            istock_header=["Filename", "Date", "Description", "Country", "Title", "Keywords"],
            extensions={".jpg"},
            overwrite_csv=False,
        )

        assert count == 2
        assert [row[0] for row in csv.reader(istock_csv.open(encoding="utf-8"))][1:] == [
            "commercial.jpg",
            "editorial.jpg",
        ]
        assert [row[0] for row in csv.reader(commercial_csv.open(encoding="utf-8"))][1:] == ["commercial.jpg"]
        assert [row[0] for row in csv.reader(editorial_csv.open(encoding="utf-8"))][1:] == ["editorial.jpg"]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_editorial_placeholder_city_uses_reverse_geocode(monkeypatch) -> None:
    tmp_path = make_local_tmp_dir()

    def fake_reverse_geocode(latitude, longitude, cache_path):
        assert latitude == 13.7439
        assert longitude == 100.4889
        assert cache_path == tmp_path / "reverse_geocode_cache.json"
        return type(
            "ReverseResult",
            (),
            {"city": "Bangkok", "state": "", "country": "Thailand", "source": "test"},
        )()

    monkeypatch.setattr("stock_metadata_agent.workflow.reverse_geocode_location", fake_reverse_geocode)
    meta = Metadata(
        filename="temple.jpg",
        created_date="2026-04-21",
        country="Thailand",
        title="Temple detail",
        description="[City], Thailand - April 21, 2026: Visitors walk near a temple.",
        keywords=["temple", "travel", "editorial", "thailand", "architecture", "visitor", "city", "landmark"],
        shutterstock_categories=["Buildings/Landmarks"],
        adobe_category="Travel",
        editorial="yes",
        mature_content="no",
        illustration="no",
        releases="",
        notes="",
    )

    try:
        updated = normalise_editorial_metadata(
            meta,
            {"latitude": 13.7439, "longitude": 100.4889},
            True,
            tmp_path / "reverse_geocode_cache.json",
        )

        assert updated.description.startswith("Bangkok, Thailand - April 21, 2026:")
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_split_istock_batches_moves_assets_and_writes_batch_csvs() -> None:
    tmp_path = make_local_tmp_dir()
    try:
        commercial_dir = tmp_path / "commercial"
        commercial_dir.mkdir()
        header = ["file name", "created date", "description", "country", "title", "keywords"]
        rows = [
            ["image_001.jpg", "2026-04-21", "Description one.", "Taiwan", "Title one", "one, two"],
            ["image_002.jpg", "2026-04-22", "Description two.", "Taiwan", "Title two", "three, four"],
            ["image_003.jpg", "2026-04-23", "Description three.", "Taiwan", "Title three", "five, six"],
        ]
        with (commercial_dir / "istock_metadata_commercial_generated_all.csv").open(
            "w", encoding="utf-8", newline=""
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)

        for row in rows:
            filename = row[0]
            image_path = commercial_dir / filename
            image_path.write_bytes(b"not a real jpeg")
            image_path.with_suffix(".md").write_text(f"# Metadata\n\n- Filename: `{filename}`\n", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "stock_metadata_agent" / "scripts" / "split_istock_batches.py"),
                str(commercial_dir),
                "2",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        assert "batches: 2" in result.stdout
        assert sorted(path.name for path in (commercial_dir / "batch_001").glob("*.jpg")) == [
            "image_001.jpg",
            "image_002.jpg",
        ]
        assert sorted(path.name for path in (commercial_dir / "batch_002").glob("*.jpg")) == [
            "image_003.jpg",
        ]
        assert not (commercial_dir / "image_001.jpg").exists()
        with (commercial_dir / "batch_001" / "istock_metadata_commercial_generated.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            assert [row[0] for row in csv.reader(handle)][1:] == ["image_001.jpg", "image_002.jpg"]
        with (commercial_dir / "batch_002" / "istock_metadata_commercial_generated.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            assert [row[0] for row in csv.reader(handle)][1:] == ["image_003.jpg"]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_split_istock_batches_discovers_multiple_istock_folders() -> None:
    tmp_path = make_local_tmp_dir()
    try:
        root = tmp_path / "istock_uploads"
        batch_a = root / "260501" / "commercial"
        batch_b = root / "260502" / "commercial"
        batch_a.mkdir(parents=True)
        batch_b.mkdir(parents=True)
        header = ["file name", "created date", "description", "country", "title", "keywords"]

        for folder, prefix, count in ((batch_a, "a", 3), (batch_b, "b", 2)):
            csv_path = folder / "istock_metadata_commercial_generated.csv"
            rows = []
            for index in range(1, count + 1):
                filename = f"{prefix}_{index:03d}.jpg"
                rows.append([filename, "2026-05-01", "Description.", "Taiwan", "Title", "keyword"])
                (folder / filename).write_bytes(b"not a real jpeg")
                (folder / f"{prefix}_{index:03d}.md").write_text(
                    f"# Metadata\n\n- Filename: `{filename}`\n",
                    encoding="utf-8",
                )
            with csv_path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerows(rows)

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "stock_metadata_agent" / "scripts" / "split_istock_batches.py"),
                str(root),
                "--max-images",
                "2",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        assert str(batch_a) in result.stdout
        assert str(batch_b) in result.stdout
        assert sorted(path.name for path in (batch_a / "batch_001").glob("*.jpg")) == [
            "a_001.jpg",
            "a_002.jpg",
        ]
        assert sorted(path.name for path in (batch_a / "batch_002").glob("*.jpg")) == ["a_003.jpg"]
        assert sorted(path.name for path in (batch_b / "batch_001").glob("*.jpg")) == [
            "b_001.jpg",
            "b_002.jpg",
        ]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def test_split_istock_batches_also_handles_editorial_uploads() -> None:
    tmp_path = make_local_tmp_dir()
    try:
        root = tmp_path / "istock_uploads"
        commercial_dir = root / "commercial"
        editorial_dir = root / "editorial"
        commercial_dir.mkdir(parents=True)
        editorial_dir.mkdir(parents=True)
        header = ["file name", "created date", "description", "country", "title", "keywords"]

        for folder, csv_name, prefix, count in (
            (commercial_dir, "istock_metadata_commercial_generated.csv", "commercial", 2),
            (editorial_dir, "istock_metadata_editorial_generated.csv", "editorial", 3),
        ):
            rows = []
            for index in range(1, count + 1):
                filename = f"{prefix}_{index:03d}.jpg"
                rows.append([filename, "2026-05-01", "Description.", "Taiwan", "Title", "keyword"])
                (folder / filename).write_bytes(b"not a real jpeg")
                (folder / f"{prefix}_{index:03d}.md").write_text(
                    f"# Metadata\n\n- Filename: `{filename}`\n",
                    encoding="utf-8",
                )
            with (folder / csv_name).open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(header)
                writer.writerows(rows)

        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "stock_metadata_agent" / "scripts" / "split_istock_batches.py"),
                str(root),
                "--max-images",
                "2",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=True,
        )

        assert "kind: commercial" in result.stdout
        assert "kind: editorial" in result.stdout
        assert (commercial_dir / "batch_001" / "istock_metadata_commercial_generated.csv").exists()
        assert (editorial_dir / "batch_001" / "istock_metadata_editorial_generated.csv").exists()
        assert (editorial_dir / "batch_002" / "istock_metadata_editorial_generated.csv").exists()
        assert sorted(path.name for path in (editorial_dir / "batch_001").glob("*.jpg")) == [
            "editorial_001.jpg",
            "editorial_002.jpg",
        ]
        assert sorted(path.name for path in (editorial_dir / "batch_002").glob("*.jpg")) == [
            "editorial_003.jpg",
        ]
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)
