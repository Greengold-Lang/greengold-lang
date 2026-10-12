"""std.tasks and `async fn` / `await`: tasks that take turns on one thread (fibers / ucontext)."""

from tests.helpers import run_built

BASICS = r"""
import std.tasks
import std.time

async fn twice(n: i32) -> i32:
    tasks.sleep(100)
    return n * 2

async fn greet(name: string, times: i32) -> string:
    out = string.new()
    for i in 0..times:
        out.append(f"{name}{i} ")
        tasks.yield_now()
    return out

async fn log(msg: string):
    print("log:", msg)

async fn sum_children(n: i32) -> i32:
    total = 0
    for i in 0..n:
        total += await twice(i)
    return total

fn main():
    t = time.Instant.now()
    a = twice(1)
    b = twice(2)
    c = twice(3)
    print(await a + await b + await c)
    print(t.elapsed_millis() < 250)
    g1 = greet(string.from("x"), 3)
    g2 = greet(string.from("y"), 3)
    print(await g1, await g2)
    await log(string.from("done"))
    print(await sum_children(4))
    h = tasks.spawn(fn() -> string => string.from("spawned"))
    print(h.is_done(), await h)
"""

MANY = r"""
import std.tasks

async fn echo[T](x: T) -> T:
    tasks.yield_now()
    return x

async fn count(n: i64) -> i64:
    tasks.sleep(1)
    return n

async fn noisy(tag: string):
    tasks.sleep(5)
    print("finished", tag)

fn main():
    print(await echo(5), await echo(string.from("s")))
    if true:
        t = noisy(string.from("dropped"))
        print("before drop")
    print("after drop")
    hs = List[tasks.Task[i64]]()
    for i in 0..2000:
        hs.push(count(i))
    total: i64 = 0
    while hs.len > 0:
        match consume hs.pop():
            Valid(h): total += await h
            None: pass
    print(total)
"""

SOCKETS = r"""
import std.net
import std.tasks

# Answers one connection: reads a line and sends it back upper-cased.
async fn serve_one(stream: net.TcpStream) -> i32:
    match stream.receive_async(100):
        Ok(text):
            sent = stream.send(text.as_str().to_upper().as_str())
            return i32(text.len())
        Err(_e): return -1

async fn server(listener: net.TcpListener, clients: i32) -> i32:
    handlers = List[tasks.Task[i32]]()
    for _i in 0..clients:
        match consume listener.accept_async():
            Ok(s): handlers.push(serve_one(s))
            Err(_e): pass
    total = 0
    while handlers.len > 0:
        match consume handlers.pop():
            Valid(h): total += await h
            None: pass
    return total

async fn client(port: u16, word: string) -> string:
    match consume net.TcpStream.connect("127.0.0.1", port):
        Ok(c):
            tasks.sleep(20)  # every client waits at once
            sent = c.send(word.as_str())
            match consume c.receive_async(100):
                Ok(back): return back
                Err(e): return e
        Err(e): return e

fn main():
    match consume net.TcpListener.bind("127.0.0.1", 0):
        Ok(l):
            port = l.port()
            srv = server(l, 3)
            a = client(port, string.from("one"))
            b = client(port, string.from("two"))
            c = client(port, string.from("three"))
            print(await a, await b, await c, await srv)
        Err(e): print(e)
"""

ERRORS = r"""
async fn a(xs: read List[i32]) -> usize:
    return xs.len

async fn b(s: str) -> usize:
    return s.len

struct P:
    x: i32

impl P:
    async fn m(self) -> i32:
        return self.x

fn main():
    print(await b("x"))
"""


def test_async_fn_await_sleep_and_yield(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(BASICS, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    # three 100 ms sleeps run at the same time: well under 300 ms in all (loose, CI machines are slow)
    assert r.stdout.splitlines() == ["12", "true", "x0 x1 x2  y0 y1 y2 ", "log: done", "12", "false spawned"]


def test_generic_async_fn_dropped_task_and_many_tasks(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(MANY, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["5 s", "before drop", "finished dropped", "after drop", "1999000"]


def test_tasks_wait_for_sockets(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SOCKETS, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.strip() == "ONE TWO THREE 11"


def test_async_fn_errors(tmp_path):
    from greengold.cli import analyze
    src = tmp_path / "bad.gg"
    src.write_text(ERRORS, encoding="utf-8")
    _p, _s, diags, _c = analyze([str(src)])
    codes = sorted(d.code for d in diags.items if d.severity == "error")
    assert codes == ["GG0134", "GG0326", "GG0328"], [d.message for d in diags.items]


def test_return_inside_a_match_on_a_temporary_frees_it(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(r"""
fn make() -> Result[string, string]:
    return Ok(string.from("hello"))

fn a() -> i32:
    match make():
        Ok(text):
            return i32(text.len())
        Err(_e): return -1

fn b() -> i32:
    match consume make():
        Ok(text):
            return i32(text.len())
        Err(_e): return -1

fn main():
    print(a(), b())
""")
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.strip() == "5 5"


def test_lambda_passed_to_a_generic_fn_parameter_owns_its_captures(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(r"""
fn keep(body: send Fn() -> string) -> string:
    return body()

fn keep_g[T](body: send Fn() -> T) -> T:
    return body()

fn greet(n: string) -> string:
    return f"hi {n}"

fn main():
    a = string.from("x")
    print(keep(fn() -> string => greet(a)))
    b = string.from("y")
    print(keep_g(fn() -> string => greet(b)))
""")
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == ["hi x", "hi y"]
