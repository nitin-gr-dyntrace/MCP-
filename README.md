# Dynatrace Support MCP

This project is a Python Model Context Protocol (MCP) server for Dynatrace support workflows.

It helps a support engineer:

- search `docs.dynatrace.com`
- search `community.dynatrace.com`
- read allowed Dynatrace pages
- classify a customer concern into support-relevant buckets
- triage cases with support-oriented next steps
- draft engineering escalations and customer responses
- cache topic-specific knowledge locally for faster follow-up searches

It is also structured for future enterprise connectors such as Jira, Slack, and Stack Overflow.
It now includes editable product-area support playbooks in `playbooks.json`.
It also includes a lightweight evaluation harness in `eval.py`.

## Project Layout

The entry script [server.py](/Users/nitin/Documents/Playground/server.py) is intentionally small.

Core modules now live under [dynatrace_mcp](/Users/nitin/Documents/Playground/dynatrace_mcp):

- [app.py](/Users/nitin/Documents/Playground/dynatrace_mcp/app.py) for MCP handlers, retrieval, and CLI/demo flow
- [diagnosis.py](/Users/nitin/Documents/Playground/dynatrace_mcp/diagnosis.py) for product-area and playbook diagnosis
- [failure_modes.py](/Users/nitin/Documents/Playground/dynatrace_mcp/failure_modes.py) for generic failure-mode reasoning and evidence mapping
- [config.py](/Users/nitin/Documents/Playground/dynatrace_mcp/config.py) for constants and product profiles
- [models.py](/Users/nitin/Documents/Playground/dynatrace_mcp/models.py) for shared data models
- [playbooks.py](/Users/nitin/Documents/Playground/dynatrace_mcp/playbooks.py) for playbook loading

## Included Tools

1. `search_dynatrace_knowledge`
   Searches Dynatrace documentation and community content using Dynatrace sitemap discovery, local cache, and hybrid support-oriented ranking.

2. `read_dynatrace_page`
   Fetches an allowed Dynatrace page and extracts readable content.

3. `analyze_customer_concern`
   Classifies the issue and suggests a support path for:
   product not working, possible bug, and customer environment impact.

4. `triage_case`
   Produces a support-style triage summary with likely component, severity, hypotheses, evidence needs, risk flags, actions, and references.

5. `build_bug_escalation`
   Creates an engineering-ready escalation draft.

6. `build_customer_response`
   Drafts a customer-facing support response.

7. `prime_topic_cache`
   Preloads Dynatrace pages for a topic into a local cache.

8. `build_investigation_plan`
   Produces an ordered investigation plan for a case.

9. `search_support_sources`
   Searches across configured connectors.

10. `list_connectors`
   Shows which connectors are live now and which are scaffolded for later integration.

## Playbooks

Support playbooks live in [playbooks.json](/Users/nitin/Documents/Playground/playbooks.json).

They inject product-specific:

- failure domains
- investigative questions
- evidence checklists
- mitigations
- escalation criteria

Current playbooks cover:

- OneAgent
- ActiveGate
- Log Monitoring
- Extensions
- DEM
- Kubernetes Monitoring
- API / Authentication
- Metrics Ingestion
- Davis / Alerting

To create or extend your own playbook:

1. Copy an existing object in `playbooks.json`
2. Set the `product_area`, `triggers`, and `keywords`
3. Fill in `failure_domains`, `questions`, `evidence`, `mitigations`, and `escalate_when`
4. Re-run the `--demo` commands to see the updated behavior

## Evaluation

Evaluation cases live in [eval_cases.json](/Users/nitin/Documents/Playground/eval_cases.json).

Run the diagnosis/playbook evaluation with:

```bash
python3 eval.py
```

This gives you a baseline for:

- product-area accuracy
- concern-type coverage
- playbook-hit rate

## Connector Architecture

The MCP is now organized so retrieval can grow source by source.

Live now:

- `docs`
- `community`

Scaffolded for later enterprise rollout:

- `jira`
- `slack`
- `stackoverflow`

The scaffold matters because later you can add APIs and credentials without redesigning the MCP tools.

Expected future environment variables:

- Jira: `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`
- Slack: `SLACK_BOT_TOKEN`, `SLACK_ALLOWED_CHANNELS`
- Stack Overflow: `STACKEXCHANGE_API_KEY`

Runtime network and host configuration:

- `MCP_ALLOWED_HOSTS`
- `HTTP_PROXY`
- `HTTPS_PROXY`
- `NO_PROXY`

