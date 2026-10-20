"""The lessons under website/learn/content: every runnable example and every exercise solution builds and prints what
the lesson says (English is the source; the other languages must carry the very same code), every language has the same
structure, and the manifest matches the files.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.helpers import run_gg_source

ROOT = Path(__file__).resolve().parent.parent / "website" / "learn" / "content"
UI_JS = ROOT.parent / "ui.js"
LANGS = ["en", "tr", "es", "de", "ru", "zh"]
OTHERS = [lang for lang in LANGS if lang != "en"]
MANIFEST = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
LESSONS = [lesson for ch in MANIFEST["chapters"] for lesson in ch["lessons"]]
CODE_KEYS = ("code", "output", "starter", "solution", "expected", "run", "local", "lang", "id", "answer")


def load(lang, lesson):
    return json.loads((ROOT / lang / (lesson + ".json")).read_text(encoding="utf-8"))


def programs(data):
    """(label, source, expected stdout lines) for each program a lesson claims to run."""
    for i, b in enumerate(data["blocks"]):
        if b["t"] == "code" and b.get("run") and "output" in b:
            yield "code#%d" % i, "\n".join(b["code"]) + "\n", b["output"]
        elif b["t"] == "exercise":
            yield "solution:" + b["id"], "\n".join(b["solution"]) + "\n", b["expected"]


def texts(block):
    """The strings of a block that are prose (translated), not code."""
    if block["t"] in ("p", "h"):
        return [block["text"]]
    if block["t"] == "exercise":
        return [block["prompt"], block["hint"]]
    if block["t"] == "quiz":
        return [block["q"], block["why"]] + block["options"]
    return []


def test_manifest_files_exist_and_ids_are_unique():
    assert len(LESSONS) == len(set(LESSONS))
    for lang in LANGS:
        for lesson in LESSONS:
            assert (ROOT / lang / (lesson + ".json")).is_file(), (lang, lesson)
        extra = {p.stem for p in (ROOT / lang).glob("*.json")} - set(LESSONS)
        assert not extra, (lang, extra)
        for ch in MANIFEST["chapters"]:
            assert ch["title"].get(lang), (lang, ch["id"])


def test_every_language_has_interface_strings():
    src = UI_JS.read_text(encoding="utf-8")
    listed = re.findall(r'\["([a-z]{2})", "[^"]+"\]', src.split("strings:")[0])
    assert listed == LANGS, listed
    keys = {}
    for lang in LANGS:
        body = src.split("\n    %s: {" % lang)[1].split("\n    }")[0]
        keys[lang] = set(re.findall(r'\b([A-Za-z_0-9]+): "', body))
    for lang in OTHERS:
        assert keys[lang] == keys["en"], (lang, keys["en"] ^ keys[lang])


@pytest.mark.parametrize("lesson", LESSONS)
def test_languages_have_the_same_shape_and_code(lesson):
    en = load("en", lesson)
    for lang in OTHERS:
        other = load(lang, lesson)
        assert [b["t"] for b in other["blocks"]] == [b["t"] for b in en["blocks"]], (lang, lesson)
        assert other["title"].strip(), (lang, lesson)
        for a, b in zip(en["blocks"], other["blocks"]):
            for key in CODE_KEYS:
                assert a.get(key) == b.get(key), (lang, lesson, key)
            if a["t"] == "quiz":
                assert len(a["options"]) == len(b["options"])
                assert 0 <= b["answer"] < len(b["options"])
            for text in texts(b):
                assert text.strip(), (lang, lesson)
            # inline code spans stay closed in every translation (placeholder words inside them may be translated)
            for tb in texts(b):
                assert tb.count("`") % 2 == 0, (lang, lesson, tb[:50])
                assert tb.count("**") % 2 == 0, (lang, lesson, tb[:50])


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
def test_programs_build_and_print_what_the_lesson_says(tmp_path, lesson):
    for label, source, expected in programs(load("en", lesson)):
        r = run_gg_source(tmp_path, source)
        assert r.returncode == 0, (lesson, label, r.stderr)
        assert [l.rstrip() for l in r.stdout.splitlines()] == expected, (lesson, label)
