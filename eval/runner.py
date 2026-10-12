"""Score Greengold tasks without calling an external API.

The model is any object with `complete(prompt: str) -> Completion`.
`ReferenceModel` returns the checked-in solution for each task.
`python eval/runner.py --model reference` writes JSON and a short summary.

Repair feedback is the raw `gg check --json` document. At most 5 repair
rounds follow the first attempt. Hidden tests are not part of the prompt.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = Path(__file__).resolve().parent / "tasks"
REPAIR_CAP = 5

_FENCE = re.compile(r"```(?:gg)?[^\n]*\n(.*?)```", re.S)
_TASK_ID = re.compile(r"^Task-Id: (\S+)\s*$", re.M)
_UNIT = re.compile(r"^fn (test_\w+)\(\)\s*:", re.M)
_TOKEN = re.compile(r"\w+|[^\w\s]")


def estimate_tokens(text: str) -> int:
    """Counts words and punctuation. This is the harness count, not a vendor count."""
    return len(_TOKEN.findall(text))


@dataclass
class Completion:
    code: str
    prompt_tokens: int
    completion_tokens: int


@dataclass
class Task:
    id: str
    prompt_body: str
    solution: str
    tests: str

    @property
    def tests_total(self) -> int:
        return len(_UNIT.findall(self.tests))


def load_tasks() -> list[Task]:
    found: list[Task] = []
    for directory in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        found.append(Task(
            id=directory.name,
            prompt_body=(directory / "task.md").read_text(encoding="utf-8"),
            solution=(directory / "solution.gg").read_text(encoding="utf-8"),
            tests=(directory / "tests.gg").read_text(encoding="utf-8"),
        ))
    return found


class ReferenceModel:
    """Returns the task's solution.gg. It does not call a network."""

    def __init__(self, tasks: list[Task]) -> None:
        self._solutions = {task.id: task.solution for task in tasks}

    def complete(self, prompt: str) -> Completion:
        match = _TASK_ID.search(prompt)
        if match is None or match.group(1) not in self._solutions:
            raise RuntimeError("prompt is missing a known Task-Id")
        code = self._solutions[match.group(1)]
        return Completion(code, estimate_tokens(prompt), estimate_tokens(code))


def extract_code(text: str) -> str:
    fences = _FENCE.findall(text)
    body = fences[0] if fences else text
    return body.strip() + "\n"


def with_main(source: str) -> str:
    if re.search(r"^fn main\(", source, re.M):
        return source if source.endswith("\n") else source + "\n"
    return source.rstrip() + "\n\nfn main():\n    pass\n"


def _gg(args: list[str], path: Path) -> subprocess.CompletedProcess[str]:
    env = dict(**__import__("os").environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [sys.executable, "-m", "greengold", *args, str(path)],
        capture_output=True, text=True, encoding="utf-8", cwd=ROOT, env=env, timeout=180,
    )


def check_source(source: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "candidate.gg"
        path.write_text(with_main(source), encoding="utf-8", newline="\n")
        result = _gg(["check", "--json"], path)
    try:
        document = json.loads(result.stdout)
    except json.JSONDecodeError:
        document = {
            "ok": False,
            "diagnostics": [{
                "message": (result.stderr or result.stdout or "gg check produced no JSON").strip(),
            }],
        }
    return document


def test_source(source: str, tests: str) -> dict:
    combined = with_main(source).rstrip() + "\n\n" + tests
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "candidate.gg"
        path.write_text(combined, encoding="utf-8", newline="\n")
        result = _gg(["test", "--json"], path)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "summary": {"passed": 0, "failed": 0}, "tests": []}


def _first_prompt(task: Task) -> str:
    return (
        f"Task-Id: {task.id}\n\n"
        "Write one Greengold file. Reply with source code only.\n"
        "Do not write `fn main`. Do not write tests.\n"
        "Use the signatures below exactly. A parameter mode is written only on the signature.\n\n"
        f"{task.prompt_body.strip()}\n"
    )


def _repair_prompt(task: Task, source: str, report: dict) -> str:
    feedback = json.dumps(report, indent=2)
    return (
        f"Task-Id: {task.id}\n\n"
        "The compiler rejected this file. `gg check --json` returned:\n\n"
        f"{feedback}\n\n"
        "Reply with the full corrected source and nothing else.\n\n"
        f"{source}"
    )


