"""Typed program generator for the memory-safety guarantee.

Builds random Greengold programs from ~200 operations over the language's owning types: strings and views of
them, lists, boxes, structs, enums, `Optional`, `Shared` and `Arc`, closures (borrowing and owned), `dyn`
objects, arrays, tuples, hash maps, threads, references (`read` / `lend` / `-> ref` / `tied to`), types with
`drop`, `defer`, loops with `break` / `continue`, and early `return`. The generator tracks which variables are
moved or borrowed, but breaks its own rules now and then on purpose, so the checker has to say no.

Every program the compiler accepts is built with the oracle allocator and run with a leaking and a poisoning
heap (`safety_oracle.py`). The program also counts live `Tok` values (a type with `drop`): the count has to be
zero when `main` ends. A difference between the two runs, a double free, a crash, or a non-zero count means a
program passed the checker that is not memory safe.

    python tools/fuzz_typed.py --selftest             # does every operation compile on its own?
    python tools/fuzz_typed.py --show 7               # print program 7
    python tools/fuzz_typed.py --count 2000 --jobs 10 --out findings/
"""
from __future__ import annotations

import argparse
import collections
import random
import re
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import safety_oracle as O  # noqa: E402

PREAMBLE = (HERE / "typed_preamble.gg").read_text(encoding="utf-8")

VIEW_TYPES = {"str", "vw", "sl", "slot", "lv", "lam", "lam2", "rd", "ld", "slh"}
OWNER_TYPES = None  # everything that is not a view

# ---------------------------------------------------------------- operation table
OPS: list[dict] = []


def op(name, weight, ins, out, code, tie=None, adds=None, hazard=False):
    """ins: ["string:r", "li:l", ...] (type:effect, effect r=read l=mutate c=move n=copy).
    out: type of the new variable or None. tie: index of the input the new variable is a view of.
    adds: (i, j) the container input i now holds views of input j. hazard: breaks a rule on purpose."""
    OPS.append(dict(name=name, weight=weight, ins=ins, out=out, code=code, tie=tie, adds=adds, hazard=hazard))


# --- integers
op("int_new", 3, [], "int", "$o = $n")
op("int_add", 1, ["int:n"], "int", "$o = $0 + $n")
op("int_print", 2, ["int:n"], None, "print($0)")

# --- string
op("str_new", 4, [], "string", '$o = string.from("$s")')
op("str_empty", 1, [], "string", "$o = string.new()")
op("str_append", 4, ["string:l"], None, '$0.append_str("$s")')
op("str_append_int", 1, ["string:l", "int:n"], None, "$0.append_i64(i64($1))")
op("str_print", 3, ["string:r"], None, "print($0)")
op("str_len", 1, ["string:r"], None, "print($0.len)")
op("str_clone", 3, ["string:r"], "string", "$o = $0.clone()")
op("str_move", 3, ["string:c"], "string", "$o = $0")
op("str_sink", 2, ["string:c"], None, "gg_sink($0)")
op("str_peek", 1, ["string:r"], None, "gg_peek($0)")
op("str_touch", 1, ["string:l"], None, "gg_touch($0)")
op("str_view", 6, ["string:r"], "str", "$o = $0.as_str()", tie=0)
op("str_slice", 3, ["string:r"], "str", "$o = $0[0..1]", tie=0)
op("str_trim", 2, ["string:r"], "str", "$o = $0.trim()", tie=0)
op("str_concat", 2, ["string:r", "string:r"], "string", "$o = $0 + $1")
op("str_concat_lit", 1, ["string:r"], "string", '$o = $0 + "$s"')
op("str_self_concat", 1, ["string:l"], None, "$0 = $0 + $0")
op("str_clear", 2, ["string:l"], None, "$0.clear()")
op("str_reassign", 3, ["string:l"], None, '$0 = string.from("$s")')
op("str_assign_clone", 1, ["string:l", "string:r"], None, "$0 = $1.clone()")
op("str_assign_move", 2, ["string:l", "string:c"], None, "$0 = $1")
op("str_replace", 1, ["string:r"], "string", '$o = $0.replace("a", "bb")')
op("str_upper", 1, ["string:r"], "string", "$o = $0.to_upper()")
op("str_split", 3, ["string:r"], "lv", '$o = $0.split(" ")', tie=0)
op("str_eq", 1, ["string:r", "string:r"], None, "print($0 == $1)")
op("str_append_view", 3, ["string:l", "str:r"], None, "$0.append_str($1)")
op("str_append_self_view", 1, ["string:l"], None, "$0.append_str($0.as_str())", hazard=True)
op("str_push_ls", 3, ["ls:l", "string:c"], None, "$0.push($1)")
op("str_into_box", 2, ["string:c"], "bs", "$o = Box[string]($0)")
op("str_into_opt", 2, ["string:c"], "os", "$o = Valid($0)")
op("str_into_shared", 1, ["string:c"], "sh", "$o = Shared[string]($0)")
op("str_into_arc", 1, ["string:c"], "ar", "$o = Arc[string]($0)")
op("str_defer", 1, ["string:r"], None, "defer print($0)", hazard=True)

# --- str views
op("view_print", 5, ["str:r"], None, "print($0)")
op("view_len", 1, ["str:r"], None, "print($0.len)")
op("view_copy", 2, ["str:r"], "string", "$o = string.from($0)")
op("view_reassign", 2, ["str:l", "string:r"], None, "$0 = $1.as_str()", adds=(0, 1))
op("view_copyview", 1, ["str:r"], "str", "$o = $0", tie=0)
op("view_peek", 1, ["str:r"], None, "gg_peek($0)")
op("view_hold", 2, ["str:r"], "vw", "$o = Vw{ v: $0 }", tie=0)
op("vw_print", 3, ["vw:r"], None, "print($0.v)")
op("view_find", 1, ["str:r"], None, 'print($0.contains("a"))')

