# Greengold conformance suite

`docs/SPEC.md` is the definition of the language. This directory holds programs that pin down what it
says. An implementation conforms when every program here behaves as its header states. When the
compiler and the spec disagree, the compiler is wrong; when a program here and the spec disagree, the
program is wrong.

- `spec/sNN_KK.gg`: example KK of SPEC section NN, with the output it must print.
- `reject/<name>.gg`: one program per form that section 17 rejects, with the diagnostic code it must get.

Each file starts with a comment header:

```text
# conformance: SPEC section 12 (Numbers), example 1
# stdin: abc                      (optional: standard input for the program)
# expect-output:
#   100
#   4
```

```text
# conformance: SPEC section 17, rejected form: `else if`
# expect-error: GG0119 at line 8
```

`expect-output` lists the lines the program prints, each after `#` and three spaces (a lone `#` is an
empty line). `expect-error` names the code of an error the program must get and the line it is on.

Run it with `python -m pytest tests/test_conformance.py`. Adding a rule to the spec means adding a
program here: a passing example of the rule, and a rejected form when the rule forbids something.
