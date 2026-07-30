"""Code Fix Agent — built with the **GitHub Copilot SDK**.

This is the agent that runs a real *plan -> execute (shell/filesystem) -> assess ->
iterate* **harness loop**. It operates on an **isolated temporary sandbox** (a fresh copy
of ``sandbox_seed/``) — it never touches the real repository. Each tool the harness runs
is auto-approved and surfaced as a live ``harness_step`` event so the web app can animate
the loop in real time.

The harness is presented to the Microsoft Agent Framework through
:class:`CopilotCodeFixClient`, a ``BaseChatClient`` adapter (the common Agent Harness
surface). Internally it drives ``agent_framework_github_copilot.GitHubCopilotAgent``.
"""
from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_framework import Agent, BaseChatClient

if __package__:  # imported as `src.code_fix_copilot`
    from .harness import (
        CODE_FIX,
        EventBus,
        CodeFixResult,
        HarnessChatClient,
        HarnessTodos,
        build_todo_provider,
        extract_last_json,
        fenced_json,
        last_user_text,
    )
else:  # run directly as `python src/code_fix_copilot.py`
    from harness import (  # type: ignore[no-redef]
        CODE_FIX,
        EventBus,
        CodeFixResult,
        HarnessChatClient,
        HarnessTodos,
        build_todo_provider,
        extract_last_json,
        fenced_json,
        last_user_text,
    )

SANDBOX_SEED = Path(__file__).resolve().parent.parent / "sandbox_seed"
CODE_FIX_MODEL = os.getenv("CODE_FIX_MODEL", "claude-sonnet-4.5")
CODE_FIX_TIMEOUT = int(os.getenv("CODE_FIX_TIMEOUT", "300"))

FIX_PROMPT = """You are Zava's Code Fix agent working in an ISOLATED sandbox directory.

The file `reorder.py` implements the nightly reorder service. It has a defect: it produced
NEGATIVE reorder quantities for well-stocked SKUs and rounded genuine deficits DOWN below
target. The tests in `test_reorder.py` encode the correct behaviour and currently FAIL.

Do the following:
1. Run `pytest -q` to observe the failing tests.
2. Fix ONLY `reorder.py` so that every test passes. Do NOT modify the tests.
3. Keep the change minimal and preserve these invariants: a reorder quantity is never
   negative; it is 0 when on_hand is above the reorder point; otherwise it is rounded UP
   to whole case packs so on_hand + reorder >= target_level.
4. Re-run `pytest -q` to confirm all tests pass.

When finished, briefly summarise what was wrong and what you changed.
"""


def _make_sandbox() -> Path:
    """Create a fresh temp copy of the seeded sandbox."""
    dest = Path(tempfile.mkdtemp(prefix="zava-codefix-"))
    for item in SANDBOX_SEED.glob("*"):
        if item.is_file():
            shutil.copy2(item, dest / item.name)
    return dest


def _run_pytest(sandbox: Path) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=str(sandbox),
        capture_output=True,
        text=True,
        timeout=120,
    )
    return proc.returncode == 0, (proc.stdout + proc.stderr).strip()


def _args_dict(tool_args: Any) -> dict[str, Any]:
    """Normalise a Copilot SDK tool-argument payload to a plain dict.

    The SDK types ``toolArgs`` as ``Any`` and in practice hands the hook a **JSON string**
    (``'{"command":"pytest -q", ...}'``); other builds pass a dict or a typed object. Read all
    three shapes — otherwise the harness step degrades to a bare tool name and the ``pytest``
    heuristic below never fires.
    """
    if isinstance(tool_args, str):
        try:
            parsed = json.loads(tool_args)
        except (json.JSONDecodeError, ValueError):
            return {"command": tool_args} if tool_args else {}
        return parsed if isinstance(parsed, dict) else {}
    if isinstance(tool_args, dict):
        return tool_args
    for method in ("model_dump", "dict", "to_dict"):
        fn = getattr(tool_args, method, None)
        if callable(fn):
            try:
                data = fn()
            except Exception:  # noqa: BLE001 - best effort only
                continue
            if isinstance(data, dict):
                return data
    data = getattr(tool_args, "__dict__", None)
    if isinstance(data, dict) and data:
        return dict(data)
    return {}


def _tool_summary(tool_name: str, tool_args: Any) -> str:
    """A short human label for a harness step from the tool call."""
    args = _args_dict(tool_args)
    for key in ("command", "cmd", "script", "commandLine", "command_line"):
        if args.get(key):
            return f"$ {str(args[key])[:80]}"
    for key in ("path", "filePath", "file_path", "file", "target"):
        if args.get(key):
            return f"{tool_name}: {args[key]}"
    return tool_name


