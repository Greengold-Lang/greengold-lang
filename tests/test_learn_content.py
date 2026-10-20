"""The lessons under website/learn/content: every runnable example and every exercise solution builds and prints what
the lesson says, both languages carry the same structure, and the manifest matches the files.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import run_gg_source

ROOT = Path(__file__).resolve().parent.parent / "website" / "learn" / "content"
LANGS = ["tr", "en"]
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
LESSONS = [lesson for ch in MANIFEST["chapters"] for lesson in ch["lessons"]]


def load(lang, lesson):
    return json.loads((ROOT / lang / (lesson + ".json")).read_text(encoding="utf-8"))


def programs(data):
    """(label, source, expected stdout lines) for each program a lesson claims to run."""
    for i, b in enumerate(data["blocks"]):
        if b["t"] == "code" and b.get("run") and "output" in b:
            yield "code#%d" % i, "\n".join(b["code"]) + "\n", b["output"]
        elif b["t"] == "exercise":
            yield "solution:" + b["id"], "\n".join(b["solution"]) + "\n", b["expected"]


def test_manifest_files_exist_and_ids_are_unique():
    assert len(LESSONS) == len(set(LESSONS))
    for lang in LANGS:
        for lesson in LESSONS:
            assert (ROOT / lang / (lesson + ".json")).is_file(), (lang, lesson)
        extra = {p.stem for p in (ROOT / lang).glob("*.json")} - set(LESSONS)
        assert not extra, (lang, extra)


@pytest.mark.parametrize("lesson", LESSONS)
def test_languages_have_the_same_shape(lesson):
    tr, en = load("tr", lesson), load("en", lesson)
    assert [b["t"] for b in tr["blocks"]] == [b["t"] for b in en["blocks"]]
    for a, b in zip(tr["blocks"], en["blocks"]):
        for key in ("id", "answer", "run"):
            assert a.get(key) == b.get(key), (lesson, key)
        if a["t"] == "quiz":
            assert len(a["options"]) == len(b["options"])
            assert 0 <= a["answer"] < len(a["options"])


def local_programs(data):
    """Whole programs shown without running (they need files, threads or sockets): they must still type-check."""
    for i, b in enumerate(data["blocks"]):
        if b["t"] == "code" and b.get("local"):
            yield "local#%d" % i, "\n".join(b["code"]) + "\n"


@pytest.mark.parametrize("lesson", LESSONS)
def test_local_programs_type_check(tmp_path, lesson):
    for label, source in local_programs(load("en", lesson)):
        f = tmp_path / "a.gg"
        f.write_text(source, encoding="utf-8")
        r = subprocess.run([sys.executable, "-m", "greengold", "check", str(f)], capture_output=True, text=True,
                           encoding="utf-8", cwd=ROOT.parents[2], timeout=120)
        assert r.returncode == 0, (lesson, label, r.stdout + r.stderr)


@pytest.mark.parametrize("lesson", LESSONS)
@pytest.mark.parametrize("lang", LANGS)
def test_programs_build_and_print_what_the_lesson_says(tmp_path, lang, lesson):
    for label, source, expected in programs(load(lang, lesson)):
        r = run_gg_source(tmp_path, source)
        assert r.returncode == 0, (lang, lesson, label, r.stderr)
        assert [l.rstrip() for l in r.stdout.splitlines()] == expected, (lang, lesson, label)
