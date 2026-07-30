#!/usr/bin/env python3
"""Cloud evaluation for the Zava **InventoryAgent** (Foundry prompt agent).

Demonstrates all **three evaluator flavours** of Microsoft Foundry in one run, scored by the
evaluation service so every result lands in **Foundry portal -> Evaluations** (and in the
web app's *Evaluations* tab):

1. **Built-in evaluators** — ``builtin.relevance``, ``builtin.intent_resolution``,
   ``builtin.task_adherence``, ``builtin.violence``.
2. **Custom evaluators** — ``zava_answer_grounding`` (code-based ``grade()``) and
   ``zava_ops_briefing`` (prompt-based LLM judge), both registered in the project's
   evaluator catalog.
3. **Rubric evaluator** — ``zava_inventory_rubric``, weighted dimensions judged by an LLM;
   auto-generated from the agent's own context when available, hand-authored otherwise.

The run uses an **agent target**: Foundry sends each dataset query to the live InventoryAgent,
captures the response (including MCP tool calls) and then scores it.

Run (repo root, venv):
    .venv\\Scripts\\python.exe agents/inventory-agent/run_eval.py
    .venv\\Scripts\\python.exe agents/inventory-agent/run_eval.py --limit 3 --no-rubric-generation
"""
from __future__ import annotations

import argparse
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
    register_prompt_evaluator,
    register_rubric_evaluator,
    save_results,
    upload_dataset,
    wait_for_run,
    write_jsonl,
)

AGENT_NAME = "InventoryAgent"
DATASET = HERE / "evals" / "inventory_eval.jsonl"
RESULTS = HERE / ".foundry" / "results" / "eval_result.json"

