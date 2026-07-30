#!/usr/bin/env python3
"""Cloud evaluation for the Zava **incident-response orchestration** (multi-framework).

The pipeline's output is *structured*: Triage (LangGraph) emits ``{"triage": ...}``, Code Fix
(GitHub Copilot SDK) emits ``{"code_fix": ...}`` and Compliance (Foundry prompt agent) emits
``{"compliance": ...}``. That makes **code-based custom evaluators** the right primary measure —
they check the pipeline's decisions against ground truth deterministically, with no LLM judge:

* ``zava_triage_match`` — severity / category / component versus the expected classification.
* ``zava_fix_verified`` — the fix really changed a file *and* left the test suite green.
* ``zava_compliance_decision`` — the policy verdict matches the expected one (and blocks red tests).

Those are paired with ``builtin.task_adherence`` + ``builtin.coherence`` for the narrative and a
weighted **rubric evaluator** for end-to-end incident-response quality.

This is a **dataset evaluation**: rows are completed pipeline transcripts, so the run is fast and
repeatable. Use ``--from-run`` to execute the live orchestration once and score its real output.

Run (repo root, venv):
    .venv\\Scripts\\python.exe agents/incident-orchestration/run_eval.py
    .venv\\Scripts\\python.exe agents/incident-orchestration/run_eval.py --from-run
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from scripts.foundry_eval import (  # noqa: E402
    builtin_criterion,
    clients,
    collect_output_items,
    custom_criterion,
    judge_model,
    print_summary,
    read_jsonl,
    register_code_evaluator,
    register_rubric_evaluator,
    save_results,
    upload_dataset,
    wait_for_run,
    write_jsonl,
)

DATASET = HERE / "evals" / "incident_eval.jsonl"
RESULTS = HERE / ".foundry" / "results" / "eval_result.json"

# Every code-based evaluator needs the same tiny JSON extractor, so it is prepended to each one
# (the sandbox has no shared imports between evaluators).
JSON_HELPER = '''
import json
import re


def _blocks(text: str) -> dict:
    """Collect every fenced JSON object in the transcript into one merged dict."""
    merged = {}
    for match in re.findall(r"```json\\s*(\\{.*?\\})\\s*```", text or "", re.DOTALL):
        try:
            merged.update(json.loads(match))
        except Exception:
            continue
    return merged


def _text(item: dict) -> str:
    return item.get("sample", {}).get("output_text") or item.get("response") or ""
'''

TRIAGE_MATCH_CODE = JSON_HELPER + '''

def grade(sample: dict, item: dict) -> float:
    """Fraction of triage fields (severity, category, component) that match ground truth."""
    try:
        triage = _blocks(_text(item)).get("triage") or {}
        if not triage:
            return 0.0
        checks = [
            (str(triage.get("severity", "")).lower(), str(item.get("expected_severity", "")).lower()),
            (str(triage.get("category", "")).lower(), str(item.get("expected_category", "")).lower()),
            (str(triage.get("component", "")).lower(), str(item.get("expected_component", "")).lower()),
        ]
        checks = [(actual, expected) for actual, expected in checks if expected]
        if not checks:
            return 0.0
        return round(sum(1 for actual, expected in checks if actual == expected) / len(checks), 4)
    except Exception:
        return 0.0
'''

FIX_VERIFIED_CODE = JSON_HELPER + '''

def grade(sample: dict, item: dict) -> float:
    """1.0 only when the Code Fix stage changed a file AND left the test suite green."""
    try:
        code_fix = _blocks(_text(item)).get("code_fix") or {}
        if not code_fix:
            return 0.0
        changed = bool(code_fix.get("files_changed"))
        passed = bool(code_fix.get("test_passed"))
        has_diff = bool(str(code_fix.get("diff", "")).strip())
        return 1.0 if (changed and passed and has_diff) else 0.0
    except Exception:
        return 0.0
'''

COMPLIANCE_DECISION_CODE = JSON_HELPER + '''

def grade(sample: dict, item: dict) -> float:
    """Does the policy verdict match the expected one - and does it fail closed on red tests?"""
    try:
        blocks = _blocks(_text(item))
        compliance = blocks.get("compliance") or {}
        code_fix = blocks.get("code_fix") or {}
        if not compliance:
            return 0.0
        decision = str(compliance.get("decision", "")).strip().lower().replace("_", "-")
        expected = str(item.get("expected_decision", "")).strip().lower().replace("_", "-")
        # Approving a change whose tests are red is always wrong, whatever the dataset says.
        if decision == "approved" and code_fix and not code_fix.get("test_passed"):
            return 0.0
        # A needs-changes verdict must say what has to change.
        if decision == "needs-changes" and not compliance.get("required_changes"):
            return 0.5
        if not expected:
            return 1.0 if decision in ("approved", "needs-changes") else 0.0
        return 1.0 if decision == expected else 0.0
    except Exception:
        return 0.0
'''

INCIDENT_RUBRIC_DIMENSIONS = [
    {
        "id": "triage_correctness",
        "description": (
            "Classifies severity, category and the failing component correctly from the incident "
            "text alone, and routes the incident to the stage that can actually fix it."
        ),
        "weight": 9,
    },
    {
        "id": "fix_quality",
        "description": (
            "The proposed change is minimal, targets the real defect rather than the symptom, "
            "preserves the documented invariants, and is backed by a green test run."
        ),
        "weight": 8,
    },
    {
        "id": "policy_enforcement",
        "description": (
            "Applies the Zava engineering policy honestly: never approves a change with failing "
            "tests or a removed validation guard, and lists concrete required changes when blocking."
        ),
        "weight": 7,
    },
    {
        "id": "handoff_integrity",
        "description": (
            "Each stage carries the previous stage's structured result forward, so triage, fix and "
            "compliance describe the same incident and the same change."
        ),
        "weight": 5,
    },
    {
        "id": "operator_summary",
        "description": (
            "The final message tells an on-call engineer what broke, what changed, whether tests "
            "pass and whether it may ship - without needing to read the JSON."
        ),
        "weight": 4,
    },
    {
        "id": "general_quality",
        "description": "Other important quality factors not covered by the listed criteria.",
        "weight": 5,
        "always_applicable": True,
    },
]


def _row_from_live_run() -> dict:
    """Execute the real orchestration once and turn its output into an evaluation row."""
    sys.path.insert(0, str(HERE))
    sys.path.insert(0, str(HERE / "src"))
    from orchestration import incident_text_from_seed, run_incident  # type: ignore

    incident = incident_text_from_seed()
    result = asyncio.run(run_incident(incident))
    payload = result.to_dict()
    blocks = "\n\n".join(
        "```json\n" + __import__("json").dumps({key: payload[key]}, ensure_ascii=False, indent=2) + "\n```"
        for key in ("triage", "code_fix", "compliance")
        if payload.get(key)
    )
    return {
        "incident_id": (payload.get("triage") or {}).get("incident_id", "live-run"),
        "query": incident,
        "response": blocks + "\n\n" + (payload.get("final_text") or ""),
        "expected_severity": "high",
        "expected_category": "bug",
        "expected_component": "reorder.py",
        "expected_decision": "approved",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the incident-orchestration cloud evaluation.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument(
        "--from-run",
        action="store_true",
        help="run the live orchestration once and append its real output as an extra row",
    )
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()

    project, openai_client = clients()
    model = judge_model()
    print(f"judge={model}")

    rows = read_jsonl(Path(args.dataset))
    if args.limit:
        rows = rows[: args.limit]
    if args.from_run:
        print("running the live orchestration (this takes 1-2 minutes)...")
        rows.append(_row_from_live_run())
    dataset_path = HERE / ".foundry" / "datasets" / "incident_eval_prepared.jsonl"
    write_jsonl(dataset_path, rows)
    print(f"dataset rows: {len(rows)}")
    dataset_id = upload_dataset(project, "zava-incident-eval", dataset_path)

    item_properties = {
        "query": {"type": "string"},
        "response": {"type": "string"},
        "expected_severity": {"type": "string"},
        "expected_category": {"type": "string"},
        "expected_component": {"type": "string"},
        "expected_decision": {"type": "string"},
    }
    register_code_evaluator(
        project,
        name="zava_triage_match",
        display_name="Zava Triage Match",
        description="Do severity, category and component match the expected classification?",
        code_text=TRIAGE_MATCH_CODE,
        item_properties=item_properties,
    )
    register_code_evaluator(
        project,
        name="zava_fix_verified",
        display_name="Zava Fix Verified",
        description="Did the Code Fix stage change a file and leave the tests green?",
        code_text=FIX_VERIFIED_CODE,
        item_properties=item_properties,
    )
    register_code_evaluator(
        project,
        name="zava_compliance_decision",
        display_name="Zava Compliance Decision",
        description="Does the policy verdict match ground truth and fail closed on red tests?",
        code_text=COMPLIANCE_DECISION_CODE,
        item_properties=item_properties,
    )
    rubric = register_rubric_evaluator(
        project,
        name="zava_incident_rubric",
        display_name="Zava Incident Response Quality",
        description="Weighted quality criteria for the Zava multi-framework incident pipeline.",
        dimensions=INCIDENT_RUBRIC_DIMENSIONS,
        pass_threshold=0.6,
    )

    testing_criteria = [
        custom_criterion(
            "triage_match", "zava_triage_match", {},
            init={"deployment_name": model, "pass_threshold": 0.99},
        ),
        custom_criterion(
            "fix_verified", "zava_fix_verified", {},
            init={"deployment_name": model, "pass_threshold": 1.0},
        ),
        custom_criterion(
            "compliance_decision", "zava_compliance_decision", {},
            init={"deployment_name": model, "pass_threshold": 0.99},
        ),
        builtin_criterion(
            "task_adherence", "builtin.task_adherence",
            {"query": "{{item.query}}", "response": "{{item.response}}"},
        ),
        builtin_criterion(
            "coherence", "builtin.coherence",
            {"query": "{{item.query}}", "response": "{{item.response}}"},
        ),
        custom_criterion(
            "incident_rubric", rubric.name,
            {"query": "{{item.query}}", "response": "{{item.response}}"},
            init={"deployment_name": model},
        ),
    ]

    from openai.types.eval_create_params import DataSourceConfigCustom
    from openai.types.evals.create_eval_jsonl_run_data_source_param import (
        CreateEvalJSONLRunDataSourceParam,
        SourceFileID,
    )

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": item_properties,
            "required": ["query", "response"],
        },
    )

    evaluation = openai_client.evals.create(
        name="Zava incident orchestration quality",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"[eval] {evaluation.id}")

    run = openai_client.evals.runs.create(
        eval_id=evaluation.id,
        name="incident-pipeline-outcomes",
        data_source=CreateEvalJSONLRunDataSourceParam(
            type="jsonl",
            source=SourceFileID(type="file_id", id=dataset_id),
        ),
    )
    print(f"[run] {run.id} started")

    run = wait_for_run(openai_client, eval_id=evaluation.id, run_id=run.id, timeout_seconds=args.timeout)
    summary = print_summary(run)
    items = collect_output_items(openai_client, eval_id=evaluation.id, run_id=run.id)
    save_results(RESULTS, {"summary": summary, "items": items})


if __name__ == "__main__":
    main()