# --- List[str] of views
op("lv_new", 1, [], "lv", "$o = List[str]()")
op("lv_push", 3, ["lv:l", "str:r"], None, "$0.push($1)", adds=(0, 1))
op("lv_print", 3, ["lv:r"], None, "if $0.len > 0:\n    print($0[0])")
op("lv_for", 1, ["lv:r"], None, "for gg_w in $0:\n    print(gg_w)")
op("lv_len", 1, ["lv:r"], None, "print($0.len)")

# --- List[i32]
op("li_new", 4, [], "li", "$o = mk_li($n)")
op("li_push", 4, ["li:l"], None, "$0.push($n)")
op("li_pop", 2, ["li:l"], None, "match $0.pop():\n    Valid(gg_v):\n        print(gg_v)\n    None:\n        print(-1)")
op("li_len", 1, ["li:r"], None, "print($0.len)")
op("li_get", 2, ["li:r"], None, "if $0.len > 0:\n    print($0[0])")
op("li_set", 2, ["li:l"], None, "if $0.len > 0:\n    $0[0] = $n")
op("li_clone", 2, ["li:r"], "li", "$o = $0.clone()")
op("li_move", 2, ["li:c"], "li", "$o = $0")
op("li_sink", 1, ["li:c"], None, "gg_sink($0)")
op("li_peek", 1, ["li:r"], None, "gg_peek($0)")
op("li_touch", 1, ["li:l"], None, "gg_touch($0)")
op("li_sum", 2, ["li:r"], None, "print($0.sum())")
op("li_map", 1, ["li:r"], "li", "$o = $0.map(fn(gg_x: i32) -> i32 => gg_x * 2)")
op("li_filter", 1, ["li:r"], "li", "$o = $0.filter(fn(gg_x: i32) -> bool => gg_x > 1)")
op("li_fold", 1, ["li:r"], None, "print($0.fold(0, fn(gg_a: i32, gg_x: i32) -> i32 => gg_a + gg_x))")
op("li_sort", 1, ["li:l"], None, "$0.sort()")
op("li_reverse", 1, ["li:l"], None, "$0.reverse()")
op("li_extend_self", 1, ["li:l"], None, "$0.extend($0)", hazard=True)
op("li_extend", 2, ["li:l", "li:r"], None, "$0.extend($1)")
op("li_slice", 5, ["li:r"], "sl", "$o = $0[0..1]", tie=0)
op("li_for_push", 1, ["li:l"], None, "for gg_x in $0:\n    $0.push(gg_x)", hazard=True)
op("li_for_print", 2, ["li:r"], None, "for gg_x in $0:\n    print(gg_x)")
op("li_remove", 1, ["li:l"], None, "if $0.len > 0:\n    print($0.remove(0))")
op("li_swap_remove", 1, ["li:l"], None, "if $0.len > 0:\n    print($0.swap_remove(0))")
op("li_insert", 1, ["li:l"], None, "$0.insert(0, $n)")
op("li_clear", 1, ["li:l"], None, "$0.clear()")
op("li_reserve", 2, ["li:l"], None, "$0.reserve(64)")
op("li_into_box", 1, ["li:c"], "bli", "$o = Box[List[i32]]($0)")
op("li_push_elem", 1, ["li:l"], None, "if $0.len > 0:\n    $0.push($0[0])")
op("li_ref_get", 2, ["li:r"], None, "print($0.get(0))")

# --- slices
op("sl_print", 4, ["sl:r"], None, "for gg_x in $0:\n    print(gg_x)")
op("sl_sum", 2, ["sl:r"], None, "print(sum_sl($0))")
op("sl_hold", 2, ["sl:r"], "slh", "$o = Sl{ s: $0 }", tie=0)
op("slh_print", 2, ["slh:r"], None, "print(sum_sl($0.s))")
op("sl_sub", 1, ["sl:r"], "sl", "$o = $0[0..1]", tie=0)
op("sl_arr", 1, [], None, "print(sum_sl([1, 2, 3]))")

# --- List[string]
op("ls_new", 3, [], "ls", "$o = mk_ls($n)")
op("ls_push_new", 3, ["ls:l"], None, '$0.push(string.from("$s"))')
op("ls_pop", 2, ["ls:l"], None, 'match $0.pop():\n    Valid(gg_s):\n        print(gg_s)\n    None:\n        print("-")')
op("ls_get", 3, ["ls:r"], None, "if $0.len > 0:\n    print($0[0])")
op("ls_elem_append", 3, ["ls:l"], None, 'if $0.len > 0:\n    $0[0].append_str("$s")')
op("ls_elem_set", 2, ["ls:l"], None, 'if $0.len > 0:\n    $0[0] = string.from("$s")')
op("ls_elem_view", 5, ["ls:r"], "str", "$o = $0[0].as_str()", tie=0)
op("ls_clone", 2, ["ls:r"], "ls", "$o = $0.clone()")
op("ls_move", 2, ["ls:c"], "ls", "$o = $0")
op("ls_sink", 1, ["ls:c"], None, "gg_sink($0)")
op("ls_peek", 1, ["ls:r"], None, "gg_peek($0)")
op("ls_touch", 1, ["ls:l"], None, "gg_touch($0)")
op("ls_remove", 2, ["ls:l"], "string", "$o = $0.remove(0)")
op("ls_swap_remove", 1, ["ls:l"], "string", "$o = $0.swap_remove(0)")
op("ls_insert", 2, ["ls:l", "string:c"], None, "$0.insert(0, $1)")
op("ls_clear", 2, ["ls:l"], None, "$0.clear()")
op("ls_join", 1, ["ls:r"], "string", '$o = $0.join(",")')
op("ls_for", 2, ["ls:r"], None, "for gg_s in $0:\n    print(gg_s)")
op("ls_for_push", 1, ["ls:l"], None, "for gg_s in $0:\n    $0.push(gg_s.clone())", hazard=True)
op("ls_slice", 2, ["ls:r"], None, "gg_a = $0[0..1]\nprint(count_strs(gg_a))")

