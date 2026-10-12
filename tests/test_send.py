"""Send/Share inference: what may cross to another thread, `Arc`, `Queue[T]`, and capturing `Thread.spawn`."""
import pytest

from greengold.cli import load_sources_and_ast
from greengold.typecheck import check_program
from tests.helpers import HAS_CC, run_built

HEAD = "import std.thread { Thread, Queue, AtomicI64 }\n\n"


def messages(src):
    """Diagnostics of `src` checked as a file, so `import std.thread` resolves."""
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "main.gg"
        path.write_text(src, encoding="utf-8")
        program, _, diags = load_sources_and_ast([str(path)])
        if not diags.has_errors():
            check_program(program, diags, str(path))
        return [x.message for x in diags.items if not x.hidden and x.severity == "error"]


def has(msgs, text):
    return any(text in m for m in msgs)


def main(body):
    return HEAD + "fn main():\n" + "".join("    " + line + "\n" for line in body.splitlines())


@pytest.mark.parametrize("body, reason", [
    ('name = "x"\nt = Thread.spawn(fn() => print(name))', "`str` is a view"),
    ("s = Shared[i32](1)\nt = Thread.spawn(fn() => print(s.value))", "use `Arc[i32]`"),
    ("f: Fn() = fn() => print(1)\nt = Thread.spawn(f)", "write the lambda itself"),
    ("q = Queue[Shared[i32]].new()\nq.send(Shared[i32](3))", "without atomics"),
    ("a = Arc[Shared[i32]](Shared[i32](1))\nt = Thread.spawn(fn() => print(a.value.value))", "without atomics"),
])
def test_not_send_is_rejected(body, reason):
    msgs = messages(main(body))
    assert has(msgs, "cannot go to another thread"), msgs
    assert has(msgs, reason), msgs


@pytest.mark.parametrize("body", [
    "n = 5\nt = Thread.spawn(fn() => print(n))\nt.join()",
    "xs = List[i32]()\nt = Thread.spawn(fn() => print(xs.len))\nt.join()",
    "s = string.from(\"x\")\nt = Thread.spawn(fn() => print(s))\nt.join()",
    "a = Arc[List[i32]](List[i32]())\nb = a.clone()\nt = Thread.spawn(fn() => print(b.value.len))\nt.join()",
])
def test_send_values_are_accepted(body):
    assert messages(main(body)) == []


def test_plain_function_still_spawns():
    src = HEAD + "fn work():\n    print(1)\n\nfn main():\n    t = Thread.spawn(work)\n    t.join()\n"
    assert messages(src) == []


def test_arc_clone_adds_an_owner():
    res = run_built("fn main():\n    a = Arc[List[i32]](List[i32]())\n    b = a.clone()\n    print(a.value.len, b.value)\n")
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["0", "[]"]


def test_generic_associated_function_call():
    src = ("struct W[T]:\n    v: T\n\nimpl W[T]:\n    fn make(v: T) -> W[T]:\n        return W[T]{ v: v }\n\n"
           "fn main():\n    w = W[i32].make(3)\n    print(w.v)\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["3"]


@pytest.mark.skipif(not HAS_CC, reason="no C compiler")
def test_workers_share_a_queue_and_a_counter():
    src = HEAD + (
        "fn work(q: Arc[Queue[string]], sum: Arc[AtomicI64]):\n"
        "    while let Valid(job) = q.value.recv():\n"
        "        sum.value.fetch_and_add(i64(job.len))\n\n"
        "fn main():\n"
        "    q = Arc[Queue[string]](Queue[string].new())\n"
        "    total = Arc[AtomicI64](AtomicI64.new(0))\n"
        "    workers = List[Thread]()\n"
        "    for w in 0..3:\n"
        "        mine = q.clone()\n"
        "        sum = total.clone()\n"
        "        workers.push(Thread.spawn(fn() => work(mine, sum)))\n"
        "    for i in 0..30:\n"
        "        q.value.send(f\"job {i}\")\n"
        "    q.value.close()\n"
        "    for t in workers:\n"
        "        t.join()\n"
        "    print(total.value.load())\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["170"]


def test_ptr_read_write_and_size_of():
    src = ('extern "stdlib.h" fn malloc(size: usize) -> *mut u8\nextern "stdlib.h" fn free(ptr: *u8)\n\n'
           "fn main():\n    print(size_of[i64](), align_of[i32]())\n    xs = List[i32]()\n    xs.push(7)\n"
           "    unsafe:\n        raw = malloc(size_of[List[i32]]())\n        ptr_write[List[i32]](raw, xs)\n"
           "        back = ptr_read[List[i32]](raw)\n        free(raw)\n        print(back)\n")
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.split() == ["8", "4", "[7]"]
    assert has(messages("fn main():\n    x = 1\n    p = ptr_read[i32](null)\n"), "unsafe")
