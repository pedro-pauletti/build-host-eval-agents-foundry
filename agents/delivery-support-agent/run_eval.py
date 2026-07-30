#!/usr/bin/env python3
"""Cloud evaluation for the Zava **DeliverySupport** agent (hosted MAF agent).

The evaluator set is chosen for what an order-tracking assistant can actually get wrong:

* **Built-in agent evaluators** — ``builtin.intent_resolution`` (did it understand the ask?),
  ``builtin.task_adherence`` (did it follow its rules?) and ``builtin.tool_call_success``
  (did the ``lookup_order`` / ``track_shipment`` calls actually succeed?).
* **Custom code-based evaluators** — ``zava_tracking_facts`` (are the real status, ETA and
  location in the answer?) and ``zava_no_fabrication`` (the hard one: when there is no order
  id, or the order does not exist, the agent must NOT invent a status, an ETA or a tracking
  number).
* **Rubric evaluator** — ``zava_delivery_rubric``, weighted delivery-support criteria judged
  by an LLM.

Every result is written to the Foundry project, so it shows up in the portal and in the web
app's *Evaluations* tab.

Run (repo root, venv):
    .venv\\Scripts\\python.exe agents/delivery-support-agent/run_eval.py
    .venv\\Scripts\\python.exe agents/delivery-support-agent/run_eval.py --limit 3
"""
from __future__ import annotations

import argparse
import os
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
    generate_rubric_from_agent,
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

AGENT_NAME = os.getenv("DELIVERY_AGENT_NAME", "DeliverySupport")
DATASET = HERE / "evals" / "delivery_eval.jsonl"
RESULTS = HERE / ".foundry" / "results" / "eval_result.json"

# --------------------------------------------------------------------------------------
# Custom evaluator #1 — CODE-BASED: are the real tracking facts in the answer?
# --------------------------------------------------------------------------------------
TRACKING_FACTS_CODE = '''
def grade(sample: dict, item: dict) -> float:
    """Fraction of the required tracking facts present in the answer.

    Each `must_include` entry is one fact; alternatives are separated by "|" so a date can be
    written as "Feb 17", "February 17" or "2026-02-17" and still count.
    """
    try:
        response = item.get("sample", {}).get("output_text") or item.get("response") or ""
        required = item.get("must_include") or []
        if isinstance(required, str):
            required = [required]
        if not required:
            return 1.0 if response.strip() else 0.0
        haystack = response.lower().replace(",", "")
        hits = 0
        for entry in required:
            options = [o.strip().lower().replace(",", "") for o in str(entry).split("|") if o.strip()]
            if any(o in haystack for o in options):
                hits += 1
        return round(hits / len(required), 4)
    except Exception:
        return 0.0
'''

# --------------------------------------------------------------------------------------
# Custom evaluator #2 — CODE-BASED: the anti-hallucination guard.
# --------------------------------------------------------------------------------------
NO_FABRICATION_CODE = '''
def grade(sample: dict, item: dict) -> float:
    """1.0 when the answer contains none of the forbidden phrases, 0.0 otherwise.

    Used for the rows where the agent has nothing to look up: an unknown order id, or a
    question with no order id at all. Inventing a status, an ETA or a tracking number there is
    the single worst failure mode for an order-tracking agent, so this is a hard gate.
    """
    try:
        response = (item.get("sample", {}).get("output_text") or item.get("response") or "").lower()
        forbidden = item.get("forbidden") or []
        if isinstance(forbidden, str):
            forbidden = [forbidden]
        if not forbidden:
            return 1.0
        leaked = [f for f in forbidden if str(f).strip().lower() in response]
        return 0.0 if leaked else 1.0
    except Exception:
        return 0.0
'''

