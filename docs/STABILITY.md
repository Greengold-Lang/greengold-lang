# Stability

This page says what Greengold promises about change: for the language, the standard library, the
compiler, the tool interfaces, and packages built with it. It has two parts. The promises that apply
today, before 1.0, are in [Before 1.0](#before-10). The promises that start with 1.0 are in
[From 1.0](#from-10). The words "must", "may", and "will" are meant literally.

## The specification is normative

`docs/SPEC.md` defines the language. When the compiler and the spec disagree, the compiler has a bug.
`conformance/` holds a program for each example in the spec and for each form the spec rejects; an
implementation conforms when all of them behave as their headers state (`conformance/README.md`).
A change to the language is a change to the spec and to `conformance/` in the same commit.

## Terms

| Term | Meaning |
|---|---|
| **Edition** | A named version of the language, such as `2026`. A package picks one in `gg.toml`. |
| **Compiler version** | The version `gg --version` prints. It follows semantic versioning from 1.0. |
| **Breaking change** | A change after which a program that compiled and ran correctly no longer compiles, or behaves differently. |
| **Soundness bug** | A program in safe Greengold (no `unsafe:`) that the compiler accepts and that corrupts memory or has a data race. See `SECURITY.md`. |

## Editions

A package names its language edition in `gg.toml`:

```toml
[package]
name = "geo"
version = "1.2.0"
edition = "2026"
```

An edition only changes how its own files are read, so a package of one edition can use a package of
another. `gg fix` migrates a package from one edition to the next. A compiler knows every edition that
it lists in `gg --version`.

| Edition | Status | Notes |
|---|---|---|
| 2026 | current | The first edition: the language of `docs/SPEC.md`. |

### What an edition may and may not change

A new edition may make changes that stop correct code from compiling: remove or rename a construct,
change the meaning of a construct, or tighten a rule. Every such change is listed in the release notes
with its migration, and `gg fix` applies the migration wherever it can be done mechanically.

An edition is chosen at most once every three years. A release that is not a new edition never makes
such a change, except as described under [Exceptions](#exceptions).

## Before 1.0

Greengold is pre-1.0 and experimental. Edition 2026 is **not frozen**.

- A minor release (0.x) may contain breaking changes to the language, the standard library, and the
  tool interfaces. A patch release (0.x.y) does not.
- Every breaking change is listed under a **Breaking** heading in `CHANGELOG.md` for its release, with
  the migration. Where a mechanical migration exists, `gg fix` applies it.
- A construct is not removed without notice when it can be avoided: it first produces a diagnostic
  that names the replacement, in the release before the one that removes it.
- Diagnostic codes (`GGxxxx`) keep their meaning once published, also before 1.0.

Do not use Greengold for anything that must be correct yet. `README.md` lists the known limits.

## From 1.0

1.0 freezes edition 2026. After that:

1. **A program that compiles and runs correctly with a 1.x compiler under edition 2026 compiles and
   runs the same way with every later 1.y compiler.** The language, the standard library, and the
   semantics in `docs/SPEC.md` do not change in a way that breaks such a program.
2. **A compiler release keeps every edition it already supported.** Only a new major compiler version
   may drop an edition, and it announces that at least twelve months before in the release notes and
   with a warning.
3. **Within an edition the language only grows.** These may change in any release:
   - New features, new syntax that did not compile before, and new library items.
   - New diagnostics, new fixes, and clearer messages. A diagnostic code never changes its meaning, and
     a code is never reused.
   - New warnings. A warning never makes a build fail unless the package asks for that.
   - Compiler speed, code size, and the machine code produced, as long as the program's defined
     behavior stays the same. Behavior that the spec leaves unspecified is not a promise.
4. **Deprecation comes first.** An item of the language or the standard library is marked deprecated
   with a diagnostic that names its replacement. It stays for at least the rest of the edition, and it
   can be removed only by a new edition.

### Exceptions

These can break a program inside an edition. They are listed so that they are the only ones.

- **A soundness bug.** A rule that turns out to accept an unsafe program is fixed even if code relied
  on the hole. The fix goes into a patch release when it is small, the diagnostic names the change,
  and where it can it offers a fix. The release notes list it under **Soundness**. A soundness fix
  never changes a program that is sound.
- **A compiler bug.** When the compiler and the spec disagree, the compiler is fixed to match the spec.
  A program that relied on the bug may stop compiling.
- **A security fix** in the package tooling (`gg fetch`, `gg.lock`), reported through `SECURITY.md`.
- **`unsafe:` code and `extern`.** The behavior of a program that uses `unsafe:`, `trust`, a raw
  pointer, inline assembly, or `extern` is only defined while it keeps the rules the spec states for
  them; it can change when it does not.

## The standard library

The standard library is part of the edition. From 1.0, items are added but not removed or changed in
behavior, except through deprecation and a new edition. An item that is documented as experimental is
not covered; the documentation says so on the item.

## Tool interfaces

| Interface | Promise from 1.0 |
|---|---|
| `gg check --json`, `gg test --json`, `gg api --json`, `gg attrs` | Their schemas (`docs/gg-diagnostics.schema.json`, `docs/gg-test.schema.json`) only gain fields within a major version. A field is never removed or given a new meaning. A tool must ignore fields it does not know. |
| Diagnostic codes (`docs/ERROR_CODES.md`) | A code keeps its meaning, also before 1.0. |
| Exit codes of `gg` commands | They keep their meaning. |
| The text of messages, the layout of `gg fmt`, the output of `gg doc` | Not covered. Do not parse them; use the JSON interfaces. |
| The Python package `greengold` | Not covered. Its modules are the implementation, not an interface. |

## Versions of the compiler

`gg --version` prints the compiler version and the editions it knows. From 1.0 the compiler follows
semantic versioning:

- **Major:** may drop an old edition or change a tool interface.
- **Minor:** adds features, library items, diagnostics, and editions.
- **Patch:** fixes bugs, including soundness bugs.

## Versions of a package

Parameter modes are inferred from function bodies, so a package records its public API in
`gg.api.lock` (`gg api --lock`). `gg api --check` reports a breaking change that the version in
`gg.toml` does not allow under semantic versioning, and `gg build` warns about it. See section 18 of
the spec for what counts as breaking.

## How a change is made

1. The change is made in `docs/SPEC.md` and `conformance/`, with tests, in one commit.
2. `CHANGELOG.md` records it under the release: new features, **Breaking** (before 1.0),
   **Soundness**, and **Deprecated**.
3. A breaking change names its migration, and `gg fix` applies it when it is mechanical.
4. A change to this page is itself listed in the release notes.

## Road to 1.0

1.0 freezes edition 2026 under the rules above. It waits for these:

- The known soundness gaps listed in `README.md` are closed or have a documented, tested workaround.
- The specification and `conformance/` agree on every construct, with no section marked incomplete.
- The compiler is verified on Windows, Linux, and macOS in CI.
- At least one release with every breaking change that is still wanted has been published, so that the
  freeze starts from the language the community has tried.

Before 1.0, the edition may still change in breaking ways under [Before 1.0](#before-10).
