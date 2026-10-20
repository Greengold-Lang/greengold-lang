"""Built-in attributes (@section, @used, @weak, @export, @interrupt, @inline, @cold, @naked, @panic_handler) and the
static limits (--forbid-heap, --forbid-recursion, --max-stack, gg stack-usage)."""
import json
import subprocess
import sys

from tests.helpers import ROOT, run_gg_source

ATTRS = """static counter: u32 = 0

@section(".isr_vector")
@used
static vectors: [2]u32 = [1, 2]

@interrupt
fn Tick():
    unsafe:
        counter = counter + 1

@inline(never)
@export("my_add")
fn add(a: i32, b: i32) -> i32:
    return a + b

@inline(always)
fn twice(a: i32) -> i32:
    return a * 2

@weak
@cold
fn rare():
    pass

fn main():
    Tick()
    rare()
    print(add(twice(3), 1))
    unsafe:
        print(counter, vectors[1])
"""


def gg(*args, cwd=ROOT):
    return subprocess.run([sys.executable, "-m", "greengold", *args], capture_output=True, text=True, cwd=cwd)


def test_builtin_attributes_run_and_reach_the_ir(tmp_path):
    r = run_gg_source(tmp_path, ATTRS)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["7", "1 2"]
    f = tmp_path / "a.gg"
    ir = gg("emit-ll", str(f), "-o", str(tmp_path / "a.ll"))
    assert ir.returncode == 0, ir.stderr
    text = (tmp_path / "a.ll").read_text(encoding="utf-8")
    assert 'define external void @"Tick"' in text
    assert 'define external i32 @"my_add"' in text and "noinline" in text
    assert 'section ".isr_vector"' in text
    assert "@\"llvm.used\"" in text
    assert 'define weak void @"gg_rare"() cold' in text


def test_bad_attribute_arguments_are_errors(tmp_path):
    f = tmp_path / "bad.gg"
    f.write_text('@inline(sometimes)\nfn f():\n    pass\n\n@panic_handler\nfn h(x: i32):\n    pass\n\n@section\nfn g():\n    pass\n\n'
                 'fn main():\n    pass\n', encoding="utf-8")
    r = gg("check", str(f))
    assert r.returncode != 0
    assert "`@inline` takes" in r.stdout + r.stderr
    assert "takes no parameters" in r.stdout + r.stderr
    assert "needs the argument `name`" in r.stdout + r.stderr


def test_panic_handler_runs_before_exit(tmp_path):
    r = run_gg_source(tmp_path, '@panic_handler\nfn on_panic():\n    print("handler ran")\n\n'
                                'fn main():\n    xs = [1, 2, 3]\n    i = 7\n    print(xs[i])\n')
    assert r.returncode != 0
    assert "handler ran" in r.stdout
    assert "index out of bounds" in r.stderr


LEAF = """fn leaf(a: i32) -> i32:
    buf: [64]i32 = [0; 64]
    buf[0] = a
    return buf[0] + 1

fn mid(a: i32) -> i32:
    pad: [16]i32 = [0; 16]
    pad[1] = a
    return leaf(pad[1])

fn main():
    print(mid(2))
"""


def test_limits(tmp_path):
    rec = tmp_path / "rec.gg"
    rec.write_text("fn fact(n: u32) -> u32:\n    if n <= 1:\n        return 1\n    return n * fact(n - 1)\n\n"
                   "fn main():\n    xs = List[i32]()\n    xs.push(1)\n    print(fact(5), xs.len)\n", encoding="utf-8")
    r = gg("emit-ll", str(rec), "--forbid-heap", "--forbid-recursion")
    assert r.returncode != 0
    assert "--forbid-heap: the program allocates: main -> List_i32__push -> rt_realloc" in r.stderr
    assert "--forbid-recursion: recursive call cycle: fact" in r.stderr
    leaf = tmp_path / "leaf.gg"
    leaf.write_text(LEAF, encoding="utf-8")
    assert gg("emit-ll", str(leaf), "--forbid-heap", "--forbid-recursion", "--max-stack", "100000",
              "-o", str(tmp_path / "x.ll")).returncode == 0
    over = gg("emit-ll", str(leaf), "--max-stack", "400")
    assert over.returncode != 0 and "over the limit of 400" in over.stderr


def test_stack_usage_report(tmp_path):
    leaf = tmp_path / "leaf.gg"
    leaf.write_text(LEAF, encoding="utf-8")
    r = gg("stack-usage", str(leaf), "--json")
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["recursive"] is False
    assert data["functions"]["gg_leaf"]["frame_bytes"] >= 64 * 4
    assert data["worst_case_bytes"] > data["functions"]["gg_leaf"]["frame_bytes"]
