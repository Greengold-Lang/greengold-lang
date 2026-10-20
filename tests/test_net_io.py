"""std.net (TCP) and std.io (streamed files), plus `target_os()` and `weak extern`."""
import pytest

from greengold.cli import compile_to_ir

from .helpers import HAS_CC, run_built


@pytest.mark.skipif(not HAS_CC, reason="no C toolchain to link")
def test_tcp_echo_between_threads():
    src = """import std.net { TcpListener, TcpStream }
import std.thread { Thread }

fn serve(l: TcpListener):
    match consume l.accept():
        Ok(conn):
            msg = conn.receive(100).value_or_panic()
            reply = f"echo {msg}"
            conn.send(reply.as_str()).value_or_panic()
        Err(e):
            print(e)

fn main():
    listener = TcpListener.bind("127.0.0.1", 0).value_or_panic()
    port = listener.port()
    server = Thread.spawn(fn() => serve(listener))
    client = TcpStream.connect("localhost", port).value_or_panic()
    client.send("ping").value_or_panic()
    print(client.receive_all().value_or_panic())
    server.join()
    print(TcpStream.connect("not.an.ip", 1).is_err())
"""
    res = run_built(src, timeout=30)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["echo ping", "true"]


@pytest.mark.skipif(not HAS_CC, reason="no C toolchain to link")
def test_file_stream(tmp_path):
    path = (tmp_path / "t.txt").as_posix()
    src = f"""import std.io {{ File }}

fn main():
    if true:
        f = File.create("{path}").value_or_panic()
        f.write_line("first").value_or_panic()
        f.write("second\\r\\nthird").value_or_panic()
    g = File.open("{path}").value_or_panic()
    while true:
        line = g.read_line().value_or_panic()
        if line.is_none():
            break
        print(line.value_or_panic())
    h = File.open("{path}").value_or_panic()
    print(h.read_rest().value_or_panic().len)
    a = File.append("{path}").value_or_panic()
    a.write("!").value_or_panic()
    a.flush()
    k = File.open("{path}").value_or_panic()
    print(k.read_rest().value_or_panic().len)
"""
    res = run_built(src)
    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines() == ["first", "second", "third", "19", "20"]


def test_target_constants_and_weak_externs():
    from greengold.codegen_llvm import target_arch, target_os
    assert target_os("x86_64-pc-linux-gnu") == "linux"
    assert target_os("aarch64-apple-darwin") == "macos"
    assert target_os("x86_64-w64-windows-gnu") == "windows"
    assert target_os("thumbv7em-none-eabi") == "none"
    assert target_arch("arm64-apple-macosx") == "aarch64"
    ir_text = compile_to_ir('weak extern "x.h" fn only_here(x: i32) -> i32\n\nfn main():\n    print(target_os())\n'
                            '    if target_os() == "plan9":\n        unsafe:\n            only_here(1)\n')
    assert "only_here" in ir_text
