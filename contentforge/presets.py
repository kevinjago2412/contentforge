"""Simple preset loader for ContentForge workflows.

A preset stores a reusable configuration for a specific content style.
When the user mentions a preset name (e.g., "kabuki"), load it and apply
its defaults to the analysis/render pipeline.
"""

import json
from pathlib import Path
from typing import Any, Optional

_PRESETS_DIR = Path(__file__).parent / "presets"


def load_preset(name: str) -> Optional[dict[str, Any]]:
    """Load a preset JSON file by name."""
    path = _PRESETS_DIR / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_presets() -> list[str]:
    """Return all available preset names."""
    if not _PRESETS_DIR.exists():
        return []
    return [p.stem for p in _PRESETS_DIR.glob("*.json")]
