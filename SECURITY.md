# Security policy

Greengold is pre-1.0 software. The compiler has not been audited, and the memory-safety guarantees of the language are still being tightened (see the known gaps under [Status](README.md#status)).

## Reporting a vulnerability

Please do not open a public issue for a security problem. Email **founder@greengoldlang.com** with:

- what is affected (the compiler, the standard library, the language server, or generated code),
- a minimal `.gg` program or steps that reproduce it,
- the Greengold version (`gg --version`) and the output of `gg toolchain`.

You can expect an answer within a week.

## What counts

- A program in safe Greengold (no `unsafe:`) that corrupts memory, such as a use-after-free, an out-of-bounds access that is not trapped, or a data race.
- A way for a malicious `.gg` file, `gg.toml`, or package to run code at compile time beyond what `comptime fn` is documented to do.
- Flaws in package fetching (`gg fetch`, `gg.lock`).

Soundness gaps that are already listed in the README are known and are tracked as ordinary issues.
