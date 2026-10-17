"""std.net time limits, Poller, frames, std.packet, and the http client's timeout, redirects, and chunked bodies."""
import pytest

from tests.helpers import run_built

PACKET_SRC = r"""
import std.packet

fn main():
    w = packet.ByteWriter.new()
    w.put_u8(7)
    w.put_bool(true)
    w.put_u16(65000)
    w.put_u32(4000000000)
    w.put_u64(18000000000000000000)
    w.put_u16_be(258)
    w.put_u32_be(16909060)
    w.put_i16(-2)
    w.put_i32(-5)
    w.put_i64(-9000000000)
    w.put_f32(1.5)
    w.put_f64(-2.25)
    w.put_str("hello")
    r = packet.ByteReader.new(w.as_str())
    print(r.get_u8().value_or_panic(), r.get_bool().value_or_panic(), r.get_u16().value_or_panic(),
          r.get_u32().value_or_panic(), r.get_u64().value_or_panic())
    print(r.get_u16_be().value_or_panic(), r.get_u32_be().value_or_panic(), r.get_i16().value_or_panic(),
          r.get_i32().value_or_panic(), r.get_i64().value_or_panic(), r.get_f32().value_or_panic(),
          r.get_f64().value_or_panic())
    print(r.get_str().value_or_panic(), r.remaining(), r.get_u8().is_err())
    # a frame stream cut into one-byte pieces still yields whole messages
    fb = packet.FrameBuffer.new()
    stream = string.new()
    stream.append(packet.frame("one"))
    stream.append(packet.frame(""))
    stream.append(packet.frame("three!"))
    s = stream.as_str()
    got = 0
    for i in 0..s.len:
        fb.push(s[i..i + 1])
        while true:
            m = fb.next(100).value_or_panic()
            if m.is_none():
                break
            print("frame", m.value_or_panic())
            got += 1
    print(got, fb.pending())
    big = packet.FrameBuffer.new()
    big.push(packet.frame("0123456789").as_str())
    print(big.next(5).is_err())
"""


def test_packet_round_trip_and_frames():
    r = run_built(PACKET_SRC, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "7 true 65000 4000000000 18000000000000000000",
        "258 16909060 -2 -5 -9000000000 1.5 -2.25",
        "hello 0 true",
        "frame one",
        "frame ",
        "frame three!",
        "3 0",
        "true",
    ]


TIMEOUT_SRC = r"""
import std.net
import std.http
import std.thread
import std.time

fn timed_out[T](r: read Result[T, string]) -> bool:
    match r:
        Ok(_v): return false
        Err(e): return net.is_timeout(e.as_str())

fn quiet_server(l: net.TcpListener, hold_ms: i64):
    match consume l.accept():
        Ok(conn):
            time.sleep_millis(hold_ms)
            conn.send("late").value_or_panic()
        Err(e): print(e)

fn main():
    # a receive that waits too long is an error, and the stream stays usable
    l = net.TcpListener.bind("127.0.0.1", 0).value_or_panic()
    port = l.port()
    t = thread.Thread.spawn(fn() => quiet_server(l, 700))
    c = net.TcpStream.connect_timeout("127.0.0.1", port, 2000).value_or_panic()
    c.set_timeout(150)
    started = time.Instant.now()
    r = c.receive(10)
    waited = started.elapsed_millis()
    print(r.is_err(), timed_out(r), waited >= 100 and waited < 600)
    c.set_timeout(5000)
    print(c.receive(10).value_or_panic())
    t.join()

    # the http client gives up on a server that never answers
    l2 = net.TcpListener.bind("127.0.0.1", 0).value_or_panic()
    port2 = l2.port()
    t2 = thread.Thread.spawn(fn() => quiet_server(l2, 900))
    started2 = time.Instant.now()
    res = http.get_timeout(f"http://127.0.0.1:{port2}/x".as_str(), 200)
    waited2 = started2.elapsed_millis()
    print(res.is_err(), timed_out(res), waited2 < 800)
    t2.join()

    # connecting to a name that does not exist
    print(net.TcpStream.connect_timeout("nonexistent.invalid", 80, 1000).is_err())

    # accept_timeout / try_accept / receive_from_try with nothing there
    l3 = net.TcpListener.bind("127.0.0.1", 0).value_or_panic()
    print(l3.try_accept().value_or_panic().is_none(), l3.accept_timeout(50).value_or_panic().is_none())
    u = net.UdpSocket.bind("127.0.0.1", 0).value_or_panic()
    print(u.receive_from_try(10).value_or_panic().is_none())
    u.set_timeout(80)
    print(timed_out(u.receive_from(10)))
"""


def test_timeouts():
    r = run_built(TIMEOUT_SRC, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        "true true true",
        "late",
        "true true true",
        "true",
        "true true",
        "true",
        "true",
    ]


