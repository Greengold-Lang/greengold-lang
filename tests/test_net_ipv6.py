"""std.net over IPv6 (loopback), including a dual-stack listener."""
import socket

import pytest

from tests.helpers import run_gg_source

PROGRAM = r'''import std.net
import std.thread { Thread }

fn main():
    l = net.TcpListener.bind("::1", 0).value_or_panic()
    port = l.port()
    t = Thread.spawn(fn() => client(port))
    s = l.accept().value_or_panic()
    peer = s.peer_addr().value_or_panic()
    print(peer.host)
    msg = s.receive(100).value_or_panic()
    s.send(msg.as_str()).value_or_panic()
    t.join()
    u = net.UdpSocket.bind("::1", 0).value_or_panic()
    up = u.port()
    c = net.UdpSocket.bind("::1", 0).value_or_panic()
    c.send_to("ping6", "::1", up).value_or_panic()
    d = u.receive_from(100).value_or_panic()
    print(d.data, d.host)
    l4 = net.TcpListener.bind("::", 0).value_or_panic()
    p4 = l4.port()
    t2 = Thread.spawn(fn() => client4(p4))
    s4 = l4.accept().value_or_panic()
    print(s4.peer_addr().value_or_panic().host)
    t2.join()

fn client(port: u16):
    c = net.TcpStream.connect("::1", port).value_or_panic()
    c.send("hello v6").value_or_panic()
    print(c.receive(100).value_or_panic())

fn client4(port: u16):
    c = net.TcpStream.connect("127.0.0.1", port).value_or_panic()
    c.send("x").value_or_panic()
'''


def _ipv6_loopback_works():
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.bind(("::1", 0))
        s.close()
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _ipv6_loopback_works(), reason="no IPv6 loopback on this machine")
def test_ipv6_tcp_udp_and_dual_stack(tmp_path):
    r = run_gg_source(tmp_path, PROGRAM)
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == ["::1", "hello v6", "ping6 ::1", "127.0.0.1"]