class CopilotCodeFixClient(HarnessChatClient, BaseChatClient):
    """MAF adapter that runs the GitHub Copilot SDK harness on a sandbox."""

    agent_id = CODE_FIX

    def __init__(self, bus: EventBus | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bus = bus

    async def _produce(self, messages: Any, options: Any) -> str:
        triage = extract_last_json(messages, must_have="triage") or {}
        triage_info = triage.get("triage", triage)
        incident = last_user_text(messages)

        sandbox = _make_sandbox()
        original = (sandbox / "reorder.py").read_text(encoding="utf-8")

        await self._emit(
            "agent_started",
            note="Running the GitHub Copilot SDK harness on an isolated sandbox",
            sandbox=str(sandbox),
            model=CODE_FIX_MODEL,
        )

        tool_calls: list[str] = []
        pytest_runs = 0

        async def on_pre_tool_use(hook_input: Any, _ctx: Any) -> dict[str, str]:
            nonlocal pytest_runs
            tool_name = _get(hook_input, "toolName") or "tool"
            tool_args = _get(hook_input, "toolArgs")
            label = _tool_summary(tool_name, tool_args)
            tool_calls.append(tool_name)
            probe = f"{label} {_args_dict(tool_args)}".lower()
            if "pytest" in probe:
                pytest_runs += 1
                phase = "assess"
            elif any(k in tool_name.lower() for k in ("write", "edit", "apply", "create")):
                phase = "execute"
            elif "read" in tool_name.lower() or "view" in tool_name.lower():
                phase = "plan"
            else:
                phase = "execute"
            await self._emit("harness_step", step=phase, tool=tool_name, detail=label)
            # Auto-approve every tool inside the sandbox (headless, non-interactive).
            return {"permissionDecision": "allow"}

        agent_text = ""
        run_error: str | None = None
        try:
            from agent_framework_github_copilot import GitHubCopilotAgent
            from copilot import CopilotClient

            gh_token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
            client_kwargs: dict[str, Any] = {"working_directory": str(sandbox), "log_level": "error"}
            if gh_token:
                client_kwargs["github_token"] = gh_token
            else:
                client_kwargs["use_logged_in_user"] = True
            client = CopilotClient(**client_kwargs)
            async with GitHubCopilotAgent(
                name="CodeFix",
                client=client,
                default_options={
                    "model": CODE_FIX_MODEL,
                    "timeout": CODE_FIX_TIMEOUT,
                    "on_pre_tool_use": on_pre_tool_use,
                },
            ) as agent:
                response = await agent.run(FIX_PROMPT)
                agent_text = getattr(response, "text", None) or str(response)
        except Exception as exc:  # pragma: no cover - surfaced to the transcript
            run_error = f"{type(exc).__name__}: {exc}"
            await self._emit("error", note=f"Copilot harness error: {run_error}")

        test_passed, test_output = _run_pytest(sandbox)
        fixed = (sandbox / "reorder.py").read_text(encoding="utf-8")
        diff = "".join(
            difflib.unified_diff(
                original.splitlines(keepends=True),
                fixed.splitlines(keepends=True),
                fromfile="reorder.py (before)",
                tofile="reorder.py (after)",
            )
        )
        files_changed = ["reorder.py"] if fixed != original else []
        iterations = max(pytest_runs, 1 if files_changed else 0)

        result = CodeFixResult(
            test_passed=test_passed,
            iterations=iterations,
            files_changed=files_changed,
            diff=diff,
            summary=(agent_text or run_error or "").strip(),
            test_output=test_output[-1500:],
            sandbox_path=str(sandbox),
        )
        await self._emit(
            "agent_completed",
            result={**result.to_dict(), "diff": diff[:4000], "tool_calls": len(tool_calls)},
        )

        # Tick off the plan Triage wrote, but only from *real* signals of this run.
        todos = HarnessTodos(options)
        if todos.available:
            done: list[tuple[int, str]] = []
            if pytest_runs:
                item = await todos.find("reproduce")
                if item:
                    done.append((item, f"pytest executed {pytest_runs}x in the sandbox"))
            if files_changed:
                item = await todos.find("patch")
                if item:
                    done.append((item, f"edited {', '.join(files_changed)}"))
            if test_passed:
                item = await todos.find("re-run", "test suite")
                if item:
                    done.append((item, "suite green after the fix"))
            if done:
                await todos.complete(*done)
                await self._emit(
                    "harness_step", step="assess", detail=f"{len(done)} plan item(s) completed"
                )

        status = "✅ all tests pass" if test_passed else "❌ tests still failing"
        human = (
            f"**Code Fix complete** — {status} after {iterations} iteration(s); "
            f"changed: {', '.join(files_changed) or 'none'}.\n\n{result.summary}"
        )
        payload = {
            "code_fix": {
                "test_passed": test_passed,
                "iterations": iterations,
                "files_changed": files_changed,
                "diff": diff,
                "test_output": result.test_output,
                "summary": result.summary,
                "triage": triage_info,
            }
        }
        return fenced_json(payload) + "\n\n" + human


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def create_code_fix_agent(bus: EventBus | None = None, todo_store: Any = None) -> Agent:
    """Return the Code Fix stage as a MAF agent."""
    return Agent(
        client=CopilotCodeFixClient(bus=bus),
        name="CodeFix",
        description="Fixes the defect in an isolated sandbox using the GitHub Copilot SDK harness.",
        instructions="You are the Zava incident Code Fix agent.",
        context_providers=[build_todo_provider(todo_store)] if todo_store is not None else None,
    )


if __name__ == "__main__":  # manual smoke test
    import asyncio

    from harness import load_env  # type: ignore

    load_env()

    async def _main() -> None:
        bus = EventBus()
        agent = create_code_fix_agent(bus)
        seed = (
            "```json\n{\"triage\": {\"severity\": \"high\", \"category\": \"bug\", "
            "\"component\": \"reorder.py\", \"route\": \"code_fix\"}}\n```\n"
            "Fix the reorder defect."
        )
        resp = await agent.run(seed)
        print("\n--- EVENTS ---")
        for event in bus.events:
            print(f"  [{event.agent}] {event.type}: {event.data.get('detail') or event.data.get('note') or ''}")
        print("\n--- RESULT ---")
        print(resp.text[:1500])

    asyncio.run(_main())
