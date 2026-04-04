from __future__ import annotations

import json
import re
import sys
import argparse
import os
import socket
import gzip
import math
from collections import Counter
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from urllib.error import URLError
from urllib.request import Request, build_opener, getproxies, ProxyHandler
from xml.etree import ElementTree


SERVER_INFO = {
    "name": "dynatrace-support-mcp",
    "version": "0.1.0",
}

BASE_ALLOWED_HOSTS = {
    "docs.dynatrace.com",
    "community.dynatrace.com",
}

SEARCH_SOURCES = {
    "docs": "docs.dynatrace.com",
    "community": "community.dynatrace.com",
}

SITEMAP_URLS = {
    "docs": "https://docs.dynatrace.com/sitemap.xml",
    "community": "https://community.dynatrace.com/sitemap.xml",
}

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
    "grail": ["dql", "logs", "security investigator"],
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
        "keywords": ["extension", "extensions", "extension framework", "remote plugin", "sql extension"],
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
]


def configured_allowed_hosts() -> set[str]:
    extra_hosts = {
        host.strip().lower()
        for host in os.environ.get("MCP_ALLOWED_HOSTS", "").split(",")
        if host.strip()
    }
    return BASE_ALLOWED_HOSTS | extra_hosts


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str


@dataclass
class CorpusEntry:
    source: str
    url: str
    title: str
    excerpt: str
    page_type: str = "article"


@dataclass
class ConnectorDocument:
    source: str
    source_type: str
    title: str
    url: str
    text: str
    tags: list[str]
    trust_level: str
    updated_at: str = ""


@dataclass
class Playbook:
    id: str
    product_area: str
    title: str
    triggers: list[str]
    keywords: list[str]
    failure_domains: list[str]
    questions: list[str]
    evidence: list[str]
    mitigations: list[str]
    escalate_when: list[str]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "div", "section", "article", "li", "h1", "h2", "h3", "h4", "br"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._chunks.append(stripped)

    def text(self) -> str:
        value = " ".join(self._chunks)
        return normalize_whitespace(value)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_playbooks() -> list[Playbook]:
    if not PLAYBOOKS_PATH.exists():
        return []

    try:
        raw = json.loads(PLAYBOOKS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    playbooks: list[Playbook] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        playbooks.append(
            Playbook(
                id=str(item.get("id", "")),
                product_area=str(item.get("product_area", "")),
                title=str(item.get("title", "")),
                triggers=[str(value) for value in item.get("triggers", []) if isinstance(value, str)],
                keywords=[str(value) for value in item.get("keywords", []) if isinstance(value, str)],
                failure_domains=[str(value) for value in item.get("failure_domains", []) if isinstance(value, str)],
                questions=[str(value) for value in item.get("questions", []) if isinstance(value, str)],
                evidence=[str(value) for value in item.get("evidence", []) if isinstance(value, str)],
                mitigations=[str(value) for value in item.get("mitigations", []) if isinstance(value, str)],
                escalate_when=[str(value) for value in item.get("escalate_when", []) if isinstance(value, str)],
            )
        )
    return playbooks


def tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 1]


def char_ngrams(value: str, size: int = 3) -> list[str]:
    normalized = re.sub(r"\s+", " ", value.lower()).strip()
    if len(normalized) < size:
        return [normalized] if normalized else []
    return [normalized[index : index + size] for index in range(len(normalized) - size + 1)]


def expand_query_terms(query: str) -> list[str]:
    expanded: list[str] = []
    for token in tokenize(query):
        expanded.append(token)
        expanded.extend(SUPPORT_SYNONYMS.get(token, []))
    return list(dict.fromkeys(expanded))


def classify_page_type(url: str, source: str, title: str, excerpt: str) -> str:
    path = urlparse(url).path.lower()
    text = f"{title} {excerpt}".lower()

    if ".xml" in path or "sitemap" in path:
        return "sitemap"

    if source == "community":
        if "/t5/" in path and ("/m-p/" in path or "/td-p/" in path):
            return "thread"
        if any(part in path for part in ["/board/", "/label-name/", "/kb/", "/blog/"]):
            return "index"

    if source == "docs":
        if path in {"/", "/docs", "/docs/"}:
            return "navigation"
        if any(part in path for part in ["/whats-new", "/release-notes", "/search"]):
            return "navigation"

    if any(token in path for token in ["/tag/", "/tags/", "/category/", "/categories/"]):
        return "index"

    if any(token in text for token in ["documentation search", "ctrl k", "try it free login"]):
        return "article"

    return "article"


def page_type_penalty(page_type: str) -> float:
    penalties = {
        "article": 0.0,
        "thread": 0.0,
        "index": -25.0,
        "navigation": -40.0,
        "sitemap": -100.0,
    }
    return penalties.get(page_type, 0.0)


def page_type_allowed(page_type: str) -> bool:
    return page_type in {"article", "thread"}


def entry_feature_text(entry: CorpusEntry) -> str:
    return f"{entry.title} {entry.excerpt} {unquote(entry.url)}"


def document_frequency(entries: list[CorpusEntry]) -> Counter[str]:
    frequencies: Counter[str] = Counter()
    for entry in entries:
        unique_terms = set(tokenize(entry_feature_text(entry)))
        frequencies.update(unique_terms)
    return frequencies


def tfidf_cosine_similarity(query_text: str, document_text: str, doc_freq: Counter[str], corpus_size: int) -> float:
    query_terms = tokenize(query_text)
    document_terms = tokenize(document_text)
    if not query_terms or not document_terms or corpus_size <= 0:
        return 0.0

    query_counter = Counter(query_terms)
    document_counter = Counter(document_terms)
    vocabulary = set(query_counter) | set(document_counter)

    numerator = 0.0
    query_norm = 0.0
    document_norm = 0.0

    for term in vocabulary:
        idf = math.log((1 + corpus_size) / (1 + doc_freq.get(term, 0))) + 1.0
        query_weight = query_counter.get(term, 0) * idf
        document_weight = document_counter.get(term, 0) * idf
        numerator += query_weight * document_weight
        query_norm += query_weight * query_weight
        document_norm += document_weight * document_weight

    if query_norm == 0.0 or document_norm == 0.0:
        return 0.0

    return numerator / math.sqrt(query_norm * document_norm)


def ngram_jaccard_similarity(query_text: str, document_text: str) -> float:
    query_ngrams = set(char_ngrams(query_text))
    document_ngrams = set(char_ngrams(document_text))
    if not query_ngrams or not document_ngrams:
        return 0.0
    intersection = len(query_ngrams & document_ngrams)
    union = len(query_ngrams | document_ngrams)
    return intersection / union if union else 0.0


