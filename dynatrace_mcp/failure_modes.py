from __future__ import annotations

import re

from .models import FailureMode, Playbook


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1]


FAILURE_MODE_LIBRARY: dict[str, FailureMode] = {
    "compatibility_mismatch": FailureMode(
        id="compatibility_mismatch",
        title="Compatibility or version mismatch",
        summary="A version, framework, or supported-matrix mismatch introduced after a change or upgrade.",
        evidence=[
            "Product, extension, or component version details before and after the change",
            "Supported-version or compatibility matrix relevant to the impacted workflow",
            "Upgrade timeline and whether rollback or mixed-version state exists",
        ],
        questions=[
            "What exactly changed in version, upgrade path, or runtime before the issue started?",
            "Is the impacted component running on a supported version combination?",
            "Did the problem start immediately after the version or framework change?",
        ],
        mitigations=[
            "Validate the supported-version combination and runtime prerequisites",
            "If safe, compare against a known-good version or rollback path",
        ],
        escalate_when=[
            "The issue reproduces on a validated supported version combination",
            "A specific upgrade path consistently triggers the same failure",
        ],
        signals=["upgrade", "version", "compatibility", "supported", "framework", "schema", "runtime"],
    ),
    "configuration_drift": FailureMode(
        id="configuration_drift",
        title="Configuration drift or prerequisite gap",
        summary="A setting, prerequisite, or deployment detail changed and no longer matches the expected configuration.",
        evidence=[
            "Configuration before and after the issue started",
            "Deployment parameters, feature flags, or environment-specific settings",
            "Comparison between working and failing entities",
        ],
        questions=[
            "What configuration or rollout change happened immediately before the issue started?",
            "Does a known-good environment or host still work with the older configuration?",
            "Is the issue isolated to one scope or present across all equivalent deployments?",
        ],
        mitigations=[
            "Compare against a known-good baseline and restore validated settings where safe",
            "Re-apply the intended configuration to eliminate drift or partial rollout state",
        ],
        escalate_when=[
            "The issue persists after validating documented prerequisites and configuration",
        ],
        signals=["configuration", "config", "setting", "prerequisite", "changed", "rollout", "parameter"],
    ),
    "connectivity_tls": FailureMode(
        id="connectivity_tls",
        title="Connectivity, proxy, or TLS trust issue",
        summary="A network path, proxy, certificate, or trust condition is interrupting communication between components.",
        evidence=[
            "Connectivity test results such as curl -v or openssl s_client",
            "Proxy, DNS, routing, certificate chain, or trust-store details",
            "Comparison of network path between working and failing entities",
        ],
        questions=[
            "Can the impacted component resolve and reach the expected endpoint successfully?",
            "Were there any recent proxy, certificate, routing, or firewall changes?",
            "Does the failure occur only on a subset of hosts, zones, or network paths?",
        ],
        mitigations=[
            "Validate endpoint reachability, TLS handshake, and certificate chain",
            "Compare network path and trust configuration with a working baseline",
        ],
        escalate_when=[
            "Validated connectivity and trust conditions are healthy but failures continue",
        ],
        signals=["proxy", "network", "routing", "firewall", "tls", "certificate", "trust", "dns", "san", "hostname"],
    ),
    "authentication_permissions": FailureMode(
        id="authentication_permissions",
        title="Authentication, credential, or permission failure",
        summary="Credentials, scopes, or permissions no longer satisfy the requested workflow.",
        evidence=[
            "Authentication method, credential metadata, and permission scope details",
            "HTTP status codes, auth errors, or access-denied messages",
            "Recent policy, token, or account ownership changes",
        ],
        questions=[
            "Did credentials, token scopes, or permission policies change recently?",
            "Is the failure limited to one identity, token, or endpoint?",
            "What exact auth or permission error is returned?",
        ],
        mitigations=[
            "Re-test with known-good credentials or a validated service account",
            "Confirm the requested action is covered by the documented permissions or scopes",
        ],
        escalate_when=[
            "Validated supported auth flows still fail with correct scopes and endpoints",
        ],
        signals=["credential", "auth", "authentication", "authorization", "permission", "scope", "401", "403", "token"],
    ),
    "runtime_execution": FailureMode(
        id="runtime_execution",
        title="Runtime or execution-path failure",
        summary="The component activates or starts poorly because the execution path, controller, or runtime environment is unhealthy.",
        evidence=[
            "Controller, execution, or component runtime logs",
            "Service status, process state, and activation or startup error details",
            "Runtime environment changes such as permissions or dependency updates",
        ],
        questions=[
            "Is the failure occurring during startup, activation, execution, or data collection?",
            "What controller or runtime logs show at the point of failure?",
            "Did service dependencies, permissions, or execution environment change recently?",
        ],
        mitigations=[
            "Validate runtime health and restart the affected service or controller if appropriate",
            "Re-run the activation or startup path with detailed logs enabled",
        ],
        escalate_when=[
            "Runtime failures persist with validated dependencies and supported versions",
        ],
        signals=["activation", "runtime", "execution", "controller", "service", "startup", "unhealthy", "plugin"],
    ),
    "ingestion_pipeline": FailureMode(
        id="ingestion_pipeline",
        title="Ingestion or processing-pipeline failure",
        summary="Data is being dropped, transformed, or blocked in the ingest or processing path before it becomes usable.",
        evidence=[
            "Sample raw payloads or records before processing",
            "Pipeline, parser, routing, or processing configuration",
            "Timestamps showing where the data gap begins",
        ],
        questions=[
            "Is the data missing at ingest, during processing, or only in final visualizations?",
            "What pipeline, parser, or routing changes happened before the issue started?",
            "Can raw records still be observed before transformation is applied?",
        ],
        mitigations=[
            "Validate raw ingest separately from processed output",
            "Roll back or disable the recent processing change if operationally safe",
        ],
        escalate_when=[
            "Validated supported pipeline configuration still drops or mutates data unexpectedly",
        ],
        signals=["ingest", "ingestion", "pipeline", "parser", "processing", "dropped", "missing data", "no data"],
    ),
    "visualization_query_mismatch": FailureMode(
        id="visualization_query_mismatch",
        title="Query, selector, or visualization mismatch",
        summary="The underlying data path may still work, but dashboards, selectors, or capture assumptions no longer align with the current data shape.",
        evidence=[
            "Current queries, selectors, dashboard definitions, or monitor steps",
            "Examples of data shape or field-name differences before and after the change",
            "Rendered page, UI, or selector state if the issue affects frontend capture",
        ],
        questions=[
            "Is raw data still present even though the dashboard or monitor result is wrong?",
            "Did field names, selectors, queries, or UI structure change recently?",
            "Is the issue limited to one dashboard, monitor, or capture path?",
        ],
        mitigations=[
            "Validate whether dashboards, selectors, or monitors rely on changed fields or DOM structure",
            "Compare working and failing query or selector behavior directly",
        ],
        escalate_when=[
            "Validated supported queries or monitors still fail against stable data and application behavior",
        ],
        signals=["dashboard", "query", "selector", "visualization", "beacon", "monitor", "field", "capture"],
    ),
    "capacity_saturation": FailureMode(
        id="capacity_saturation",
        title="Capacity, queueing, or resource saturation",
        summary="The component is constrained by backlog, queue growth, or resource exhaustion rather than a functional bug.",
        evidence=[
            "CPU, memory, queue, backlog, or throughput indicators",
            "Timing correlation between load growth and the observed failures",
            "Comparison with healthy peers handling similar traffic",
        ],
        questions=[
            "Are queue, backlog, CPU, or memory indicators elevated on the impacted component?",
            "Did the issue begin during a traffic spike or infrastructure capacity change?",
            "Do healthy peers show materially different utilization patterns?",
        ],
        mitigations=[
            "Reduce load or redistribute traffic if operationally possible",
            "Validate sizing assumptions and compare against healthy peers",
        ],
        escalate_when=[
            "Validated healthy capacity and resource conditions still produce the same failures",
        ],
        signals=["capacity", "queue", "backlog", "saturation", "cpu", "memory", "throughput", "load"],
    ),
    "regression_platform": FailureMode(
        id="regression_platform",
        title="Possible platform or product regression",
        summary="The behavior appears to align with a reproducible regression after change, while documented prerequisites look healthy.",
        evidence=[
            "Reproducible steps with expected versus actual behavior",
            "Version timeline showing when the change introduced the issue",
            "Comparable environment or customer evidence showing the same pattern",
        ],
        questions=[
            "Can the issue be reproduced consistently with clear steps?",
            "Did the same workflow work before a specific change or version boundary?",
            "Are there comparable environments showing the same behavior with validated configuration?",
        ],
        mitigations=[
            "Capture a minimal reproducible scenario before escalating",
            "Use a temporary workaround or rollback path if the customer impact is active and change control allows it",
        ],
        escalate_when=[
            "Documented prerequisites are validated and the issue remains reproducible after a specific change",
            "Multiple environments show the same validated regression pattern",
        ],
        signals=["regression", "bug", "unexpected", "reproducible", "worked before", "after upgrade", "after change"],
    ),
}


