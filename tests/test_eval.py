"""The eval harness measures compile, repair, and hidden tests. It does not call an API."""
import json

import eval.runner as runner


class Scripted:
    def __init__(self, replies: list[str]) -> None:
        self.replies = replies
        self.prompts: list[str] = []

    def complete(self, prompt: str):
        self.prompts.append(prompt)
        text = self.replies[min(len(self.prompts) - 1, len(self.replies) - 1)]
        return runner.Completion(text, runner.estimate_tokens(prompt), runner.estimate_tokens(text))


def test_reference_model_passes_every_hidden_test():
    tasks = runner.load_tasks()
    assert len(tasks) == 10
    document = runner.evaluate(runner.ReferenceModel(tasks), tasks)
    summary = document["summary"]
    assert summary["first_try_compile"] == 10
    assert summary["compiled"] == 10
    assert summary["tests_passed"] == summary["tests_total"]
    assert summary["tests_total"] == 20
    assert summary["mean_repair_rounds"] == 0
    assert summary["tokens"] > 0
    assert document["model"] == "ReferenceModel"


def test_one_repair_round_feeds_check_json():
    task = next(task for task in runner.load_tasks() if task.id == "05_translate")
    model = Scripted([
        "struct Point:\n    x: i32\n\nfn translate(p: lend Point, dx: i32, dy: i32):\n    p.y += dy\n",
        task.solution,
    ])
    row = runner.evaluate_task(model, task)
    assert row["first_try_compile"] is False
    assert row["repair_rounds"] == 1
    assert row["compiled"] is True
    assert row["tests_passed"] == 2
    assert "gg check --json" in model.prompts[1]
    feedback = json.loads(model.prompts[1].split("returned:\n\n", 1)[1].split("\n\nReply", 1)[0])
    assert feedback["ok"] is False
    assert feedback["diagnostics"]


def test_repair_stops_at_five():
    task = next(task for task in runner.load_tasks() if task.id == "07_median3")
    model = Scripted(["not greengold"])
    row = runner.evaluate_task(model, task)
    assert len(model.prompts) == 6
    assert row["repair_rounds"] == 5
    assert row["compiled"] is False
    assert row["first_try_compile"] is False
    assert row["tests_passed"] == 0
    assert row["tests_total"] == 2
    assert row["tests_ran"] is False