# --- Box
op("bi_new", 2, [], "bi", "$o = Box[i32]($n)")
op("bi_set", 1, ["bi:l"], None, "$0.value = $n")
op("bi_print", 1, ["bi:r"], None, "print($0.value)")
op("bs_append", 3, ["bs:l"], None, '$0.value.append_str("$s")')
op("bs_view", 5, ["bs:r"], "str", "$o = $0.value.as_str()", tie=0)
op("bs_print", 2, ["bs:r"], None, "print($0.value)")
op("bs_replace", 3, ["bs:l"], None, '$0 = Box[string](string.from("$s"))')
op("bs_move", 2, ["bs:c"], "bs", "$o = $0")
op("bs_clone", 1, ["bs:r"], "bs", "$o = $0.clone()")
op("bs_value_clone", 1, ["bs:r"], "string", "$o = $0.value.clone()")
op("bs_set_value", 2, ["bs:l"], None, '$0.value = string.from("$s")')
op("bs_sink", 1, ["bs:c"], None, "gg_sink($0)")
op("bli_push", 2, ["bli:l"], None, "$0.value.push($n)")
op("bli_slice", 4, ["bli:r"], "sl", "$o = $0.value[0..1]", tie=0)
op("bli_print", 1, ["bli:r"], None, "print($0.value.len)")
op("bli_replace", 2, ["bli:l"], None, "$0 = Box[List[i32]](mk_li(1))")

# --- Pl struct
op("p_new", 3, [], "Pl", "$o = mk_p($n)")
op("p_from", 2, ["string:c", "li:c"], "Pl", "$o = Pl{ name: $0, items: $1, k: $n }")
op("p_total", 2, ["Pl:r"], None, "print($0.total())")
op("p_bump", 3, ["Pl:l"], None, "$0.bump()")
op("p_rename", 2, ["Pl:l"], None, '$0.rename("$s")')
op("p_rename_view", 1, ["Pl:l", "str:r"], None, "$0.rename($1)")
op("p_label_view", 5, ["Pl:r"], "str", "$o = $0.label()", tie=0)
op("p_head_clone", 1, ["Pl:r"], "string", "$o = $0.head().clone()")
op("p_head_view", 3, ["Pl:r"], "str", "$o = $0.head().as_str()", tie=0)
op("p_name_move", 1, ["Pl:l"], "string", "$o = $0.name", hazard=True)
op("p_items_push", 2, ["Pl:l"], None, "$0.items.push($n)")
op("p_name_append", 2, ["Pl:l"], None, '$0.name.append_str("$s")')
op("p_items_slice", 4, ["Pl:r"], "sl", "$o = $0.items[0..1]", tie=0)
op("p_read_fn", 2, ["Pl:r"], None, "print(p_read($0))")
op("p_lend_fn", 2, ["Pl:l"], None, "p_lend($0)")
op("p_consume_fn", 2, ["Pl:c"], None, "print(p_consume($0))")
op("p_move", 2, ["Pl:c"], "Pl", "$o = $0")
op("p_clone", 2, ["Pl:r"], "Pl", "$o = $0.clone()")
op("p_sink", 1, ["Pl:c"], None, "gg_sink($0)")
op("p_ref_read", 4, ["Pl:r"], "rd", "$o = read $0", tie=0)
op("rd_print", 4, ["rd:r"], None, "print($0.total())")
op("p_ref_lend", 3, ["Pl:l"], "ld", "$o = lend $0", tie=0)
op("ld_bump", 3, ["ld:l"], None, "$0.bump()")
op("p_slot", 3, ["Pl:r"], "slot", "$o = Slot{ who: $0 }", tie=0)
op("slot_print", 3, ["slot:r"], None, "print($0.who.total())")
op("p_pick", 2, ["Pl:r", "Pl:r"], None, "print(pick_p($0, $1).total())")
op("p_reassign", 2, ["Pl:l"], None, "$0 = mk_p($n)")
op("p_show", 2, ["Pl:r"], None, "show_p($0)")

# --- Ev enum
op("e_num", 2, [], "Ev", "$o = Ev.Num($n)")
op("e_nothing", 1, [], "Ev", "$o = Ev.Nothing")
op("e_txt", 3, ["string:c"], "Ev", "$o = Ev.Txt($0)")
op("e_both", 2, ["string:c", "li:c"], "Ev", "$o = Ev.Both($0, $1)")
op("e_show", 2, ["Ev:r"], None, "show_e($0)")
op("e_match_read", 3, ["Ev:r"], None,
   "match $0:\n    Num(gg_a):\n        print(gg_a)\n    Txt(gg_a):\n        print(gg_a)\n"
   "    Both(gg_a, gg_b):\n        print(gg_a, gg_b.len)\n    Nothing:\n        pass")
op("e_match_lend", 3, ["Ev:l"], None,
   'match lend $0:\n    Txt(gg_a):\n        gg_a.append_str("$s")\n    Both(gg_a, gg_b):\n        gg_b.push($n)\n    _:\n        pass')
op("e_match_consume", 3, ["Ev:c"], None,
   "match consume $0:\n    Txt(gg_a):\n        print(gg_a)\n    Both(gg_a, gg_b):\n        print(gg_a, gg_b.len)\n    _:\n        pass")
op("e_consume_out", 2, ["Ev:c", "ls:l"], None,
   "match consume $0:\n    Txt(gg_a):\n        $1.push(gg_a)\n    _:\n        pass")
