"""A constant or static may hold function addresses (interrupt vector tables).

Spec: 14
"""
import subprocess
import sys

from tests.helpers import ROOT, run_gg_source


def test_const_table_of_functions_runs(tmp_path):
    r = run_gg_source(tmp_path, """fn on_reset():
    print("reset")

fn on_tick():
    print("tick")

const TABLE: [2]fn() = [on_reset, on_tick]

struct Ops:
    first: fn()
    second: fn()

const OPS: Ops = Ops{ first: on_tick, second: on_reset }

fn main():
    f = TABLE[1]
    f()
    g = OPS.second
    g()
""")
    assert r.returncode == 0, r.stderr
    assert r.stdout.split() == ["tick", "reset"]


def test_isr_table_static_lands_in_its_section_for_cortex_m(tmp_path):
    src = tmp_path / "v.gg"
    src.write_text("""fn uart_irq():
    pass

fn timer_irq():
    pass

@section(".isr_vector")
@used
static IRQ_TABLE: [2]fn() = [uart_irq, timer_irq]

fn main():
    pass
""", encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "greengold", "emit-ll", str(src), "--no-std", "--target", "cortex-m4"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    line = next(ln for ln in r.stdout.splitlines() if ln.startswith('@"gg_const_IRQ_TABLE"'))
    assert 'section ".isr_vector"' in line and "@\"gg_uart_irq\"" in line and "@\"gg_timer_irq\"" in line


def test_generic_and_unknown_names_are_still_rejected(tmp_path):
    r = run_gg_source(tmp_path, """fn id[T](x: T) -> T:
    return x

const BAD: i32 = missing

fn main():
    pass
""")
    assert r.returncode != 0 and "missing" in r.stderr
