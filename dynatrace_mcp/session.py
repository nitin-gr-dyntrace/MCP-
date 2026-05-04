from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .config import CACHE_DIR

SESSIONS_DIR = CACHE_DIR / "sessions"
_MAX_CONTEXT_TURNS = 4


@dataclass
class SessionTurn:
    turn: int
    tool: str
    input_text: str
    response_summary: str
    timestamp: str = ""
    product_area: str = ""
    severity: str = ""


@dataclass
class Session:
    id: str
    created_at: str
    updated_at: str
    turns: list[SessionTurn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "turns": [asdict(t) for t in self.turns],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return cls(
            id=data["id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            turns=[SessionTurn(**t) for t in data.get("turns", [])],
        )


def _session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def create_session() -> Session:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    session = Session(id=str(uuid.uuid4())[:12], created_at=now, updated_at=now)
    _save_session(session)
    return session


def load_session(session_id: str) -> Session | None:
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def _save_session(session: Session) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    _session_path(session.id).write_text(
        json.dumps(session.to_dict(), indent=2), encoding="utf-8"
    )


def append_turn(
    session: Session,
    tool: str,
    input_text: str,
    full_response: str,
    product_area: str = "",
    severity: str = "",
) -> None:
    session.turns.append(
        SessionTurn(
            turn=len(session.turns) + 1,
            tool=tool,
            input_text=input_text[:400],
            response_summary=full_response[:600],
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            product_area=product_area,
            severity=severity,
        )
    )
    session.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    _save_session(session)


def build_session_context(session: Session) -> str:
    """Returns a compact, text-only summary of the last N turns for follow-up diagnosis."""
    if not session.turns:
        return ""
    recent = session.turns[-_MAX_CONTEXT_TURNS:]
    lines = [f"[Session {session.id} — {len(session.turns)} prior turn(s)]"]
    for turn in recent:
        lines.append(f"\nTurn {turn.turn} [{turn.tool}]")
        lines.append(f"  Input   : {turn.input_text}")
        if turn.product_area:
            lines.append(f"  Assessed: {turn.product_area} | severity {turn.severity}")
        lines.append(f"  Summary : {turn.response_summary}")
    return "\n".join(lines)


def session_footer(session: Session) -> str:
    return (
        "\n-------------------------------------\n"
        f"Session ID : {session.id}\n"
        f"Turn       : {len(session.turns)}\n"
        "To continue this conversation use the  follow_up  tool with this Session ID."
    )