op("e_match_view", 3, ["Ev:r"], "str", '$o = match $0:\n    Txt(gg_a) => gg_a.as_str()\n    _ => "none"', tie=0)
op("e_reassign", 2, ["Ev:l"], None, "$0 = Ev.Nothing")
op("e_clone", 1, ["Ev:r"], "Ev", "$o = $0.clone()")
op("e_move", 1, ["Ev:c"], "Ev", "$o = $0")
op("e_sink", 1, ["Ev:c"], None, "gg_sink($0)")

# --- Optional
op("os_none", 1, [], "os", "$o: Optional[string] = None")
op("os_match", 3, ["os:r"], None, 'match $0:\n    Valid(gg_a):\n        print(gg_a)\n    None:\n        print("none")')
op("os_consume", 3, ["os:c"], None, 'match consume $0:\n    Valid(gg_a):\n        print(gg_a)\n    None:\n        print("none")')
op("os_lend", 2, ["os:l"], None, 'match lend $0:\n    Valid(gg_a):\n        gg_a.append_str("$s")\n    None:\n        pass')
op("os_view", 3, ["os:r"], "str", '$o = match $0:\n    Valid(gg_a) => gg_a.as_str()\n    None => "none"', tie=0)
op("os_reassign", 2, ["os:l"], None, "$0 = None")
op("os_clone", 1, ["os:r"], "os", "$o = $0.clone()")

# --- Shared / Arc
op("sh_clone", 3, ["sh:r"], "sh", "$o = $0.clone()")
op("sh_print", 2, ["sh:r"], None, "print($0.value)")
op("sh_view", 3, ["sh:r"], "str", "$o = $0.value.as_str()", tie=0)
op("sh_sink", 2, ["sh:c"], None, "gg_sink($0)")
op("sh_to_list", 1, ["ls:l", "sh:r"], None, "$0.push($1.value.clone())")
op("ar_clone", 2, ["ar:r"], "ar", "$o = $0.clone()")
op("ar_print", 2, ["ar:r"], None, "print($0.value)")
op("ar_view", 2, ["ar:r"], "str", "$o = $0.value.as_str()", tie=0)
op("ar_sink", 1, ["ar:c"], None, "gg_sink($0)")
op("ar_thread", 2, ["ar:r"], None,
   "gg_c = $0.clone()\ngg_th = thread.Thread.spawn(fn() => gg_noop_len(gg_c.value.clone()))\ngg_th.join()")

# --- Tok (drop)
op("tok_new", 3, [], "tok", "$o = new_tok($n)")
op("tok_print", 2, ["tok:r"], None, "print($0.id)")
op("tok_move", 2, ["tok:c"], "tok", "$o = $0")
op("tok_sink", 2, ["tok:c"], None, "gg_sink($0)")
op("tok_reassign", 2, ["tok:l"], None, "$0 = new_tok($n)")
op("lt_new", 2, [], "lt", "$o = List[Tok]()")
op("lt_push", 3, ["lt:l", "tok:c"], None, "$0.push($1)")
op("lt_pop", 2, ["lt:l"], None, "match $0.pop():\n    Valid(gg_t):\n        print(gg_t.id)\n    None:\n        pass")
op("lt_clear", 2, ["lt:l"], None, "$0.clear()")
op("lt_remove", 1, ["lt:l"], None, "if $0.len > 0:\n    gg_t = $0.remove(0)\n    print(gg_t.id)")
op("lt_for", 1, ["lt:r"], None, "for gg_t in $0:\n    print(gg_t.id)")
op("lt_move", 1, ["lt:c"], "lt", "$o = $0")
op("lt_sink", 1, ["lt:c"], None, "gg_sink($0)")
op("lt_set", 1, ["lt:l"], None, "if $0.len > 0:\n    $0[0] = new_tok($n)")
op("hold_new", 2, ["tok:c", "string:c"], "hold", "$o = Hold{ t: $0, s: $1 }")
op("hold_print", 2, ["hold:r"], None, "print($0.t.id, $0.s)")
op("hold_reassign", 1, ["hold:l"], None, '$0 = Hold{ t: new_tok($n), s: string.from("$s") }')
op("hold_s_view", 3, ["hold:r"], "str", "$o = $0.s.as_str()", tie=0)
op("tok_box", 1, ["tok:c"], "bt", "$o = Box[Tok]($0)")
op("bt_print", 1, ["bt:r"], None, "print($0.value.id)")
op("bt_replace", 1, ["bt:l"], None, "$0 = Box[Tok](new_tok($n))")

# --- closures
op("cl_adder", 2, [], "cl", "$o = make_adder($n)")
op("cl_call", 3, ["cl:r"], None, "print($0(3))")
op("cl_clone", 2, ["cl:r"], "cl", "$o = $0.clone()")
op("cl_sink", 1, ["cl:c"], None, "gg_sink($0)")
op("cl_len", 3, ["string:c"], "cl2", "$o = make_len($0)")
op("cl2_call", 3, ["cl2:r"], None, "print($0())")
op("cl2_clone", 1, ["cl2:r"], "cl2", "$o = $0.clone()")
op("cl2_sink", 1, ["cl2:c"], None, "gg_sink($0)")
op("lam_borrow", 4, ["string:r"], "lam", "$o = fn() -> usize => $0.len", tie=0)
op("lam_call", 4, ["lam:r"], None, "print($0())")
op("lam_mut", 3, ["li:l"], "lam2", "$o = fn(gg_x: i32) => $0.push(gg_x)", tie=0)
op("lam2_call", 3, ["lam2:l"], None, "$0(5)")
op("lam_int", 1, ["int:n"], None, "gg_f = fn(gg_x: i32) -> i32 => gg_x + $0\nprint(apply_fn(gg_f, 4))")
op("lam_arg", 1, ["li:r"], None, "print(apply_fn(fn(gg_x: i32) -> i32 => gg_x + i32($0.len), 4))")
op("lam_to_list", 1, ["string:r"], None, "gg_fs = List[Fn() -> usize]()\ngg_fs.push(make_len($0.clone()))\nprint(gg_fs[0]())")

