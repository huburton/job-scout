"""Search profile: a Markdown note (YAML frontmatter + free text), re-read on every run.

File: SCOUT_PROFILE (default ./profile.md); start from profile.example.md. Changing criteria means editing the note,
not the code.
"""
import re
from pathlib import Path

import yaml

from . import config

EXAMPLE = Path(__file__).resolve().parent.parent / "profile.example.md"
DEFAULT = {
    "commute": {"lu_max_min": 100, "other_max_min": 50, "passion_other_max_min": 65},
    "target_families": {"dev_software": 3, "sysadmin_network_devops": 3, "ai_automation_data": 3, "support_it": 3,
                        "digital_fabrication": 3, "electronics_iot": 3},
    "blocked_languages": ["de", "lb", "nl"],
    "skills": [],
    "text": "",
}


def load() -> dict:
    prof = dict(DEFAULT)
    for path in (Path(config.PROFILE_FILE), EXAMPLE):  # no profile.md yet: fall back to the bundled example
        try:
            raw = path.read_text()
            break
        except OSError:
            continue
    else:
        return prof
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    meta, text = ({}, raw) if not m else (m.group(1), m.group(2))
    if m:
        try:
            meta = yaml.safe_load(meta) or {}
        except yaml.YAMLError:
            meta = {}
    prof.update({k: v for k, v in meta.items() if v is not None})
    prof["commute"] = {**DEFAULT["commute"], **(meta.get("commute") or {})}
    prof["target_families"] = meta.get("target_families") or DEFAULT["target_families"]
    prof["text"] = text.strip()
    return prof