PRODUCT_AREA_FAILURE_WEIGHTS: dict[str, dict[str, float]] = {
    "OneAgent": {
        "configuration_drift": 1.0,
        "connectivity_tls": 1.0,
        "compatibility_mismatch": 0.9,
        "runtime_execution": 0.7,
        "regression_platform": 0.5,
    },
    "ActiveGate": {
        "connectivity_tls": 1.0,
        "capacity_saturation": 0.9,
        "configuration_drift": 0.8,
        "compatibility_mismatch": 0.5,
        "regression_platform": 0.5,
    },
    "Log Monitoring": {
        "ingestion_pipeline": 1.0,
        "visualization_query_mismatch": 0.9,
        "configuration_drift": 0.8,
        "regression_platform": 0.5,
    },
    "Extensions": {
        "runtime_execution": 1.0,
        "compatibility_mismatch": 1.0,
        "authentication_permissions": 0.8,
        "configuration_drift": 0.8,
        "connectivity_tls": 0.7,
        "regression_platform": 0.6,
    },
    "DEM": {
        "visualization_query_mismatch": 1.0,
        "configuration_drift": 0.8,
        "connectivity_tls": 0.5,
        "regression_platform": 0.5,
    },
    "Kubernetes Monitoring": {
        "configuration_drift": 1.0,
        "connectivity_tls": 0.7,
        "compatibility_mismatch": 0.8,
        "runtime_execution": 0.6,
        "regression_platform": 0.5,
    },
    "API / Authentication": {
        "authentication_permissions": 1.0,
        "configuration_drift": 0.7,
        "connectivity_tls": 0.6,
        "regression_platform": 0.5,
    },
    "Metrics Ingestion": {
        "ingestion_pipeline": 1.0,
        "visualization_query_mismatch": 0.9,
        "configuration_drift": 0.7,
        "regression_platform": 0.5,
    },
    "Davis / Alerting": {
        "configuration_drift": 1.0,
        "visualization_query_mismatch": 0.7,
        "regression_platform": 0.6,
    },
    "Cloud Integration": {
        "authentication_permissions": 1.0,
        "configuration_drift": 0.9,
        "connectivity_tls": 0.6,
        "compatibility_mismatch": 0.5,
        "regression_platform": 0.4,
    },
    "Grail / DQL": {
        "visualization_query_mismatch": 1.0,
        "ingestion_pipeline": 0.7,
        "configuration_drift": 0.6,
        "regression_platform": 0.5,
    },
}


