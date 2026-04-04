from __future__ import annotations

import json
import subprocess
import sys
from typing import Any


SERVER_PATH = "/Users/nitin/Documents/Playground/server.py"


def send_message(process: subprocess.Popen[bytes], message: dict[str, Any]) -> None:
    body = json.dumps(message).encode("utf-8")
    payload = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
    assert process.stdin is not None
    process.stdin.write(payload)
    process.stdin.flush()


def read_message(process: subprocess.Popen[bytes]) -> dict[str, Any]:
    assert process.stdout is not None

    header = b""
    while b"\r\n\r\n" not in header:
        chunk = process.stdout.read(1)
        if not chunk:
            raise RuntimeError("Server closed before sending a response.")
        header += chunk

    content_length = 0
    for line in header.decode("utf-8").split("\r\n"):
        if line.lower().startswith("content-length:"):
            content_length = int(line.split(":", 1)[1].strip())
            break

    if content_length <= 0:
        raise RuntimeError("Invalid Content-Length in server response.")

    body = process.stdout.read(content_length)
    if not body:
        raise RuntimeError("Missing server response body.")

    return json.loads(body.decode("utf-8"))


def pretty_print(title: str, payload: dict[str, Any]) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, indent=2))


def main() -> int:
    process = subprocess.Popen(
        ["python3", SERVER_PATH],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "local-test-client",
                        "version": "0.1.0",
                    },
                },
            },
        )
        pretty_print("initialize", read_message(process))

        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )

        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        pretty_print("tools/list", read_message(process))

        send_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "analyze_customer_concern",
                    "arguments": {
                        "problemStatement": "Customer reports the product is not working and their production environment is affected.",
                        "sources": ["docs"],
                        "maxResults": 3,
                    },
                },
            },
        )
        pretty_print("tools/call analyze_customer_concern", read_message(process))
        return 0
    finally:
        process.terminate()
        process.wait(timeout=5)
        if process.stderr is not None:
            stderr = process.stderr.read().decode("utf-8", errors="replace").strip()
            if stderr:
                print("\n=== stderr ===")
                print(stderr)


if __name__ == "__main__":
    raise SystemExit(main())