# --- dyn
op("dyn_new", 2, [], "dyn", "$o = List[dyn Speak]()")
op("dyn_dog", 3, ["dyn:l", "string:c"], None, "$0.push(Dog{ name: $1 })")
op("dyn_cat", 2, ["dyn:l"], None, "$0.push(Cat{ n: $n })")
op("dyn_speak", 3, ["dyn:r"], None, "for gg_d in $0:\n    print(gg_d.speak(), gg_d.twice())")
op("dyn_pop", 2, ["dyn:l"], None, "match $0.pop():\n    Valid(gg_d):\n        print(gg_d.speak())\n    None:\n        pass")
op("dyn_clear", 1, ["dyn:l"], None, "$0.clear()")
op("dyn_move", 1, ["dyn:c"], "dyn", "$o = $0")

# --- arrays and tuples
op("arrs_new", 2, ["string:c", "string:c"], "arrs", "$o = [$0, $1]")
op("arrs_count", 2, ["arrs:r"], None, "print(count_strs($0))")
op("arrs_view", 4, ["arrs:r"], "str", "$o = $0[0].as_str()", tie=0)
op("arrs_append", 2, ["arrs:l"], None, '$0[0].append_str("$s")')
op("arrs_set", 1, ["arrs:l"], None, '$0[1] = string.from("$s")')
op("arrs_move", 1, ["arrs:c"], "arrs", "$o = $0")
op("arrs_slice", 2, ["arrs:r"], None, "gg_a = $0[0..1]\nprint(count_strs(gg_a))")
op("tup_new", 2, ["string:c", "int:n"], "tup", "$o = ($0, $1)")
op("tup_print", 2, ["tup:r"], None, "print($0.0, $0.1)")
op("tup_view", 2, ["tup:r"], "str", "$o = $0.0.as_str()", tie=0)
op("tup_move", 1, ["tup:c"], "tup", "$o = $0")
op("tup_split", 1, ["tup:c"], None, "gg_a, gg_b = $0\nprint(gg_a, gg_b)", hazard=True)

# --- hash map
op("hm_new", 2, [], "hm", "$o = collections.hashmap_new[string, List[i32]]()")
op("hm_seed", 3, ["hm:l"], None, '$0.insert(string.from("a"), mk_li($n))')
op("hm_insert", 2, ["hm:l", "string:c", "li:c"], None, "$0.insert($1, $2)")
op("hm_len", 1, ["hm:r"], None, "print($0.len())")
op("hm_ref_len", 2, ["hm:r"], None, 'if $0.contains(string.from("a")):\n    print($0.get_ref(string.from("a")).len)')
op("hm_remove", 2, ["hm:l"], None,
   'match $0.remove(string.from("a")):\n    Valid(gg_l):\n        print(gg_l.len)\n    None:\n        pass')
op("hm_get", 1, ["hm:r"], None,
   'match $0.get(string.from("a")):\n    Valid(gg_l):\n        print(gg_l.len)\n    None:\n        pass')
op("hm_clear_by_move", 1, ["hm:c"], None, "gg_sink($0)")

# --- threads
op("thr_spawn", 2, ["string:c"], "th", "$o = thread.Thread.spawn(fn() => gg_noop_len($0))")
op("thr_join", 2, ["th:c"], None, "$0.join()")
op("thr_run", 1, ["string:c"], None, "gg_th = thread.Thread.spawn(fn() => gg_noop_len($0))\ngg_th.join()")
op("thr_borrow", 1, ["string:r"], None,
   "gg_th = thread.Thread.spawn(fn() => gg_noop_len($0.clone()))\ngg_th.join()", hazard=True)

# --- set B: operators, generics, iterators, Result and `?`, nested containers, threads
op("bag_new", 2, [], "bag", "$o = Bag{ items: mk_li($n) }")
op("bag_add", 2, ["bag:r", "bag:r"], "bag", "$o = $0 + $1")
op("bag_print", 1, ["bag:r"], None, "print($0.items.len)")
op("stks_new", 2, [], "stks", "$o = stack_new[string]()")
op("stks_push", 3, ["stks:l", "string:c"], None, "$0.push($1)")
op("stks_pop", 2, ["stks:l"], None, "match $0.pop():\n    Valid(gg_a):\n        print(gg_a)\n    None:\n        pass")
op("stks_peek", 4, ["stks:r"], "str", "$o = $0.peek().as_str()", tie=0)
op("stks_size", 1, ["stks:r"], None, "print($0.size())")
op("stks_move", 1, ["stks:c"], "stks", "$o = $0")
op("stkp_new", 1, [], "stkp", "$o = stack_new[Pl]()")
op("stkp_push", 2, ["stkp:l", "Pl:c"], None, "$0.push($1)")
op("stkp_pop", 2, ["stkp:l"], None, "match $0.pop():\n    Valid(gg_a):\n        print(gg_a.total())\n    None:\n        pass")
op("stkt_new", 1, [], "stkt", "$o = stack_new[Tok]()")
op("stkt_push", 2, ["stkt:l", "tok:c"], None, "$0.push($1)")
op("stkt_pop", 2, ["stkt:l"], None, "match $0.pop():\n    Valid(gg_a):\n        print(gg_a.id)\n    None:\n        pass")
op("it_new", 1, [], "it", "$o = Counter{ cur: 0, end: $n }")
op("it_for", 1, ["it:l"], None, "for gg_x in $0:\n    print(gg_x)")
op("try_chain", 3, ["string:r", "string:c", "ls:c"], None,
   "match try_chain($0, $1, $2):\n    Ok(gg_n):\n        print(gg_n)\n    Err(gg_e):\n        print(gg_e)")