def _playbook_alignment_score(mode: FailureMode, playbooks: list[Playbook]) -> float:
    score = 0.0
    mode_terms = set(_tokenize(mode.title + " " + mode.summary + " " + " ".join(mode.signals)))
    for playbook in playbooks:
        playbook_terms = set(
            _tokenize(
                " ".join(
                    playbook.failure_domains
                    + playbook.keywords
                    + playbook.triggers
                    + playbook.evidence
                    + playbook.questions
                )
            )
        )
        overlap = len(mode_terms & playbook_terms)
        score += min(0.35, overlap * 0.04)
    return score


def infer_failure_modes(problem_statement: str, product_area: str, playbooks: list[Playbook]) -> tuple[list[FailureMode], dict[str, float]]:
    lower = problem_statement.lower()
    weights = PRODUCT_AREA_FAILURE_WEIGHTS.get(product_area, {})
    scored: list[tuple[float, FailureMode]] = []

    for mode_id, mode in FAILURE_MODE_LIBRARY.items():
        score = weights.get(mode_id, 0.0) * 0.35
        for signal in mode.signals:
            if signal in lower:
                score += 0.16 if " " in signal else 0.11
        score += _playbook_alignment_score(mode, playbooks)
        if "upgrade" in lower or "changed" in lower or "rollout" in lower:
            if mode_id in {"compatibility_mismatch", "configuration_drift", "regression_platform"}:
                score += 0.08
        if "unhealthy" in lower or "activation" in lower or "service" in lower:
            if mode_id == "runtime_execution":
                score += 0.12
        if "missing data" in lower or "stopped appearing" in lower:
            if mode_id in {"ingestion_pipeline", "visualization_query_mismatch"}:
                score += 0.08
        if score >= 0.28:
            scored.append((min(0.98, score), mode))

    scored.sort(key=lambda item: item[0], reverse=True)
    top_modes = [mode for _, mode in scored[:3]]
    confidence = {mode.id: score for score, mode in scored[:5]}
    return top_modes, confidence
