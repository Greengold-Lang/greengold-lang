"""The libraries in packages/ (units, linalg, geo, dsp, protocols) pass their own tests, and the protocol bytes agree with an
independent implementation written here in Python.

Spec: 16
"""
import subprocess
import sys

import pytest

from tests.helpers import ROOT, run_gg_source

PACKAGES = ["gg-units", "gg-linalg", "gg-geo", "gg-dsp", "gg-protocols"]


@pytest.mark.parametrize("package", PACKAGES)
def test_package_tests_pass(package):
    r = subprocess.run([sys.executable, "-m", "greengold", "test", f"packages/{package}/tests"], capture_output=True, text=True,
                       cwd=ROOT, encoding="utf-8", timeout=600)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "0 failed" in r.stdout


@pytest.mark.parametrize("package", PACKAGES)
def test_package_manifest_is_valid(package):
    from greengold.tools import load_manifest
    m = load_manifest(ROOT / "packages" / package / "gg.toml")
    assert m.name == package.removeprefix("gg-") and m.version == "0.1.0"
    assert m.main.is_file()
    assert (ROOT / "packages" / package / "README.md").is_file()


def test_units_refuse_to_mix_quantities(tmp_path):
    src = ROOT / "packages" / "gg-units" / "src" / "units.gg"
    r = run_gg_source(tmp_path, f'import "{src.as_posix()}"\n\nfn main():\n    x = units.metres(1.0) + units.knots(1.0)\n')
    assert r.returncode != 0 and "Length" in r.stderr


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc16_mcrf4xx(data: bytes, extra: int) -> int:
    crc = 0xFFFF
    for b in data + bytes([extra]):
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    return crc


def test_ccsds_and_mavlink_bytes_match_python_reference(tmp_path):
    base = (ROOT / "packages" / "gg-protocols" / "src").as_posix()
    r = run_gg_source(tmp_path, f'''import "{base}/ccsds.gg"
import "{base}/mavlink.gg"

fn show(bytes: List[u8]):
    for b in bytes:
        print(i32(b))
    print(-1)

fn main():
    h = ccsds.PacketHeader{{ version: 0, is_command: false, secondary_header: true, apid: 100, seq_flags: 3, seq_count: 513 }}
    payload: [4]u8 = [10, 20, 30, 40]
    show(ccsds.build_packet(h, payload[..], true))
    body = List[u8]()
    for b in [1, 2, 3, 0, 0, 7]:
        body.push(u8(b))
    f = mavlink.Frame{{ sysid: 42, compid: 7, msgid: 300, seq: 9, payload: body, incompat_flags: 0, compat_flags: 0 }}
    show(mavlink.build_v2(f, 99))
''')
    assert r.returncode == 0, r.stderr
    parts = [[int(x) for x in chunk.split()] for chunk in r.stdout.split("-1") if chunk.strip()]
    ccsds_bytes, mav_bytes = bytes(parts[0]), bytes(parts[1])
    first = (1 << 11) | 100                       # version 0, telemetry, secondary header, APID 100
    second = (3 << 14) | 513                      # unsegmented, sequence count 513
    head = first.to_bytes(2, "big") + second.to_bytes(2, "big") + (4 + 2 - 1).to_bytes(2, "big") + bytes([10, 20, 30, 40])
    assert ccsds_bytes == head + crc16_ccitt_false(head).to_bytes(2, "big")
    body = bytes([1, 2, 3, 0, 0, 7])
    frame = bytes([0xFD, len(body), 0, 0, 9, 42, 7, 300 & 255, (300 >> 8) & 255, 0]) + body
    assert mav_bytes == frame + crc16_mcrf4xx(frame[1:], 99).to_bytes(2, "little")
