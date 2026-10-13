"""Does the compiler's rule for what may cross threads match an independent table?

For every type below and every way of handing a value to another thread (a lambda given to `Thread.spawn`, a
`send` parameter, `Queue.send`, `Locked.new` / `set`, an `Arc` shared by two threads), a small program is built
and the compiler's answer (accepted or rejected) is compared with `SEND`, written by hand from the rule:
a value may cross when nothing in it is a view, a raw pointer, a non-atomic owner count (`Shared`, a stored
`Fn`), or a reference field. A type that must not cross but is accepted is a hole; one that may cross but is
rejected is a false error.

    python tools/send_matrix.py
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import safety_oracle as O  # noqa: E402

DECLS = """import std.thread { Thread, Locked, Queue, Atomic }

struct Plain:
    name: string
    n: i32

struct WithView:
    who: read string tied to self

struct HasShared:
    s: Shared[i32]

struct HasArc:
    a: Arc[string]

enum Ev:
    Txt(string)
    Num(i32)

enum EvS:
    Sh(Shared[i32])
    Num(i32)

fn mk_fn() -> Fn():
    s = string.from("a")
    return fn() => print(s)

struct Rec:
    next: Optional[Box[Rec]]
    name: string

struct RecS:
    next: Optional[Box[RecS]]
    s: Shared[i32]

"""

# type: (constructor expression, may it cross a thread?)
SEND = {
    "i32": ("1", True),
    "string": ('string.from("a")', True),
    "List[string]": ('List[string]()', True),
    "Box[string]": ('Box[string](string.from("a"))', True),
    "Optional[string]": ('Optional[string].Valid(string.from("a"))', True),
    "Plain": ('Plain{ name: string.from("a"), n: 1 }', True),
    "Ev": ('Ev.Txt(string.from("a"))', True),
    "Rec": ('Rec{ next: None, name: string.from("a") }', True),
    "Arc[string]": ('Arc[string](string.from("a"))', True),
    "Arc[List[string]]": ('Arc[List[string]](List[string]())', True),
    "HasArc": ('HasArc{ a: Arc[string](string.from("a")) }', True),
    "(i32, string)": ('(1, string.from("a"))', True),
    "[2]i32": ("[1, 2]", True),
    "Locked[string]": ('Locked[string].new(string.from("a"))', True),
    "Queue[string]": ('Queue[string].new()', True),
    "Atomic[i64]": ("Atomic[i64].new(0)", True),
    "Thread": ("Thread.spawn(fn() => print(1))", True),
    "Shared[i32]": ("Shared[i32](1)", False),
    "Shared[string]": ('Shared[string](string.from("a"))', False),
    "Arc[Shared[i32]]": ("Arc[Shared[i32]](Shared[i32](1))", False),
    "Optional[Shared[i32]]": ("Optional[Shared[i32]].Valid(Shared[i32](1))", False),
    "List[Shared[i32]]": ("List[Shared[i32]]()", False),
    "Box[Shared[i32]]": ("Box[Shared[i32]](Shared[i32](1))", False),
    "HasShared": ("HasShared{ s: Shared[i32](1) }", False),
    "EvS": ("EvS.Num(1)", False),
    "RecS": ("RecS{ next: None, s: Shared[i32](1) }", False),
    "(i32, Shared[i32])": ("(1, Shared[i32](1))", False),
    "[1]Shared[i32]": ("[Shared[i32](1)]", False),
    "Locked[Shared[i32]]": ("Locked[Shared[i32]].new(Shared[i32](1))", False),  # the control fails: `new` takes a `send` value
    "Queue[Shared[i32]]": ("Queue[Shared[i32]].new()", False),
    "Arc[Locked[Shared[i32]]]": ("Arc[Locked[Shared[i32]]](Locked[Shared[i32]].new(Shared[i32](1)))", False),
    "Fn()": ("mk_fn()", False),
    "Optional[Fn()]": ("Optional[Fn()].None", False),
}

MECHS = {
    "spawn-capture": "    t = Thread.spawn(fn() => use(v))\n    t.join()\n",
    "send-param": "    go(v)\n",
    "queue-send": "    q = Queue[$T].new()\n    q.send(v)\n",
    "locked-new": "    m = Locked[$T].new(v)\n",
    "arc-two-threads": "    a = Arc[$T](v)\n    b = a.clone()\n    t = Thread.spawn(fn() => use_arc(b))\n    t.join()\n",
}


def program(ty: str, ctor: str, mech: str) -> str:
    helpers = f"fn use(x: read {ty}):\n    pass\n\nfn use_arc(x: read Arc[{ty}]):\n    pass\n\nfn go(x: send {ty}):\n    pass\n\n"
    body = MECHS[mech].replace("$T", ty)
    return DECLS + helpers + "fn main():\n    v = " + ctor + "\n" + body


def control(ty: str, ctor: str) -> str:
    """The same value used without any thread: must compile, or the case says nothing."""
    helpers = f"fn use(x: read {ty}):\n    pass\n\n"
    return DECLS + helpers + "fn main():\n    v = " + ctor + "\n    use(v)\n"


def main() -> int:
    holes, false_errors, invalid = [], [], []
    total = 0
    for ty, (ctor, may) in SEND.items():
        ok, err = O.accepted(control(ty, ctor))
        if not ok:
            invalid.append((ty, err))
            continue
        for mech in MECHS:
            if mech == "arc-two-threads" and ty in ("Thread", "Fn()", "Optional[Fn()]"):
                continue
            ok, err = O.accepted(program(ty, ctor, mech))
            total += 1
            if ok and not may:
                holes.append((ty, mech))
            elif not ok and may:
                false_errors.append((ty, mech, err[:150]))
    print(f"{total} cases")
    for ty, err in invalid:
        print(f"  control fails: {ty}: {err[:120]}")
    for ty, mech in holes:
        print(f"  HOLE: {ty} crosses a thread through {mech}")
    for ty, mech, err in false_errors:
        print(f"  false error: {ty} through {mech}: {err}")
    print("holes:", len(holes), "false errors:", len(false_errors))
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
