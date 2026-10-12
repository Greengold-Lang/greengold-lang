"""std.http (requests, responses, serve, client) and std.net UDP; slicing an empty string."""
from tests.helpers import run_built

SRC = r"""
import std.net
import std.http
import std.thread

struct App:
    tag: string

impl App:
    fn handle(self: read Self, req: read http.Request) -> http.Response:
        name = match req.query_param("name"):
            Valid(n) => n.clone()
            None => string.from("nobody")
        if req.path.as_str() == "/missing":
            return http.response(404, "no such page")
        r = http.response(200, f"{req.method} {req.path} hello {name} body={req.body}".as_str())
        r.set_header("X-Test", self.tag.as_str())
        return r

fn client(port: u16):
    base = f"http://127.0.0.1:{port}"
    match http.get(f"{base}/greet?name=Ada%20L&x=1".as_str()):
        Ok(r): print(r.status, r.body, r.header("x-test"), r.header("content-length"))
        Err(e): print("error", e)
    match http.request("POST", f"{base}/submit".as_str(), "a=1"):
        Ok(r): print(r.status, r.body)
        Err(e): print("error", e)
    match http.get(f"{base}/missing".as_str()):
        Ok(r): print(r.status, r.body)
        Err(e): print("error", e)

fn main():
    print(http.parse_request("GET /a%20b?q=1 HTTP/1.1\r\nHost: x\r\nContent-Length: 2\r\n\r\nhi"))
    print(http.parse_request("nonsense"), http.url_encode("a b&c/é"), http.url_decode("a+b%2Fc"))
    match net.TcpListener.bind("127.0.0.1", 0):
        Ok(listener):
            port = listener.port()
            t = thread.Thread.spawn(fn() => client(port))
            http.serve(listener, App{ tag: string.from("yes") }, 3)
            t.join()
        Err(e): print(e)
    match net.UdpSocket.bind("127.0.0.1", 0):
        Ok(a):
            match net.UdpSocket.bind("127.0.0.1", 0):
                Ok(b):
                    sent = a.send_to("ping", "127.0.0.1", b.port())
                    match b.receive_from(100):
                        Ok(d): print(d.data, d.host, d.port == a.port(), sent)
                        Err(e): print(e)
                Err(e): print(e)
        Err(e): print(e)
"""


def test_http_server_client_and_udp(monkeypatch):
    monkeypatch.setenv("GG_LEAKCHECK", "1")
    r = run_built(SRC, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "LEAK" not in r.stderr
    assert r.stdout.splitlines() == [
        'Ok(Request { method: "GET", path: "/a b", query: "q=1", version: "HTTP/1.1", headers: [Header { name: '
        '"Host", value: "x" }, Header { name: "Content-Length", value: "2" }], body: "hi" })',
        'Err("the request has no blank line after its headers") a%20b%26c%2F%C3%A9 a b/c',
        '200 GET /greet hello Ada L body= Valid("yes") Valid("28")',
        "200 POST /submit hello nobody body=a=1",
        "404 no such page",
        "ping 127.0.0.1 true Ok(4)",
    ]


def test_slicing_an_empty_string_does_not_read_its_missing_buffer():
    src = """fn main():
    e = string.new()
    v = e.as_str()
    print(v[0..].len, v[..0].len, v.split("&").len, e.as_str().trim().len)
"""
    r = run_built(src)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "0 0 1 0"