def semantic_similarity(entry: CorpusEntry, query: str, corpus_entries: list[CorpusEntry]) -> float:
    feature_text = entry_feature_text(entry)
    frequencies = document_frequency(corpus_entries)
    tfidf_score = tfidf_cosine_similarity(query, feature_text, frequencies, len(corpus_entries))
    ngram_score = ngram_jaccard_similarity(query, feature_text)

    profile_bonus = 0.0
    matched_profiles = matched_product_profiles(query)
    if matched_profiles:
        for profile in matched_profiles[:2]:
            if any(keyword in feature_text.lower() for keyword in profile["keywords"]):
                profile_bonus += 0.08

    return (tfidf_score * 0.75) + (ngram_score * 0.17) + profile_bonus


def source_type_boost(source: str, page_type: str, url: str) -> float:
    path = urlparse(url).path.lower()
    boost = 0.0

    if source == "community":
        if page_type == "thread":
            boost += 18.0
        if "/m-p/" in path or "/td-p/" in path:
            boost += 8.0

    if source == "docs":
        if any(token in path for token in ["/how-to/", "/installation", "/troubleshoot", "/troubleshooting"]):
            boost += 14.0
        if any(token in path for token in ["/reference/", "/api", "/extension", "/log-monitoring", "/synthetic"]):
            boost += 8.0

    return boost


def strip_html(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value)
    return parser.text()


def allowed_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    if parsed.hostname not in configured_allowed_hosts():
        raise ValueError(f"Unsupported hostname: {parsed.hostname}")
    return url


