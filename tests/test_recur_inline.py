"""The self-inlining pass gives LLVM the expansion GCC does on its own."""
from greengold.recur_inline import recur_inline


def test_small_self_recursion_is_cloned_two_levels():
    ir = """
define internal i32 @"fib"(i32 %"n")
{
entry:
  %"c" = icmp slt i32 %"n", 2
  br i1 %"c", label %"then", label %"else"
then:
  ret i32 %"n"
else:
  %"a" = sub i32 %"n", 1
  %"b" = call i32 @"fib"(i32 %"a")
  %"d" = sub i32 %"n", 2
  %"e" = call i32 @"fib"(i32 %"d")
  %"s" = add i32 %"b", %"e"
  ret i32 %"s"
}
"""
    out = recur_inline(ir)
    assert 'define internal i32 @"fib"(i32 %"n") alwaysinline' not in out
    assert 'call i32 @"fib.ri1"(i32 %"a")' in out
    assert 'define internal i32 @"fib.ri1"(i32 %"n") alwaysinline' in out
    assert 'call i32 @"fib.ri2"(i32 %"a")' in out
    assert 'define internal i32 @"fib.ri2"(i32 %"n") alwaysinline' in out
    assert 'call i32 @"fib"(i32 %"a")' in out.split('@"fib.ri2"')[-1]


def test_non_recursive_function_is_left_alone():
    ir = """
define i32 @"id"(i32 %"n")
{
entry:
  ret i32 %"n"
}
"""
    assert recur_inline(ir) == ir
