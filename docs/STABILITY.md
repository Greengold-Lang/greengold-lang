# Stability

This page says what Greengold promises about change: for the language, for the compiler, and for
packages built with it.

## The specification is normative

`docs/SPEC.md` defines the language. When the compiler and the spec disagree, the compiler has a bug.
`conformance/` holds a program for each example in the spec and for each form the spec rejects; an
implementation conforms when all of them behave as their headers state (`conformance/README.md`).

## Editions

A package names its language edition in `gg.toml`:

```toml
[package]
name = "geo"
version = "1.2.0"
edition = "2026"
```

Within an edition the language only grows. These may change inside an edition:

- New features, new syntax that did not compile before, and new library items.
- Better diagnostics: new codes, new fixes, clearer messages. A code's meaning does not change.
- A rule that turns out unsound is fixed even if code that relied on the hole stops compiling. The
  diagnostic names the change and, where it can, offers a fix.

A change that would stop correct code from compiling waits for the next edition. `gg fix` migrates a
package from one edition to the next. An edition only changes how its own files are read, so a package
of one edition can use a package of another.

| Edition | Status | Notes |
|---|---|---|
| 2026 | current | The first edition: the language of `docs/SPEC.md`. |

## Versions of the compiler

`gg --version` prints the compiler version and the editions it knows. The compiler follows semantic
versioning: a new major version may drop an old edition; every other release keeps compiling every
edition it already supported.

## Versions of a package

Parameter modes are inferred from function bodies, so a package records its public API in
`gg.api.lock` (`gg api --lock`). `gg api --check` reports a breaking change that the version in
`gg.toml` does not allow under semantic versioning, and `gg build` warns about it. See section 18 of
the spec for what counts as breaking.

## Road to 1.0

1.0 freezes the 2026 edition under the rules above. Before 1.0, the edition may still change in
breaking ways; each such change is listed in the release notes with its migration.