def fetch_text(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "dynatrace-support-mcp/0.1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    proxies = getproxies()
    opener = build_opener(ProxyHandler(proxies))
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read()
            if url.endswith(".gz"):
                raw = gzip.decompress(raw)
            return raw.decode("utf-8", errors="replace")
    except URLError as exc:
        raise RuntimeError(
            f"Network request failed for {url}. Check internet/DNS access, VPN, and proxy settings on the machine running this MCP server."
        ) from exc


def diagnose_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    report: dict[str, Any] = {
        "url": url,
        "hostname": hostname,
        "allowed": False,
        "dns_resolves": False,
        "http_reachable": False,
        "extractable": False,
        "proxy_env": getproxies(),
    }

    try:
        allowed_url(url)
        report["allowed"] = True
    except Exception as exc:
        report["allow_error"] = str(exc)
        return report

    try:
        socket.getaddrinfo(hostname, 443)
        report["dns_resolves"] = True
    except OSError as exc:
        report["dns_error"] = str(exc)
        return report

    try:
        html = fetch_text(url)
        report["http_reachable"] = True
        extracted = strip_html(html)
        report["extractable"] = bool(extracted)
        report["text_preview"] = extracted[:400]
        report["text_length"] = len(extracted)
    except Exception as exc:
        report["http_error"] = str(exc)

    return report


def decode_duckduckgo_href(href: str) -> str | None:
    if href.startswith("//"):
        href = f"https:{href}"

    parsed = urlparse(href)

    # DuckDuckGo may return both relative and absolute redirect links.
    if href.startswith("/") or parsed.hostname in {
        "duckduckgo.com",
        "www.duckduckgo.com",
        "html.duckduckgo.com",
    }:
        query = parse_qs(parsed.query)
        uddg = query.get("uddg", [])
        return unescape(uddg[0]) if uddg else None

    return href


def iter_loc_elements(root: ElementTree.Element) -> list[str]:
    locations: list[str] = []
    for element in root.iter():
        if element.tag.endswith("loc") and element.text:
            locations.append(element.text.strip())
    return locations


def fetch_sitemap_urls(source: str, visited: set[str] | None = None) -> list[str]:
    sitemap_url = SITEMAP_URLS[source]
    pending = [sitemap_url]
    visited_urls = visited or set()
    discovered: list[str] = []

    while pending:
        current = pending.pop(0)
        if current in visited_urls:
            continue
        visited_urls.add(current)

        xml_text = fetch_text(current)
        try:
            root = ElementTree.fromstring(xml_text)
        except ElementTree.ParseError as exc:
            raise RuntimeError(f"Unable to parse sitemap XML from {current}") from exc

        for loc in iter_loc_elements(root):
            if loc.endswith(".xml") or loc.endswith(".xml.gz"):
                pending.append(loc)
                continue

            try:
                discovered.append(allowed_url(loc))
            except ValueError:
                continue

    return discovered


def query_terms(query: str) -> list[str]:
    return tokenize(query)


def score_url_for_query(url: str, query: str) -> int:
    haystack = unquote(url).lower()
    compact_query = normalize_whitespace(query.lower())
    terms = expand_query_terms(query)
    source = "community" if "community.dynatrace.com" in haystack else "docs"
    page_type = classify_page_type(url, source, "", "")

    score = 0
    if compact_query and compact_query in haystack:
        score += 50

    for term in terms:
        if term in haystack:
            score += 10

    path = urlparse(url).path.lower()
    if "oneagent" in terms and "oneagent" in path:
        score += 15
    if "kubernetes" in terms and "kubernetes" in path:
        score += 15

    score += int(page_type_penalty(page_type))
    score += int(source_type_boost(source, page_type, url))

    return score


def score_entry_for_query(entry: CorpusEntry, query: str) -> float:
    title_terms = Counter(tokenize(entry.title))
    excerpt_terms = Counter(tokenize(entry.excerpt))
    url_text = unquote(entry.url).lower()
    expanded_terms = expand_query_terms(query)
    compact_query = normalize_whitespace(query.lower())

    score = 0.0
    if compact_query and compact_query in normalize_whitespace(
        f"{entry.title} {entry.excerpt} {url_text}".lower()
    ):
        score += 30.0

    for term in expanded_terms:
        score += title_terms.get(term, 0) * 6.0
        score += excerpt_terms.get(term, 0) * 2.0
        if term in url_text:
            score += 4.0

    score += source_type_boost(entry.source, entry.page_type, entry.url)
    score += page_type_penalty(entry.page_type)

    if entry.source == "community" and any(term in url_text for term in ["error", "failed", "issue", "problem", "proxy"]):
        score += 6.0
    if entry.source == "docs" and any(term in url_text for term in ["install", "configuration", "troubleshoot", "reference"]):
        score += 6.0

    return score


def rank_cached_entries(query: str, sources: list[str], max_results: int) -> list[SearchResult]:
    entries = [
        entry
        for entry in load_corpus()
        if entry.source in sources and page_type_allowed(entry.page_type)
    ]
    corpus_entries = entries or load_corpus()
    ranked = sorted(
        (
            (
                score_entry_for_query(entry, query)
                + (semantic_similarity(entry, query, corpus_entries) * 100.0),
                entry,
            )
            for entry in entries
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        entry_to_search_result(entry)
        for score, entry in ranked
        if score > 0
    ][:max_results]


def search_source(query: str, source: str, max_results: int) -> list[SearchResult]:
    sitemap_urls = fetch_sitemap_urls(source)
    ranked = sorted(
        ((score_url_for_query(url, query), url) for url in sitemap_urls),
        key=lambda item: item[0],
        reverse=True,
    )

    candidate_limit = max(max_results * 6, 12)
    top_urls = [url for score, url in ranked if score > 0][:candidate_limit]
    if len(top_urls) < max_results:
        fallback_urls = [url for _, url in ranked if url not in top_urls][:candidate_limit - len(top_urls)]
        top_urls.extend(fallback_urls)

    entries: list[CorpusEntry] = []

    for url in top_urls:
        try:
            entry = entry_from_url(url, source)
            if not page_type_allowed(entry.page_type):
                continue
            entries.append(entry)
        except Exception:
            continue
        if len(entries) >= candidate_limit:
            break

    if entries:
        upsert_corpus_entries(entries)

    corpus_entries = entries or load_corpus()
    reranked = sorted(
        (
            (
                score_entry_for_query(entry, query)
                + (semantic_similarity(entry, query, corpus_entries) * 100.0),
                entry,
            )
            for entry in entries
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    return [
        entry_to_search_result(entry)
        for score, entry in reranked
        if score > 0
    ][:max_results]


def debug_search_source(query: str, source: str) -> dict[str, Any]:
    sitemap_url = SITEMAP_URLS[source]
    sitemap_urls = fetch_sitemap_urls(source)
    ranked = sorted(
        ((score_url_for_query(url, query), url) for url in sitemap_urls),
        key=lambda item: item[0],
        reverse=True,
    )[:10]
    return {
        "search_url": sitemap_url,
        "result_count": len([item for item in ranked if item[0] > 0]),
        "results": [
            {
                "score": score,
                "url": url,
            }
            for score, url in ranked
        ],
        "sitemap_url_count": len(sitemap_urls),
    }


def prime_topic_cache(query: str, sources: list[str], max_pages: int) -> dict[str, Any]:
    added_entries: list[CorpusEntry] = []
    per_source = max(1, (max_pages + len(sources) - 1) // len(sources))

    for source in sources:
        sitemap_urls = fetch_sitemap_urls(source)
        ranked = sorted(
            ((score_url_for_query(url, query), url) for url in sitemap_urls),
            key=lambda item: item[0],
            reverse=True,
        )
        for score, url in ranked:
            if score <= 0:
                continue
            try:
                added_entries.append(entry_from_url(url, source))
            except Exception:
                continue
            if len([entry for entry in added_entries if entry.source == source]) >= per_source:
                break

    if added_entries:
        upsert_corpus_entries(added_entries)

    return {
        "query": query,
        "sources": sources,
        "cached_pages": len(added_entries),
        "cache_file": str(CORPUS_PATH),
    }


def search_knowledge(query: str, sources: list[str], max_results: int) -> list[SearchResult]:
    cached_results = rank_cached_entries(query, sources, max_results)
    if len(cached_results) >= max_results:
        return cached_results[:max_results]

    per_source = max(2, (max_results + len(sources) - 1) // len(sources))
    live_results_by_source: dict[str, list[SearchResult]] = {}
    for source in sources:
        live_results_by_source[source] = search_source(query, source, per_source)

    combined_by_url: dict[str, SearchResult] = {}
    for result in cached_results:
        combined_by_url[result.url] = result
    for source in sources:
        for result in live_results_by_source.get(source, []):
            combined_by_url[result.url] = result

    combined = list(combined_by_url.values())
    cached_entries_by_url = {
        entry.url: entry
        for entry in load_corpus()
        if entry.source in sources and page_type_allowed(entry.page_type)
    }
    candidate_entries = [
        cached_entries_by_url.get(
            result.url,
            CorpusEntry(
                source=result.source,
                url=result.url,
                title=result.title,
                excerpt=result.snippet,
                page_type=classify_page_type(result.url, result.source, result.title, result.snippet),
            ),
        )
        for result in combined
    ]
    candidate_by_url = {entry.url: entry for entry in candidate_entries}
    combined.sort(
        key=lambda result: (
            score_entry_for_query(candidate_by_url[result.url], query)
            + (semantic_similarity(candidate_by_url[result.url], query, candidate_entries) * 100.0)
        ),
        reverse=True,
    )

    if len(sources) <= 1:
        return combined[:max_results]

    balanced: list[SearchResult] = []
    seen_urls: set[str] = set()
    grouped = {
        source: [result for result in combined if result.source == source]
        for source in sources
    }

    while len(balanced) < max_results:
        progressed = False
        for source in sources:
            while grouped[source]:
                candidate = grouped[source].pop(0)
                if candidate.url in seen_urls:
                    continue
                balanced.append(candidate)
                seen_urls.add(candidate.url)
                progressed = True
                break
            if len(balanced) >= max_results:
                break
        if not progressed:
            break

    return balanced[:max_results]


def search_connectors(query: str, connector_names: list[str], max_results: int) -> list[SearchResult]:
    public_sources = [name for name in connector_names if name in SEARCH_SOURCES]
    external_sources = [name for name in connector_names if name not in SEARCH_SOURCES]

    results: list[SearchResult] = []
    if public_sources:
        results.extend(search_knowledge(query, public_sources, max_results))

    per_connector = max(1, max_results // max(len(external_sources), 1))
    for name in external_sources:
        connector = CONNECTORS[name]
        if not connector.enabled:
            continue
        try:
            docs = connector.search(query, per_connector)
        except Exception:
            continue
        for document in docs:
            results.append(entry_to_search_result(document_to_entry(document)))

    deduped: dict[str, SearchResult] = {}
    for result in results:
        deduped[result.url] = result
    return list(deduped.values())[:max_results]


def read_page(url: str) -> dict[str, str]:
    allowed = allowed_url(url)
    html = fetch_text(allowed)
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = strip_html(unescape(title_match.group(1))) if title_match else allowed
    excerpt = strip_html(html)[:4000]
    hostname = urlparse(allowed).hostname or ""
    source = "docs" if hostname == SEARCH_SOURCES["docs"] else "community"
    return {
        "title": title or allowed,
        "url": allowed,
        "source": source,
        "excerpt": excerpt or "No readable content could be extracted.",
    }


def load_corpus() -> list[CorpusEntry]:
    if not CORPUS_PATH.exists():
        return []

    try:
        raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    entries: list[CorpusEntry] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        entries.append(
            CorpusEntry(
                source=str(item.get("source", "")),
                url=str(item.get("url", "")),
                title=str(item.get("title", "")),
                excerpt=str(item.get("excerpt", "")),
                page_type=str(item.get("page_type", "article")),
            )
        )
    return entries


def save_corpus(entries: list[CorpusEntry]) -> None:
    ensure_cache_dir()
    serializable = [
        {
            "source": entry.source,
            "url": entry.url,
            "title": entry.title,
            "excerpt": entry.excerpt,
            "page_type": entry.page_type,
        }
        for entry in entries
    ]
    CORPUS_PATH.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


def upsert_corpus_entries(new_entries: list[CorpusEntry]) -> None:
    current = {entry.url: entry for entry in load_corpus()}
    for entry in new_entries:
        current[entry.url] = entry
    save_corpus(list(current.values()))


def entry_from_url(url: str, source: str) -> CorpusEntry:
    page = read_page(url)
    return CorpusEntry(
        source=source,
        url=page["url"],
        title=page["title"],
        excerpt=page["excerpt"],
        page_type=classify_page_type(page["url"], source, page["title"], page["excerpt"]),
    )


def entry_to_search_result(entry: CorpusEntry) -> SearchResult:
    return SearchResult(
        title=entry.title,
        url=entry.url,
        snippet=entry.excerpt[:300] or "No snippet available.",
        source=entry.source,
    )


def document_to_entry(document: ConnectorDocument) -> CorpusEntry:
    return CorpusEntry(
        source=document.source,
        url=document.url,
        title=document.title,
        excerpt=document.text,
    )


class BaseConnector:
    name = "base"
    enabled = True
    source_type = "document"
    trust_level = "unknown"

    def search(self, query: str, max_results: int) -> list[ConnectorDocument]:
        raise NotImplementedError

    def status(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "source_type": self.source_type,
            "trust_level": self.trust_level,
        }


class SitemapConnector(BaseConnector):
    source_type = "article"
    trust_level = "public"

    def __init__(self, name: str) -> None:
        self.name = name

    def search(self, query: str, max_results: int) -> list[ConnectorDocument]:
        results = search_source(query, self.name, max_results)
        documents: list[ConnectorDocument] = []
        for result in results:
            documents.append(
                ConnectorDocument(
                    source=result.source,
                    source_type=self.source_type,
                    title=result.title,
                    url=result.url,
                    text=result.snippet,
                    tags=expand_query_terms(query)[:8],
                    trust_level=self.trust_level,
                )
            )
        return documents


class StackOverflowConnector(BaseConnector):
    name = "stackoverflow"
    enabled = False
    source_type = "qa_thread"
    trust_level = "external"

    def search(self, query: str, max_results: int) -> list[ConnectorDocument]:
        raise RuntimeError(
            "Stack Overflow connector is scaffolded but not enabled yet. Add API integration and credentials before use."
        )

    def status(self) -> dict[str, Any]:
        status = super().status()
        status["required_env"] = ["STACKEXCHANGE_API_KEY"]
        return status


class SlackConnector(BaseConnector):
    name = "slack"
    enabled = False
    source_type = "chat_thread"
    trust_level = "internal"

    def search(self, query: str, max_results: int) -> list[ConnectorDocument]:
        raise RuntimeError(
            "Slack connector is scaffolded but not enabled yet. Add Slack Web API integration and approved channel scoping."
        )

    def status(self) -> dict[str, Any]:
        status = super().status()
        status["required_env"] = ["SLACK_BOT_TOKEN", "SLACK_ALLOWED_CHANNELS"]
        return status


class JiraConnector(BaseConnector):
    name = "jira"
    enabled = False
    source_type = "ticket"
    trust_level = "internal"

    def search(self, query: str, max_results: int) -> list[ConnectorDocument]:
        raise RuntimeError(
            "Jira connector is scaffolded but not enabled yet. Add Jira REST API integration and credentials before use."
        )

    def status(self) -> dict[str, Any]:
        status = super().status()
        status["required_env"] = ["JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"]
        return status


def build_connector_registry() -> dict[str, BaseConnector]:
    return {
        "docs": SitemapConnector("docs"),
        "community": SitemapConnector("community"),
        "stackoverflow": StackOverflowConnector(),
        "slack": SlackConnector(),
        "jira": JiraConnector(),
    }


CONNECTORS = build_connector_registry()


def classify_concern(problem_statement: str) -> list[str]:
    lower = problem_statement.lower()
    labels: list[str] = []

    if re.search(
        r"not working|broken|failing|error|issue|down|unavailable|stopped|not sending|missing data|no data",
        lower,
    ):
        labels.append("product_not_working")
    if re.search(r"bug|defect|regression|unexpected|incorrect behavior", lower):
        labels.append("possible_bug_for_engineering")
    if re.search(r"impact|affected|outage|degradation|production|environment|tenant|cluster", lower):
        labels.append("customer_environment_impact")

    return labels or ["general_support_investigation"]


def matched_product_profiles(problem_statement: str) -> list[dict[str, Any]]:
    lower = problem_statement.lower()
    matches: list[tuple[int, dict[str, Any]]] = []
    for profile in PRODUCT_AREA_PROFILES:
        score = sum(1 for keyword in profile["keywords"] if keyword in lower)
        if score > 0:
            matches.append((score, profile))
    matches.sort(key=lambda item: item[0], reverse=True)
    return [profile for _, profile in matches]


def matched_playbooks(problem_statement: str) -> list[Playbook]:
    lower = problem_statement.lower()
    component = identify_component(problem_statement)
    matches: list[tuple[int, Playbook]] = []

    for playbook in load_playbooks():
        score = 0
        if playbook.product_area == component:
            score += 12
        for trigger in playbook.triggers:
            if trigger.lower() in lower:
                score += 6
        for keyword in playbook.keywords:
            if keyword.lower() in lower:
                score += 3
        if score > 0:
            matches.append((score, playbook))

    matches.sort(key=lambda item: item[0], reverse=True)
    return [playbook for _, playbook in matches[:2]]


def identify_component(problem_statement: str) -> str:
    matches = matched_product_profiles(problem_statement)
    if matches:
        return matches[0]["name"]

    lower = problem_statement.lower()
    component_map = [
        ("oneagent", "OneAgent"),
        ("activegate", "ActiveGate"),
        ("kubernetes", "Kubernetes Monitoring"),
        ("openshift", "Kubernetes Monitoring"),
        ("log", "Log Monitoring"),
        ("rum", "DEM"),
        ("synthetic", "Synthetic monitoring"),
        ("api", "API / authentication"),
        ("token", "API / authentication"),
        ("extension", "Extensions"),
        ("metric", "Metrics ingestion"),
    ]
    for needle, label in component_map:
        if needle in lower:
            return label
    return "General Dynatrace platform"


def estimate_severity(problem_statement: str, concern_types: list[str]) -> str:
    lower = problem_statement.lower()
    if "customer_environment_impact" in concern_types and re.search(
        r"production|outage|critical|all hosts|tenant down|cluster down", lower
    ):
        return "high"
    if "product_not_working" in concern_types or "customer_environment_impact" in concern_types:
        return "medium"
    return "normal"


def investigation_questions(problem_statement: str, component: str, concern_types: list[str]) -> list[str]:
    questions = [
        "What changed just before the issue started, such as configuration, rollout, upgrade, or network changes?",
        "What is the exact scope of impact: one host, one cluster, one tenant, or all environments?",
        "Can the customer share timestamps, screenshots, logs, and exact error messages?",
    ]

    for profile in matched_product_profiles(problem_statement)[:2]:
        questions.extend(profile["questions"])
    for playbook in matched_playbooks(problem_statement):
        questions.extend(playbook.questions)
    if "possible_bug_for_engineering" in concern_types:
        questions.append("Can the issue be reproduced consistently, and what are the exact steps?")

    deduped = list(dict.fromkeys(questions))
    return deduped[:7]


def recommended_actions(concern_types: list[str], component: str) -> list[str]:
    actions = [
        f"Validate the expected behavior for {component} against the top Dynatrace references.",
        "Confirm scope, timeline, and blast radius before proposing a fix or escalation.",
    ]
    if "product_not_working" in concern_types:
        actions.append("Collect diagnostic evidence and compare against configuration prerequisites.")
    if "possible_bug_for_engineering" in concern_types:
        actions.append("Prepare a DE-ready defect summary with repro steps, expected behavior, and impact.")
    if "customer_environment_impact" in concern_types:
        actions.append("Prioritize mitigation, temporary workaround, and customer communication cadence.")
    return actions


def evidence_checklist(problem_statement: str, concern_types: list[str]) -> list[str]:
    evidence = [
        "Timeline of when the issue started and whether it is still active",
        "Exact error text, screenshots, and affected entity identifiers",
        "Recent changes before impact started",
    ]
    for profile in matched_product_profiles(problem_statement)[:2]:
        evidence.extend(profile["evidence"])
    for playbook in matched_playbooks(problem_statement):
        evidence.extend(playbook.evidence)
    if "possible_bug_for_engineering" in concern_types:
        evidence.append("Expected versus actual behavior with reproducible steps")
    return list(dict.fromkeys(evidence))[:8]


def risk_flags(problem_statement: str, concern_types: list[str]) -> list[str]:
    flags: list[str] = []
    for profile in matched_product_profiles(problem_statement)[:2]:
        flags.extend(profile["risks"])
    if "customer_environment_impact" in concern_types:
        flags.append("active customer-environment impact")
    if "possible_bug_for_engineering" in concern_types:
        flags.append("possible product defect or regression")
    return list(dict.fromkeys(flags))[:6]


def generate_hypotheses(problem_statement: str, concern_types: list[str], component: str) -> list[str]:
    hypotheses = [
        f"The issue may be caused by a configuration or prerequisite gap in {component}.",
        "The issue may align with a documented limitation or expected behavior that needs verification.",
    ]
    for playbook in matched_playbooks(problem_statement):
        hypotheses.extend([f"Likely failure domain: {domain}." for domain in playbook.failure_domains])
    if "product_not_working" in concern_types:
        hypotheses.append("A deployment, upgrade, or environmental change may have interrupted normal product behavior.")
    if "possible_bug_for_engineering" in concern_types:
        hypotheses.append("The behavior may indicate a regression or undocumented product defect.")
    if "customer_environment_impact" in concern_types:
        hypotheses.append("The issue may have operational blast radius and should be treated as an active incident until scoped.")
    return hypotheses[:5]


def playbook_mitigations(problem_statement: str) -> list[str]:
    mitigations: list[str] = []
    for playbook in matched_playbooks(problem_statement):
        mitigations.extend(playbook.mitigations)
    return list(dict.fromkeys(mitigations))[:5]


def escalation_criteria(problem_statement: str) -> list[str]:
    criteria: list[str] = []
    for playbook in matched_playbooks(problem_statement):
        criteria.extend(playbook.escalate_when)
    return list(dict.fromkeys(criteria))[:5]


def summarize_results(results: list[SearchResult]) -> list[str]:
    summaries: list[str] = []
    for result in results[:3]:
        summaries.append(f"{result.title} ({result.source})")
    return summaries


def compare_results_by_source(results: list[SearchResult]) -> str:
    docs_count = sum(1 for result in results if result.source == "docs")
    community_count = sum(1 for result in results if result.source == "community")

    if docs_count and community_count:
        return "Both official docs and community discussions are available. Prefer docs for authoritative behavior and use community results for field patterns and workarounds."
    if docs_count:
        return "Matches are primarily from official docs, which is a strong sign the behavior can be validated against documented guidance."
    if community_count:
        return "Matches are primarily from community content, so validate any workaround or interpretation against product documentation before concluding."
    return "No source comparison is available yet."


def build_triage_text(problem_statement: str, sources: list[str], max_results: int) -> str:
    concern_types = classify_concern(problem_statement)
    component = identify_component(problem_statement)
    severity = estimate_severity(problem_statement, concern_types)
    results = search_knowledge(problem_statement, sources, max_results)
    questions = investigation_questions(problem_statement, component, concern_types)
    actions = recommended_actions(concern_types, component)
    hypotheses = generate_hypotheses(problem_statement, concern_types, component)
    evidence = evidence_checklist(problem_statement, concern_types)
    risks = risk_flags(problem_statement, concern_types)
    source_insight = compare_results_by_source(results)
    risk_items = [f"- {flag}" for flag in risks] if risks else ["- No elevated risk flags identified yet."]
    playbooks = matched_playbooks(problem_statement)
    mitigation_items = [f"- {item}" for item in playbook_mitigations(problem_statement)]
    escalation_items = [f"- {item}" for item in escalation_criteria(problem_statement)]

    return "\n".join(
        [
            f"Problem statement: {problem_statement}",
            f"Concern types: {', '.join(concern_types)}",
            f"Likely component: {component}",
            f"Estimated severity: {severity}",
            f"Matched playbooks: {', '.join(playbook.title for playbook in playbooks) if playbooks else 'None'}",
            f"Source insight: {source_insight}",
            "",
            "Working hypotheses:",
            *[f"- {hypothesis}" for hypothesis in hypotheses],
            "",
            "Immediate questions:",
            *[f"- {question}" for question in questions],
            "",
            "Evidence to collect:",
            *[f"- {item}" for item in evidence],
            "",
            "Risk flags:",
            *risk_items,
            "",
            "Recommended next actions:",
            *[f"- {action}" for action in actions],
            "",
            "Suggested mitigations:",
            *(mitigation_items or ["- No playbook-specific mitigation suggestions yet."]),
            "",
            "Escalate to engineering when:",
            *(escalation_items or ["- Escalate after configuration and environment causes are ruled out."]),
            "",
            "Top references:",
            format_results(results),
        ]
    )


def build_bug_escalation_text(problem_statement: str, sources: list[str], max_results: int) -> str:
    concern_types = classify_concern(problem_statement)
    component = identify_component(problem_statement)
    results = search_knowledge(problem_statement, sources, max_results)
    evidence = evidence_checklist(problem_statement, concern_types)
    hypotheses = generate_hypotheses(problem_statement, concern_types, component)
    escalation_items = escalation_criteria(problem_statement)

    return "\n".join(
        [
            "Engineering escalation draft",
            f"Component: {component}",
            f"Concern types: {', '.join(concern_types)}",
            "",
            f"Problem summary: {problem_statement}",
            "Expected behavior: Dynatrace should continue to behave according to documented product behavior for this workflow.",
            "Actual behavior: Customer reports unexpected or failing behavior that needs validation against docs and potentially DE review.",
            "Customer impact: Describe current scope, severity, production risk, and any workaround status.",
            "Current hypotheses:",
            *[f"- {hypothesis}" for hypothesis in hypotheses],
            "Evidence checklist:",
            *[f"- {item}" for item in evidence],
            "Escalation threshold that was considered:",
            *([f"- {item}" for item in escalation_items] or ["- Config and environment causes have been sufficiently ruled out."]),
            "",
            "Relevant references to compare against:",
            format_results(results),
        ]
    )


def build_customer_response_text(problem_statement: str, sources: list[str], max_results: int) -> str:
    concern_types = classify_concern(problem_statement)
    component = identify_component(problem_statement)
    results = search_knowledge(problem_statement, sources, max_results)
    summaries = summarize_results(results)
    next_steps = recommended_actions(concern_types, component)[:3]
    checked_items = [f"- {summary}" for summary in summaries]
    if not checked_items:
        checked_items = ["- Relevant Dynatrace references are still being gathered."]
    requests = investigation_questions(problem_statement, component, concern_types)[:3]
    mitigations = playbook_mitigations(problem_statement)[:2]

    return "\n".join(
        [
            "Draft customer response",
            "",
            f"We reviewed the reported issue related to {component}. Based on the current information, the case appears to fit: {', '.join(concern_types)}.",
            "",
            "What we checked:",
            *checked_items,
            "",
            "Recommended next steps:",
            *[f"- {step}" for step in next_steps],
            *[f"- Consider: {item}" for item in mitigations],
            "",
            "Information needed from the customer:",
            *[f"- {item}" for item in requests],
        ]
    )


def build_investigation_plan_text(problem_statement: str, sources: list[str], max_results: int) -> str:
    concern_types = classify_concern(problem_statement)
    component = identify_component(problem_statement)
    results = search_knowledge(problem_statement, sources, max_results)
    hypotheses = generate_hypotheses(problem_statement, concern_types, component)
    evidence = evidence_checklist(problem_statement, concern_types)
    actions = recommended_actions(concern_types, component)
    playbooks = matched_playbooks(problem_statement)
    mitigations = playbook_mitigations(problem_statement)
    escalation_items = escalation_criteria(problem_statement)

    steps = [
        "Validate issue scope and timeline with the customer.",
        f"Verify documented behavior for {component} using the highest-ranked references.",
        "Collect logs, screenshots, timestamps, and impacted entity identifiers.",
        "Test the leading hypotheses and eliminate configuration or environment causes first.",
    ]
    if "possible_bug_for_engineering" in concern_types:
        steps.append("If reproduced and not documented, prepare a DE escalation with expected versus actual behavior.")
    if "customer_environment_impact" in concern_types:
        steps.append("Establish mitigation or workaround options and communicate blast radius clearly.")

    return "\n".join(
        [
            "Investigation plan",
            f"Likely component: {component}",
            f"Concern types: {', '.join(concern_types)}",
            f"Matched playbooks: {', '.join(playbook.title for playbook in playbooks) if playbooks else 'None'}",
            "",
            "Ordered plan:",
            *[f"{index}. {step}" for index, step in enumerate(steps, start=1)],
            "",
            "Leading hypotheses:",
            *[f"- {hypothesis}" for hypothesis in hypotheses],
            "",
            "Evidence checklist:",
            *[f"- {item}" for item in evidence],
            "",
            "Reference pack:",
            format_results(results),
            "",
            "Decision guidance:",
            *[f"- {action}" for action in actions],
            "",
            "Targeted mitigations:",
            *([f"- {item}" for item in mitigations] or ["- No playbook-specific mitigations identified yet."]),
            "",
            "Escalation guide:",
            *([f"- {item}" for item in escalation_items] or ["- Escalate after reproducing the issue and ruling out configuration causes."]),
        ]
    )


def normalize_sources(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["docs", "community"]

    valid = [item for item in value if isinstance(item, str) and item in SEARCH_SOURCES]
    return valid or ["docs", "community"]


def normalize_connectors(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["docs", "community"]

    valid = [item for item in value if isinstance(item, str) and item in CONNECTORS]
    return valid or ["docs", "community"]


def connector_status_report() -> list[dict[str, Any]]:
    return [connector.status() for connector in CONNECTORS.values()]


def format_results(results: list[SearchResult]) -> str:
    if not results:
        return "No matching results were found from the configured Dynatrace sources."

    parts: list[str] = []
    for index, result in enumerate(results, start=1):
        parts.append(
            "\n".join(
                [
                    f"{index}. [{result.source}] {result.title}",
                    f"URL: {result.url}",
                    f"Snippet: {result.snippet}",
                ]
            )
        )
    return "\n\n".join(parts)


def ok(result: Any, request_id: Any) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": code,
            "message": message,
        },
    }


def tool_result(text: str, is_error: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "content": [
            {
                "type": "text",
                "text": text,
            }
        ]
    }
    if is_error:
        result["isError"] = True
    return result


def list_tools() -> dict[str, Any]:
    return {
        "tools": [
            {
                "name": "search_dynatrace_knowledge",
                "description": "Search Dynatrace documentation and community pages for troubleshooting guidance.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Customer issue, symptom, or troubleshooting question.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "search_support_sources",
                "description": "Search across configured support connectors. Public sources work now; Jira, Slack, and Stack Overflow are scaffolded for later integration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Customer issue, symptom, or troubleshooting question.",
                        },
                        "connectors": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community", "stackoverflow", "slack", "jira"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "list_connectors",
                "description": "Show which connectors are live now and which enterprise connectors are scaffolded for future integration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "check_url_access",
                "description": "Validate whether an allowed URL is permitted, reachable, and extractable from the current machine.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to validate.",
                        }
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "read_dynatrace_page",
                "description": "Fetch and extract readable content from an allowed Dynatrace docs or community URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "A URL under docs.dynatrace.com or community.dynatrace.com.",
                        }
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "analyze_customer_concern",
                "description": "Classify a customer concern, search relevant Dynatrace content, and suggest next support actions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "problemStatement": {
                            "type": "string",
                            "description": "Short description of the customer issue.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["problemStatement"],
                },
            },
            {
                "name": "triage_case",
                "description": "Run support triage for a customer issue with severity, component guess, questions, and references.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "problemStatement": {
                            "type": "string",
                            "description": "Short description of the customer issue.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["problemStatement"],
                },
            },
            {
                "name": "build_bug_escalation",
                "description": "Create an engineering-ready escalation draft for a likely Dynatrace bug or regression.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "problemStatement": {
                            "type": "string",
                            "description": "Customer issue summary for escalation.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["problemStatement"],
                },
            },
            {
                "name": "build_customer_response",
                "description": "Draft a polished support response using the current issue statement and relevant Dynatrace references.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "problemStatement": {
                            "type": "string",
                            "description": "Customer issue summary.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["problemStatement"],
                },
            },
            {
                "name": "prime_topic_cache",
                "description": "Preload and cache Dynatrace pages for a topic so later searches are faster and more contextual.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Topic to pre-cache, such as OneAgent or Kubernetes monitoring.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxPages": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 50,
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "build_investigation_plan",
                "description": "Turn a customer concern into an ordered investigation plan with evidence, hypotheses, and references.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "problemStatement": {
                            "type": "string",
                            "description": "Customer issue summary.",
                        },
                        "sources": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["docs", "community"],
                            },
                        },
                        "maxResults": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                        },
                    },
                    "required": ["problemStatement"],
                },
            },
        ]
    }


