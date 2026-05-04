from __future__ import annotations

import json
from typing import Any

from .config import PLAYBOOKS_PATH
from .models import Playbook

_playbooks_cache: list[Playbook] | None = None


def load_playbooks() -> list[Playbook]:
    global _playbooks_cache
    if _playbooks_cache is not None:
        return _playbooks_cache

    if not PLAYBOOKS_PATH.exists():
        _playbooks_cache = []
        return _playbooks_cache

    try:
        raw = json.loads(PLAYBOOKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _playbooks_cache = []
        return _playbooks_cache

    playbooks: list[Playbook] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        playbooks.append(
            Playbook(
                id=_as_text(item.get("id")),
                product_area=_as_text(item.get("product_area")),
                title=_as_text(item.get("title")),
                triggers=_as_list(item.get("triggers")),
                keywords=_as_list(item.get("keywords")),
                failure_domains=_as_list(item.get("failure_domains")),
                questions=_as_list(item.get("questions")),
                evidence=_as_list(item.get("evidence")),
                mitigations=_as_list(item.get("mitigations")),
                escalate_when=_as_list(item.get("escalate_when")),
            )
        )
    _playbooks_cache = playbooks
    return _playbooks_cache


def reload_playbooks() -> list[Playbook]:
    """Force re-read from disk, e.g. after editing playbooks.json at runtime."""
    global _playbooks_cache
    _playbooks_cache = None
    return load_playbooks()


def _as_text(value: Any) -> str:
    return str(value) if value is not None else ""


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]
