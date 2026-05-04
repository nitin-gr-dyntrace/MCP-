from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse


SERVER_INFO = {
    "name": "dynatrace-support-mcp",
    "version": "0.1.0",
}

BASE_ALLOWED_HOSTS = {"docs.dynatrace.com", "community.dynatrace.com"}


def _load_extra_sitemap_sources() -> tuple[dict[str, str], dict[str, str]]:
    raw = os.environ.get("MCP_EXTRA_SITEMAPS", "").strip()
    extra_sources: dict[str, str] = {}
    extra_sitemaps: dict[str, str] = {}
    if not raw:
        return extra_sources, extra_sitemaps

    for part in raw.split(","):
        item = part.strip()
        if not item or "=" not in item:
            continue
        name, sitemap_url = item.split("=", 1)
        source_name = name.strip().lower().replace(" ", "_")
        sitemap_url = sitemap_url.strip()
        hostname = urlparse(sitemap_url).hostname
        if not source_name or not sitemap_url or not hostname:
            continue
        extra_sources[source_name] = hostname.lower()
        extra_sitemaps[source_name] = sitemap_url
    return extra_sources, extra_sitemaps


SEARCH_SOURCES = {
    "docs": "docs.dynatrace.com",
    "community": "community.dynatrace.com",
}

SITEMAP_URLS = {
    "docs": "https://docs.dynatrace.com/sitemap.xml",
    "community": "https://community.dynatrace.com/sitemap.xml",
}

_EXTRA_SEARCH_SOURCES, _EXTRA_SITEMAP_URLS = _load_extra_sitemap_sources()
SEARCH_SOURCES.update(_EXTRA_SEARCH_SOURCES)
SITEMAP_URLS.update(_EXTRA_SITEMAP_URLS)

CACHE_DIR = Path(".cache")
CORPUS_PATH = CACHE_DIR / "dynatrace_corpus.json"
PLAYBOOKS_PATH = Path("playbooks.json")

SUPPORT_SYNONYMS = {
    "install": ["installation", "deploy", "deployment", "setup"],
    "installation": ["install", "deploy", "deployment", "setup"],
    "oneagent": ["agent", "fullstack", "host monitoring"],
    "activegate": ["gateway", "environment activegate"],
    "kubernetes": ["k8s", "openshift", "aks", "eks", "gke"],
    "log": ["logs", "logging", "log monitoring"],
    "metric": ["metrics", "timeseries", "data point"],
    "problem": ["issue", "incident", "failure"],
    "bug": ["defect", "regression"],
    "impact": ["affected", "outage", "degradation"],
    "production": ["prod", "critical"],
    "extension": ["extensions", "extension framework", "custom extension"],
    "dem": ["digital experience monitoring", "rum", "synthetic", "frontend"],
    "rum": ["real user monitoring", "browser", "frontend"],
    "synthetic": ["synthetic monitoring", "browser clickpath", "api synthetic"],
    "extension framework": ["extension", "extensions", "custom extension"],
    "logs": ["log", "logging", "grail logs"],
    "grail": ["dql", "logs", "security investigator", "dynatrace query language", "data explorer", "notebook"],
    "dql": ["grail", "dynatrace query language", "fetch", "summarize", "fieldsadd"],
    "notebook": ["grail", "dql", "data explorer"],
    "retention": ["bucket", "grail", "data retention", "ingestion"],
    "lookup": ["dql lookup", "join", "joined query", "cross-environment"],
    "javascript tile": ["js tile", "app tile", "notebook tile", "grail notebook"],
    "aws": ["amazon", "aws integration", "cloud integration", "aws extension"],
    "iam": ["aws iam", "aws role", "aws policy", "authorization error"],
    "pending connection": ["aws pending", "cloud pending", "connection status"],
}