This is not yet embedding-based vector search, but it is a strong stepping stone toward true semantic retrieval.

## Run

```bash
python3 server.py
```

This starts the MCP server over `stdio`, so it will look idle in a terminal until an MCP client connects.

## Test Before Connecting

You can test it in two ways.

### 1. Test The MCP Protocol

This checks the handshake, tool listing, and one tool call through the actual MCP wire format:

```bash
python3 test_client.py
```

What this proves:

- the server starts correctly
- `initialize` works
- `tools/list` works
- `tools/call` works

### 2. Test A Tool Directly

This is useful when you want quick manual testing without an MCP client.

Classify a support concern:

```bash
python3 server.py --demo analyze "Customer reports the product is not working and production is impacted"
```

Run offline classification only:

```bash
python3 server.py --demo classify "Customer reports the product is not working and production is impacted"
```

Search Dynatrace docs:

```bash
python3 server.py --demo search "oneagent installation" --sources docs --max-results 3
```

Search across all configured connectors:

```bash
python3 server.py --demo search-all "oneagent installation" --connectors docs community jira slack stackoverflow --max-results 6
```

## Validation UI

For teammates who do not want to use CLI commands, there is now a lightweight local UI in [ui.py](/Users/nitin/Documents/Playground/ui.py).

Run it with:

```bash
python3 ui.py
```

Then open:

```text
http://127.0.0.1:8765
```

The UI is intentionally simple:

- paste a customer case
- choose `Triage`, `Investigation Plan`, or `Customer Response`
- choose `docs` and `community`
- review the MCP output in the browser

List connector readiness:

```bash
python3 server.py --demo list-connectors
```

Validate whether a URL is allowed and reachable from the current machine:

```bash
python3 server.py --demo check-url "https://community.dynatrace.com/t5/Container-platforms/Helm-chart-installation-behind-proxy/m-p/205901"
```

Prime the local cache for a topic:

```bash
python3 server.py --demo prime "oneagent installation" --sources docs community --max-pages 8
```

After priming the cache, later searches and triage runs use semantic-style reranking over the cached corpus.

Debug what the sitemap search returned for one source:

```bash
python3 server.py --demo debug-search "oneagent installation" --source docs
```

Read a Dynatrace page:

```bash
python3 server.py --demo read "https://docs.dynatrace.com/"
```

Run a triage flow:

```bash
python3 server.py --demo triage "Customer reports OneAgent stopped sending data after upgrade and production hosts are affected" --sources docs community --max-results 4
```

Draft an engineering escalation:

```bash
python3 server.py --demo bug-escalation "Customer reports OneAgent stopped sending data after upgrade and production hosts are affected" --sources docs community --max-results 4
```

Draft a customer response:

```bash
python3 server.py --demo customer-response "Customer reports OneAgent stopped sending data after upgrade and production hosts are affected" --sources docs community --max-results 4
```

Build an investigation plan:

```bash
python3 server.py --demo investigation-plan "Customer reports DEM synthetic monitors are failing after a frontend rollout and checkout traffic is impacted" --sources docs community --max-results 4
```

Note:

- `analyze` can still trigger live search, so it needs internet access.
- `classify` is fully offline and is the fastest first smoke test.
- `search`, `prime`, `triage`, `bug-escalation`, `customer-response`, and `read` require internet/DNS access from the machine where you run the server.
- `debug-search` is helpful when search returns no matches and you want to inspect ranked sitemap URLs.
- in restricted environments, classification-only behavior can still be tested locally.

## Example MCP Client Config

```json
{
  "mcpServers": {
    "dynatrace-support": {
      "command": "python3",
      "args": [
        "/absolute/path/to/server.py"
      ]
    }
  }
}
```

## Notes

- The server only allows content from `docs.dynatrace.com` and `community.dynatrace.com`.
- You can extend the hostname allowlist with `MCP_ALLOWED_HOSTS`, for example: `MCP_ALLOWED_HOSTS=intranet.company.com,confluence.company.com`
- Proxy-aware fetching uses standard environment variables such as `HTTP_PROXY`, `HTTPS_PROXY`, and `NO_PROXY`.
- Search uses Dynatrace site sitemaps instead of a third-party search engine.
- Cached knowledge is stored locally in `.cache/dynatrace_corpus.json`.
- The MCP transport is stdio, so it works well with desktop AI clients and local agent frameworks.
- A strong next step after this would be adding true embeddings, solved-case memory, contradiction detection, and a formal eval suite.
- Enterprise connectors are scaffolded, but public docs/community remain the only live sources in the current POC.
