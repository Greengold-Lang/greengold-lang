"""svd2gg: turn a CMSIS-SVD file (the register description that chip vendors publish) into a Greengold module.

    python tools/svd2gg.py STM32F407.svd -o stm32f407.gg

For a peripheral GPIOA with a register ODR that has a field OD5 the module has

    const GPIOA_BASE: usize = 0x40020000
    fn gpioa_odr() -> Reg[u32]            # the register at GPIOA_BASE + 0x14
    fn gpioa_odr_od5() -> Field           # bits 5..5 of it

and the program uses them with `std.mmio`:

    import stm32f407 { gpioa_odr, gpioa_odr_od5 }
    gpioa_odr().set_field(gpioa_odr_od5(), 1)

Peripherals that derive from another (`derivedFrom`) get their own base address with the registers of the original.
Clusters and register arrays (`%s` names, `dim`) are expanded. Names are lower-cased with `_` between parts, and a name that
is a Greengold keyword gets a trailing `_`.
"""
from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET

KEYWORDS = {"fn", "if", "else", "elif", "for", "while", "in", "let", "return", "match", "const", "static", "struct", "enum",
            "impl", "import", "public", "private", "read", "lend", "consume", "true", "false", "and", "or", "not", "break",
            "continue", "defer", "step", "as", "unsafe", "feature", "dyn", "test", "require", "yield", "extern", "union",
            "packed", "weak", "type", "async", "await", "soa", "hot", "wrapping", "overflow", "trust", "allocator",
            "comptime", "attribute", "on", "copy", "fixed", "send", "tied", "to"}


def num(text: str | None, default: int = 0) -> int:
    if text is None:
        return default
    text = text.strip()
    if text.startswith(("0x", "0X")):
        return int(text, 16)
    if text.startswith("#"):
        return int(text[1:], 2)
    return int(text)


def text_of(node: ET.Element, tag: str, default: str | None = None) -> str | None:
    child = node.find(tag)
    return child.text.strip() if child is not None and child.text else default


def ident(name: str) -> str:
    s = re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s).lower()
    if not s or s[0].isdigit():
        s = "_" + s
    return s + "_" if s in KEYWORDS else s


def expand_dim(node: ET.Element, base_name: str) -> list[tuple[str, int]]:
    """(name, offset-added) pairs for an element with <dim>, or just the element itself."""
    dim = text_of(node, "dim")
    if dim is None:
        return [(base_name, 0)]
    count = num(dim)
    inc = num(text_of(node, "dimIncrement"), 0)
    idx_text = text_of(node, "dimIndex")
    if idx_text and "," in idx_text:
        indexes = [i.strip() for i in idx_text.split(",")]
    elif idx_text and "-" in idx_text and re.fullmatch(r"\d+-\d+", idx_text):
        lo, hi = idx_text.split("-")
        indexes = [str(i) for i in range(int(lo), int(hi) + 1)]
    else:
        indexes = [str(i) for i in range(count)]
    out = []
    for i, label in enumerate(indexes[:count]):
        out.append((base_name.replace("[%s]", label).replace("%s", label), i * inc))
    return out


class Emitter:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.seen: set[str] = set()

    def unique(self, name: str) -> str:
        n, k = name, 2
        while n in self.seen:
            n = f"{name}_{k}"
            k += 1
        self.seen.add(n)
        return n

    def register(self, periph: str, name: str, address: int, size: int, fields: list[tuple[str, int, int]], doc: str) -> None:
        fn = self.unique(f"{ident(periph)}_{ident(name)}")
        ty = {8: "u8", 16: "u16", 32: "u32", 64: "u64"}.get(size, "u32")
        reg = {"u8": "reg8", "u16": "reg16", "u32": "reg32", "u64": "reg64"}[ty]
        if doc:
            self.lines.append(f"# {doc}")
        self.lines.append(f"fn {fn}() -> Reg[{ty}]:")
        self.lines.append(f"    return {reg}(0x{address:X})")
        self.lines.append("")
        for fname, shift, width in fields:
            self.lines.append(f"fn {self.unique(fn + '_' + ident(fname))}() -> Field:")
            self.lines.append(f"    return Field.new({shift}, {width})")
            self.lines.append("")


def registers_of(node: ET.Element, base: int, prefix: str, default_size: int, out: Emitter, periph: str) -> None:
    for child in node:
        if child.tag == "register":
            name = text_of(child, "name", "reg") or "reg"
            size = num(text_of(child, "size"), default_size)
            for expanded, extra in expand_dim(child, name):
                offset = num(text_of(child, "addressOffset"))
                fields = []
                for f in child.iterfind("fields/field"):
                    fname = text_of(f, "name", "f") or "f"
                    if text_of(f, "bitRange"):
                        m = re.match(r"\[(\d+):(\d+)\]", text_of(f, "bitRange") or "")
                        lsb, width = (int(m.group(2)), int(m.group(1)) - int(m.group(2)) + 1) if m else (0, 1)
                    else:
                        lsb = num(text_of(f, "bitOffset"))
                        width = num(text_of(f, "bitWidth"), 1)
                    fields.append((fname, lsb, width))
                out.register(periph, prefix + expanded, base + offset + extra, size, fields,
                             (text_of(child, "description", "") or "").split("\n")[0][:100])
        elif child.tag == "cluster":
            cname = text_of(child, "name", "cluster") or "cluster"
            for expanded, extra in expand_dim(child, cname):
                registers_of(child, base + num(text_of(child, "addressOffset")) + extra, prefix + expanded + "_",
                             default_size, out, periph)


def convert(svd_text: str) -> str:
    root = ET.fromstring(svd_text)
    device = text_of(root, "name", "device") or "device"
    default_size = num(text_of(root, "size"), 32)
    out = Emitter()
    peripherals = {text_of(p, "name"): p for p in root.iterfind("peripherals/peripheral")}
    head = [
        f"# Registers of {device}, generated by tools/svd2gg.py from the vendor's SVD file. Do not edit by hand.",
        "import std.mmio { Reg, Field, reg8, reg16, reg32, reg64 }",
        "",
    ]
    body: list[str] = []
    for name, p in peripherals.items():
        base = num(text_of(p, "baseAddress"))
        body.append(f"const {ident(name).upper()}_BASE: usize = 0x{base:X}")
    body.append("")
    out.lines = body
    for name, p in peripherals.items():
        source = p
        derived = p.get("derivedFrom")
        if derived and derived in peripherals and p.find("registers") is None:
            source = peripherals[derived]
        base = num(text_of(p, "baseAddress"))
        regs = source.find("registers")
        if regs is None:
            continue
        registers_of(regs, base, "", default_size, out, name)
    return "\n".join(head + out.lines).rstrip("\n") + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("svd", help="the .svd file")
    ap.add_argument("-o", "--output", help="the .gg module to write (default: standard output)")
    args = ap.parse_args(argv)
    text = open(args.svd, encoding="utf-8").read()
    result = convert(text)
    if args.output:
        open(args.output, "w", encoding="utf-8").write(result)
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
