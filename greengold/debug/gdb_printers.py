"""gdb pretty printers for Greengold programs built with `gg build -g`.

Load with `source <path>` in gdb (`gg debug-scripts` prints the path), or add that line to `~/.gdbinit`.
`string` and `str` print as text, `List[T]`, `[]T`, and `HashMap[K, V]` as their elements, `Box[T]` as its
value, and an enum as `Variant(values)`.
"""
import re

import gdb  # type: ignore[import-not-found]


def _name(val):
    t = val.type.strip_typedefs()
    return t.tag or t.name or ""


def _text(ptr, length):
    if int(length) == 0:
        return '""'
    data = bytes(gdb.selected_inferior().read_memory(ptr, int(length)))
    return '"' + data.decode("utf-8", "replace").replace("\\", "\\\\").replace('"', '\\"') + '"'


class StrPrinter:
    """`str`: a `{ptr, len}` view."""

    def __init__(self, val):
        self.val = val

    def to_string(self):
        return _text(self.val["ptr"], self.val["len"])


class StringPrinter:
    """`string`: the bytes of its `List[u8]`."""

    def __init__(self, val):
        self.val = val["bytes"]

    def to_string(self):
        return _text(self.val["ptr"], self.val["len"])


class ListPrinter:
    """`List[T]` and slices `[]T`: their `len` elements."""

    def __init__(self, val):
        self.val = val

    def to_string(self):
        n = int(self.val["len"])
        return f"{_name(self.val)} (len {n})"

    def children(self):
        ptr = self.val["ptr"]
        for i in range(int(self.val["len"])):
            yield f"[{i}]", (ptr + i).dereference()

    def display_hint(self):
        return "array"


class HashMapPrinter:
    """`HashMap[K, V]`: keys and values are stored densely in `ks` and `vs`."""

    def __init__(self, val):
        self.val = val

    def to_string(self):
        return f"{_name(self.val)} (len {int(self.val['ks']['len'])})"

    def children(self):
        ks, vs = self.val["ks"], self.val["vs"]
        for i in range(int(ks["len"])):
            yield f"k{i}", (ks["ptr"] + i).dereference()
            yield f"v{i}", (vs["ptr"] + i).dereference()

    def display_hint(self):
        return "map"


class HashSetPrinter:
    def __init__(self, val):
        self.val = val["map"]["ks"]

    def to_string(self):
        return f"HashSet (len {int(self.val['len'])})"

    def children(self):
        for i in range(int(self.val["len"])):
            yield f"[{i}]", (self.val["ptr"] + i).dereference()

    def display_hint(self):
        return "array"


class BoxPrinter:
    def __init__(self, val):
        self.val = val

    def to_string(self):
        ptr = self.val["ptr"]
        if int(ptr) == 0:
            return "Box(null)"
        try:
            return f"Box({ptr.dereference().format_string()})"
        except gdb.error:
            return f"Box({ptr})"


class EnumPrinter:
    """An enum: `{tag, payload}` where the payload is a union with one member per variant with values."""

    def __init__(self, val):
        self.val = val

    def to_string(self):
        tag = self.val["tag"]
        variant = tag.format_string()
        payload = self._payload(variant)
        if payload is None:
            return variant
        parts = [payload[f.name].format_string() for f in payload.type.strip_typedefs().fields()]
        return f"{variant}({', '.join(parts)})"

    def _payload(self, variant):
        t = self.val.type.strip_typedefs()
        if not any(f.name == "payload" for f in t.fields()):
            return None
        union = self.val["payload"]
        if not any(f.name == variant for f in union.type.strip_typedefs().fields()):
            return None
        return union[variant]


def _is_enum(val):
    t = val.type.strip_typedefs()
    if t.code != gdb.TYPE_CODE_STRUCT:
        return False
    fields = t.fields()
    return bool(fields) and fields[0].name == "tag" and fields[0].type.strip_typedefs().code == gdb.TYPE_CODE_ENUM


def lookup(val):
    t = val.type.strip_typedefs()
    if t.code != gdb.TYPE_CODE_STRUCT:
        return None
    name = _name(val)
    if name == "string":
        return StringPrinter(val)
    if name == "str":
        return StrPrinter(val)
    if name.startswith("List[") or name.startswith("[]"):
        return ListPrinter(val)
    if re.search(r"(^|\.)HashMap\[", name):
        return HashMapPrinter(val)
    if re.search(r"(^|\.)HashSet\[", name):
        return HashSetPrinter(val)
    if name.startswith("Box["):
        return BoxPrinter(val)
    if _is_enum(val):
        return EnumPrinter(val)
    return None


def register(objfile=None):
    target = objfile if objfile is not None else gdb
    target.pretty_printers.append(lookup)


register()