# --------------------------------------------------------------------------------------
# Rubric evaluator — delivery-support quality (manual fallback).
# --------------------------------------------------------------------------------------
DELIVERY_RUBRIC_DIMENSIONS = [
    {
        "id": "lookup_before_answer",
        "description": (
            "Calls lookup_order or track_shipment before stating any status, and asks the customer "
            "for an order or tracking number when none was given. Never answers from assumption."
        ),
        "weight": 9,
    },
    {
        "id": "factual_tracking_detail",
        "description": (
            "Reports the exact status label, estimated delivery date, carrier and last known "
            "location returned by the tool, without altering or rounding them."
        ),
        "weight": 7,
    },
    {
        "id": "delay_explanation",
        "description": (
            "Explains weather, customs, volume and address exceptions in plain language and says "
            "clearly whether the customer needs to do anything."
        ),
        "weight": 6,
    },
    {
        "id": "no_fabrication",
        "description": (
            "Never invents an order, ETA, tracking number or delivery confirmation. For unknown "
            "orders it says so and asks the customer to check the number."
        ),
        "weight": 8,
    },
    {
        "id": "conversational_continuity",
        "description": (
            "Uses the conversation and remembered customer preferences for follow-ups such as "
            "'when will it arrive?' instead of asking for the order number again."
        ),
        "weight": 4,
    },
    {
        "id": "tone",
        "description": "Warm, brief and empathetic; acknowledges frustration without over-apologising.",
        "weight": 3,
    },
    {
        "id": "general_quality",
        "description": "Other important quality factors not covered by the listed criteria.",
        "weight": 5,
        "always_applicable": True,
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the DeliverySupport cloud evaluation.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--no-rubric-generation", action="store_true")
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()

    project, openai_client = clients()
    model = judge_model()
    print(f"agent={AGENT_NAME} judge={model}")

    dataset_path = Path(args.dataset)
    rows = read_jsonl(dataset_path)
    if args.limit:
        rows = rows[: args.limit]
        dataset_path = HERE / ".foundry" / "datasets" / "delivery_eval_subset.jsonl"
        write_jsonl(dataset_path, rows)
    print(f"dataset rows: {len(rows)}")
    dataset_id = upload_dataset(project, "zava-delivery-eval", dataset_path)

    register_code_evaluator(
        project,
        name="zava_tracking_facts",
        display_name="Zava Tracking Facts",
        description="Fraction of the real status/ETA/location facts present in the answer.",
        code_text=TRACKING_FACTS_CODE,
        item_properties={
            "query": {"type": "string"},
            "ground_truth": {"type": "string"},
            "must_include": {"type": "array"},
        },
    )
    register_code_evaluator(
        project,
        name="zava_no_fabrication",
        display_name="Zava No Fabrication",
        description="Hard gate: the answer must not invent a status, ETA or tracking number.",
        code_text=NO_FABRICATION_CODE,
        item_properties={"query": {"type": "string"}, "forbidden": {"type": "array"}},
    )

    rubric_name = "zava_delivery_rubric"
    rubric = None
    if not args.no_rubric_generation:
        rubric = generate_rubric_from_agent(
            project,
            agent_name=AGENT_NAME,
            evaluator_name=rubric_name,
            display_name="Zava Delivery Quality (generated)",
            model=model,
        )
    if rubric is None:
        rubric = register_rubric_evaluator(
            project,
            name=rubric_name,
            display_name="Zava Delivery Quality",
            description="Weighted quality criteria for Zava order-tracking answers.",
            dimensions=DELIVERY_RUBRIC_DIMENSIONS,
            pass_threshold=0.6,
        )

    testing_criteria = [
        builtin_criterion(
            "intent_resolution", "builtin.intent_resolution",
            {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        ),
        builtin_criterion(
            "task_adherence", "builtin.task_adherence",
            {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        ),
        builtin_criterion(
            "tool_call_success", "builtin.tool_call_success",
            {"response": "{{sample.output_items}}"},
        ),
        custom_criterion(
            "tracking_facts", "zava_tracking_facts", {},
            init={"deployment_name": model, "pass_threshold": 0.99},
        ),
        custom_criterion(
            "no_fabrication", "zava_no_fabrication", {},
            init={"deployment_name": model, "pass_threshold": 1.0},
        ),
        custom_criterion(
            "delivery_rubric", rubric.name,
            {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
            init={"deployment_name": model},
        ),
    ]

    from openai.types.eval_create_params import DataSourceConfigCustom

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ground_truth": {"type": "string"},
                "must_include": {"type": "array"},
                "forbidden": {"type": "array"},
                "expected_tool": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,
    )

    evaluation = openai_client.evals.create(
        name="Zava DeliverySupport quality",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"[eval] {evaluation.id}")

    run = openai_client.evals.runs.create(
        eval_id=evaluation.id,
        name="delivery-agent-target",
        data_source={
            "type": "azure_ai_target_completions",
            "source": {"type": "file_id", "id": dataset_id},
            "input_messages": {
                "type": "template",
                "template": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": {"type": "input_text", "text": "{{item.query}}"},
                    }
                ],
            },
            "target": {"type": "azure_ai_agent", "name": AGENT_NAME},
        },
    )
    print(f"[run] {run.id} started")

    run = wait_for_run(openai_client, eval_id=evaluation.id, run_id=run.id, timeout_seconds=args.timeout)
    summary = print_summary(run)
    items = collect_output_items(openai_client, eval_id=evaluation.id, run_id=run.id)
    save_results(RESULTS, {"summary": summary, "items": items})


if __name__ == "__main__":
    main()