PRODUCT_AREA_PROFILES = [
    {
        "name": "OneAgent",
        "keywords": ["oneagent", "agent", "fullstack", "host monitoring", "code module"],
        "questions": [
            "Which OneAgent version, OS, and deployment method are involved?",
            "Did the issue start after installation, upgrade, or host changes?",
            "Are all monitored hosts affected or only a subset?",
        ],
        "evidence": [
            "OneAgent version and installer type",
            "Host OS and architecture",
            "Relevant OneAgent or installer logs",
        ],
        "risks": ["host visibility gap", "data ingestion interruption"],
    },
    {
        "name": "ActiveGate",
        "keywords": ["activegate", "gateway", "network zone", "environment activegate"],
        "questions": [
            "Is the issue isolated to one ActiveGate or all ActiveGates in the network zone?",
            "Did any certificate, routing, or proxy configuration change recently?",
            "Are queue or forwarding indicators elevated on the impacted ActiveGate?",
        ],
        "evidence": [
            "ActiveGate version and logs",
            "Network zone and connectivity details",
            "Relevant certificate or proxy configuration",
        ],
        "risks": ["data forwarding interruption", "monitoring blind spot"],
    },
    {
        "name": "Log Monitoring",
        "keywords": ["log", "logs", "logging", "grail logs", "log monitoring"],
        "questions": [
            "Are logs missing, delayed, duplicated, or incorrectly parsed?",
            "Which ingest path is used: OneAgent, API, or pipeline?",
            "Did parsing rules, processors, or retention settings change recently?",
        ],
        "evidence": [
            "Sample raw log lines",
            "Ingest path and processing configuration",
            "Timestamp range where logs are missing or malformed",
        ],
        "risks": ["observability blind spot", "compliance or audit gap"],
    },
    {
        "name": "Extensions",
        "keywords": ["extension", "extensions", "extension 2.0", "activation", "extension framework", "remote plugin", "sql extension"],
        "questions": [
            "Which extension type and version is affected?",
            "Is the failure during deployment, activation, or data collection?",
            "Does the extension work in one environment but fail in another?",
        ],
        "evidence": [
            "Extension name, version, and configuration",
            "Activation or execution logs",
            "Target endpoint connectivity details",
        ],
        "risks": ["monitoring gap for external dependency", "false health reporting"],
    },
    {
        "name": "DEM",
        "keywords": ["dem", "rum", "synthetic", "user session", "browser monitor", "frontend"],
        "questions": [
            "Is the issue in RUM, Synthetic, session replay, or a browser/API monitor?",
            "Are real users impacted, or only synthetic tests?",
            "Did an application deployment or JS tag change precede the issue?",
        ],
        "evidence": [
            "Application URL and monitor identifiers",
            "Screenshots, HAR, or failing step details",
            "Timing of deployment or script-tag changes",
        ],
        "risks": ["customer-facing experience degradation", "alert noise or missed outage"],
    },
    {
        "name": "Kubernetes Monitoring",
        "keywords": ["kubernetes", "k8s", "openshift", "cluster", "daemonset", "operator"],
        "questions": [
            "Which distribution and operator or Helm version are in use?",
            "Is the issue cluster-wide, namespace-specific, or workload-specific?",
            "Did the issue begin after a cluster upgrade or policy change?",
        ],
        "evidence": [
            "Cluster distribution and version",
            "Dynatrace operator or Helm version",
            "Affected namespaces, pods, and relevant logs",
        ],
        "risks": ["cluster observability gap", "workload blind spot"],
    },
    {
        "name": "API / Authentication",
        "keywords": ["api", "token", "oauth", "auth", "authentication", "authorization"],
        "questions": [
            "Which endpoint, token type, or auth flow is involved?",
            "Is the issue a permission error, expiry problem, or transport failure?",
            "Did credentials or scopes change recently?",
        ],
        "evidence": [
            "Endpoint and HTTP status codes",
            "Token type and scopes",
            "Timestamped request and response samples",
        ],
        "risks": ["automation outage", "integration breakage"],
    },
    {
        "name": "Metrics Ingestion",
        "keywords": ["metric ingestion", "timeseries", "custom metric", "schema"],
        "questions": [
            "Did metric dimensions, names, or payload schema change recently?",
            "Is the issue visible at ingest or only in charts and selectors?",
            "Did send volume or cardinality change sharply?",
        ],
        "evidence": [
            "Sample metric payloads",
            "Metric selectors or dashboard queries",
            "Timeline of schema or sender changes",
        ],
        "risks": ["dashboard blind spot", "alerting gap"],
    },
    {
        "name": "Davis / Alerting",
        "keywords": ["davis", "problem", "alert", "alerting", "anomaly", "noise"],
        "questions": [
            "Did thresholds, event settings, or notifications change recently?",
            "Is the issue false positives, missed alerts, or wrong root cause grouping?",
            "Did telemetry quality change before the behavior changed?",
        ],
        "evidence": [
            "Problem IDs and timestamps",
            "Alerting configuration snapshots",
            "Expected versus actual alert behavior examples",
        ],
        "risks": ["alert fatigue", "missed incident detection"],
    },
    {
        "name": "Grail / DQL",
        "keywords": [
            "grail", "dql", "dynatrace query language", "notebook", "data explorer",
            "fetch", "summarize", "fieldsadd", "bucket", "retention",
            "javascript tile", "js tile", "lookup", "joined query", "app tile",
            "cross-environment", "merge environments", "join query",
        ],
        "questions": [
            "Is the issue with query syntax, an unsupported function, or unexpected results?",
            "Which data type is being queried: logs, metrics, events, spans, or entities?",
            "Is the query running inside a Notebook tile, App tile, or a dashboard widget?",
            "Does the query work in isolation but fail when combined with a join or lookup?",
        ],
        "evidence": [
            "Full DQL query text and the exact error message or unexpected output",
            "Expected versus actual result set with a sample of the data",
            "Whether the query uses lookup, join, or cross-environment references",
            "Relevant retention bucket and time range",
        ],
        "risks": ["data not queryable", "incorrect analysis or alerting based on bad query results"],
    },
    {
        "name": "Cloud Integration",
        "keywords": [
            "aws", "amazon", "aws integration", "cloud integration", "iam", "cloudwatch",
            "s3", "ec2", "lambda", "datasync", "kms", "cloud connector", "aws extension",
            "azure", "gcp", "google cloud", "aws account", "aws connection", "pending connection",
            "authorization error", "cloud metrics", "aws credentials", "arn",
        ],
        "questions": [
            "Which cloud provider and accounts are affected, and when did the connection status change?",
            "Have the IAM roles, policies, or trust relationships changed since the integration was set up?",
            "Is the issue isolated to specific AWS services or all metrics across all accounts?",
            "Does the connection show differently in the classic Extensions page versus the new Settings UI?",
        ],
        "evidence": [
            "IAM role ARN, attached policies, and any recent policy change history",
            "Connection status from both the classic Extensions page and the new cloud integration settings",
            "Full authorization error messages with exact IAM action names",
            "CloudTrail or AWS access logs around the time the connectivity dropped",
        ],
        "risks": ["cloud monitoring blind spot", "IAM policy drift causing partial or full metric loss", "silent data gap if pending status is not caught early"],
    },
]


def configured_allowed_hosts() -> set[str]:
    extra_hosts = {
        host.strip().lower()
        for host in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    source_hosts = {host.lower() for host in SEARCH_SOURCES.values()}
    return BASE_ALLOWED_HOSTS | source_hosts | extra_hosts
