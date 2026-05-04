from __future__ import annotations

import re

from .config import PRODUCT_AREA_PROFILES
from .failure_modes import infer_failure_modes
from .models import Diagnosis, Playbook
from .playbooks import load_playbooks


SUBDOMAIN_RULES: dict[str, list[dict[str, object]]] = {
    "DEM": [
        {"name": "RUM Capture", "keywords": ["user session", "rum", "beacon", "snippet", "javascript", "waterfall", "action", "frontend", "browser", "csp", "spa", "route"]},
        {"name": "Synthetic Monitoring", "keywords": ["synthetic", "browser monitor", "clickpath", "monitor", "location", "step", "availability"]},
    ],
    "Davis / Alerting": [
        {"name": "Alerting Profiles", "keywords": ["alerting profile", "notification", "on-call", "routing", "delivery", "email", "slack", "webhook", "profile", "notify"]},
        {"name": "Problem Detection", "keywords": ["problem", "root cause", "anomaly", "davis", "false positive", "noise", "correlation"]},
    ],
    "Log Monitoring": [
        {"name": "Log Ingestion Pipeline", "keywords": ["log", "pipeline", "ingest", "processing", "parser", "grail", "dql"]},
        {"name": "Dashboard and Query", "keywords": ["dashboard", "query", "field", "selector", "visualization"]},
    ],
    "Metrics Ingestion": [
        {"name": "Metric Ingestion", "keywords": ["metric", "timeseries", "payload", "dimension", "schema", "cardinality"]},
        {"name": "Dashboard and Selector", "keywords": ["dashboard", "chart", "selector", "visualization", "query"]},
    ],
    "Extensions": [
        {"name": "Extension Runtime", "keywords": ["extension", "activation", "runtime", "controller", "plugin", "unhealthy"]},
        {"name": "Extension Compatibility", "keywords": ["upgrade", "version", "compatibility", "supported"]},
    ],
    "Grail / DQL": [
        {"name": "DQL Query", "keywords": ["dql", "fetch", "summarize", "fieldsadd", "query", "syntax", "notebook", "data explorer"]},
        {"name": "Grail Retention", "keywords": ["retention", "bucket", "delete", "expire", "policy", "storage"]},
    ],
}


ENTITY_SIGNAL_RULES: list[tuple[str, list[str]]] = [
    ("frontend_deployment", ["frontend deployment", "frontend rollout", "deployment", "new version", "build"]),
    ("rum_snippet", ["snippet", "javascript", "rum", "beacon", "auto-injection", "manual injection"]),
    ("browser_csp", ["csp", "content-security-policy", "blocked script", "console", "har", "network tab"]),
    ("alerting_profile", ["alerting profile", "notification", "notify", "webhook", "email", "slack", "on-call"]),
    ("profile_filters", ["management zone", "severity", "tag", "filter", "rule"]),
    ("log_pipeline", ["pipeline", "parser", "grail", "dql", "retention", "processing"]),
    ("metric_schema", ["schema", "dimension", "selector", "cardinality", "custom metric", "timeseries"]),
    ("extension_runtime", ["extension", "activation", "runtime", "controller", "unhealthy", "plugin"]),
]


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1]


def _score_playbook(problem_lower: str, playbook: "Playbook") -> float:
    score = sum(7.0 if " " in t else 5.0 for t in playbook.triggers if t.lower() in problem_lower)
    score += sum(2.0 for k in playbook.keywords if k.lower() in problem_lower)
    return score


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
    has_impact = "customer_environment_impact" in concern_types
    has_bug = "possible_bug_for_engineering" in concern_types
    if has_impact and has_bug:
        return "high"
    if has_impact and re.search(
        r"production|outage|critical|all hosts|tenant down|cluster down|blocked", lower
    ):
        return "high"
    if "product_not_working" in concern_types or has_impact:
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


def detect_subdomain(problem_statement: str, product_area: str) -> tuple[str, float]:
    lower = problem_statement.lower()
    rules = SUBDOMAIN_RULES.get(product_area, [])
    if not rules:
        return product_area, 0.35

    scored: list[tuple[float, str]] = []
    for rule in rules:
        keywords = rule["keywords"]
        score = 0.0
        for keyword in keywords:
            if keyword in lower:
                score += 7.0 if " " in keyword else 4.0
        if score > 0:
            scored.append((score, str(rule["name"])))

    if not scored:
        return product_area, 0.35

    scored.sort(key=lambda item: item[0], reverse=True)
    top_score, top_name = scored[0]
    return top_name, min(0.98, 0.3 + (top_score / 24.0))


