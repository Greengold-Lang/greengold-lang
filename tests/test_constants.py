"""Global constants.

Spec: 14
"""
from pathlib import Path
import subprocess
import sys
import pytest

from greengold.cli import compile_to_ir
from tests.helpers import run_built
from greengold.diagnostics import CompileError

ROOT = Path(__file__).resolve().parent.parent


def run_prog(src: str) -> list[str]:
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    return res.stdout.splitlines()



def must_fail(src: str, text: str):
    with pytest.raises(CompileError) as exc_info:
        compile_to_ir(src)
    msgs = [d.message for d in exc_info.value.diagnostics]
    assert any(text in m for m in msgs), f"Expected `{text}` not in error messages: {msgs}"


def test_const_declaration_and_usage():
    src = """
const PI: f64 = 3.14159
const N = 10
const M = N * 2 + 5

fn main():
    print(PI)
    print(N)
    print(M)
    print(AFTER)

const AFTER = 42
"""
    out = run_prog(src)
    assert out[0] == "3.14159"
    assert out[1] == "10"
    assert out[2] == "25"
    assert out[3] == "42"


def test_top_level_var_is_removed():
    from tests.helpers import messages
    msgs = messages("var x = 5\n\nfn main():\n    print(x)\n")
    assert any("`var` was removed" in m for m in msgs)


def test_const_forward_ref_rejected():
    src = "const A = B + 1\nconst B = 10\n\nfn main():\n    print(A)\n"
    must_fail(src, "`B` constant has not been declared yet.")


def test_assign_to_const_rejected():
    src = "const N = 10\n\nfn main():\n    N = 20\n"
    must_fail(src, "Cannot assign to variable `N`: `N` is a constant (const).")


def test_shadow_const_rejected():
    src1 = "const N = 10\n\nfn main():\n    N: i32 = 5\n"
    must_fail(src1, "shadowing is not allowed")
    must_fail("const N = 10\n\nfn main():\n    N = 5\n", "Cannot assign to variable `N`")

    src2 = "const N = 10\n\nfn f(N: i32):\n    print(N)\n\nfn main():\n    f(1)\n"
    must_fail(src2, "shadowing is not allowed")


def test_const_duplicate_name():
    src = "const N = 10\nconst N = 20\n\nfn main():\n    print(N)\n"
    must_fail(src, "`N` constant is already defined.")