def handle_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name == "search_dynatrace_knowledge":
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        sources = normalize_sources(arguments.get("sources"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        results = search_knowledge(query, sources, max_results)
        return tool_result(format_results(results))

    if name == "search_support_sources":
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        connectors = normalize_connectors(arguments.get("connectors"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        results = search_connectors(query, connectors, max_results)
        return tool_result(format_results(results))

    if name == "list_connectors":
        report = connector_status_report()
        return tool_result(json.dumps(report, indent=2))

    if name == "check_url_access":
        url = str(arguments.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")
        return tool_result(json.dumps(diagnose_url(url), indent=2))

    if name == "read_dynatrace_page":
        url = str(arguments.get("url", "")).strip()
        if not url:
            raise ValueError("url is required")
        page = read_page(url)
        return tool_result(
            "\n".join(
                [
                    f"Title: {page['title']}",
                    f"Source: {page['source']}",
                    f"URL: {page['url']}",
                    "",
                    page["excerpt"],
                ]
            )
        )

    if name == "analyze_customer_concern":
        problem_statement = str(arguments.get("problemStatement", "")).strip()
        if not problem_statement:
            raise ValueError("problemStatement is required")
        sources = normalize_sources(arguments.get("sources"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        return tool_result(build_triage_text(problem_statement, sources, max_results))

    if name == "triage_case":
        problem_statement = str(arguments.get("problemStatement", "")).strip()
        if not problem_statement:
            raise ValueError("problemStatement is required")
        sources = normalize_sources(arguments.get("sources"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        return tool_result(build_triage_text(problem_statement, sources, max_results))

    if name == "build_bug_escalation":
        problem_statement = str(arguments.get("problemStatement", "")).strip()
        if not problem_statement:
            raise ValueError("problemStatement is required")
        sources = normalize_sources(arguments.get("sources"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        return tool_result(build_bug_escalation_text(problem_statement, sources, max_results))

    if name == "build_customer_response":
        problem_statement = str(arguments.get("problemStatement", "")).strip()
        if not problem_statement:
            raise ValueError("problemStatement is required")
        sources = normalize_sources(arguments.get("sources"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        return tool_result(build_customer_response_text(problem_statement, sources, max_results))

    if name == "prime_topic_cache":
        query = str(arguments.get("query", "")).strip()
        if not query:
            raise ValueError("query is required")
        sources = normalize_sources(arguments.get("sources"))
        max_pages = max(1, min(int(arguments.get("maxPages", 10)), 50))
        summary = prime_topic_cache(query, sources, max_pages)
        return tool_result(
            "\n".join(
                [
                    f"Topic cache primed for: {summary['query']}",
                    f"Sources: {', '.join(summary['sources'])}",
                    f"Cached pages: {summary['cached_pages']}",
                    f"Cache file: {summary['cache_file']}",
                ]
            )
        )

    if name == "build_investigation_plan":
        problem_statement = str(arguments.get("problemStatement", "")).strip()
        if not problem_statement:
            raise ValueError("problemStatement is required")
        sources = normalize_sources(arguments.get("sources"))
        max_results = max(1, min(int(arguments.get("maxResults", 5)), 10))
        return tool_result(build_investigation_plan_text(problem_statement, sources, max_results))

    raise ValueError(f"Unknown tool: {name}")


def read_message() -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        header = line.decode("utf-8").strip()
        if ":" in header:
            key, value = header.split(":", 1)
            headers[key.lower()] = value.strip()

    content_length = int(headers.get("content-length", "0"))
    if content_length <= 0:
        return None

    body = sys.stdin.buffer.read(content_length)
    if not body:
        return None

    return json.loads(body.decode("utf-8"))


def send_message(message: dict[str, Any]) -> None:
    body = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    request_id = message.get("id")
    params = message.get("params", {})

    if method == "initialize":
        return ok(
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": SERVER_INFO,
            },
            request_id,
        )

    if method == "notifications/initialized":
        return None

    if method == "tools/list":
        return ok(list_tools(), request_id)

    if method == "tools/call":
        try:
            result = handle_tool_call(
                str(params.get("name", "")),
                params.get("arguments", {}) or {},
            )
            return ok(result, request_id)
        except Exception as exc:
            return ok(tool_result(str(exc), is_error=True), request_id)

    return error_response(request_id, -32601, f"Method not found: {method}")


def run_stdio_server() -> None:
    while True:
        message = read_message()
        if message is None:
            break
        response = handle_request(message)
        if response is not None:
            send_message(response)


def run_demo(tool_name: str, arguments: dict[str, Any]) -> int:
    try:
        result = handle_tool_call(tool_name, arguments)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for item in result.get("content", []):
        if item.get("type") == "text":
            print(item.get("text", ""))
    return 0


def parse_demo_args(values: list[str]) -> tuple[str, dict[str, Any]]:
    parser = argparse.ArgumentParser(
        description="Run a Dynatrace MCP tool directly from the command line."
    )
    subparsers = parser.add_subparsers(dest="tool", required=True)

    search_parser = subparsers.add_parser("search", help="Run search_dynatrace_knowledge")
    search_parser.add_argument("query", help="Search query")
    search_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    search_parser.add_argument("--max-results", type=int, default=5)

    support_search_parser = subparsers.add_parser("search-all", help="Run search_support_sources")
    support_search_parser.add_argument("query", help="Search query")
    support_search_parser.add_argument(
        "--connectors",
        nargs="*",
        choices=["docs", "community", "stackoverflow", "slack", "jira"],
        default=None,
    )
    support_search_parser.add_argument("--max-results", type=int, default=5)

    debug_parser = subparsers.add_parser("debug-search", help="Inspect raw search parsing for one source")
    debug_parser.add_argument("query", help="Search query")
    debug_parser.add_argument("--source", choices=["docs", "community"], default="docs")

    subparsers.add_parser("list-connectors", help="Show configured connectors")

    check_parser = subparsers.add_parser("check-url", help="Validate whether a URL is allowed and reachable")
    check_parser.add_argument("url", help="URL to validate")

    read_parser = subparsers.add_parser("read", help="Run read_dynatrace_page")
    read_parser.add_argument("url", help="Allowed Dynatrace page URL")

    analyze_parser = subparsers.add_parser("analyze", help="Run analyze_customer_concern")
    analyze_parser.add_argument("problem_statement", help="Customer issue description")
    analyze_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    analyze_parser.add_argument("--max-results", type=int, default=5)

    classify_parser = subparsers.add_parser("classify", help="Run offline concern classification only")
    classify_parser.add_argument("problem_statement", help="Customer issue description")

    triage_parser = subparsers.add_parser("triage", help="Run triage_case")
    triage_parser.add_argument("problem_statement", help="Customer issue description")
    triage_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    triage_parser.add_argument("--max-results", type=int, default=5)

    bug_parser = subparsers.add_parser("bug-escalation", help="Run build_bug_escalation")
    bug_parser.add_argument("problem_statement", help="Customer issue description")
    bug_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    bug_parser.add_argument("--max-results", type=int, default=5)

    response_parser = subparsers.add_parser("customer-response", help="Run build_customer_response")
    response_parser.add_argument("problem_statement", help="Customer issue description")
    response_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    response_parser.add_argument("--max-results", type=int, default=5)

    plan_parser = subparsers.add_parser("investigation-plan", help="Run build_investigation_plan")
    plan_parser.add_argument("problem_statement", help="Customer issue description")
    plan_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    plan_parser.add_argument("--max-results", type=int, default=5)

    prime_parser = subparsers.add_parser("prime", help="Run prime_topic_cache")
    prime_parser.add_argument("query", help="Topic to cache")
    prime_parser.add_argument("--sources", nargs="*", choices=["docs", "community"], default=None)
    prime_parser.add_argument("--max-pages", type=int, default=10)

    parsed = parser.parse_args(values)

    if parsed.tool == "search":
        return (
            "search_dynatrace_knowledge",
            {
                "query": parsed.query,
                "sources": parsed.sources,
                "maxResults": parsed.max_results,
            },
        )

    if parsed.tool == "debug-search":
        return (
            "__debug_search__",
            {
                "query": parsed.query,
                "source": parsed.source,
            },
        )

    if parsed.tool == "list-connectors":
        return ("list_connectors", {})

    if parsed.tool == "check-url":
        return (
            "check_url_access",
            {
                "url": parsed.url,
            },
        )

    if parsed.tool == "read":
        return (
            "read_dynatrace_page",
            {
                "url": parsed.url,
            },
        )

    if parsed.tool == "search-all":
        return (
            "search_support_sources",
            {
                "query": parsed.query,
                "connectors": parsed.connectors,
                "maxResults": parsed.max_results,
            },
        )

    if parsed.tool == "classify":
        return (
            "__classify_only__",
            {
                "problemStatement": parsed.problem_statement,
            },
        )

    if parsed.tool == "triage":
        return (
            "triage_case",
            {
                "problemStatement": parsed.problem_statement,
                "sources": parsed.sources,
                "maxResults": parsed.max_results,
            },
        )

    if parsed.tool == "bug-escalation":
        return (
            "build_bug_escalation",
            {
                "problemStatement": parsed.problem_statement,
                "sources": parsed.sources,
                "maxResults": parsed.max_results,
            },
        )

    if parsed.tool == "customer-response":
        return (
            "build_customer_response",
            {
                "problemStatement": parsed.problem_statement,
                "sources": parsed.sources,
                "maxResults": parsed.max_results,
            },
        )

    if parsed.tool == "investigation-plan":
        return (
            "build_investigation_plan",
            {
                "problemStatement": parsed.problem_statement,
                "sources": parsed.sources,
                "maxResults": parsed.max_results,
            },
        )

    if parsed.tool == "prime":
        return (
            "prime_topic_cache",
            {
                "query": parsed.query,
                "sources": parsed.sources,
                "maxPages": parsed.max_pages,
            },
        )

    return (
        "analyze_customer_concern",
        {
            "problemStatement": parsed.problem_statement,
            "sources": parsed.sources,
            "maxResults": parsed.max_results,
        },
    )


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        tool_name, arguments = parse_demo_args(sys.argv[2:])
        if tool_name == "__classify_only__":
            print(", ".join(classify_concern(str(arguments["problemStatement"]))))
            raise SystemExit(0)
        if tool_name == "__debug_search__":
            try:
                debug = debug_search_source(
                    str(arguments["query"]),
                    str(arguments["source"]),
                )
                print(json.dumps(debug, indent=2))
                raise SystemExit(0)
            except Exception as exc:
                print(f"Error: {exc}", file=sys.stderr)
                raise SystemExit(1)
        raise SystemExit(run_demo(tool_name, arguments))

    run_stdio_server()


if __name__ == "__main__":
    main()
