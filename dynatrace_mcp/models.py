from __future__ import annotations

from dataclasses import dataclass


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


@dataclass
class FailureMode:
    id: str
    title: str
    summary: str
    evidence: list[str]
    questions: list[str]
    mitigations: list[str]
    escalate_when: list[str]
    signals: list[str]


@dataclass
class Diagnosis:
    product_area: str
    product_confidence: float
    subdomain: str
    subdomain_confidence: float
    concern_types: list[str]
    severity: str
    matched_playbooks: list[Playbook]
    playbook_confidence: dict[str, float]
    failure_modes: list[FailureMode]
    failure_mode_confidence: dict[str, float]
    failure_domains: list[str]
    component_keywords: list[str]
    entity_signals: list[str]
