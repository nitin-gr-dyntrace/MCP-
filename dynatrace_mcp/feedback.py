from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import asdict, dataclass
from typing import Any

from .config import CACHE_DIR

FEEDBACK_PATH = CACHE_DIR / "learned_facts.json"
_SIMILARITY_THRESHOLD = 0.30


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1]


def _jaccard(tokens_a: list[str], tokens_b: list[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    a, b = set(tokens_a), set(tokens_b)
    return len(a & b) / len(a | b)


@dataclass
class FeedbackEntry:
    id: str
    timestamp: str
    problem_tokens: list[str]
    product_area: str
    what_was_wrong: str
    corrected_info: str
    use_count: int = 0
    original_problem: str = ""


@dataclass
class ConfirmationEntry:
    id: str
    timestamp: str
    problem_tokens: list[str]
    product_area: str
    confirmed_info: str
    use_count: int = 0
    original_problem: str = ""


class FeedbackStore:
    def __init__(self) -> None:
        self._corrections: list[FeedbackEntry] = []
        self._confirmations: list[ConfirmationEntry] = []
        self._loaded = False

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not FEEDBACK_PATH.exists():
            return
        try:
            raw = json.loads(FEEDBACK_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        correction_fields = set(FeedbackEntry.__dataclass_fields__)
        for item in raw.get("corrections", []):
            if isinstance(item, dict):
                try:
                    self._corrections.append(
                        FeedbackEntry(**{k: v for k, v in item.items() if k in correction_fields})
                    )
                except TypeError:
                    continue
        confirm_fields = set(ConfirmationEntry.__dataclass_fields__)
        for item in raw.get("confirmations", []):
            if isinstance(item, dict):
                try:
                    self._confirmations.append(
                        ConfirmationEntry(**{k: v for k, v in item.items() if k in confirm_fields})
                    )
                except TypeError:
                    continue

    def _save(self) -> None:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        FEEDBACK_PATH.write_text(
            json.dumps(
                {
                    "corrections": [asdict(c) for c in self._corrections],
                    "confirmations": [asdict(c) for c in self._confirmations],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

    def add_correction(
        self,
        problem: str,
        what_was_wrong: str,
        corrected_info: str,
        product_area: str = "",
    ) -> FeedbackEntry:
        self._ensure_loaded()
        entry = FeedbackEntry(
            id=str(uuid.uuid4())[:8],
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            problem_tokens=_tokenize(problem),
            product_area=product_area,
            what_was_wrong=what_was_wrong,
            corrected_info=corrected_info,
            original_problem=problem,
        )
        self._corrections.append(entry)
        self._save()
        return entry

    def add_confirmation(
        self,
        problem: str,
        confirmed_info: str,
        product_area: str = "",
    ) -> ConfirmationEntry:
        self._ensure_loaded()
        entry = ConfirmationEntry(
            id=str(uuid.uuid4())[:8],
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
            problem_tokens=_tokenize(problem),
            product_area=product_area,
            confirmed_info=confirmed_info,
            original_problem=problem,
        )
        self._confirmations.append(entry)
        self._save()
        return entry

    def find_corrections(
        self, problem: str, top_n: int = 3
    ) -> list[tuple[float, FeedbackEntry]]:
        self._ensure_loaded()
        query_tokens = _tokenize(problem)
        scored = [(_jaccard(query_tokens, e.problem_tokens), e) for e in self._corrections]
        scored = [(s, e) for s, e in scored if s >= _SIMILARITY_THRESHOLD]
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = scored[:top_n]
        for _, e in hits:
            e.use_count += 1
        if hits:
            self._save()
        return hits

    def find_confirmations(
        self, problem: str, top_n: int = 3
    ) -> list[tuple[float, ConfirmationEntry]]:
        self._ensure_loaded()
        query_tokens = _tokenize(problem)
        scored = [(_jaccard(query_tokens, e.problem_tokens), e) for e in self._confirmations]
        scored = [(s, e) for s, e in scored if s >= _SIMILARITY_THRESHOLD]
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_n]

    def stats(self) -> dict[str, Any]:
        self._ensure_loaded()
        return {
            "total_corrections": len(self._corrections),
            "total_confirmations": len(self._confirmations),
            "top_corrections_by_use": sorted(
                [
                    {
                        "id": e.id,
                        "product_area": e.product_area,
                        "use_count": e.use_count,
                        "snippet": e.corrected_info[:100],
                    }
                    for e in self._corrections
                ],
                key=lambda x: x["use_count"],
                reverse=True,
            )[:5],
        }


_store: FeedbackStore | None = None


def get_feedback_store() -> FeedbackStore:
    global _store
    if _store is None:
        _store = FeedbackStore()
    return _store


def inject_learned_context(problem_statement: str) -> str:
    """Returns a formatted block of engineer-verified corrections and confirmations
    relevant to the given problem. Empty string when nothing matches."""
    store = get_feedback_store()
    corrections = store.find_corrections(problem_statement)
    confirmations = store.find_confirmations(problem_statement)
    if not corrections and not confirmations:
        return ""

    lines = ["=== LEARNED FROM PAST CASES ==="]
    for score, entry in corrections:
        area = entry.product_area or "general"
        lines.append(f"\n[!] Verified Correction  (match {score:.0%} | area: {area})")
        if entry.what_was_wrong:
            lines.append(f"   What was wrong : {entry.what_was_wrong}")
        lines.append(f"   Correct info   : {entry.corrected_info}")
    for score, entry in confirmations:
        area = entry.product_area or "general"
        lines.append(f"\n[+] Confirmed Correct  (match {score:.0%} | area: {area})")
        lines.append(f"   {entry.confirmed_info}")
    lines.append("\n================================")
    return "\n".join(lines)