# --------------------------------------------------------------------------------------
# Custom evaluator #1 — CODE-BASED. A sandboxed `grade(sample, item) -> float in [0, 1]`.
# Deterministic fact-checking: how much of the ground truth actually shows up in the answer.
# --------------------------------------------------------------------------------------
ANSWER_GROUNDING_CODE = '''
def grade(sample: dict, item: dict) -> float:
    """Fraction of the required facts that appear in the agent's answer.

    `must_include` holds one entry per required fact; an entry may list interchangeable
    spellings separated by "|" (for example "distribution center|facilities").
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
# Custom evaluator #2 — PROMPT-BASED. An LLM judge scoring 1-5 with a reason.
# --------------------------------------------------------------------------------------
OPS_BRIEFING_PROMPT = """You grade answers written for Maya, a Zava inventory operations manager
who is standing on a warehouse floor. A great answer is a short operational briefing: it leads with
the number or status that matters, names the facility or SKU it refers to, and ends with the action
to take. A poor answer is a wall of prose, hedges without numbers, or buries the decision.

Rate the answer between one and five:

1 - Unusable: no numbers, no entities, or off-topic.
2 - Vague: mentions the topic but gives no actionable figures or entities.
3 - Acceptable: correct and readable, but padded or missing the next action.
4 - Good: concise, quantified, names SKUs/facilities, minor padding.
5 - Excellent: leads with the decisive number, names SKUs/facilities, states the next action, no filler.

Question:
{{query}}

Answer:
{{response}}

Output Format (JSON):
{
  "result": <integer from 1 to 5>,
  "reason": "<one sentence explaining the score>"
}
"""

# --------------------------------------------------------------------------------------
# Rubric evaluator — weighted dimensions, judged by an LLM (manual fallback).
# --------------------------------------------------------------------------------------
INVENTORY_RUBRIC_DIMENSIONS = [
    {
        "id": "source_routing",
        "description": (
            "Routes the question to the right source: live stock/alert questions call the Zava MCP "
            "toolbox, policy/how-to questions use the Foundry IQ knowledge base. Does not answer a "
            "live-inventory question from memory or a policy question from a tool."
        ),
        "weight": 9,
    },
    {
        "id": "numeric_fidelity",
        "description": (
            "Every quantity, SKU, facility code and status in the answer comes from a tool or "
            "knowledge-base result. No invented or rounded-away numbers."
        ),
        "weight": 8,
    },
    {
        "id": "operational_completeness",
        "description": (
            "Answers the whole question: on-hand versus reorder point, the facility breakdown when "
            "asked, and the affected SKUs rather than only a count."
        ),
        "weight": 5,
    },
    {
        "id": "citation_discipline",
        "description": (
            "Policy answers cite the Zava document they came from; tool answers make clear the data "
            "is live. No fabricated citations."
        ),
        "weight": 4,
    },
    {
        "id": "briefing_clarity",
        "description": (
            "Concise, scannable and written for an operations manager: leads with the decisive number "
            "and closes with the recommended action."
        ),
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
    parser = argparse.ArgumentParser(description="Run the InventoryAgent cloud evaluation.")
    parser.add_argument("--limit", type=int, default=0, help="evaluate only the first N rows")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument(
        "--no-rubric-generation",
        action="store_true",
        help="skip LLM rubric generation and register the hand-authored rubric directly",
    )
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()

    project, openai_client = clients()
    model = judge_model()
    print(f"agent={AGENT_NAME} judge={model}")

    # ---- dataset ---------------------------------------------------------------------
    dataset_path = Path(args.dataset)
    rows = read_jsonl(dataset_path)
    if args.limit:
        rows = rows[: args.limit]
        dataset_path = HERE / ".foundry" / "datasets" / "inventory_eval_subset.jsonl"
        write_jsonl(dataset_path, rows)
    print(f"dataset rows: {len(rows)}")
    dataset_id = upload_dataset(project, "zava-inventory-eval", dataset_path)

    # ---- custom evaluators (code + prompt) --------------------------------------------
    register_code_evaluator(
        project,
        name="zava_answer_grounding",
        display_name="Zava Answer Grounding",
        description="Fraction of the required Zava facts that appear in the answer (deterministic).",
        code_text=ANSWER_GROUNDING_CODE,
        item_properties={
            "query": {"type": "string"},
            "ground_truth": {"type": "string"},
            "must_include": {"type": "array"},
        },
    )
    register_prompt_evaluator(
        project,
        name="zava_ops_briefing",
        display_name="Zava Ops Briefing Quality",
        description="LLM judge: is the answer a concise, quantified operational briefing (1-5)?",
        prompt_text=OPS_BRIEFING_PROMPT,
        item_properties={"query": {"type": "string"}, "response": {"type": "string"}},
    )

    # ---- rubric evaluator --------------------------------------------------------------
    rubric_name = "zava_inventory_rubric"
    rubric = None
    if not args.no_rubric_generation:
        rubric = generate_rubric_from_agent(
            project,
            agent_name=AGENT_NAME,
            evaluator_name=rubric_name,
            display_name="Zava Inventory Quality (generated)",
            model=model,
        )
    if rubric is None:
        rubric = register_rubric_evaluator(
            project,
            name=rubric_name,
            display_name="Zava Inventory Quality",
            description="Weighted quality criteria for Zava inventory answers.",
            dimensions=INVENTORY_RUBRIC_DIMENSIONS,
            pass_threshold=0.6,
        )

    # ---- testing criteria: built-in + custom + rubric ----------------------------------
    testing_criteria = [
        # 1. built-in
        builtin_criterion(
            "relevance", "builtin.relevance",
            {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
        ),
        builtin_criterion(
            "intent_resolution", "builtin.intent_resolution",
            {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        ),
        builtin_criterion(
            "task_adherence", "builtin.task_adherence",
            {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
        ),
        builtin_criterion(
            "violence", "builtin.violence",
            {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
            model=False,
        ),
        # 2. custom — code-based (deterministic) and prompt-based (LLM judge)
        custom_criterion(
            "answer_grounding", "zava_answer_grounding", {},
            init={"deployment_name": model, "pass_threshold": 0.99},
        ),
        custom_criterion(
            "ops_briefing", "zava_ops_briefing",
            {"query": "{{item.query}}", "response": "{{sample.output_text}}"},
            init={"deployment_name": model, "threshold": 4},
        ),
        # 3. rubric
        custom_criterion(
            "inventory_rubric", rubric.name,
            {"query": "{{item.query}}", "response": "{{sample.output_items}}"},
            init={"deployment_name": model},
        ),
    ]

    # ---- create the evaluation + run it against the live agent --------------------------
    from openai.types.eval_create_params import DataSourceConfigCustom

    data_source_config = DataSourceConfigCustom(
        type="custom",
        item_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "ground_truth": {"type": "string"},
                "must_include": {"type": "array"},
                "expected_tool": {"type": "string"},
            },
            "required": ["query"],
        },
        include_sample_schema=True,
    )

    evaluation = openai_client.evals.create(
        name="Zava InventoryAgent quality",
        data_source_config=data_source_config,
        testing_criteria=testing_criteria,
    )
    print(f"[eval] {evaluation.id}")

    run = openai_client.evals.runs.create(
        eval_id=evaluation.id,
        name="inventory-builtin-custom-rubric",
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
