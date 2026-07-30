"""**Evaluations** view for the web app — reads live results from the Foundry project.

Every evaluation the demos run (``agents/*/run_eval.py`` and the notebooks) is created in the
Foundry project through the evaluation service, so nothing is stored locally: this module simply
reads the same objects the **Foundry portal → Evaluations** tab shows.

Three endpoints back the *Evaluations* tab:

* ``GET /api/evals`` — the evaluations in the project, each with its latest run summary.
* ``GET /api/evals/{eval_id}/runs`` — every run of one evaluation (pass/fail per criterion).
* ``GET /api/evals/{eval_id}/runs/{run_id}/items`` — per-row detail: the query, the agent's
  answer, and each evaluator's score, label and reason.

Results are cached for a few seconds because the tab polls while a run is in progress.
"""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

PROJECT_ENDPOINT_VARS = ("AZURE_AI_PROJECT_ENDPOINT", "FOUNDRY_PROJECT_ENDPOINT")
CACHE_SECONDS = float(os.getenv("EVALS_CACHE_SECONDS", "8"))
MAX_EVALS = int(os.getenv("EVALS_MAX", "25"))
MAX_RUNS = int(os.getenv("EVALS_MAX_RUNS", "10"))
MAX_ITEMS = int(os.getenv("EVALS_MAX_ITEMS", "60"))

# Which agent each demo evaluation belongs to, so the UI can group and badge them.
AGENT_BY_KEYWORD = (
    ("inventory", "inventory"),
    ("delivery", "delivery"),
    ("incident", "orchestration"),
    ("orchestration", "orchestration"),
)

_credential: Any = None
_client: Any = None
_cache: dict[str, tuple[float, Any]] = {}


def project_endpoint() -> str:
    """Read the endpoint lazily: this module is imported before ``load_dotenv()`` runs."""
    for name in PROJECT_ENDPOINT_VARS:
        value = os.getenv(name, "")
        if value:
            return value
    return ""


def _openai_client() -> Any:
    global _credential, _client
    if _client is None:
        _credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        project = AIProjectClient(endpoint=project_endpoint(), credential=_credential)
        _client = project.get_openai_client()
    return _client


def _cached(key: str, producer: Any) -> Any:
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = producer()
    _cache[key] = (now + CACHE_SECONDS, value)
    return value


