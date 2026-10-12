"""Enum variant constructors and type checking for the `match` statement (a mixin joining TypeChecker).

`TypeChecker` inherits from this class; here we directly use TypeChecker members like
`self._err`, `self._expr`, `self._declare`, `self.enums` (this is the contract of the mixin).
The only reason this file is separated is to keep `typecheck.py` small.

Match modes follow the exact same rules as parameter modes:
    match s:           -> bindings are like value parameters (immutable, copy)
    match lend s:      -> bindings are like `lend` parameters (modifies payload in-place)
    match consume s:   -> bindings are like `consume` parameters (local owner), s is considered moved
"""
from __future__ import annotations

import difflib

from .ast_nodes import (
    BoolLit, CharLit, Expr, FieldAccess, IndexAccess, IntLit, Match, MatchArm, Name, Node, RangePat, StrLit, Try,
    TypeApp, TypeRef, Unary, unparse_pat,
)
from dataclasses import fields as dc_fields

from .ast_nodes import Yield
from .diagnostics import Edit, Fix, Note
from .typeinfo import ERR, INT_RANGES, INTS, VOID, EnumInfo, ParamInfo, VarInfo, generic_parts


def _last_line(node: object, best: int = 0) -> int:
    """Last source line any part of `node` sits on."""
    if isinstance(node, list):
        for item in node:
            best = _last_line(item, best)
        return best
    if not isinstance(node, Node):
        return best
    best = max(best, node.line)
    for f in dc_fields(node):
        best = _last_line(getattr(node, f.name, None), best)
    return best