op("first_of_view", 4, ["ls:r"], "str", "$o = first_of($0).as_str()", tie=0)
op("first_of_print", 1, ["ls:r"], None, "if $0.len > 0:\n    print(first_of($0))")
op("longer_view", 3, ["string:r", "string:r"], "str", "$o = longer($0, $1).as_str()", tie=1)
op("iflet_pop", 2, ["ls:l"], None, "if let Valid(gg_a) = $0.pop():\n    print(gg_a)")
op("fmt_string", 1, ["string:r", "int:n"], None, 'print(f"{$0} {$1}")')
op("lls_new", 1, [], "lls", "$o = List[List[string]]()")
op("lls_push", 2, ["lls:l", "ls:c"], None, "$0.push($1)")
op("lls_view", 4, ["lls:r"], "str", "$o = $0[0][0].as_str()", tie=0)
op("lls_inner_push", 2, ["lls:l"], None, 'if $0.len > 0:\n    $0[0].push(string.from("$s"))')
op("lls_pop", 1, ["lls:l"], None, "match $0.pop():\n    Valid(gg_a):\n        print(gg_a.len)\n    None:\n        pass")
op("lp_new", 1, [], "lp", "$o = List[Pl]()")
op("lp_push", 3, ["lp:l", "Pl:c"], None, "$0.push($1)")
op("lp_bump", 2, ["lp:l"], None, "if $0.len > 0:\n    $0[0].bump()")
op("lp_for", 2, ["lp:r"], None, "for gg_p in $0:\n    print(gg_p.total())")
op("lp_for_bump", 2, ["lp:l"], None, "for gg_p in $0:\n    gg_p.bump()")
op("lp_label", 4, ["lp:r"], "str", "$o = $0[0].label()", tie=0)
op("lp_remove", 1, ["lp:l"], "Pl", "$o = $0.remove(0)")
op("lp_clear", 1, ["lp:l"], None, "$0.clear()")
op("lp_for_push", 1, ["lp:l"], None, "for gg_p in $0:\n    $0.push(mk_p(1))", hazard=True)
op("shp_new", 1, ["Pl:c"], "shp", "$o = Shared[Pl]($0)")
op("shp_clone", 1, ["shp:r"], "shp", "$o = $0.clone()")
op("shp_total", 1, ["shp:r"], None, "print($0.value.total())")
op("shp_view", 2, ["shp:r"], "str", "$o = $0.value.label()", tie=0)
op("ac_new", 1, [], "ac", "$o = Arc[thread.AtomicI64](thread.AtomicI64.new(0))")
op("ac_spawn", 2, ["ac:r"], None, "gg_c = $0.clone()\ngg_th = thread.Thread.spawn(fn() => gg_inc(gg_c))\ngg_th.join()")
op("ac_print", 1, ["ac:r"], None, "print($0.value.load())")
op("alk_new", 1, [], "alk", "$o = Arc[thread.Locked[List[i32]]](thread.Locked[List[i32]].new(mk_li(1)))")
op("alk_spawn", 2, ["alk:r"], None, "gg_c = $0.clone()\ngg_th = thread.Thread.spawn(fn() => gg_push_locked(gg_c))\ngg_th.join()")
op("alk_print", 1, ["alk:r"], None, "gg_g = $0.value.lock()\nprint(gg_g.value().len)")
op("q_new", 1, [], "aq", "$o = Arc[thread.Queue[string]](thread.Queue[string].new())")
op("q_send", 2, ["aq:r", "string:c"], None,
   "gg_c = $0.clone()\ngg_th = thread.Thread.spawn(fn() => gg_send(gg_c, $1))\ngg_th.join()")
op("q_drain", 1, ["aq:r"], None,
   "$0.value.close()\nmatch $0.value.recv():\n    Valid(gg_a):\n        print(gg_a)\n    None:\n        pass")
op("thr_shared", 1, ["sh:r"], None,
   "gg_th = thread.Thread.spawn(fn() => gg_noop_len($0.value.clone()))\ngg_th.join()", hazard=True)
op("thr_view", 1, ["str:r"], None,
   "gg_th = thread.Thread.spawn(fn() => gg_noop_len(string.from($0)))\ngg_th.join()", hazard=True)


def _ops_by_out():
    d = collections.defaultdict(list)
    for o in OPS:
        if o["out"]:
            d[o["out"]].append(o)
    return d


PRODUCERS = _ops_by_out()

SHOW = {
    "int": "print($)", "string": "print($)", "str": "print($)", "li": "print($.len, $.sum())",
    "ls": 'print($.join(","))', "bi": "print($.value)", "bs": "print($.value)", "bli": "print($.value.len)",
    "Pl": "show_p($)", "Ev": "show_e($)", "sh": "print($.value)", "ar": "print($.value)",
    "tok": "print($.id)", "lt": "print($.len)", "hold": "print($.t.id, $.s)", "bt": "print($.value.id)",
    "vw": "print($.v)", "sl": "print(sum_sl($))", "slh": "print(sum_sl($.s))", "lv": "print($.len)",
    "cl": "print($(1))", "cl2": "print($())", "lam": "print($())", "dyn": "print($.len)",
    "arrs": "print(count_strs($))", "tup": "print($.0, $.1)", "hm": "print($.len())", "rd": "print($.total())",
    "slot": "print($.who.total())", "os": 'match $:\n    Valid(gg_a):\n        print(gg_a)\n    None:\n        pass',
    "th": "$.join()", "bag": "print($.items.len)", "stks": "print($.size())", "stkp": "print($.size())",
    "stkt": "print($.size())", "lls": "print($.len)", "lp": "print($.len)", "shp": "print($.value.total())",
    "ac": "print($.value.load())", "it": "print($.cur)",
}


# ---------------------------------------------------------------- generator
class Var:
    __slots__ = ("name", "ty", "moved", "retired", "srcs", "loop", "scope")

    def __init__(self, name, ty, loop, scope):
        self.name, self.ty, self.loop, self.scope = name, ty, loop, scope
        self.moved = False
        self.retired = False
        self.srcs: set[str] = set()


