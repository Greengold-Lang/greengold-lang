"""lldb formatters for Greengold programs built with `gg build -g`.

Load with `command script import <path>` in lldb (`gg debug-scripts` prints the path), or add that line to
`~/.lldbinit`. `string` and `str` show as text, `List[T]`, `[]T`, and `HashMap[K, V]` as their elements,
`Box[T]` as its value, and an enum as `Variant(values)`.
"""
import lldb  # type: ignore[import-not-found]


def _text(ptr, length):
    n = length.GetValueAsUnsigned()
    if n == 0:
        return '""'
    err = lldb.SBError()
    data = ptr.GetProcess().ReadMemory(ptr.GetValueAsUnsigned(), n, err)
    if not err.Success():
        return "<unreadable>"
    return '"' + data.decode("utf-8", "replace").replace("\\", "\\\\").replace('"', '\\"') + '"'


def str_summary(val, _dict):
    val = val.GetNonSyntheticValue()
    return _text(val.GetChildMemberWithName("ptr"), val.GetChildMemberWithName("len"))


def string_summary(val, _dict):
    b = val.GetNonSyntheticValue().GetChildMemberWithName("bytes")
    return _text(b.GetChildMemberWithName("ptr"), b.GetChildMemberWithName("len"))


def len_summary(val, _dict):
    return f"len {val.GetNumChildren()}"


def _short(v):
    s = v.GetSummary()
    return s if s else (v.GetValue() or "?")


class ListProvider:
    """`List[T]` and slices `[]T`: `len` elements behind `ptr`."""

    def __init__(self, val, _dict):
        self.val = val

    def update(self):
        self.ptr = self.val.GetChildMemberWithName("ptr")
        self.len = self.val.GetChildMemberWithName("len").GetValueAsUnsigned()
        self.elem = self.ptr.GetType().GetPointeeType()
        return False

    def num_children(self):
        return self.len

    def get_child_at_index(self, i):
        return self.ptr.CreateChildAtOffset(f"[{i}]", i * self.elem.GetByteSize(), self.elem)

    def get_child_index(self, name):
        try:
            return int(name.strip("[]"))
        except ValueError:
            return -1

    def has_children(self):
        return True


class HashMapProvider:
    """`HashMap[K, V]`: keys in `ks` and values in `vs`, dense and in the same order."""

    def __init__(self, val, _dict):
        self.val = val

    def update(self):
        ks = self.val.GetChildMemberWithName("ks")
        vs = self.val.GetChildMemberWithName("vs")
        self.kp, self.vp = ks.GetChildMemberWithName("ptr"), vs.GetChildMemberWithName("ptr")
        self.len = ks.GetChildMemberWithName("len").GetValueAsUnsigned()
        self.kt, self.vt = self.kp.GetType().GetPointeeType(), self.vp.GetType().GetPointeeType()
        return False

    def num_children(self):
        return self.len

    def get_child_at_index(self, i):
        k = self.kp.CreateChildAtOffset("k", i * self.kt.GetByteSize(), self.kt)
        v = self.vp.CreateChildAtOffset(f"[{_short(k)}]", i * self.vt.GetByteSize(), self.vt)
        return v

    def get_child_index(self, _name):
        return -1

    def has_children(self):
        return True


def box_summary(val, _dict):
    ptr = val.GetNonSyntheticValue().GetChildMemberWithName("ptr")
    if ptr.GetValueAsUnsigned() == 0:
        return "Box(null)"
    return f"Box({_short(ptr.Dereference())})"


def enum_summary(val, _dict):
    val = val.GetNonSyntheticValue()
    variant = val.GetChildMemberWithName("tag").GetValue()
    payload = val.GetChildMemberWithName("payload")
    if not payload.IsValid():
        return variant
    arm = payload.GetChildMemberWithName(variant)
    if not arm.IsValid():
        return variant
    parts = [_short(arm.GetChildAtIndex(i)) for i in range(arm.GetNumChildren())]
    return f"{variant}({', '.join(parts)})"


def _is_enum(sbtype, _dict):
    t = sbtype.GetCanonicalType()
    if t.GetNumberOfFields() == 0:
        return False
    first = t.GetFieldAtIndex(0)
    return first.GetName() == "tag" and first.GetType().GetCanonicalType().GetTypeClass() == lldb.eTypeClassEnumeration


def __lldb_init_module(debugger, _dict):
    m = __name__
    run = debugger.HandleCommand
    run(f'type summary add -F {m}.string_summary "string"')
    run(f'type summary add -F {m}.str_summary "str"')
    run(f'type synthetic add -l {m}.ListProvider -x "^(List\\[.*\\]|\\[\\].*)$"')
    run(f'type summary add -F {m}.len_summary -e -x "^(List\\[.*\\]|\\[\\].*)$"')
    run(f'type synthetic add -l {m}.HashMapProvider -x "(^|\\.)HashMap\\[.*\\]$"')
    run(f'type summary add -F {m}.len_summary -e -x "(^|\\.)HashMap\\[.*\\]$"')
    run(f'type summary add -F {m}.box_summary -x "^Box\\[.*\\]$"')
    run(f"type summary add -F {m}.enum_summary --recognizer-function {m}._is_enum")
