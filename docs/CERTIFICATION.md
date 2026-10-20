# Using Greengold in certified projects

This page says what Greengold gives a project that has to satisfy DO-178C, ISO 26262, IEC 61508, EN 50128, IEC 62304, or a
defense equivalent, and what it does not. **Greengold is not qualified or certified under any of these standards, and nothing
here is a claim that a certification authority has accepted it.** A project that wants certification credit has to qualify the
tools it relies on (DO-330 / ISO 26262-8 / IEC 61508-3 tool classification), and the evidence below is input to that work, not a
substitute for it.

## 1. The language subset

`gg check --profile safety` holds a program to a subset small enough to review. In the program's own files (never the standard
library) it rejects:

| Rule | What is rejected | Why a safety standard cares |
|---|---|---|
| `unsafe_code` | an `unsafe:` block (raw pointers, `asm`, `static` access, FFI) | unchecked memory access and calls |
| `panic` | `panic(...)`, `value_or_panic()`, `unreachable` | a way to stop the program on purpose |
| `recursion` | a function that can call itself, directly or through others | unbounded stack |
| `heap` | `List`, `string`, `Box`, `Shared`, `Arc`, `Fn`, `dyn`, f-strings, the heap collections | allocation failure and fragmentation |
| `unbounded_loop` | a `while` loop | no bound in the form of the loop |
| `mutable_static` | a `static` variable | global mutable state |
| `complexity` | cyclomatic complexity over `--max-complexity` (default 15) | reviewability, testability |
| `long_function` | more than `--max-statements` (default 80) statements | reviewability |

An exception is written `@allow(rule)` on the function and listed by `--list-allowed`, so a review sees every one. What stays in a
program that passes: run-time checks (bounds, integer overflow, division by zero, shifts) that stop the program, with
`@panic_handler` deciding what then happens. `--forbid-heap`, `--forbid-recursion`, and `--max-stack BYTES` check the generated code, not
only the source, and fail the build.

Integer arithmetic is defined (traps by default, `wrapping_*`, `checked_*`, `saturating_*` on request). Floating point is IEEE 754
with no fast-math and no automatic multiply-add fusing; `std.dmath` gives results that are identical bit for bit on every machine.
Code outside `unsafe:` is meant to have no undefined behavior; that is a design rule, not a proof, and a compiler defect would break it.

## 2. Evidence the repository produces

| Need | Where it comes from |
|---|---|
| Language definition | `docs/SPEC.md`, `docs/GRAMMAR.md`; the spec's examples are compiled by the test suite |
| Requirements to tests | `docs/TRACEABILITY.md` (generated; `python tools/traceability.py --check` fails when a spec section has no test) |
| Conformance suite | `conformance/` (accepted examples with expected output, rejected forms with expected diagnostic codes) |
| Structural coverage | `gg test --coverage` and `gg coverage`: statement, decision, condition, and MC/DC; `--lcov` for other tools |
| Robustness | `gg fuzz` (coverage-guided, saves and shrinks failing inputs) |
| Library inventory | `gg api`, `gg api --lock` (the public surface of a package, with a breaking-change check) |
| Unsafe inventory | `gg unsafe-audit` lists every `unsafe` block, inline assembly, foreign function, custom allocator, and static |
| Software bill of materials | `gg sbom` (CycloneDX, SPDX) |
| Reproducible build | `gg repro` builds twice in different directories and compares the bytes |
| Stack bounds | `gg stack-usage`, `--max-stack` |
| Stable diagnostics | every diagnostic has a `GGxxxx` code (`docs/ERROR_CODES.md`), JSON output has a published schema |

## 3. What is missing

These are the gaps a certification project has to close itself or with us. They are listed so nobody assumes otherwise.

- **No tool qualification.** The compiler, the formatter, and the coverage tool have no qualification kit (tool operational
  requirements, verification of the tool, qualification report). The coverage tool instruments the generated code, so its own correctness is
  an argument you have to make.
- **The optimizer is LLVM.** Release builds are not proven to preserve behavior; the usual mitigations are to certify with optimization off,
  or to review object code against the source (coverage at the object-code level, DO-178C section 6.4.4.2), and `-g` keeps the line map for that.
- **No formal semantics.** The spec is prose with an executable conformance suite. There is no machine-checked model of the language.
- **Traceability is at section level.** A certification authority usually asks for individual requirements traced to tests; `docs/SPEC.md`
  sections are the unit here.
- **MC/DC is masking MC/DC**, measured on the instrumented program from the condition vectors the tests observed (`greengold/coverage.py`
  explains how). Whether that meets your standard's definition (masking versus unique-cause) is for the project to decide with its authority.
- **Library maturity.** `std.crypto` is not FIPS-validated and not constant time in all paths (the module header says which), `std.tls` is client-side (the operating
  system's library does the work; there is no TLS server, mutual TLS, or certificate pinning yet), and the RTOS and hardware layers are described in `docs/RTOS.md` but not run on hardware.
- **No 1.0 freeze.** The language and the library can still change between 0.x versions (`docs/STABILITY.md`). A certified project pins the
  compiler version, the edition (`gg.toml`), and the API lock (`gg.api.lock`).

## 4. A reasonable first project plan

1. Pin the compiler version and the edition; keep `gg.toml`, `gg.lock`, and `gg.api.lock` in the configuration baseline.
2. Write the software requirements; give every test a line saying which requirement it checks.
3. Develop under `gg check --profile safety` with the complexity limits your coding standard sets; review `--list-allowed` at every baseline.
4. Run the tests with `gg test --coverage`; close gaps in MC/DC with more tests or with a recorded justification.
5. Build with `--forbid-heap --forbid-recursion --max-stack N`, keep `gg stack-usage` and `gg unsafe-audit` output in the review package.
6. Produce `gg sbom` and a `gg repro` result for every release candidate.
7. Decide with the authority which tools need qualification and at what level, and plan their verification (the tool's own test suite is
   `tests/`, and the conformance suite is the natural start of a verification suite).
