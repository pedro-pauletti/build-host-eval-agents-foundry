"""Shared helpers for **Microsoft Foundry cloud evaluations** across the three Zava demos.

Everything here talks to the *evaluation service in your Foundry project*, so every run
shows up in the **Foundry portal → Evaluations** tab (and is readable from the web app's
Evaluations view). Nothing is scored locally.

The three evaluator flavours the demos use:

* **Built-in** — Microsoft-curated evaluators (``builtin.relevance``, ``builtin.task_adherence``,
  ``builtin.tool_call_accuracy``, ``builtin.violence`` …). Referenced by name.
* **Custom** — your own evaluators registered in the project's evaluator catalog:
  *code-based* (a sandboxed Python ``grade()`` function) and *prompt-based* (an LLM judge prompt).
* **Rubric** — weighted, LLM-judged criteria; either auto-generated from a Foundry agent's
  context or hand-authored.

Used by ``agents/*/run_eval.py`` and mirrored inline in the notebooks.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO = Path(__file__).resolve().parent.parent

TERMINAL_RUN_STATES = {"completed", "failed", "canceled", "cancelled", "error"}


# ---------------------------------------------------------------------------
# environment + clients
# ---------------------------------------------------------------------------
def load_env() -> None:
    """Load the repo-root ``.env`` without overriding real environment variables."""
    from dotenv import load_dotenv

    load_dotenv(REPO / ".env", override=False)


def judge_model() -> str:
    """Deployment used as the LLM judge for AI-assisted evaluators."""
    return os.getenv("EVAL_JUDGE_MODEL") or os.getenv("FOUNDRY_MODEL_DEPLOYMENT_NAME", "gpt-4.1")


def clients() -> tuple[Any, Any]:
    """Return ``(project_client, openai_client)`` authenticated with Microsoft Entra."""
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    load_env()
    endpoint = os.environ.get("AZURE_AI_PROJECT_ENDPOINT") or os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    project = AIProjectClient(
        endpoint=endpoint,
        credential=DefaultAzureCredential(exclude_interactive_browser_credential=True),
    )
    return project, project.get_openai_client()


# ---------------------------------------------------------------------------
# datasets
# ---------------------------------------------------------------------------
def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: str | Path, rows: Iterable[dict[str, Any]]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8"
    )
    return target


def upload_dataset(project: Any, name: str, path: str | Path, *, version: str = "1") -> str:
    """Upload a JSONL file as a **versioned dataset** in the project; return its id.

    Dataset versions are immutable, so an existing version is bumped until the upload
    succeeds — that keeps re-runs idempotent from the caller's point of view.
    """
    attempt = int(version)
    last_error: Exception | None = None
    for _ in range(60):
        try:
            dataset = project.datasets.upload_file(name=name, version=str(attempt), file_path=str(path))
            print(f"[dataset] {name}:{attempt} -> {dataset.id}")
            return dataset.id
        except Exception as exc:  # noqa: BLE001 - version conflict / transient
            last_error = exc
            attempt += 1
    raise RuntimeError(f"Could not upload dataset {name}: {last_error}")


# ---------------------------------------------------------------------------
# custom evaluators (code-based / prompt-based) + rubric evaluators
# ---------------------------------------------------------------------------
def register_code_evaluator(
    project: Any,
    *,
    name: str,
    display_name: str,
    description: str,
    code_text: str,
    item_properties: dict[str, Any],
    categories: Sequence[str] | None = None,
) -> Any:
    """Register a **code-based** custom evaluator (sandboxed Python ``grade()``).

    ``grade(sample, item)`` must return a float in ``[0.0, 1.0]``. The sandbox has no network
    access, a 2-minute budget per call, and ships numpy/pandas/rapidfuzz/etc.
    """
    from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

    evaluator = project.beta.evaluators.create_version(
        name=name,
        evaluator_version={
            "name": name,
            "categories": list(categories or [EvaluatorCategory.QUALITY]),
            "display_name": display_name,
            "description": description,
            "definition": {
                "type": EvaluatorDefinitionType.CODE,
                "code_text": code_text,
                "init_parameters": {
                    "type": "object",
                    "properties": {
                        "deployment_name": {"type": "string"},
                        "pass_threshold": {"type": "number"},
                    },
                    "required": ["deployment_name", "pass_threshold"],
                },
                "metrics": {
                    "result": {
                        "type": "continuous",
                        "desirable_direction": "increase",
                        "min_value": 0.0,
                        "max_value": 1.0,
                    }
                },
                "data_schema": {
                    "type": "object",
                    "required": ["item"],
                    "properties": {"item": {"type": "object", "properties": item_properties}},
                },
            },
        },
    )
    print(f"[evaluator/code] {evaluator.name} v{getattr(evaluator, 'version', '?')}")
    return evaluator


def register_prompt_evaluator(
    project: Any,
    *,
    name: str,
    display_name: str,
    description: str,
    prompt_text: str,
    item_properties: dict[str, Any],
    min_value: int = 1,
    max_value: int = 5,
    categories: Sequence[str] | None = None,
) -> Any:
    """Register a **prompt-based** custom evaluator (LLM judge with an ordinal 1–5 scale).

    The judge prompt must return ``{"result": <int>, "reason": "<why>"}``.
    """
    from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

    evaluator = project.beta.evaluators.create_version(
        name=name,
        evaluator_version={
            "name": name,
            "categories": list(categories or [EvaluatorCategory.QUALITY]),
            "display_name": display_name,
            "description": description,
            "definition": {
                "type": EvaluatorDefinitionType.PROMPT,
                "prompt_text": prompt_text,
                "init_parameters": {
                    "type": "object",
                    "properties": {
                        "deployment_name": {"type": "string"},
                        "threshold": {"type": "number"},
                    },
                    "required": ["deployment_name", "threshold"],
                },
                "data_schema": {
                    "type": "object",
                    "properties": item_properties,
                    "required": list(item_properties.keys()),
                },
                "metrics": {
                    "custom_prompt": {
                        "type": "ordinal",
                        "desirable_direction": "increase",
                        "min_value": min_value,
                        "max_value": max_value,
                    }
                },
            },
        },
    )
    print(f"[evaluator/prompt] {evaluator.name} v{getattr(evaluator, 'version', '?')}")
    return evaluator


def register_rubric_evaluator(
    project: Any,
    *,
    name: str,
    display_name: str,
    description: str,
    dimensions: Sequence[dict[str, Any]],
    pass_threshold: float = 0.5,
) -> Any:
    """Register a hand-authored **rubric evaluator** (weighted, LLM-judged dimensions)."""
    from azure.ai.projects.models import EvaluatorCategory, EvaluatorDefinitionType

    evaluator = project.beta.evaluators.create_version(
        name=name,
        evaluator_version={
            "name": name,
            "categories": [EvaluatorCategory.AGENTS],
            "display_name": display_name,
            "description": description,
            "definition": {
                "type": EvaluatorDefinitionType.RUBRIC,
                "dimensions": list(dimensions),
                "pass_threshold": pass_threshold,
            },
        },
    )
    print(f"[evaluator/rubric] {evaluator.name} v{getattr(evaluator, 'version', '?')}")
    return evaluator


def generate_rubric_from_agent(
    project: Any,
    *,
    agent_name: str,
    evaluator_name: str,
    display_name: str,
    model: str | None = None,
    timeout_seconds: int = 600,
) -> Any | None:
    """Auto-generate a rubric evaluator from a Foundry agent's own context.

    The service reads the agent's instructions/description and proposes weighted dimensions.
    Returns ``None`` when generation is unavailable (preview/region), so callers can fall
    back to :func:`register_rubric_evaluator`.
    """
    from azure.ai.projects.models import (
        AgentEvaluatorGenerationJobSource,
        EvaluatorGenerationInputs,
        EvaluatorGenerationJob,
        JobStatus,
    )

    terminal = {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED}
    try:
        job = project.beta.evaluators.create_generation_job(
            job=EvaluatorGenerationJob(
                inputs=EvaluatorGenerationInputs(
                    model=model or judge_model(),
                    evaluator_name=evaluator_name,
                    evaluator_display_name=display_name,
                    sources=[AgentEvaluatorGenerationJobSource(agent_name=agent_name)],
                ),
            ),
        )
        deadline = time.time() + timeout_seconds
        while job.status not in terminal and time.time() < deadline:
            time.sleep(10)
            job = project.beta.evaluators.get_generation_job(job.id)
        if job.status != JobStatus.SUCCEEDED or job.result is None:
            print(f"[evaluator/rubric] generation did not succeed (status={job.status})")
            return None
        rubric = job.result
        print(f"[evaluator/rubric] generated {rubric.name} v{getattr(rubric, 'version', '?')}")
        for dim in rubric.definition.dimensions:
            print(f"    - {dim.id} (weight {dim.weight}): {dim.description[:90]}")
        return rubric
    except Exception as exc:  # noqa: BLE001 - preview feature, regional availability
        print(f"[evaluator/rubric] auto-generation unavailable: {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# testing criteria helpers
# ---------------------------------------------------------------------------
def builtin_criterion(
    name: str,
    evaluator: str,
    data_mapping: dict[str, str],
    *,
    model: str | None = None,
    init: dict[str, Any] | None = None,
) -> Any:
    """A testing criterion that references a **built-in** evaluator."""
    from azure.ai.projects.models import TestingCriterionAzureAIEvaluator

    parameters = dict(init or {})
    if model is not False and "deployment_name" not in parameters:
        parameters.setdefault("deployment_name", model or judge_model())
    return TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator",
        name=name,
        evaluator_name=evaluator,
        initialization_parameters=parameters,
        data_mapping=data_mapping,
    )


def custom_criterion(
    name: str,
    evaluator: str,
    data_mapping: dict[str, str],
    *,
    init: dict[str, Any],
) -> Any:
    """A testing criterion that references a **custom** (code/prompt) or **rubric** evaluator."""
    from azure.ai.projects.models import TestingCriterionAzureAIEvaluator

    return TestingCriterionAzureAIEvaluator(
        type="azure_ai_evaluator",
        name=name,
        evaluator_name=evaluator,
        initialization_parameters=init,
        data_mapping=data_mapping,
    )


# ---------------------------------------------------------------------------
# running + reading results
# ---------------------------------------------------------------------------
def wait_for_run(openai_client: Any, *, eval_id: str, run_id: str, timeout_seconds: int = 2400) -> Any:
    """Poll an evaluation run until it reaches a terminal state."""
    deadline = time.time() + timeout_seconds
    last = ""
    while time.time() < deadline:
        run = openai_client.evals.runs.retrieve(run_id=run_id, eval_id=eval_id)
        status = str(run.status)
        if status != last:
            print(f"[run] {status}")
            last = status
        if status in TERMINAL_RUN_STATES:
            return run
        time.sleep(10)
    raise TimeoutError(f"Evaluation run {run_id} did not finish within {timeout_seconds}s")


def _as_dict(value: Any) -> Any:
    """Best-effort conversion of SDK models to plain JSON-serialisable structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _as_dict(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_dict(v) for v in value]
    for method in ("model_dump", "to_dict", "as_dict"):
        fn = getattr(value, method, None)
        if callable(fn):
            try:
                return _as_dict(fn())
            except Exception:  # noqa: BLE001
                continue
    return str(value)


