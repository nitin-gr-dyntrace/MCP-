from __future__ import annotations

import re

from .config import PRODUCT_AREA_PROFILES
from .models import Diagnosis, Playbook
from .playbooks import load_playbooks


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1]


def classify_concern(problem_statement: str) -> list[str]:
    lower = problem_statement.lower()
    labels: list[str] = []

    if re.search(
        r"not working|broken|failing|error|issue|down|unavailable|stopped|not sending|missing data|no data|dropped|failed",
        lower,
    ):
        labels.append("product_not_working")
    if re.search(r"bug|defect|regression|unexpected|incorrect behavior", lower):
        labels.append("possible_bug_for_engineering")
    if re.search(r"impact|affected|outage|degradation|production|environment|tenant|cluster|blocked", lower):
        labels.append("customer_environment_impact")

    return labels or ["general_support_investigation"]


def estimate_severity(problem_statement: str, concern_types: list[str]) -> str:
    lower = problem_statement.lower()
    if "customer_environment_impact" in concern_types and re.search(
        r"production|outage|critical|all hosts|tenant down|cluster down|blocked", lower
    ):
        return "high"
    if "product_not_working" in concern_types or "customer_environment_impact" in concern_types:
        return "medium"
    return "normal"


def matched_product_profiles(problem_statement: str) -> list[dict]:
    lower = problem_statement.lower()
    matches: list[tuple[int, dict]] = []
    for profile in PRODUCT_AREA_PROFILES:
        score = sum(1 for keyword in profile["keywords"] if keyword in lower)
        if score > 0:
            matches.append((score, profile))
    matches.sort(key=lambda item: item[0], reverse=True)
    return [profile for _, profile in matches]


def product_area_candidates(problem_statement: str) -> list[tuple[float, str, dict | None]]:
    lower = problem_statement.lower()
    candidates: list[tuple[float, str, dict | None]] = []

    for profile in PRODUCT_AREA_PROFILES:
        score = 0.0
        for keyword in profile["keywords"]:
            if keyword in lower:
                score += 8.0 if " " in keyword else 5.0
        if score > 0:
            candidates.append((score, profile["name"], profile))

    fallback_map = [
        ("activegate", "ActiveGate"),
        ("oneagent", "OneAgent"),
        ("synthetic", "DEM"),
        ("rum", "DEM"),
        ("log", "Log Monitoring"),
        ("kubernetes", "Kubernetes Monitoring"),
        ("extension", "Extensions"),
        ("token", "API / Authentication"),
        ("api", "API / Authentication"),
        ("metric", "Metrics Ingestion"),
        ("davis", "Davis / Alerting"),
    ]
    if not candidates:
        for needle, label in fallback_map:
            if needle in lower:
                candidates.append((4.0, label, None))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates


def playbook_confidence_for_area(problem_statement: str, product_area: str) -> dict[str, float]:
    lower = problem_statement.lower()
    confidence: dict[str, float] = {}

    for playbook in load_playbooks():
        if playbook.product_area != product_area:
            continue

        score = 0.0
        for trigger in playbook.triggers:
            if trigger.lower() in lower:
                score += 7.0 if " " in trigger else 5.0
        for keyword in playbook.keywords:
            if keyword.lower() in lower:
                score += 2.0

        if score > 0:
            confidence[playbook.id] = min(0.98, 0.2 + (score / 24.0))

    return confidence


def matched_playbooks_for_area(problem_statement: str, product_area: str) -> list[Playbook]:
    lower = problem_statement.lower()
    matches: list[tuple[float, Playbook]] = []

    for playbook in load_playbooks():
        if playbook.product_area != product_area:
            continue

        score = 0.0
        for trigger in playbook.triggers:
            if trigger.lower() in lower:
                score += 7.0 if " " in trigger else 5.0
        for keyword in playbook.keywords:
            if keyword.lower() in lower:
                score += 2.0
        if score > 0:
            matches.append((score, playbook))

    matches.sort(key=lambda item: item[0], reverse=True)
    return [playbook for _, playbook in matches[:2]]


def diagnose_problem(problem_statement: str) -> Diagnosis:
    candidates = product_area_candidates(problem_statement)
    if candidates:
        top_score, product_area, profile = candidates[0]
    else:
        top_score, product_area, profile = (0.0, "General Dynatrace platform", None)

    concern_types = classify_concern(problem_statement)
    severity = estimate_severity(problem_statement, concern_types)
    playbook_confidence = playbook_confidence_for_area(problem_statement, product_area)
    playbooks = [
        playbook
        for playbook in matched_playbooks_for_area(problem_statement, product_area)
        if playbook_confidence.get(playbook.id, 0.0) >= 0.45
    ]

    failure_domains: list[str] = []
    if playbooks:
        for playbook in playbooks:
            failure_domains.extend(playbook.failure_domains)
    elif profile:
        failure_domains.append(f"Potential issue within {product_area} requiring product-specific validation.")

    query_tokens = set(tokenize(problem_statement))
    clue_weights = {
        "certificate": ["certificate", "trust", "tls", "san", "hostname"],
        "tls": ["certificate", "trust", "tls", "san", "hostname"],
        "proxy": ["proxy", "outbound", "network path"],
        "capacity": ["capacity", "queue", "sizing", "backlog"],
        "queue": ["capacity", "queue", "sizing", "backlog"],
        "routing": ["routing", "network path", "proxy"],
    }

    def domain_score(domain: str) -> int:
        lower_domain = domain.lower()
        score = sum(1 for token in query_tokens if token in lower_domain)
        for token in query_tokens:
            for clue in clue_weights.get(token, []):
                if clue in lower_domain:
                    score += 3
        return score

    failure_domains = sorted(
        list(dict.fromkeys(failure_domains)),
        key=domain_score,
        reverse=True,
    )

    keywords: list[str] = []
    if profile:
        keywords.extend(profile["keywords"])
    for playbook in playbooks:
        keywords.extend(playbook.triggers)
        keywords.extend(playbook.keywords)

    product_confidence = min(0.98, 0.3 + (top_score / 30.0))

    return Diagnosis(
        product_area=product_area,
        product_confidence=product_confidence,
        concern_types=concern_types,
        severity=severity,
        matched_playbooks=playbooks,
        playbook_confidence=playbook_confidence,
        failure_domains=failure_domains[:6],
        component_keywords=list(dict.fromkeys(keywords))[:20],
    )


def identify_component(problem_statement: str) -> str:
    return diagnose_problem(problem_statement).product_area
