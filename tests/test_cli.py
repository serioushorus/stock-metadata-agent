import subprocess
import sys
from pathlib import Path


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


def test_exporter_help() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "generate_stock_metadata.py"), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "--metadata-dir" in result.stdout
