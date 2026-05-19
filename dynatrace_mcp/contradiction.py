"""
Contradiction detection across support sessions.

When a new case comes in, this module scans past sessions and flags
situations where the new case context conflicts with a prior resolution.

Examples of contradictions:
  - Same product area + same symptom, but different version was "fixed"
  - A rollback was recommended before, but now an upgrade is suggested
  - A config value that previously caused the issue is present again
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import CACHE_DIR
from .session import Session, load_session

SESSIONS_DIR = CACHE_DIR / "sessions"

# ---------------------------------------------------------------------------
# Signal extractors
# ---------------------------------------------------------------------------

_VERSION_RE = re.compile(r"v?(\d+\.\d+[\.\d]*)", re.IGNORECASE)
_ROLLBACK_SIGNALS  = {"rollback", "downgrade", "revert", "roll back", "previous version"}
_UPGRADE_SIGNALS   = {"upgrade", "update", "newer version", "latest version"}
_RESTART_SIGNALS   = {"restart", "reboot", "recycle", "redeploy"}
_CONFIG_SIGNALS    = {"config", "configuration", "setting", "parameter", "env var", "environment variable"}


def _extract_versions(text: str) -> list[str]:
    return _VERSION_RE.findall(text.lower())


def _has_signal(text: str, signals: set[str]) -> bool:
    lower = text.lower()
    return any(s in lower for s in signals)


def _product_area_overlap(area_a: str, area_b: str) -> bool:
    if not area_a or not area_b:
        return False
    a, b = area_a.lower(), area_b.lower()
    return a == b or a in b or b in a


# ---------------------------------------------------------------------------
# Contradiction dataclass
# ---------------------------------------------------------------------------

@dataclass
class Contradiction:
    session_id: str
    turn: int
    prior_input: str
    prior_resolution: str
    conflict_reason: str
    severity: str          # "high" | "medium" | "low"


# ---------------------------------------------------------------------------
# Core detection logic
# ---------------------------------------------------------------------------

def _check_version_conflict(
    new_versions: list[str],
    prior_versions: list[str],
    prior_summary: str,
    session_id: str,
    turn: int,
    prior_input: str,
) -> Contradiction | None:
    """Flag when the new case is on a version that was previously declared 'fixed'."""
    if not new_versions or not prior_versions:
        return None

    fixed_pattern = re.compile(
        r"(fix(?:ed)?|resolv(?:ed)?|work(?:s|ed)?|ok(?:ay)?)\s+(?:in|on|with|after)?\s*v?(\d+[\.\d]+)",
        re.IGNORECASE,
    )
    for match in fixed_pattern.finditer(prior_summary):
        fixed_ver = match.group(2)
        for new_ver in new_versions:
            if new_ver == fixed_ver:
                return Contradiction(
                    session_id=session_id,
                    turn=turn,
                    prior_input=prior_input[:200],
                    prior_resolution=prior_summary[:300],
                    conflict_reason=(
                        f"Version {new_ver} was marked as resolved in a prior case "
                        f"(session {session_id}, turn {turn}), but the same issue is reappearing. "
                        "Check whether a regression was introduced or the fix was not fully applied."
                    ),
                    severity="high",
                )
    return None


def _check_action_conflict(
    new_text: str,
    prior_summary: str,
    session_id: str,
    turn: int,
    prior_input: str,
) -> Contradiction | None:
    """Flag when current recommendation conflicts with prior recommendation."""
    new_rollback  = _has_signal(new_text, _ROLLBACK_SIGNALS)
    new_upgrade   = _has_signal(new_text, _UPGRADE_SIGNALS)
    prior_rollback = _has_signal(prior_summary, _ROLLBACK_SIGNALS)
    prior_upgrade  = _has_signal(prior_summary, _UPGRADE_SIGNALS)

    if new_upgrade and prior_rollback:
        return Contradiction(
            session_id=session_id,
            turn=turn,
            prior_input=prior_input[:200],
            prior_resolution=prior_summary[:300],
            conflict_reason=(
                f"Prior session {session_id} recommended a rollback/downgrade, "
                "but the current case suggests upgrading. Verify which direction is safe before advising the customer."
            ),
            severity="high",
        )

    if new_rollback and prior_upgrade:
        return Contradiction(
            session_id=session_id,
            turn=turn,
            prior_input=prior_input[:200],
            prior_resolution=prior_summary[:300],
            conflict_reason=(
                f"Prior session {session_id} recommended an upgrade, "
                "but the current case suggests rolling back. Validate the environment difference before proceeding."
            ),
            severity="medium",
        )
    return None


def _check_config_conflict(
    new_text: str,
    prior_summary: str,
    session_id: str,
    turn: int,
    prior_input: str,
) -> Contradiction | None:
    """Flag when config guidance appears contradictory across cases."""
    if not (_has_signal(new_text, _CONFIG_SIGNALS) and _has_signal(prior_summary, _CONFIG_SIGNALS)):
        return None
    # Look for explicit "do not" / "disable" in prior vs positive action in new
    prior_disable = re.search(r"(disable|remove|delete|do not enable)\s+\w+", prior_summary, re.I)
    new_enable    = re.search(r"(enable|add|set|configure)\s+\w+", new_text, re.I)
    if prior_disable and new_enable:
        prior_action = prior_disable.group(0)
        new_action   = new_enable.group(0)
        if _token_overlap(prior_action, new_action) >= 1:
            return Contradiction(
                session_id=session_id,
                turn=turn,
                prior_input=prior_input[:200],
                prior_resolution=prior_summary[:300],
                conflict_reason=(
                    f"Prior session {session_id} advised '{prior_action}', "
                    f"but current guidance suggests '{new_action}'. "
                    "Confirm the correct configuration state before advising the customer."
                ),
                severity="medium",
            )
    return None


def _token_overlap(a: str, b: str) -> int:
    tokens_a = set(re.findall(r"[a-z0-9]+", a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9]+", b.lower()))
    return len(tokens_a & tokens_b)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_contradictions(
    problem_statement: str,
    current_resolution_draft: str,
    product_area: str,
    max_sessions: int = 30,
) -> list[Contradiction]:
    """
    Scan recent sessions and return a list of contradictions found.

    Args:
        problem_statement:       The new case description.
        current_resolution_draft: The draft resolution/triage text being generated.
        product_area:            Detected product area for the new case.
        max_sessions:            How many past sessions to scan.

    Returns:
        List of Contradiction objects, sorted by severity (high first).
    """
    if not SESSIONS_DIR.exists():
        return []

    session_files = sorted(
        SESSIONS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:max_sessions]

    new_versions = _extract_versions(problem_statement)
    contradictions: list[Contradiction] = []

    for sf in session_files:
        try:
            session = load_session(sf.stem)
        except Exception:
            continue
        if session is None:
            continue

        for turn in session.turns:
            # Only compare turns from the same product area
            if not _product_area_overlap(product_area, turn.product_area):
                continue

            prior_summary = turn.response_summary
            prior_input   = turn.input_text
            prior_versions = _extract_versions(prior_input + " " + prior_summary)

            # Check 1 — version conflict
            c = _check_version_conflict(
                new_versions, prior_versions, prior_summary,
                session.id, turn.turn, prior_input,
            )
            if c:
                contradictions.append(c)
                continue

            # Check 2 — action conflict (upgrade vs rollback)
            c = _check_action_conflict(
                current_resolution_draft, prior_summary,
                session.id, turn.turn, prior_input,
            )
            if c:
                contradictions.append(c)
                continue

            # Check 3 — config conflict
            c = _check_config_conflict(
                current_resolution_draft, prior_summary,
                session.id, turn.turn, prior_input,
            )
            if c:
                contradictions.append(c)

    # Sort: high → medium → low
    order = {"high": 0, "medium": 1, "low": 2}
    contradictions.sort(key=lambda x: order.get(x.severity, 3))
    return contradictions


def format_contradictions(contradictions: list[Contradiction]) -> str:
    """Return a formatted warning block for inclusion in triage output."""
    if not contradictions:
        return ""

    lines = [
        "\n⚠️  CONTRADICTION WARNINGS — Review before responding to customer",
        "-" * 60,
    ]
    for i, c in enumerate(contradictions, 1):
        lines.append(f"\n[{i}] Severity: {c.severity.upper()}")
        lines.append(f"    Prior case  : Session {c.session_id}, Turn {c.turn}")
        lines.append(f"    Prior input : {c.prior_input}")
        lines.append(f"    Conflict    : {c.conflict_reason}")
    lines.append("-" * 60)
    return "\n".join(lines)