HTTP_SRC = r"""
import std.net
import std.http
import std.thread

fn raw_server(l: net.TcpListener, n: i32):
    for i in 0..n:
        match consume l.accept():
            Ok(conn):
                req = http.read_request(conn, 65536)
                path = match req:
                    Ok(q) => q.path.clone()
                    Err(_e) => string.from("?")
                if path.as_str() == "/a":
                    conn.send("HTTP/1.1 302 Found\r\nLocation: /dir/b\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").value_or_panic()
                elif path.as_str() == "/dir/b":
                    conn.send("HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n4\r\nWiki\r\n5;ext=1\r\npedia\r\nE\r\n in\r\nchunks.\r\n\r\n0\r\n\r\n").value_or_panic()
                elif path.as_str() == "/loop":
                    conn.send("HTTP/1.1 301 Moved\r\nLocation: /loop\r\nContent-Length: 0\r\n\r\n").value_or_panic()
                elif path.as_str() == "/nolen":
                    conn.send("HTTP/1.1 200 OK\r\n\r\nuntil close").value_or_panic()
                elif path.as_str() == "/short":
                    conn.send("HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\ntoo little").value_or_panic()
                else:
                    conn.send("HTTP/1.1 404 Not Found\r\nContent-Length: 2\r\n\r\nno").value_or_panic()
            Err(e): print(e)

fn show(url: str, port: u16):
    match http.get_timeout(f"http://127.0.0.1:{port}{url}".as_str(), 2000):
        Ok(r): print(url, r.status, r.body)
        Err(e): print(url, "error:", e)

fn main():
    l = net.TcpListener.bind("127.0.0.1", 0).value_or_panic()
    port = l.port()
    t = thread.Thread.spawn(fn() => raw_server(l, 11))
    show("/a", port)
    show("/loop", port)
    show("/nolen", port)
    show("/short", port)
    opts = http.options()
    opts.max_redirects = 0
    match http.fetch("GET", f"http://127.0.0.1:{port}/a".as_str(), "", opts):
        Ok(r): print("no follow", r.status, r.header("location"))
        Err(e): print("error", e)
    t.join()
    print(http.decode_chunked("3\r\nabc\r\n0\r\n\r\n"))
    print(http.decode_chunked("3\r\nab"))
    print(http.decode_chunked("zz\r\n"))
    print(http.get("ftp://x/").is_err())
"""