class MatchMixin:
    def _missing_arm_fix(self, s: Match, patterns: list[str], description: str) -> list[Fix]:
        """Append `Pattern:` + `pass` arms after the last arm of a statement `match`."""
        if not s.arms or any(arm.body and isinstance(arm.body[0], Yield) for arm in s.arms):
            return []
        indent = " " * (s.arms[0].col - 1)
        last = _last_line(s)
        text = "".join(f"{indent}{p}:\n{indent}    pass\n" for p in patterns)
        return [Fix(description, "likely", [Edit(last + 1, 1, last + 1, 1, text, getattr(s, "filename", None))])]

    # -- enum variant constructors ---------------------------------------------

    def _enum_target(self, obj: Expr) -> tuple[str, list[TypeRef] | None] | None:
        """Is `obj` an enum name? (`Shape`, `Optional`, `Optional[i32]`) -> (name, type arguments | None)."""
        if isinstance(obj, FieldAccess) and isinstance(obj.obj, Name) and self._lookup(obj.obj.name) is None:
            qual = self._qualified_item(obj.obj.name, obj.field_name, obj)
            if qual is False:
                return None
            if isinstance(qual, str) and (qual in self.enums or qual in self.generic_enums):
                return qual, None
        if isinstance(obj, Name):
            key = self._resolve_simple(obj.name) or obj.name
            if key in self.enums or key in self.generic_enums:
                return key, None
        if isinstance(obj, TypeApp) and obj.name in self.generic_enums:
            return obj.name, obj.type_args
        if (isinstance(obj, IndexAccess) and obj.type_alt is not None and isinstance(obj.obj, Name)
                and obj.obj.name in self.generic_enums):
            return obj.obj.name, obj.type_alt
        return None

    def _variant_ctor(self, node: Node, target: tuple[str, list[TypeRef] | None], vname: str,
                      args: list[Expr] | None, expected: str | None) -> str:
        """Checks `Shape.Circle(1.0)` (args list) or `Shape.Empty` (args=None) expression."""
        base, targs = target
        if base in self.generic_enums:
            ety = self._generic_enum_type(base, targs, vname, args, expected, node)
            if ety == ERR:
                self._eval_args_quietly(args)
                return ERR
        else:
            ety = base
        info: EnumInfo = self.enums[ety]
        v = info.variants.get(vname)
        if v is None:
            near = difflib.get_close_matches(vname, list(info.variants), n=1)
            hint = f"Did you mean: `{near[0]}`?" if near else \
                f"`{base}` variants: {', '.join(info.variants)}."
            self._err(node, f"`{base}` enum has no variant named `{vname}`.", hint)
            self._eval_args_quietly(args)
            return ERR
        if args is None:
            if v.payload:
                self._err(node, f"`{vname}` variant has {len(v.payload)} payload field(s), value must be provided.",
                          f"Construct as `{base}.{vname}({', '.join(v.payload)})`.")
                return ERR
        else:
            if not v.payload:
                self._err(node, f"`{vname}` variant has no payload, do not write parentheses.",
                          f"Write `{base}.{vname}`.")
                self._eval_args_quietly(args)
                return ERR
            # Heap-owning payloads are moved (`consume`) into the constructor or given as fresh values.
            params = [ParamInfo("", t, "consume" if self._drop(t) else "val", None) for t in v.payload]
            self._check_args(node, f"{base}.{vname}", params, args)
        node.ctor_enum = ety
        return ety

    def _eval_args_quietly(self, args: list[Expr] | None) -> None:
        """Traverses expressions to report other errors in arguments upon an invalid call."""
        for a in args or []:
            self._expr_any(a)

    # -- postfix `?` -----------------------------------------------------------------

    def _whole_expr(self, e: Expr) -> None:
        """Marks the expression that is the ENTIRE value of the statement: `?` is only valid here."""
        self.try_allowed = e if isinstance(e, Try) else None

    def _try(self, e: Try) -> str:
        """`f()?`: if Ok/Valid, payload value; if Err/None, early return from enclosing function."""
        if e is not self.try_allowed:
            self._err(e, "`?` can only be used on the whole expression.",
                      "First assign to a variable: `x = f()?`; then use `x`.")
            ty = self._expr(e.operand)
            parts = generic_parts(ty)
            return parts[1][0] if parts and parts[0] in ("Result", "Optional") else ERR
        ty = self._expr(e.operand)
        if ty == ERR:
            return ERR
        parts = generic_parts(ty)
        if parts is None or parts[0] not in ("Result", "Optional"):
            self._err(e, f"`?` can only be applied to Result or Optional values, found `{ty}`.",
                      "Operand must be `Result[T, E]` or `Optional[T]`.")
            return ERR
        base, targs = parts
        ret = self.cur.ret if self.cur is not None else VOID
        shown = "none" if ret == VOID else ret
        rparts = generic_parts(ret)
        wanted = "Result[_, " + targs[1] + "]" if base == "Result" else "Optional[_]"
        if rparts is not None and rparts[0] in ("Result", "Optional") and rparts[0] != base:
            self._err(e, f"`?` cannot mix Result and Optional: operand is `{ty}`, function returns `{ret}`.",
                      f"Change function return type to `{wanted}` or unpack the value with `match`.")
            return ERR
        if rparts is None or rparts[0] != base:
            self._err(e, f"Function using `?` must have return type {wanted}, currently {shown}.",
                      f"Write return type as `-> {wanted}` or unpack the value with `match`.")
            return ERR
        e.from_fn = None  # type: ignore[attr-defined]
        if base == "Result" and rparts[1][1] != targs[1]:
            target_err = rparts[1][1]
            conv = self.funcs.get(f"{target_err}.from")  # `fn Target.from(e: Source) -> Target`
            if (conv is not None and getattr(conv.decl, "is_static", False)
                    and len(conv.params) == 1 and conv.params[0].ty == targs[1]
                    and conv.params[0].mode in ("val", "") and conv.ret == target_err):
                e.from_fn = f"{target_err}.from"  # type: ignore[attr-defined]
            else:
                self._err(e, f"`?`: error types do not match: operand `Err` type is `{targs[1]}`, "
                             f"function returns `Result[_, {target_err}]`.",
                          f"Define `fn {target_err}.from(e: {targs[1]}) -> {target_err}` to convert automatically.")
                return ERR
        self._no_implicit_copy(e.operand, ty)  # payload would be copied if `x?` read from somewhere
        e.operand_ty, e.ret_ty = ty, ret
        return targs[0]

    # -- match -----------------------------------------------------------------

    def _match_stmt(self, s: Match) -> None:
        scr = s.scrutinee
        ty = self._expr(scr)
        if ty != ERR and s.mode != "" and self._root_var(scr) is None and not (
                s.mode == "consume" and not isinstance(scr, (Name, FieldAccess, IndexAccess))):
            self._err(scr, f"Value for `match {s.mode}` must be addressable (variable or field).",
                      f"First assign the value to a variable, then write `match {s.mode} variable:`.")
            ty = ERR
        if ty != ERR and s.mode == "lend":
            self._check_mutable(scr, "lend")
        elif ty != ERR and s.mode == "consume":
            self._check_move(scr, scr)

        info: EnumInfo | None = self.enums.get(ty)
        scalar = info is None and (ty in INTS or ty in ("bool", "str"))
        if ty != ERR and info is None and not scalar:
            self._err(scr, f"`match` can only be used on enum, integer, char, bool and string values, found `{ty}`.",
                      "Use `if`/`elif` for other types.")
        if scalar and s.mode != "":
            self._err(s, f"`match {s.mode}` can only be used on enum values, found `{ty}`.",
                      "Remove the mode keyword.")
        if info is not None and s.mode == "consume" and info.user_drop:
            self._err(s, f"`match consume` cannot take `{ty}` apart: it has a destructor (`drop`).",
                      "Use `match` or `match lend` on it; `drop` needs the whole value.",
                      rule="drop-misuse", details={"type": ty})
        s.enum_ty = ty if info is not None else None
        s.scalar_ty = ty if scalar else None
        if scalar:
            self._scalar_match(s, ty)
            return

        covered: dict[str, MatchArm] = {}
        wild: MatchArm | None = None
        for arm in s.arms:
            payload: list[str] | None = None  # None: pattern could not be resolved (bindings get ERR type)
            if arm.whole is not None and info is not None and arm.whole in info.variants:
                arm.whole = None  # `Leaf if ...:` is the variant `Leaf` with a guard
            elif arm.whole is not None:
                arm.variant = None  # `n if ...:` is every value, named `n`
            if arm.pats:
                self._err(arm, "Literal/range patterns can only be used when matching integer, char, bool or string values.",
                          "Write enum variants here (e.g. `Variant:` or `Variant(x):`).")
                payload = []
            elif wild is not None:
                self._err(arm, "unreachable arm: cannot write arm after `_` arm.",
                          "Move this arm before the `_` arm or remove it.",
                          notes=[Note(wild.line, wild.col, wild.length, "`_` arm is here")])
            elif arm.variant is None:
                if info is not None and len(covered) == len(info.variants):
                    self._err(arm, "redundant `_` arm: all variants are already covered.",
                              "Remove the `_` arm.")
                if arm.guard is None:  # a guarded arm may not run, so it covers nothing
                    wild = arm
                payload = []
            elif info is not None:
                payload = self._arm_pattern(arm, info, covered if arm.guard is None else dict(covered))
            self._arm_body(s, arm, payload)

        if info is not None and wild is None:
            missing = [n for n in info.variants if n not in covered]
            if missing:
                shown = ", ".join(f"`{m}`" for m in missing)
                pats = ", ".join(self._pattern_text(info, m) for m in missing)
                arm_pats = [self._pattern_text(info, m) for m in missing]
                guarded = any(a.guard is not None and (a.variant in missing or a.variant is None) for a in s.arms)
                self._err(s, f"match does not cover all cases: missing {shown}",
                          f"Add missing arms ({pats}) or write a `_:` arm to catch the rest."
                          + (" An arm with `if` does not count: its condition may be false." if guarded else ""),
                          fixes=self._missing_arm_fix(s, arm_pats, f"Add the missing arms ({pats})")
                          + self._missing_arm_fix(s, ["_"], "Add a `_:` arm for the rest"))

    # -- scalar match (integer / char / bool / string) ----------------------------
    @staticmethod
    def _lit_value(e: object) -> int | str | None:
        """Constant value of a literal pattern (None if it is not a literal)."""
        if isinstance(e, IntLit):
            return e.value
        if isinstance(e, Unary) and e.op == "-" and isinstance(e.operand, IntLit):
            return -e.operand.value
        if isinstance(e, CharLit):
            return e.value
        if isinstance(e, BoolLit):
            return int(e.value)
        if isinstance(e, StrLit):
            return e.value
        return None

    def _scalar_match(self, s: Match, ty: str) -> None:
        wild: MatchArm | None = None
        intervals: list[tuple[int, int]] = []   # covered integer/bool values (inclusive)
        strings: dict[str, Node] = {}
        for arm in s.arms:
            if arm.whole is not None:
                arm.variant = None  # `n if ...:` is every value, named `n`
            if wild is not None:
                self._err(arm, "unreachable arm: cannot write arm after `_` arm.",
                          "Move this arm before the `_` arm or remove it.",
                          notes=[Note(wild.line, wild.col, wild.length, "`_` arm is here")])
            elif arm.variant is not None:
                self._err(arm, f"`{arm.variant}` is not a valid pattern when matching `{ty}`.",
                          "Write a literal (`1:`, `'a':`, `\"text\":`, `true:`), a range (`1..=5:`) or `_:`.")
            elif not arm.pats:
                if self._scalar_covered(ty, intervals):
                    self._err(arm, "redundant `_` arm: all values are already covered.", "Remove the `_` arm.")
                if arm.guard is None:  # a guarded arm may not run, so it covers nothing
                    wild = arm
            seen = intervals if arm.guard is None else list(intervals)
            for p in arm.pats:
                self._scalar_pat(arm, p, ty, seen, strings if arm.guard is None else dict(strings))
            self._arm_body(s, arm, [])
        if wild is None and not self._scalar_covered(ty, intervals):
            if ty == "bool":
                missing = [n for n, v in (("true", 1), ("false", 0)) if not any(a <= v <= b for a, b in intervals)]
                self._err(s, f"match does not cover all cases: missing {', '.join(f'`{m}`' for m in missing)}",
                          "Add the missing arms or write a `_:` arm to catch the rest.",
                          fixes=self._missing_arm_fix(s, missing, "Add the missing arms"))
            else:
                guarded = any(a.guard is not None for a in s.arms)
                self._err(s, f"match on `{ty}` does not cover all cases.",
                          "Add a `_:` arm to catch the remaining values."
                          + (" An arm with `if` does not count: its condition may be false." if guarded else ""),
                          fixes=self._missing_arm_fix(s, ["_"], "Add a `_:` arm for the rest"))

    @staticmethod
    def _scalar_covered(ty: str, intervals: list[tuple[int, int]]) -> bool:
        if ty == "str":
            return False
        lo, hi = (0, 1) if ty == "bool" else INT_RANGES[ty]
        cur = lo
        for a, b in sorted(intervals):
            if a > cur:
                return False
            cur = max(cur, b + 1)
            if cur > hi:
                return True
        return cur > hi

    def _scalar_pat(self, arm: MatchArm, p: Node, ty: str, intervals: list[tuple[int, int]],
                    strings: dict[str, Node]) -> None:
        if isinstance(p, RangePat):
            if ty not in INTS:
                self._err(p, f"Range patterns can only be used with integers and chars, found `{ty}`.")
                return
            for end in (p.lo, p.hi):
                if self._lit_value(end) is None:
                    self._err(end, "Range pattern bounds must be literals.", "Write e.g. `1..=5` or `'a'..='z'`.")
                    return
                t = self._expr(end, ty)
                if t != ERR and t != ty:
                    self._expect_type(ty, t, end, widen=False)  # a pattern stays a literal
                    return
            lo, hi = self._lit_value(p.lo), self._lit_value(p.hi)
            assert isinstance(lo, int) and isinstance(hi, int)
            if not p.inclusive:
                hi -= 1
            if lo > hi:
                self._err(p, "Empty range pattern.", "The lower bound must be smaller than the upper bound.")
                return
            self._record_scalar(p, lo, hi, intervals)
            return
        v = self._lit_value(p)
        if v is None:
            self._err(p, "`match` pattern must be a literal, range or `_`.",
                      "Patterns can be numbers, characters, strings or `true`/`false`.")
            return
        t = self._expr(p, ty)  # type: ignore[arg-type]
        if t == ERR:
            return
        if t != ty:
            self._expect_type(ty, t, p, widen=False)  # type: ignore[arg-type]
            return
        if isinstance(v, str):
            if v in strings:
                first = strings[v]
                self._err(p, f"duplicate arm: `{unparse_pat(p)}` has already been handled in this match.",
                          "Remove the duplicate arm.",
                          notes=[Note(first.line, first.col, first.length, "first arm is here")])
            else:
                strings[v] = p
        else:
            self._record_scalar(p, v, v, intervals)

    def _record_scalar(self, p: Node, lo: int, hi: int, intervals: list[tuple[int, int]]) -> None:
        if any(a <= lo and hi <= b for a, b in intervals):
            self._err(p, f"unreachable pattern: `{unparse_pat(p)}` is already covered by previous arms.",
                      "Remove the pattern.")
        intervals.append((lo, hi))

    @staticmethod
    def _pattern_text(info: EnumInfo, vname: str) -> str:
        n = len(info.variants[vname].payload)
        return vname if n == 0 else f"{vname}({', '.join('_' for _ in range(n))}):"

    def _arm_pattern(self, arm: MatchArm, info: EnumInfo, covered: dict[str, MatchArm]) -> list[str] | None:
        """Checks variant pattern; returns payload types (None if pattern is invalid)."""
        parts = generic_parts(info.name)
        base = parts[0] if parts else info.name
        assert arm.variant is not None
        if arm.qualifier is not None and arm.qualifier != base:
            self._err(arm, f"Pattern specifies `{arm.qualifier}` enum, but matched value is `{info.name}`.",
                      f"Write `{arm.variant}` or `{base}.{arm.variant}`.")
            return None
        v = info.variants.get(arm.variant)
        if v is None:
            near = difflib.get_close_matches(arm.variant, list(info.variants), n=1)
            hint = f"Did you mean: `{near[0]}`?" if near else \
                f"`{info.name}` variants: {', '.join(info.variants)}. Write `_:` to catch the rest."
            self._err(arm, f"`{arm.variant}` is not a variant of this enum.", hint)
            return None
        if arm.variant in covered:
            first = covered[arm.variant]
            self._err(arm, f"duplicate arm: variant `{arm.variant}` has already been handled in this match.",
                      "Remove the duplicate arm.",
                      notes=[Note(first.line, first.col, first.length, "first arm is here")])
        else:
            covered[arm.variant] = arm
        if len(arm.bindings) != len(v.payload):
            if v.payload:
                msg = (f"`{arm.variant}` variant has {len(v.payload)} payload field(s), "
                       f"pattern has {len(arm.bindings)} name(s).")
                hint = f"Write as `{self._pattern_text(info, arm.variant)}` (`_` for unused fields)."
            else:
                msg = f"`{arm.variant}` variant has no payload, pattern has {len(arm.bindings)} name(s)."
                hint = f"Write `{arm.variant}:`."
            self._err(arm, msg, hint)
            return None
        arm.payload_tys = list(v.payload)
        arm.tag_index = v.index
        return v.payload

    def _arm_body(self, s: Match, arm: MatchArm, payload: list[str] | None) -> None:
        """Checks arm body by declaring bindings as local variables."""
        if payload is None:
            payload = [ERR] * len(arm.bindings)
        path = self._path(s.scrutinee)
        self.scopes.append({})
        for i, (b, ty) in enumerate(zip(arm.bindings, payload)):
            if b.name == "_":
                continue
            if s.mode == "":
                var = VarInfo(b.name, ty, False, "val")
            elif s.mode == "lend":
                alias = path + (f"{arm.variant}._{i}",) if path is not None else None
                var = VarInfo(b.name, ty, True, "lend", alias)
            else:
                var = VarInfo(b.name, ty, True, "consume")
            self._declare(b.name, var, b)
        if arm.whole is not None:
            ty = s.enum_ty or s.scalar_ty or ERR
            self._declare(arm.whole, VarInfo(arm.whole, ty, False, "read" if self._moves(ty) else "val"),
                          getattr(arm, "whole_at", arm))
        if arm.guard is not None:
            gt = self._expr(arm.guard, "bool")
            if gt not in (ERR, "bool"):
                self._err(arm.guard, f"A `match` guard must be a `bool`, found `{gt}`.",
                          "Write a condition after `if`, such as `n if n > 3:`.",
                          rule="type-mismatch", details={"expected": "bool", "found": gt})
        for i, st in enumerate(arm.body):
            if self._is_new_binding(st):  # `x = v` with no `x`: a declaration
                st = arm.body[i] = self._decl_from_assign(st)  # type: ignore[arg-type]
            elif self._is_existing_binding(st):  # bare `x = v` where `x` is an imported constant/static
                st = arm.body[i] = self._assign_from_decl(st)  # type: ignore[arg-type]
            self._stmt(st)
        self.scopes.pop()
