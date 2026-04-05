from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from dynatrace_mcp.app import (
    build_customer_response_text,
    build_investigation_plan_text,
    build_triage_text,
)


HOST = "127.0.0.1"
PORT = 8765

OUTPUT_MODES = {
    "triage": ("Triage", build_triage_text),
    "investigation": ("Investigation Plan", build_investigation_plan_text),
    "customer_response": ("Customer Response", build_customer_response_text),
}


def render_page(
    *,
    problem_statement: str = "",
    sources: list[str] | None = None,
    mode: str = "triage",
    max_results: int = 6,
    output: str = "",
    error: str = "",
) -> str:
    selected_sources = sources or ["docs", "community"]
    source_docs = "checked" if "docs" in selected_sources else ""
    source_community = "checked" if "community" in selected_sources else ""

    mode_cards: list[str] = []
    for key, (label, _) in OUTPUT_MODES.items():
        checked = "checked" if key == mode else ""
        mode_cards.append(
            f"""
            <label class="mode-card">
              <input type="radio" name="mode" value="{html.escape(key)}" {checked}>
              <span>{html.escape(label)}</span>
            </label>
            """
        )

    output_html = ""
    if output:
        output_html = f"""
        <section class="panel result-panel">
          <div class="panel-header">
            <h2>Result</h2>
          </div>
          <pre>{html.escape(output)}</pre>
        </section>
        """
    elif error:
        output_html = f"""
        <section class="panel result-panel error-panel">
          <div class="panel-header">
            <h2>Error</h2>
          </div>
          <pre>{html.escape(error)}</pre>
        </section>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dynatrace Support MCP UI</title>
  <style>
    :root {{
      --bg: #f4efe8;
      --surface: #fffaf4;
      --surface-strong: #fff;
      --text: #1f1a16;
      --muted: #6b6057;
      --border: #d8c9bb;
      --accent: #0f766e;
      --accent-soft: #d8f3ef;
      --danger: #9f1239;
      --shadow: 0 18px 40px rgba(74, 58, 44, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 32%),
        linear-gradient(180deg, #f7f2ea 0%, #efe7dc 100%);
      color: var(--text);
    }}
    .shell {{
      width: min(1180px, calc(100vw - 32px));
      margin: 24px auto 40px;
      display: grid;
      gap: 18px;
    }}
    .hero {{
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 22px;
      padding: 28px;
      box-shadow: var(--shadow);
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: clamp(2rem, 4vw, 3.2rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }}
    .hero p {{
      margin: 0;
      max-width: 780px;
      color: var(--muted);
      font-size: 1.02rem;
    }}
    .grid {{
      display: grid;
      grid-template-columns: minmax(300px, 420px) minmax(0, 1fr);
      gap: 18px;
      align-items: start;
    }}
    .panel {{
      background: var(--surface-strong);
      border: 1px solid var(--border);
      border-radius: 22px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }}
    .panel-header {{
      padding: 18px 20px 0;
    }}
    .panel-header h2 {{
      margin: 0;
      font-size: 1rem;
      letter-spacing: 0.02em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .panel-body {{
      padding: 18px 20px 20px;
    }}
    label.block {{
      display: block;
      margin-bottom: 10px;
      font-size: 0.92rem;
      color: var(--muted);
    }}
    textarea {{
      width: 100%;
      min-height: 200px;
      border-radius: 16px;
      border: 1px solid var(--border);
      padding: 14px 16px;
      font: inherit;
      resize: vertical;
      background: #fffdf9;
      color: var(--text);
    }}
    .modes {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 16px;
    }}
    .mode-card {{
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      min-width: 0;
      padding: 12px 10px;
      border: 1px solid var(--border);
      border-radius: 16px;
      background: #fffcf7;
      cursor: pointer;
      font-size: 0.88rem;
      text-align: center;
    }}
    .mode-card input {{
      accent-color: var(--accent);
      flex: 0 0 auto;
    }}
    .mode-card span {{
      line-height: 1.15;
      overflow-wrap: anywhere;
    }}
    .controls {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 16px;
    }}
    .control-box {{
      padding: 12px 14px;
      border-radius: 16px;
      border: 1px solid var(--border);
      background: #fffcf7;
    }}
    .source-list {{
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 8px;
    }}
    .source-list label {{
      display: flex;
      align-items: center;
      gap: 8px;
      font-size: 0.95rem;
    }}
    input[type="number"] {{
      width: 100%;
      border-radius: 12px;
      border: 1px solid var(--border);
      padding: 10px 12px;
      font: inherit;
      background: #fffdf9;
    }}
    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 6px;
    }}
    button[type="submit"] {{
      border: 0;
      border-radius: 999px;
      background: var(--accent);
      color: white;
      padding: 12px 18px;
      font: inherit;
      cursor: pointer;
    }}
    pre {{
      margin: 0;
      padding: 18px 20px 22px;
      white-space: pre-wrap;
      word-break: break-word;
      overflow-wrap: anywhere;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 0.9rem;
      line-height: 1.5;
      background: #fffdfa;
    }}
    .error-panel pre {{
      color: var(--danger);
    }}
    .result-panel {{
      min-height: 640px;
    }}
    @media (max-width: 920px) {{
      .grid {{
        grid-template-columns: 1fr;
      }}
      .modes {{
        grid-template-columns: 1fr;
      }}
      .controls {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>
  <main class="shell">
    <section class="hero">
      <h1>Dynatrace Support MCP</h1>
      <p>Validate triage quality in the browser, without remembering CLI commands. Paste a real support case, switch between triage, investigation plan, and customer response, and share the output with teammates for quick review.</p>
    </section>
    <section class="grid">
      <form class="panel" method="post">
        <div class="panel-header">
          <h2>Case Input</h2>
        </div>
        <div class="panel-body">
          <div class="modes">
            {''.join(mode_cards)}
          </div>

          <label class="block" for="problem_statement">Customer issue</label>
          <textarea id="problem_statement" name="problem_statement" placeholder="Paste a real support case here...">{html.escape(problem_statement)}</textarea>

          <div class="controls">
            <div class="control-box">
              <div>Sources</div>
              <div class="source-list">
                <label><input type="checkbox" name="sources" value="docs" {source_docs}> Docs</label>
                <label><input type="checkbox" name="sources" value="community" {source_community}> Community</label>
              </div>
            </div>
            <div class="control-box">
              <label class="block" for="max_results">Max results</label>
              <input id="max_results" type="number" min="1" max="10" name="max_results" value="{max_results}">
            </div>
          </div>

          <div class="actions">
            <button type="submit">Run MCP Analysis</button>
          </div>
        </div>
      </form>

      {output_html or '''
      <section class="panel result-panel">
        <div class="panel-header">
          <h2>Result</h2>
        </div>
        <pre>Your result will appear here after you run the MCP analysis.</pre>
      </section>
      '''}
    </section>
  </main>
</body>
</html>
"""


class MCPUIHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        page = render_page()
        self._send_html(page)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        payload = parse_qs(raw)

        problem_statement = payload.get("problem_statement", [""])[0].strip()
        sources = payload.get("sources", ["docs", "community"])
        mode = payload.get("mode", ["triage"])[0]
        max_results_raw = payload.get("max_results", ["6"])[0]

        try:
            max_results = max(1, min(10, int(max_results_raw)))
        except ValueError:
            max_results = 6

        if mode not in OUTPUT_MODES:
            mode = "triage"

        if not sources:
            sources = ["docs", "community"]

        if not problem_statement:
            page = render_page(
                problem_statement=problem_statement,
                sources=sources,
                mode=mode,
                max_results=max_results,
                error="Please enter a customer issue before running the MCP analysis.",
            )
            self._send_html(page)
            return

        try:
            _, builder = OUTPUT_MODES[mode]
            output = builder(problem_statement, sources, max_results)
            page = render_page(
                problem_statement=problem_statement,
                sources=sources,
                mode=mode,
                max_results=max_results,
                output=output,
            )
        except Exception as exc:
            page = render_page(
                problem_statement=problem_statement,
                sources=sources,
                mode=mode,
                max_results=max_results,
                error=str(exc),
            )

        self._send_html(page)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, content: str) -> None:
        encoded = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), MCPUIHandler)
    print(json.dumps({"url": f"http://{HOST}:{PORT}", "host": HOST, "port": PORT}, indent=2))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
