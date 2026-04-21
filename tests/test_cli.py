import subprocess
import sys
from pathlib import Path

from generate_stock_metadata import Metadata
from stock_metadata_agent.workflow import normalise_editorial_metadata


ROOT = Path(__file__).resolve().parents[1]


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


def test_exporter_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "generate_stock_metadata.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--metadata-dir" in result.stdout


def test_editorial_placeholder_city_uses_reverse_geocode(monkeypatch, tmp_path) -> None:
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

    updated = normalise_editorial_metadata(
        meta,
        {"latitude": 13.7439, "longitude": 100.4889},
        True,
        tmp_path / "reverse_geocode_cache.json",
    )

    assert updated.description.startswith("Bangkok, Thailand - April 21, 2026:")
