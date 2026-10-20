"""tools/svd2gg.py: a small SVD file becomes a module that std.mmio can use."""
import subprocess
import sys

from tests.helpers import ROOT, run_gg_source

SVD = """<?xml version="1.0"?>
<device>
  <name>TOY1</name>
  <size>32</size>
  <peripherals>
    <peripheral>
      <name>GPIOA</name>
      <baseAddress>0x1000</baseAddress>
      <registers>
        <register><name>MODER</name><addressOffset>0x0</addressOffset>
          <fields><field><name>MODE5</name><bitOffset>10</bitOffset><bitWidth>2</bitWidth></field></fields></register>
        <register><name>ODR</name><description>Output data register</description><addressOffset>0x14</addressOffset>
          <fields><field><name>OD5</name><bitOffset>5</bitOffset><bitWidth>1</bitWidth></field></fields></register>
        <register><name>AFR%s</name><dim>2</dim><dimIncrement>4</dimIncrement><dimIndex>L,H</dimIndex><addressOffset>0x20</addressOffset></register>
      </registers>
    </peripheral>
    <peripheral derivedFrom="GPIOA"><name>GPIOB</name><baseAddress>0x2000</baseAddress></peripheral>
    <peripheral>
      <name>TIM</name><baseAddress>0x3000</baseAddress>
      <registers><cluster><name>CH%s</name><dim>2</dim><dimIncrement>0x10</dimIncrement><addressOffset>0x40</addressOffset>
        <register><name>CCR</name><addressOffset>0x8</addressOffset><size>16</size></register></cluster></registers>
    </peripheral>
  </peripherals>
</device>
"""


def test_svd_becomes_a_module(tmp_path):
    svd = tmp_path / "toy.svd"
    svd.write_text(SVD, encoding="utf-8")
    out = tmp_path / "toy.gg"
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "svd2gg.py"), str(svd), "-o", str(out)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    text = out.read_text(encoding="utf-8")
    assert "const GPIOA_BASE: usize = 0x1000" in text
    assert "fn gpioa_odr() -> Reg[u32]" in text and "return reg32(0x1014)" in text
    assert "fn gpiob_odr() -> Reg[u32]" in text and "return reg32(0x2014)" in text
    assert "fn gpioa_afrl()" in text and "0x1020" in text and "0x1024" in text
    assert "fn tim_ch0_ccr() -> Reg[u16]" in text and "reg16(0x3048)" in text and "reg16(0x3058)" in text
    # the module compiles and its registers work against ordinary memory
    (tmp_path / "toy.gg").write_text(text.replace("0x1014", "0x1014"), encoding="utf-8")
    r2 = run_gg_source(tmp_path, "import toy { gpioa_odr_od5, gpioa_moder_mode5, gpioa_odr, GPIOA_BASE }\n\nfn main():\n"
                                 "    print(GPIOA_BASE, gpioa_odr_od5().shift, gpioa_odr_od5().width, gpioa_moder_mode5().shift, gpioa_moder_mode5().width)\n")
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout.strip() == "4096 5 1 10 2"