def extract_entity_signals(problem_statement: str) -> list[str]:
    lower = problem_statement.lower()
    signals: list[str] = []
    for label, keywords in ENTITY_SIGNAL_RULES:
        if any(keyword in lower for keyword in keywords):
            signals.append(label)
    return signals


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


def _scored_playbooks_for_area(problem_statement: str, product_area: str) -> list[tuple[float, Playbook]]:
    lower = problem_statement.lower()
    results: list[tuple[float, Playbook]] = []
    for playbook in load_playbooks():
        if playbook.product_area != product_area:
            continue
        score = _score_playbook(lower, playbook)
        if score > 0:
            results.append((score, playbook))
    results.sort(key=lambda item: item[0], reverse=True)
    return results


def playbook_confidence_for_area(problem_statement: str, product_area: str) -> dict[str, float]:
    return {
        playbook.id: min(0.98, 0.2 + (score / 24.0))
        for score, playbook in _scored_playbooks_for_area(problem_statement, product_area)
    }


def matched_playbooks_for_area(problem_statement: str, product_area: str) -> list[Playbook]:
    return [playbook for _, playbook in _scored_playbooks_for_area(problem_statement, product_area)[:2]]


def diagnose_problem(problem_statement: str) -> Diagnosis:
    candidates = product_area_candidates(problem_statement)
    if candidates:
        top_score, product_area, profile = candidates[0]
    else:
        top_score, product_area, profile = (0.0, "General Dynatrace platform", None)

    concern_types = classify_concern(problem_statement)
    severity = estimate_severity(problem_statement, concern_types)
    subdomain, subdomain_confidence = detect_subdomain(problem_statement, product_area)
    entity_signals = extract_entity_signals(problem_statement)
    playbook_confidence = playbook_confidence_for_area(problem_statement, product_area)
    playbooks = [
        playbook
        for playbook in matched_playbooks_for_area(problem_statement, product_area)
        if playbook_confidence.get(playbook.id, 0.0) >= 0.45
    ]
    failure_modes, failure_mode_confidence = infer_failure_modes(problem_statement, product_area, playbooks)
    if product_area == "DEM" and subdomain == "RUM Capture":
        failure_modes = [mode for mode in failure_modes if mode.id != "connectivity_tls"][:3]
    if product_area == "Davis / Alerting" and subdomain == "Alerting Profiles":
        failure_modes = [mode for mode in failure_modes if mode.id != "visualization_query_mismatch"][:3]
    if product_area in {"Log Monitoring", "Metrics Ingestion"} and "metric_schema" in entity_signals:
        prioritized = sorted(
            failure_modes,
            key=lambda mode: 1 if mode.id in {"ingestion_pipeline", "visualization_query_mismatch", "configuration_drift"} else 0,
            reverse=True,
        )
        failure_modes = prioritized[:3]
    failure_mode_confidence = {
        mode.id: failure_mode_confidence.get(mode.id, 0.0)
        for mode in failure_modes
    }

    failure_domains: list[str] = []
    for failure_mode in failure_modes:
        failure_domains.append(failure_mode.summary)
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
    keywords.append(subdomain)
    for playbook in playbooks:
        keywords.extend(playbook.triggers)
        keywords.extend(playbook.keywords)
    for failure_mode in failure_modes:
        keywords.extend(failure_mode.signals)
    keywords.extend(entity_signals)

    product_confidence = min(0.98, 0.3 + (top_score / 30.0))

    return Diagnosis(
        product_area=product_area,
        product_confidence=product_confidence,
        subdomain=subdomain,
        subdomain_confidence=subdomain_confidence,
        concern_types=concern_types,
        severity=severity,
        matched_playbooks=playbooks,
        playbook_confidence=playbook_confidence,
        failure_modes=failure_modes,
        failure_mode_confidence=failure_mode_confidence,
        failure_domains=failure_domains[:6],
        component_keywords=list(dict.fromkeys(keywords))[:20],
        entity_signals=list(dict.fromkeys(entity_signals)),
    )
