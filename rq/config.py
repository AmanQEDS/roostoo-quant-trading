from __future__ import annotations
import os, yaml
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load_config(path: str | Path | None = None) -> dict:
    path = Path(path) if path else ROOT / "config" / "default.yaml"
    with open(path) as f:
        return yaml.safe_load(f)

def load_env(path: Path | None = None) -> None:
    """Minimal .env loader: tolerates BOM/quotes and overrides empty variables."""
    p = path or ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if v and not os.environ.get(k):
                os.environ[k] = v
