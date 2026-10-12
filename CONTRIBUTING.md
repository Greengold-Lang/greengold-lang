# Contributing to Greengold

Thanks for taking an interest. Greengold is an early-stage language (see [Status](README.md#status)), so the most useful contributions right now are bug reports, small programs that the compiler gets wrong, and documentation fixes.

## Setting up

```bash
git clone https://github.com/Greengold-Lang/greengold-lang
cd Greengold-lang
python -m venv .venv
.venv/bin/pip install -e ".[test]"      # Windows: .venv\Scripts\pip
.venv/bin/python -m pytest -q           # the whole suite takes a few minutes
```

Linking needs `gcc` or `clang` on `PATH`, or `pip install greengold[toolchain]` to use `zig cc`. Run `gg toolchain` to see what was found.

## Where things live

- The compiler is Python code in `greengold/`. `README.md` has a module map.
- The language is defined by [`docs/SPEC.md`](docs/SPEC.md). When the compiler and the spec disagree, the compiler is wrong. If you change the language, change the spec in the same pull request.
- `conformance/` holds programs that pin down what the spec says. Spec code blocks are mirrored in `conformance/spec/`.
- Every diagnostic has a `GGxxxx` code in `greengold/codes.py` and an entry in `docs/ERROR_CODES.md`.
- The self-hosted compiler in `selfhost/` is frozen. Do not send changes there.

## Pull requests

- Keep one logical change per pull request, and add a test for it in `tests/`.
- Run the full suite before you open the pull request. CI runs it on Linux and Windows.
- Prefer inference and a helpful error message over a new annotation. A compiler error should say how to fix the problem; when the fix is unambiguous, attach it as a verified fix (see `greengold/friendly.py`).
- Code comments and documentation are in English.

## Reporting bugs

Open an issue with the smallest `.gg` program that shows the problem, the command you ran, the output you expected, and the output you got. Include the output of `gg toolchain`.

Security problems should be reported privately, see [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the [MIT License](LICENSE).