def test_http_client_redirect_chunked_and_limits():
    r = run_built(HTTP_SRC, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "/a 200 Wikipedia in" in r.stdout
    assert "/loop error: too many redirects" in r.stdout
    assert "/nolen 200 until close" in r.stdout
    assert "/short error: the connection closed before the whole body arrived" in r.stdout
    assert 'no follow 302 Valid("/dir/b")' in r.stdout
    assert 'Ok(Valid("abc"))' in r.stdout
    assert "Ok(None)" in r.stdout
    assert 'Err("bad chunk size")' in r.stdout
    assert r.stdout.rstrip().endswith("true")


SERVER_SRC = r"""
import std.net
import std.packet
import std.thread
import std.time

# One thread serves every client: a Poller waits for any socket, try_receive reads what is there, a FrameBuffer
# cuts the bytes into messages. Each client says hello with its id; when all have, everyone is told the total.
fn server(l: net.TcpListener, expected: i32):
    poller = net.Poller.new()
    poller.add(l.handle(), false)
    streams = List[net.TcpStream]()
    bufs = List[packet.FrameBuffer]()
    joined: i32 = 0
    idsum: i64 = 0
    announced = false
    left: i32 = 0
    while left < expected:
        for ev in poller.wait(2000):
            if ev.handle == l.handle():
                while true:
                    a = l.try_accept().value_or_panic()
                    if a.is_none():
                        break
                    s = a.value_or_panic()
                    poller.add(s.handle(), false)
                    streams.push(s)
                    bufs.push(packet.FrameBuffer.new())
            else:
                idx: usize = 0
                for k in 0..streams.len:
                    if streams[k].handle() == ev.handle:
                        idx = k
                chunk = streams[idx].try_receive(4096).value_or_panic()
                if chunk.is_none():
                    continue
                text = chunk.value_or_panic()
                if text.len() == 0:
                    poller.remove(ev.handle)
                    streams.swap_remove(idx)
                    bufs.swap_remove(idx)
                    left += 1
                    continue
                bufs[idx].push(text.as_str())
                while true:
                    m = bufs[idx].next(1000).value_or_panic()
                    if m.is_none():
                        break
                    r = packet.ByteReader.new(m.value_or_panic().as_str())
                    kind = r.get_u8().value_or_panic()
                    if kind == 1:
                        idsum += i64(r.get_u32().value_or_panic())
                        joined += 1
                if joined == expected and not announced:
                    announced = true
                    w = packet.ByteWriter.new()
                    w.put_u8(2)
                    w.put_u32(u32(joined))
                    w.put_i64(idsum)
                    for k in 0..streams.len:
                        streams[k].send_frame(w.as_str()).value_or_panic()
    print("server done", joined, idsum)

fn client(port: u16, id: u32):
    c = net.TcpStream.connect_timeout("127.0.0.1", port, 3000).value_or_panic()
    c.set_timeout(10000)
    w = packet.ByteWriter.new()
    w.put_u8(1)
    w.put_u32(id)
    c.send_frame(w.as_str()).value_or_panic()
    msg = c.receive_frame(1000).value_or_panic()
    r = packet.ByteReader.new(msg.as_str())
    kind = r.get_u8().value_or_panic()
    total = r.get_u32().value_or_panic()
    sum = r.get_i64().value_or_panic()
    if kind != 2 or total != 40 or sum != 820:
        print("client", id, "got", kind, total, sum)

fn main():
    l = net.TcpListener.bind("127.0.0.1", 0).value_or_panic()
    port = l.port()
    srv = thread.Thread.spawn(fn() => server(l, 40))
    clients = List[thread.Thread]()
    for i in 0..40:
        id = u32(i + 1)
        clients.push(thread.Thread.spawn(fn() => client(port, id)))
    for t in clients:
        t.join()
    srv.join()
"""


def test_single_thread_server_with_forty_clients():
    r = run_built(SERVER_SRC, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["server done 40 820"]


UDP_SRC = r"""
import std.net
import std.packet

# A UDP "game server" step: drain every datagram that is waiting, update state, reply to each sender.
fn main():
    srv = net.UdpSocket.bind("127.0.0.1", 0).value_or_panic()
    srv.set_buffers(1048576, 1048576)
    cl = net.UdpSocket.bind("127.0.0.1", 0).value_or_panic()
    cl.set_timeout(1000)
    for i in 0..5:
        w = packet.ByteWriter.new()
        w.put_u32(u32(i))
        w.put_f32(f32(i) * 0.5)
        cl.send_to(w.as_str(), "127.0.0.1", srv.port()).value_or_panic()
    p = net.Poller.new()
    p.add(srv.handle(), false)
    p.wait(1000)
    handled = 0
    sum: f32 = 0.0
    while true:
        d = srv.receive_from_try(64).value_or_panic()
        if d.is_none():
            break
        dg = d.value_or_panic()
        r = packet.ByteReader.new(dg.data.as_str())
        r.get_u32().value_or_panic()
        sum += r.get_f32().value_or_panic()
        srv.reply(dg, "ack").value_or_panic()
        handled += 1
    print(handled, sum)
    acks = 0
    for i in 0..5:
        if cl.receive_from(10).value_or_panic().data.as_str() == "ack":
            acks += 1
    print(acks)
"""


def test_udp_drain_loop_and_reply():
    r = run_built(UDP_SRC, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["5 5", "5"]


def _online() -> bool:
    import socket
    try:
        socket.create_connection(("example.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


HTTPS_SRC = r"""
import std.http

fn try(url: str):
    match http.get_timeout(url, 10000):
        Ok(r): print("ok", r.status)
        Err(e): print("failed", e)

fn main():
    try("https://example.com/")
    try("https://expired.badssl.com/")
    try("https://wrong.host.badssl.com/")
"""


@pytest.mark.skipif(not _online(), reason="no internet")
def test_https_checks_certificates():
    r = run_built(HTTPS_SRC, timeout=90)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "ok 200"
    assert lines[1].startswith("failed TLS handshake with expired.badssl.com")
    assert lines[2].startswith("failed TLS handshake with wrong.host.badssl.com")


STALL_SRC = r"""
import std.net
import std.http
import std.thread
import std.time

struct App:
    n: i32

impl App:
    fn handle(self: read Self, req: read http.Request) -> http.Response:
        return http.response(200, "served")

fn clients(port: u16):
    # connects and says nothing: the server must give up on it
    silent = net.TcpStream.connect("127.0.0.1", port).value_or_panic()
    match http.get_timeout(f"http://127.0.0.1:{port}/".as_str(), 3000):
        Ok(r): print(r.status, r.body)
        Err(e): print("error", e)
    silent.set_timeout(2000)
    print(silent.receive(100).value_or_panic())

fn main():
    l = net.TcpListener.bind("127.0.0.1", 0).value_or_panic()
    port = l.port()
    t = thread.Thread.spawn(fn() => clients(port))
    http.serve_with(l, App{ n: 0 }, 2, 200)
    t.join()
"""


def test_server_drops_a_stalled_client():
    r = run_built(STALL_SRC, timeout=60)
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert lines[0] == "200 served"
    assert lines[1].startswith("HTTP/1.1 400")
