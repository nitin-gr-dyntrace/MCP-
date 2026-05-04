from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

_API_URL = "https://api.anthropic.com/v1/messages"
_API_VERSION = "2023-06-01"
_DEFAULT_MODEL = "claude-haiku-4-5-20251001"

_SYS_TRIAGE = """\
You are a senior Dynatrace L2 support engineer reviewing a customer case.
Given a diagnosis and the customer's problem statement, produce a specific, actionable analysis.

CRITICAL RULES:
- Every bullet must reference specific details from the problem (technology names, error patterns, timelines, specific features mentioned).
- Never write generic template text like "may be caused by a configuration gap" — that is useless.
- If the diagnosis confidence is low or no playbooks matched, focus on disambiguation questions.
- If the concern is a feature gap or missing feature, say so clearly and focus on workarounds and escalation path.

Output ONLY this format (no extra commentary):

Working hypotheses:
- [specific hypothesis tied to what the customer described]

Immediate questions:
- [question directly relevant to the specific scenario]

Evidence to collect:
- [specific artifact for this problem]

Suggested mitigations:
- [concrete step for this specific situation]"""

_SYS_CUSTOMER = """\
You are a Dynatrace L2 support engineer responding to a customer support ticket.
Write a professional, specific reply to the customer.

RULES:
- Start with "Hi [Team/Name],"
- Acknowledge the specific problem they described (reference actual details like feature names, gen version, product area)
- Ask 2-3 targeted diagnostic questions for THIS specific scenario
- If there's a known workaround or limitation, state it clearly and honestly
- Keep under 180 words
- Do NOT use hollow phrases like "thank you for reaching out" or "we understand your frustration"
- Do NOT write generic questions like "what changed recently" unless directly relevant"""

_SYS_ESCALATION = """\
You are a Dynatrace L2 support engineer writing a DE escalation.
Generate a concise, engineering-ready escalation. Be specific — reference actual details from the problem.

Output ONLY this format:

Component: [specific component name]
Defect summary: [one-line description of the unexpected behavior]
Expected behavior: [what should happen]
Actual behavior: [what is happening, with specific details from the case]
Reproduction path:
- [step 1]
- [step 2]
Evidence available: [what logs, screenshots, or data the customer has]
Customer impact: [scope and business impact — reference specifics like FiFA World Cup, production, etc.]
Config causes ruled out: [what has already been verified]"""

_SYS_INVESTIGATION = """\
You are a Dynatrace L2 support engineer building an investigation plan for a support case.
Generate a specific, ordered plan for THIS problem. Reference actual details.

Output ONLY this format:

Step 1: [specific action]
Step 2: [specific action]
Step 3: [specific action]
...

Decision points:
- If [specific condition from this case]: [action]
- ...

Most likely root causes (ordered):
- [most likely, based on actual details described]
- ..."""


def is_llm_available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", ""))


def _call(system: str, user_content: str, max_tokens: int = 900) -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return ""
    model = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_MODEL)
    payload = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_content}],
    }).encode("utf-8")
    req = Request(
        _API_URL,
        data=payload,
        headers={
            "x-api-key": key,
            "anthropic-version": _API_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"].strip()
    except (URLError, OSError, KeyError, IndexError, json.JSONDecodeError):
        return ""


def _diagnosis_context(diagnosis: Any, results: list[Any]) -> str:
    refs = "\n".join(f"- {r.title}: {r.url}" for r in results[:4]) if results else "No references found."
    playbooks = ", ".join(p.title for p in diagnosis.matched_playbooks) or "None matched"
    failure_modes = ", ".join(m.title for m in diagnosis.failure_modes) or "None inferred"
    return (
        f"Product area: {diagnosis.product_area} (confidence {diagnosis.product_confidence:.2f})\n"
        f"Subdomain: {diagnosis.subdomain} ({diagnosis.subdomain_confidence:.2f})\n"
        f"Concern types: {', '.join(diagnosis.concern_types)}\n"
        f"Matched playbooks: {playbooks}\n"
        f"Top failure modes: {failure_modes}\n"
        f"Severity: {diagnosis.severity}\n"
        f"\nTop references:\n{refs}"
    )


def generate_triage_analysis(problem: str, diagnosis: Any, results: list[Any]) -> str:
    ctx = _diagnosis_context(diagnosis, results)
    return _call(_SYS_TRIAGE, f"Diagnosis:\n{ctx}\n\nProblem statement:\n{problem}")


def generate_customer_response(problem: str, diagnosis: Any, results: list[Any]) -> str:
    ctx = _diagnosis_context(diagnosis, results)
    return _call(_SYS_CUSTOMER, f"Diagnosis:\n{ctx}\n\nCustomer problem:\n{problem}", max_tokens=600)


def generate_bug_escalation(problem: str, diagnosis: Any, results: list[Any]) -> str:
    ctx = _diagnosis_context(diagnosis, results)
    return _call(_SYS_ESCALATION, f"Diagnosis:\n{ctx}\n\nCustomer problem:\n{problem}")


def generate_investigation_plan(problem: str, diagnosis: Any, results: list[Any]) -> str:
    ctx = _diagnosis_context(diagnosis, results)
    return _call(_SYS_INVESTIGATION, f"Diagnosis:\n{ctx}\n\nCustomer problem:\n{problem}")
