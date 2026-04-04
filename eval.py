from __future__ import annotations

import json
from pathlib import Path

from server import diagnose_problem


CASES_PATH = Path("eval_cases.json")


def load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


def main() -> int:
    cases = load_cases()
    total = len(cases)
    product_hits = 0
    concern_hits = 0
    playbook_hits = 0

    print("Dynatrace MCP Evaluation")
    print("========================")

    for case in cases:
        diagnosis = diagnose_problem(case["problem_statement"])
        expected_concerns = set(case["expected_concern_types"])
        actual_concerns = set(diagnosis.concern_types)
        expected_playbooks = set(case["expected_playbook_ids"])
        actual_playbooks = {playbook.id for playbook in diagnosis.matched_playbooks}

        product_ok = diagnosis.product_area == case["expected_product_area"]
        concern_ok = expected_concerns.issubset(actual_concerns)
        playbook_ok = bool(expected_playbooks & actual_playbooks)

        product_hits += int(product_ok)
        concern_hits += int(concern_ok)
        playbook_hits += int(playbook_ok)

        status = "PASS" if product_ok and concern_ok and playbook_ok else "CHECK"
        print(f"\n[{status}] {case['id']}")
        print(f"  Expected area: {case['expected_product_area']}")
        print(f"  Actual area:   {diagnosis.product_area} ({diagnosis.product_confidence:.2f})")
        print(f"  Expected concern types: {sorted(expected_concerns)}")
        print(f"  Actual concern types:   {sorted(actual_concerns)}")
        print(f"  Expected playbooks: {sorted(expected_playbooks)}")
        print(f"  Actual playbooks:   {sorted(actual_playbooks)}")

    print("\nSummary")
    print("-------")
    print(f"Product-area accuracy: {product_hits}/{total}")
    print(f"Concern-type coverage: {concern_hits}/{total}")
    print(f"Playbook-hit rate:     {playbook_hits}/{total}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