def summarize_run(run: Any) -> dict[str, Any]:
    """Flatten a finished run into the summary shape the web app renders."""
    counts = _as_dict(getattr(run, "result_counts", None)) or {}
    criteria = []
    for entry in _as_dict(getattr(run, "per_testing_criteria_results", None)) or []:
        passed = int(entry.get("passed", 0) or 0)
        failed = int(entry.get("failed", 0) or 0)
        errored = int(entry.get("errored", 0) or 0)
        total = passed + failed + errored
        criteria.append(
            {
                "name": entry.get("testing_criteria") or entry.get("name") or "criterion",
                "passed": passed,
                "failed": failed,
                "errored": errored,
                "pass_rate": round(passed / total, 3) if total else None,
            }
        )
    return {
        "run_id": getattr(run, "id", None),
        "eval_id": getattr(run, "eval_id", None),
        "name": getattr(run, "name", None),
        "status": str(getattr(run, "status", "")),
        "created_at": getattr(run, "created_at", None),
        "report_url": getattr(run, "report_url", None),
        "result_counts": counts,
        "criteria": criteria,
    }


def print_summary(run: Any) -> dict[str, Any]:
    """Print a compact console report and return the summary dict."""
    summary = summarize_run(run)
    print("\n" + "=" * 72)
    print(f"RUN {summary['name']}  ({summary['status']})")
    counts = summary["result_counts"] or {}
    print(
        f"  items: total={counts.get('total', '?')} passed={counts.get('passed', '?')} "
        f"failed={counts.get('failed', '?')} errored={counts.get('errored', 0)}"
    )
    for criterion in summary["criteria"]:
        rate = criterion["pass_rate"]
        rate_text = f"{rate:.0%}" if rate is not None else "  n/a"
        print(
            f"  {criterion['name']:<34s} pass {criterion['passed']:>3d}  fail {criterion['failed']:>3d}"
            f"  err {criterion['errored']:>3d}   {rate_text}"
        )
    print(f"  report: {summary['report_url']}")
    print("=" * 72)
    return summary


def collect_output_items(openai_client: Any, *, eval_id: str, run_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Return per-row results (query, response, evaluator scores + reasons)."""
    rows: list[dict[str, Any]] = []
    for index, item in enumerate(openai_client.evals.runs.output_items.list(run_id=run_id, eval_id=eval_id)):
        if index >= limit:
            break
        source = _as_dict(getattr(item, "datasource_item", None)) or {}
        results = []
        for result in _as_dict(getattr(item, "results", None)) or []:
            results.append(
                {
                    "name": result.get("name"),
                    "score": result.get("score"),
                    "label": result.get("label"),
                    "passed": result.get("passed"),
                    "threshold": result.get("threshold"),
                    "reason": (result.get("reason") or "")[:600],
                }
            )
        rows.append(
            {
                "id": getattr(item, "id", None),
                "status": str(getattr(item, "status", "")),
                "query": source.get("query"),
                "response": source.get("sample.output_text") or source.get("response"),
                "results": results,
            }
        )
    return rows


def save_results(path: str | Path, payload: dict[str, Any]) -> Path:
    """Persist a run summary + rows next to the agent (handy for CI artifacts)."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[results] wrote {target}")
    return target
