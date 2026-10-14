"""Attributes: `@name(args)` above a function, struct, or field.

An attribute must be declared first, so a misspelled one is an error and not a silent no-op:

    attribute replicated(mode: ident, reliable: bool = false) on fn

    @replicated(server, reliable=true)
    fn spawn(kind: i32): ...

The compiler checks the use against the declaration (target, argument count, names, kinds) and keeps the
resolved arguments on the AST. It gives an attribute no meaning of its own. Tools and generators read the
list with `gg attrs` (JSON) and act on it: RPC stubs, serialization tables, editor metadata, and so on.
"""
from __future__ import annotations

import difflib

from .ast_nodes import Attr, AttrArg, AttrDecl, FieldDecl, FuncDecl, StructDecl
from .diagnostics import DiagnosticBag

_KIND_WORDS = {"str": "a string", "int": "an integer", "float": "a number", "bool": "`true` or `false`",
               "ident": "a bare name"}


def _fits(param_kind: str, arg: AttrArg) -> bool:
    if param_kind == "float":
        return arg.kind in ("float", "int")
    return arg.kind == param_kind


def _declarations(decls, diags: DiagnosticBag | None) -> dict[str, AttrDecl]:
    found: dict[str, AttrDecl] = {}
    for d in decls:
        if not isinstance(d, AttrDecl):
            continue
        if d.name in found:
            if diags is not None:
                diags.error(f"Attribute `{d.name}` is declared twice.", d.line, d.col, d.length,
                            "Keep one `attribute` line for it.", filename=d.filename, rule="bad-attribute")
            continue
        found[d.name] = d
        seen: set[str] = set()
        for p in d.params:
            if p.name in seen and diags is not None:
                diags.error(f"Attribute `{d.name}` has two parameters named `{p.name}`.", p.line, p.col, p.length,
                            filename=d.filename, rule="bad-attribute")
            seen.add(p.name)
            if p.default is not None and not _fits(p.kind, p.default) and diags is not None:
                diags.error(f"The default of `{p.name}` must be {_KIND_WORDS[p.kind]}.", p.default.line,
                            p.default.col, p.default.length, filename=d.filename, rule="bad-attribute")
    return found


def _bind(attr: Attr, decl: AttrDecl, diags: DiagnosticBag | None) -> dict[str, object] | None:
    """Matches the arguments to the parameters. Returns {parameter: value}, or None after reporting an error."""
    values: dict[str, object] = {}
    ok = True

    def fail(node, message: str, hint: str | None = None) -> None:
        nonlocal ok
        ok = False
        if diags is not None:
            diags.error(message, node.line, node.col, node.length, hint, filename=attr.filename, rule="bad-attribute")

    params = {p.name: p for p in decl.params}
    position = 0
    for arg in attr.args:
        if arg.name is None:
            if position >= len(decl.params):
                fail(arg, f"`@{attr.name}` takes {len(decl.params)} argument(s); this is one too many.",
                     _signature(decl))
                continue
            param = decl.params[position]
            position += 1
        else:
            param = params.get(arg.name)
            if param is None:
                near = difflib.get_close_matches(arg.name, list(params), n=1)
                fail(arg, f"`@{attr.name}` has no parameter `{arg.name}`.",
                     f"Did you mean `{near[0]}`?" if near else _signature(decl))
                continue
        if param.name in values:
            fail(arg, f"`{param.name}` is given twice in `@{attr.name}`.")
            continue
        if not _fits(param.kind, arg):
            fail(arg, f"`{param.name}` of `@{attr.name}` must be {_KIND_WORDS[param.kind]}.", _signature(decl))
            continue
        values[param.name] = float(arg.value) if param.kind == "float" else arg.value  # type: ignore[arg-type]
    for p in decl.params:
        if p.name in values:
            continue
        if p.default is not None:
            values[p.name] = p.default.value
        else:
            fail(attr, f"`@{attr.name}` needs the argument `{p.name}`.", _signature(decl))
    return values if ok else None


def _signature(decl: AttrDecl) -> str:
    inner = ", ".join(f"{p.name}: {p.kind}" + (" = ..." if p.default is not None else "") for p in decl.params)
    return f"Declared as `attribute {decl.name}({inner})`."