def evaluate_task(model: object, task: Task) -> dict:
    prompt = _first_prompt(task)
    tokens = 0
    source = ""
    compiled = False
    first_try = False
    repairs = 0
    report: dict = {"ok": False}
    for round_index in range(REPAIR_CAP + 1):
        completion = model.complete(prompt)  # type: ignore[attr-defined]
        tokens += completion.prompt_tokens + completion.completion_tokens
        source = extract_code(completion.code)
        report = check_source(source)
        if report.get("ok"):
            compiled = True
            first_try = round_index == 0
            repairs = round_index
            break
        repairs = round_index
        if round_index == REPAIR_CAP:
            break
        prompt = _repair_prompt(task, source, report)
    passed = failed = 0
    total = task.tests_total
    ran = False
    if compiled:
        ran = True
        outcome = test_source(source, task.tests)
        passed = int(outcome.get("summary", {}).get("passed", 0))
        failed = int(outcome.get("summary", {}).get("failed", 0))
        if passed + failed == 0:
            failed = total
    else:
        failed = total
    return {
        "id": task.id,
        "first_try_compile": first_try,
        "repair_rounds": repairs,
        "compiled": compiled,
        "tests_passed": passed,
        "tests_failed": failed,
        "tests_total": total,
        "tests_ran": ran,
        "tokens": tokens,
    }


def evaluate(model: object, tasks: list[Task] | None = None) -> dict:
    chosen = tasks if tasks is not None else load_tasks()
    rows = [evaluate_task(model, task) for task in chosen]
    task_count = len(rows)
    repairs = sum(row["repair_rounds"] for row in rows)
    return {
        "schema_version": 1,
        "model": type(model).__name__,
        "repair_cap": REPAIR_CAP,
        "tasks": rows,
        "summary": {
            "tasks": task_count,
            "first_try_compile": sum(1 for row in rows if row["first_try_compile"]),
            "compiled": sum(1 for row in rows if row["compiled"]),
            "tests_passed": sum(row["tests_passed"] for row in rows),
            "tests_total": sum(row["tests_total"] for row in rows),
            "tokens": sum(row["tokens"] for row in rows),
            "mean_repair_rounds": (repairs / task_count) if task_count else 0,
        },
    }


def render_summary(document: dict) -> str:
    summary = document["summary"]
    lines = [
        "# Evaluation summary",
        "",
        f"Model: `{document['model']}`. This run made no external API call.",
        "",
        f"- Tasks: {summary['tasks']}",
        f"- Compiled on the first try: {summary['first_try_compile']}/{summary['tasks']}",
        f"- Compiled after repair: {summary['compiled']}/{summary['tasks']}",
        f"- Test: {summary['tests_passed']}/{summary['tests_total']}",
        f"- Mean repair rounds: {summary['mean_repair_rounds']}",
        f"- Token: {summary['tokens']}",
        "",
        "| Task | First try | Repair | Test | Token |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in document["tasks"]:
        lines.append(
            f"| {row['id']} | {row['first_try_compile']} | {row['repair_rounds']} | "
            f"{row['tests_passed']}/{row['tests_total']} | {row['tokens']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Score Greengold eval tasks")
    parser.add_argument("--model", choices=("reference",), default="reference")
    parser.add_argument("--task", help="run one task id instead of all ten")
    parser.add_argument("--out", type=Path, help="JSON results path")
    parser.add_argument("--summary", type=Path, help="markdown summary path")
    args = parser.parse_args(argv)
    tasks = load_tasks()
    if args.task:
        tasks = [task for task in tasks if task.id == args.task]
        if not tasks:
            print(f"Unknown task {args.task}", file=sys.stderr)
            return 2
    document = evaluate(ReferenceModel(load_tasks()), tasks)
    text = json.dumps(document, indent=2) + "\n"
    summary = render_summary(document)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(summary, encoding="utf-8", newline="\n")
    summary_row = document["summary"]
    ok = summary_row["compiled"] == summary_row["tasks"] and summary_row["tests_passed"] == summary_row["tests_total"]
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