class Gen:
    def __init__(self, rng: random.Random, violate: float = 0.06):
        self.r = rng
        self.violate = violate
        self.vars: list[Var] = []
        self.n = 0
        self.scope = 0
        self.loop = 0
        self.used_ops: collections.Counter = collections.Counter()
        self.cur_loop_vars: list[str] = []

    # --- variable bookkeeping
    def fresh(self, ty):
        self.n += 1
        v = Var(f"v{self.n}", ty, self.loop, self.scope)
        self.vars.append(v)
        return v

    def borrowers(self, v: Var):
        return [w for w in self.vars if v.name in w.srcs and not w.retired and not w.moved]

    def candidates(self, ty, eff, exclude):
        out = []
        for v in self.vars:
            if v.ty != ty or v.name in exclude:
                continue
            bad = v.moved or (v.retired and ty in VIEW_TYPES)
            if bad and self.r.random() > self.violate:
                continue
            if eff in "lc" and ty not in VIEW_TYPES and self.borrowers(v) and self.r.random() > self.violate * 2:
                continue
            if eff == "c" and v.loop < self.loop and self.r.random() > self.violate:
                continue
            out.append(v)
        return out

    def ensure(self, ty, exclude, depth=0):
        """Makes sure some variable of type `ty` exists, creating one with a producer operation."""
        if depth > 3 or ty not in PRODUCERS:
            return None
        prods = [p for p in PRODUCERS[ty] if not p["hazard"]]
        # prefer producers that need nothing
        prods.sort(key=lambda p: len(p["ins"]))
        p = self.r.choice(prods[:max(2, len(prods) // 2)])
        return p, depth

    def lines_for(self, o, depth=0):
        """Emits the lines of operation `o`, creating missing inputs first. Returns None when impossible."""
        pre: list[str] = []
        for _attempt in range(6):
            chosen: list[Var] = []
            missing = None
            for spec in o["ins"]:
                ty, eff = spec.split(":")
                cand = self.candidates(ty, eff, {c.name for c in chosen})
                if not cand:
                    missing = ty
                    break
                # newer variables are likelier: programs reuse what they just made
                chosen.append(cand[-1] if self.r.random() < 0.5 else self.r.choice(cand))
            if missing is None:
                break
            if depth >= 3 or missing not in PRODUCERS:
                return None
            prods = [p for p in PRODUCERS[missing] if not p["hazard"]]
            self.r.shuffle(prods)
            prods.sort(key=lambda p: len(p["ins"]) if depth >= 1 else 0)
            for sub in prods[:4]:
                mark = len(self.vars)
                got = self.lines_for(sub, depth + 1)
                if got is not None:
                    pre += got
                    break
                del self.vars[mark:]
            else:
                return None
        else:
            return None
        text = o["code"]
        out_var = None
        if o["out"]:
            out_var = self.fresh(o["out"])
            text = text.replace("$o", out_var.name)
        for i, v in enumerate(chosen):
            text = text.replace(f"${i}", v.name)
        text = re.sub(r"\$n", lambda m: str(self.r.randint(0, 9)), text)
        text = re.sub(r"\$s", lambda m: self.r.choice(["a", "bc", "hello", "zz", " x "]), text)
        # effects
        for spec, v in zip(o["ins"], chosen):
            eff = spec.split(":")[1]
            if eff == "c":
                v.moved = True
            if v.ty in VIEW_TYPES and eff == "r" and self.r.random() < 0.5:
                v.retired = True
        if out_var is not None and o["tie"] is not None:
            src = chosen[o["tie"]]
            out_var.srcs = {src.name} | src.srcs
        if o["adds"]:
            a, b = o["adds"]
            chosen[a].srcs |= {chosen[b].name} | chosen[b].srcs
        self.used_ops[o["name"]] += 1
        return pre + text.split("\n")

    # --- statements
    def op_stmt(self):
        weights = [o["weight"] * (0.35 if o["hazard"] else 1.0) for o in OPS]
        for _ in range(12):
            o = self.r.choices(OPS, weights)[0]
            lines = self.lines_for(o)
            if lines is not None:
                return lines
        return ["pass"]

    def indent(self, lines, k=1):
        return ["    " * k + l for l in lines]

    def block(self, n, depth):
        saved = len(self.vars)
        self.scope += 1
        out = []
        for _ in range(n):
            out += self.stmt(depth)
        self.scope -= 1
        # variables declared in the block are gone
        del self.vars[saved:]
        return out or ["pass"]

    def cond(self):
        ints = [v for v in self.vars if v.ty == "int" and not v.moved]
        if ints and self.r.random() < 0.5:
            return f"{self.r.choice(ints).name} > {self.r.randint(0, 5)}"
        return f"gg_flip({self.r.randint(0, 9)})"

    def stmt(self, depth):
        r = self.r.random()
        if depth < 3 and r < 0.14:
            lines = [f"if {self.cond()}:"] + self.indent(self.block(self.r.randint(1, 4), depth + 1))
            if self.r.random() < 0.4:
                lines += ["else:"] + self.indent(self.block(self.r.randint(1, 3), depth + 1))
            return lines
        if depth < 3 and r < 0.22:
            self.n += 1
            i = f"gg_i{self.n}"
            self.loop += 1
            self.cur_loop_vars.append(i)
            body = self.block(self.r.randint(1, 4), depth + 1)
            if self.r.random() < 0.25:
                body += [f"if gg_flip({i}):", f"    {self.r.choice(['break', 'continue'])}"]
            self.cur_loop_vars.pop()
            self.loop -= 1
            return [f"for {i} in 0..{self.r.randint(1, 3)}:"] + self.indent(body)
        if depth < 3 and r < 0.26:
            self.n += 1
            w = f"gg_w{self.n}"
            self.loop += 1
            body = self.block(self.r.randint(1, 3), depth + 1)
            self.loop -= 1
            extra = []
            if self.r.random() < 0.2:
                extra = [f"if gg_flip({w}):", f"    {self.r.choice(['break', 'continue'])}"]
            return [f"{w} = 0", f"while {w} < {self.r.randint(1, 3)}:", f"    {w} += 1"] + self.indent(extra + body)
        if depth > 0 and r < 0.28:
            return [f"if gg_flip({self.r.randint(0, 9)}):", "    return"]
        return self.op_stmt()

    def epilogue(self):
        """Observe the surviving variables of the top scope, so freed memory shows up in the output."""
        lines = []
        for v in self.vars:
            if v.scope != 0 or v.moved or v.retired or v.ty not in SHOW:
                continue
            lines += SHOW[v.ty].replace("$", v.name).split("\n")
        return lines


def generate(seed: int | str, n_stmts: int | None = None) -> tuple[str, collections.Counter]:
    rng = random.Random(seed)
    g = Gen(rng, violate=rng.choice([0.0, 0.03, 0.08, 0.15]))
    body = []
    for _ in range(n_stmts or rng.randint(12, 40)):
        body += g.stmt(0)
    body += g.epilogue()
    src = PREAMBLE + "fn main():\n    defer report()\n" + "\n".join("    " + l for l in body) + "\n"
    return src, g.used_ops


# ---------------------------------------------------------------- driver
LIVE = re.compile(rb"GG_LIVE (-?\d+)")


def run_one(args):
    seed, workdir = args
    src, used = generate(seed)
    ok, err = O.accepted(src)
    res = {"seed": seed, "ops": dict(used), "status": "rejected", "error": err[:300]}
    if not ok:
        return res
    v = O.check_program(src, Path(workdir), name=f"t{abs(hash(str(seed))) % 10**8}")
    res["status"] = v.kind
    res["detail"] = v.detail
    if v.kind == "ok" and v.live:
        res["status"] = "leak"
        res["detail"] = f"{v.live} heap blocks still allocated at exit"
    if v.kind == "ok":
        m = LIVE.search(v.stdout_leak)
        if m and int(m.group(1)) != 0:
            res["status"] = "live_count"
            res["detail"] = f"GG_LIVE {m.group(1)}"
    if res["status"] not in ("ok", "rejected", "timeout"):
        res["src"] = src
        res["leak"] = v.stdout_leak[-300:].decode("utf-8", "replace")
        res["poison"] = v.stdout_poison[-300:].decode("utf-8", "replace")
        res["errors"] = v.errors
    return res


BAD = ("mismatch", "double_free", "crash", "live_count", "build_error", "leak", "write_after_free", "heap_overflow",
       "nondeterministic")


def selftest():
    """Each operation, alone with whatever it needs, must be accepted by the compiler."""
    bad = []
    for o in OPS:
        if o["hazard"]:
            continue
        for k in range(3):
            rng = random.Random(f"self:{o['name']}:{k}")
            g = Gen(rng, violate=0.0)
            lines = g.lines_for(o)
            if lines is None:
                bad.append((o["name"], "cannot build inputs", ""))
                break
            src = PREAMBLE + "fn main():\n" + "\n".join("    " + l for l in lines + g.epilogue()) + "\n"
            ok, err = O.accepted(src)
            if not ok:
                bad.append((o["name"], err[:200], "\n".join(lines)))
                break
    print(f"{len(OPS)} operations, {len(bad)} do not compile on their own")
    for name, err, code in bad:
        print(f"  {name}: {err}\n      {code!r}")
    return 1 if bad else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default="")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--show", type=int, default=-1)
    ap.add_argument("--accept-only", action="store_true", help="only report how many programs the compiler accepts")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.show >= 0:
        src, used = generate(f"{a.seed}:{a.show}")
        print(src[len(PREAMBLE):])
        ok, err = O.accepted(src)
        print("accepted" if ok else f"rejected: {err}")
        return 0
    workdir = tempfile.mkdtemp(prefix="ggtyped_")
    out = Path(a.out) if a.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    stats = collections.Counter()
    ops_total = collections.Counter()
    ops_ok = collections.Counter()
    findings = []
    t0 = time.time()
    jobs = [(f"{a.seed}:{i}", workdir) for i in range(a.count)]
    errors = collections.Counter()
    with ProcessPoolExecutor(a.jobs) as ex:
        for n, res in enumerate(ex.map(run_one, jobs, chunksize=2)):
            stats[res["status"]] += 1
            for k, c in res["ops"].items():
                ops_total[k] += c
                if res["status"] == "ok":
                    ops_ok[k] += c
            if res["status"] == "rejected":
                errors[re.sub(r"`[^`]*`", "`_`", res["error"])[:90]] += 1
            if res["status"] in BAD:
                findings.append(res)
                if out:
                    p = out / f"{res['status']}_{len(findings) - 1:03d}.gg"
                    p.write_text(f"# seed {res['seed']}: {res['detail']!r}\n# leak: {res.get('leak')!r}\n"
                                 f"# poison: {res.get('poison')!r}\n# {res.get('errors', '')[:200]!r}\n" + res["src"],
                                 encoding="utf-8")
            if (n + 1) % 200 == 0:
                print(f"  {n + 1}/{a.count}  {dict(stats)}  {time.time() - t0:.0f}s", flush=True)
    print(dict(stats))
    never = sorted(o["name"] for o in OPS if not ops_ok[o["name"]])
    print(f"operations seen in accepted programs: {len(OPS) - len(never)}/{len(OPS)}; never: {never}")
    print("top rejection reasons:", errors.most_common(6))
    print(f"FINDINGS (accepted yet unsafe): {len(findings)}")
    for f in findings[:20]:
        print(f"  [{f['status']}] seed={f['seed']} {f['detail']}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