def _targets(program):
    """Yields (target kind, node, owner name) for everything that can carry attributes."""
    for d in program.decls:
        if isinstance(d, FuncDecl):
            yield "fn", d, d.owner, getattr(d, "module_slug", "")
        elif isinstance(d, StructDecl):
            slug = getattr(d, "module_slug", "")
            yield "struct", d, None, slug
            for f in d.fields:
                yield "field", f, d.name, slug


def check_attributes(program, diags: DiagnosticBag) -> None:
    declared = _declarations(program.decls, diags)
    for kind, node, _owner, _slug in _targets(program):
        used: set[str] = set()
        for attr in getattr(node, "attrs", ()):
            decl = declared.get(attr.name)
            if decl is None:
                near = difflib.get_close_matches(attr.name, list(declared), n=1)
                hint = (f"Did you mean `@{near[0]}`?" if near
                        else f"Declare it first: `attribute {attr.name}(...)`.")
                diags.error(f"Unknown attribute `@{attr.name}`.", attr.line, attr.col, attr.length, hint,
                            filename=attr.filename, rule="unknown-attribute")
                continue
            if decl.targets and kind not in decl.targets:
                diags.error(f"`@{attr.name}` goes on {' or '.join('`' + t + '`' for t in decl.targets)}, "
                            f"not on a {kind}.", attr.line, attr.col, attr.length, filename=attr.filename,
                            rule="bad-attribute")
                continue
            if attr.name in used:
                diags.error(f"`@{attr.name}` is written twice on the same {kind}.", attr.line, attr.col,
                            attr.length, filename=attr.filename, rule="bad-attribute")
                continue
            used.add(attr.name)
            values = _bind(attr, decl, diags)
            if values is not None:
                attr.resolved = values  # type: ignore[attr-defined]


def run_handlers(program, diags: DiagnosticBag) -> None:
    """Runs the body of each `attribute ...:` for every use that checked. The body sees the arguments by name and
    `target_kind` (`fn`, `struct`, `field`), `target_name`, `target_owner`, and `target_type` (the result of a
    function, the type of a field). Each `compile_error(message)` becomes an error at the `@name` line."""
    from .comptime import ComptimeError, Interp

    declared = _declarations(program.decls, None)
    if not any(d.handler is not None for d in declared.values()):
        return
    interp = Interp(program)
    for kind, node, owner, _slug in _targets(program):
        if isinstance(node, FuncDecl):
            ty = node.ret.name if node.ret else ""
        elif isinstance(node, FieldDecl):
            ty = node.type_ref.name
        else:
            ty = ""
        for attr in getattr(node, "attrs", ()):
            decl = declared.get(attr.name)
            values = getattr(attr, "resolved", None)
            if decl is None or decl.handler is None or values is None:
                continue
            args = [values[p.name] for p in decl.params] + [kind, node.name, owner or "", ty]
            try:
                messages = interp.run_attribute(decl.handler, args)
            except ComptimeError as err:
                messages = [("error", f"The body of `attribute {attr.name}` could not run: {err}")]
            except RecursionError:
                messages = [("error", f"The body of `attribute {attr.name}` recurses too deeply.")]
            for kind_, message in messages:
                if kind_ == "note":   # `print` in the body: shown, but it does not fail the build
                    diags.error(message, attr.line, attr.col, attr.length, filename=attr.filename,
                                rule="attribute-print").severity = "note"
                else:
                    diags.error(message, attr.line, attr.col, attr.length, filename=attr.filename, rule="attribute-check")


def export(program) -> list[dict]:
    """Every attributed item with its resolved arguments, for `gg attrs`. Skips uses that did not check."""
    declared = _declarations(program.decls, None)
    out: list[dict] = []
    for kind, node, owner, slug in _targets(program):
        attrs = []
        for attr in getattr(node, "attrs", ()):
            decl = declared.get(attr.name)
            values = _bind(attr, decl, None) if decl is not None else None
            if values is not None:
                attrs.append({"name": attr.name, "args": values})
        if not attrs:
            continue
        item = {"kind": kind, "name": node.name, "attrs": attrs, "file": node.filename, "line": node.line}
        if owner:
            item["owner"] = owner
        if slug:
            item["module"] = slug
        if isinstance(node, FuncDecl):
            item["params"] = [{"name": p.name, "type": p.type_ref.name if p.type_ref else None, "mode": p.mode}
                              for p in node.params]
            item["returns"] = node.ret.name if node.ret else None
        elif isinstance(node, FieldDecl):
            item["type"] = node.type_ref.name
        out.append(item)
    return out
