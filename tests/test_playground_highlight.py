"""The playground's colors (`website/playground/highlight.js`): token classes for source, and links in compiler output."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "website" / "playground" / "highlight.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node")


def run(call: str):
    script = f"global.window = {{}}; require({json.dumps(str(JS))}); console.log(JSON.stringify({call}));"
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_source_classes():
    html = run('window.GGHighlight.source(\'fn main():\\n    x: i32 = 5  # note\\n    print("a<b")\\n\')')
    assert '<span class="tok-kw">fn</span>' in html
    assert '<span class="tok-type">i32</span>' in html
    assert '<span class="tok-num">5</span>' in html
    assert '<span class="tok-comment"># note</span>' in html
    assert '<span class="tok-str">"a&lt;b"</span>' in html
    assert '<span class="tok-fn">print</span>' in html


def test_diagnostics_have_links_and_colors():
    text = ("Error: No function named `foo`.\\n --> main.gg:5:9  GG0203 undefined-name\\n  |\\n"
            "5 |     y = foo(1)\\n  |         ^^^\\n  = help: Define it.\\n")
    html = run(f'window.GGHighlight.terminal("{text}")')
    assert '<span class="t-err">error:</span>' in html
    assert 'data-line="5" data-col="9"' in html and 'data-explain="GG0203"' in html
    assert '<span class="t-caret">^^^</span>' in html
    assert '<span class="t-help">= help:</span>' in html


def test_runtime_error_line():
    html = run('window.GGHighlight.terminal("Runtime error: boom\\n  --> main.gg:3:4\\n")')
    assert '<span class="t-err">Runtime error:</span> boom' in html
    assert 'data-line="3"' in html


@pytest.mark.parametrize("name", ["editor", "highlight", "playground", "runner", "toolchain", "worker"])
def test_playground_scripts_parse(name):
    path = JS.parent / f"{name}.js"
    r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
