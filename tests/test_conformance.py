"""Runs the conformance suite in `conformance/` (see conformance/README.md)."""
import re
from pathlib import Path

import pytest

from greengold.cli import analyze
from tests.helpers import HAS_CC, run_built

ROOT = Path(__file__).resolve().parents[1] / "conformance"
CASES = sorted(ROOT.rglob("*.gg"))


def header(text: str) -> dict:
    """`# expect-output:` lines, `# expect-error: GGxxxx at line N`, `# stdin: ...`."""
    out: dict = {"output": None, "error": None, "stdin": None}
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("#"):
            break
        if line.startswith("# stdin: "):
            out["stdin"] = line[len("# stdin: "):] + "\n"
        m = re.match(r"# expect-error: (GG\d{4}) at line (\d+)", line)
        if m:
            out["error"] = (m.group(1), int(m.group(2)))
        if line.startswith("# expect-output:"):
            body = []
            for more in lines[i + 1:]:
                if not more.startswith("#"):
                    break
                body.append(more[4:] if more.startswith("#   ") else "")
            out["output"] = body
    return out


def test_suite_is_not_empty():
    assert len(CASES) >= 80


def test_every_spec_example_is_in_the_suite():
    """Each example of docs/SPEC.md is `conformance/spec/sNN_KK.gg` (section NN, example KK), unchanged."""
    spec = (ROOT.parent / "docs" / "SPEC.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    section, count, missing = "0", {}, []
    for m in re.finditer(r"^## (\d+)\. [^\n]*$|```gg\n(.*?)```", spec, re.S | re.M):
        if m.group(1):
            section = m.group(1)
            continue
        count[section] = count.get(section, 0) + 1
        path = ROOT / "spec" / f"s{int(section):02d}_{count[section]:02d}.gg"
        body = path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n\n", 1)[-1] if path.exists() else None
        if body != m.group(2):
            missing.append(path.name)
    assert not missing, f"add or update these from docs/SPEC.md: {missing}"


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_conformance(path: Path):
    text = path.read_text(encoding="utf-8")
    want = header(text)
    assert want["output"] is not None or want["error"] is not None, "no expectation in the header"
    if want["error"] is not None:
        _p, _s, diags, _c = analyze([str(path)])
        errs = [(d.code, d.line) for d in diags.items if d.severity == "error" and not d.hidden]
        assert want["error"] in errs, errs
        return
    if not HAS_CC:
        pytest.skip("no C toolchain to link")
    res = run_built(text, filename=path.name, stdin=want["stdin"])
    assert res.returncode == 0, res.stderr
    got = res.stdout.replace("\r\n", "\n").rstrip("\n")
    assert (got.split("\n") if got else []) == want["output"]