def _plain(value: Any) -> Any:
    """Convert SDK models into plain JSON-serialisable structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    for method in ("model_dump", "to_dict", "as_dict"):
        fn = getattr(value, method, None)
        if callable(fn):
            try:
                return _plain(fn())
            except Exception:  # noqa: BLE001
                continue
    return str(value)


def _agent_for(name: str) -> str:
    lowered = (name or "").lower()
    for keyword, agent in AGENT_BY_KEYWORD:
        if keyword in lowered:
            return agent
    return "other"


def _criteria_kind(criterion_name: str, evaluator_name: str) -> str:
    """Label a criterion as built-in / custom / rubric for the legend in the UI."""
    evaluator = (evaluator_name or "").lower()
    if evaluator.startswith("builtin."):
        return "builtin"
    if "rubric" in evaluator or "rubric" in (criterion_name or "").lower():
        return "rubric"
    return "custom"


def _run_summary(run: Any) -> dict[str, Any]:
    data = _plain(run) or {}
    counts = data.get("result_counts") or {}
    criteria = []
    for entry in data.get("per_testing_criteria_results") or []:
        passed = int(entry.get("passed") or 0)
        failed = int(entry.get("failed") or 0)
        errored = int(entry.get("errored") or 0)
        total = passed + failed + errored
        criteria.append(
            {
                "name": entry.get("testing_criteria") or entry.get("name") or "criterion",
                "passed": passed,
                "failed": failed,
                "errored": errored,
                "pass_rate": round(passed / total, 4) if total else None,
            }
        )
    total = int(counts.get("total") or 0)
    passed = int(counts.get("passed") or 0)
    return {
        "id": data.get("id"),
        "eval_id": data.get("eval_id"),
        "name": data.get("name"),
        "status": data.get("status"),
        "created_at": data.get("created_at"),
        "report_url": data.get("report_url"),
        "counts": {
            "total": total,
            "passed": passed,
            "failed": int(counts.get("failed") or 0),
            "errored": int(counts.get("errored") or 0),
        },
        "pass_rate": round(passed / total, 4) if total else None,
        "criteria": criteria,
    }


def _list_evaluations() -> list[dict[str, Any]]:
    client = _openai_client()
    evaluations: list[dict[str, Any]] = []
    for index, evaluation in enumerate(client.evals.list()):
        if index >= MAX_EVALS:
            break
        data = _plain(evaluation) or {}
        criteria = []
        for criterion in data.get("testing_criteria") or []:
            criteria.append(
                {
                    "name": criterion.get("name"),
                    "evaluator": criterion.get("evaluator_name"),
                    "kind": _criteria_kind(criterion.get("name", ""), criterion.get("evaluator_name", "")),
                }
            )
        evaluations.append(
            {
                "id": data.get("id"),
                "name": data.get("name"),
                "created_at": data.get("created_at"),
                "agent": _agent_for(data.get("name", "")),
                "criteria": criteria,
                "latest_run": None,
            }
        )
    # Attach the most recent run of each evaluation so the list is useful at a glance.
    for evaluation in evaluations:
        try:
            runs = list(client.evals.runs.list(eval_id=evaluation["id"], limit=1))
        except Exception:  # noqa: BLE001
            runs = []
        if runs:
            evaluation["latest_run"] = _run_summary(runs[0])
    return evaluations


def _list_runs(eval_id: str) -> list[dict[str, Any]]:
    client = _openai_client()
    runs = []
    for index, run in enumerate(client.evals.runs.list(eval_id=eval_id)):
        if index >= MAX_RUNS:
            break
        runs.append(_run_summary(run))
    return runs


def _list_items(eval_id: str, run_id: str) -> list[dict[str, Any]]:
    client = _openai_client()
    rows = []
    for index, item in enumerate(client.evals.runs.output_items.list(run_id=run_id, eval_id=eval_id)):
        if index >= MAX_ITEMS:
            break
        data = _plain(item) or {}
        source = data.get("datasource_item") or {}
        results = []
        for result in data.get("results") or []:
            results.append(
                {
                    "name": result.get("name"),
                    "score": result.get("score"),
                    "label": result.get("label"),
                    "passed": result.get("passed"),
                    "threshold": result.get("threshold"),
                    "reason": (result.get("reason") or "")[:700],
                }
            )
        rows.append(
            {
                "id": data.get("id"),
                "status": data.get("status"),
                "query": source.get("query") or source.get("incident_id") or "",
                "response": (source.get("sample.output_text") or source.get("response") or "")[:4000],
                "results": results,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# async wrappers used by the FastAPI routes
# ---------------------------------------------------------------------------
async def list_evaluations() -> dict[str, Any]:
    if not project_endpoint():
        return {"configured": False, "evaluations": [], "error": "AZURE_AI_PROJECT_ENDPOINT is not set"}
    try:
        evaluations = await asyncio.to_thread(lambda: _cached("evals", _list_evaluations))
    except Exception as exc:  # noqa: BLE001 - surface the error in the panel
        return {"configured": True, "evaluations": [], "error": str(exc)}
    return {"configured": True, "evaluations": evaluations}


async def list_runs(eval_id: str) -> dict[str, Any]:
    try:
        runs = await asyncio.to_thread(lambda: _cached(f"runs:{eval_id}", lambda: _list_runs(eval_id)))
    except Exception as exc:  # noqa: BLE001
        return {"eval_id": eval_id, "runs": [], "error": str(exc)}
    return {"eval_id": eval_id, "runs": runs}


async def list_items(eval_id: str, run_id: str) -> dict[str, Any]:
    try:
        items = await asyncio.to_thread(
            lambda: _cached(f"items:{run_id}", lambda: _list_items(eval_id, run_id))
        )
    except Exception as exc:  # noqa: BLE001
        return {"eval_id": eval_id, "run_id": run_id, "items": [], "error": str(exc)}
    return {"eval_id": eval_id, "run_id": run_id, "items": items}
