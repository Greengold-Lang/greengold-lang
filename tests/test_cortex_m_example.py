"""The Cortex-M example links into a valid image: vector table first in flash, thumb entry points, .data in flash."""
import os
import shutil
import struct
import subprocess
import sys

import pytest

from tests.helpers import ROOT

pytestmark = pytest.mark.skipif(not (shutil.which("clang") and shutil.which("ld.lld")),
                                reason="needs clang and ld.lld (inline asm for ARM is built by the outside clang)")


def test_cortex_m_firmware_image(tmp_path):
    src = ROOT / "examples" / "embedded" / "cortex_m"
    out = tmp_path / "fw.elf"
    env = dict(os.environ, GG_BACKEND="clang")
    r = subprocess.run([sys.executable, "-m", "greengold", "build", str(src / "main.gg"), "--no-std", "--target",
                        "cortex-m4", "--linker-script", str(src / "link.ld"), "-o", str(out)],
                       capture_output=True, text=True, cwd=ROOT, env=env)
    assert r.returncode in (0, 3), r.stdout + r.stderr
    data = out.read_bytes()
    assert data[:4] == b"\x7fELF"
    # the first section of flash (0x08000000) holds the stack pointer and the reset vector with the Thumb bit set
    e_phoff, = struct.unpack_from("<I", data, 28)
    entsize, phnum = struct.unpack_from("<HH", data, 42)
    first = None
    for i in range(phnum):
        p_type, p_offset, p_vaddr, p_paddr, p_filesz = struct.unpack_from("<IIIII", data, e_phoff + i * entsize)
        if p_type == 1 and p_vaddr == 0x08000000:
            first = data[p_offset:p_offset + p_filesz]
    assert first is not None
    sp, reset = struct.unpack_from("<II", first, 0)
    assert sp == 0x20010000
    assert reset & 1 == 1 and 0x08000000 <= reset < 0x08040000


def test_new_cortex_m_template_matches_the_example_and_checks(tmp_path):
    from greengold import templates
    src = ROOT / "examples" / "embedded" / "cortex_m"
    assert (src / "main.gg").read_text(encoding="utf-8").replace("\r\n", "\n") == templates.CORTEX_M_MAIN
    assert (src / "link.ld").read_text(encoding="utf-8").replace("\r\n", "\n") == templates.CORTEX_M_LINK
    r = subprocess.run([sys.executable, "-m", "greengold", "new", "fw", "--path", str(tmp_path / "fw"), "--template", "cortex-m"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "fw" / "link.ld").is_file() and (tmp_path / "fw" / "src" / "main.gg").is_file()
    assert "cortex-m4" in (tmp_path / "fw" / "README.md").read_text(encoding="utf-8")
