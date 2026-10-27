"""Publish a failure notice without changing the last successful predictions."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from app_data import atomic_json, failed_health, workflow_url

previous_path = ROOT / "public/refresh_health.json"
previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
health = failed_health(previous, run_url=workflow_url())
for folder in ("public", "site"):
    atomic_json(ROOT / folder / "refresh_health.json", health)
print("Recorded the failed refresh; previous predictions retained.")
