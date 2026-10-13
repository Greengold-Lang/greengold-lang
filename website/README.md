# Greengold website

Static site in this directory: HTML, CSS, and JavaScript. Cloudflare Pages publishes this folder with an empty build command.

## Updating the live site: checklist

The site is published by uploading this folder directly to Cloudflare Pages (not through Git), so what is on disk when you upload is what goes live. From the repository root:

1. **Compiler, standard library, `docs/`, or any `playground/*.js` changed?** Rebuild what the site embeds (`build_site.py` also stamps the scripts' content hash into `playground.html`, so a changed script is never served from a stale cache):
   ```bash
   python tools/build_playground.py   # playground/gg-bundle.zip: the compiler the playground runs
   python tools/build_site.py         # every *.html page, spec.md, sitemap.xml
   ```
   Also regenerate `diagnostics/use-after-consume.txt` and `.json` with `gg check` when diagnostics output changed, and refresh `benchmarks/data.json` after a new benchmark run.
2. **Check that the LLVM files are present** (they are git-ignored, so a fresh clone does not have them):
   ```bash
   ls website/playground/llvm      # clang.0.wasm clang.1.wasm lld.wasm memfs.wasm
   python tools/fetch_llvm.py      # only if the folder is missing or empty
   ```
   Without them the playground's Run falls back to binji.github.io (uncompressed, about 50 MB, not under our control).
3. **Run the tests:** `python -m pytest -q` (a test fails when `gg-bundle.zip` is older than the compiler).
4. **Try the playground locally** before uploading: `python -m http.server 8765 -d website`, open `http://localhost:8765/playground.html`, press Run once.
5. **Upload the whole `website/` folder** to the Pages project (Workers & Pages, the project, Create new deployment, upload the folder). Upload the folder itself, with `playground/llvm/` inside it; the single files are each under Pages' 25 MiB limit, and `_headers` goes with it.
6. **After the upload,** open the live `/playground.html` in a private window and press Run: the first Run should download the compiler (about 20 MB) and print output; a second Run should be instant.
7. Commit the generated files (`gg-bundle.zip`, the `*.html` pages) so the repository matches what is live. Do not commit `playground/llvm/`.

Do not run `python tools/fetch_llvm.py` on every update; the files only change if the pinned versions in that script change.

## Cloudflare Pages (connect to Git instead)

Only for a Git-connected project. A Git-connected deploy does not contain `playground/llvm/` (it is git-ignored), so Run would use the slow fallback; to use Git, remove the `website/playground/llvm/` line from `.gitignore` and commit those files (about 51 MB).

1. Open Workers & Pages, then Create application, Pages, Connect to Git.
2. Select the Greengold-lang repository.
3. Build settings:
   - Framework preset: None
   - Build command: leave empty
   - Build output directory: `website`
4. Save and deploy.

From the repository root, Wrangler does the same upload:

```bash
npx wrangler pages deploy website --project-name greengold
```

## Building the pages

The HTML pages are generated. Edit `tools/build_site.py` (layout, page text, examples), `style.css`, or `app.js`, then run from the repository root:

```bash
python tools/build_site.py
```

The script writes every `*.html` page, copies `docs/SPEC.md` to `website/spec.md`, renders `spec.html` from it, builds `benchmarks.html` from `benchmarks/data.json` (workload descriptions live in `tools/site_workloads.json`), and refreshes `sitemap.xml`. Commit the output; Cloudflare Pages serves the folder as it is and does not run the script.

When `docs/SPEC.md` changes, run the script again. When the compiler output changes, regenerate `diagnostics/use-after-consume.txt` and `.json` with `gg check` first.

## Files

- `index.html`, `why.html`, `spec.html`, `benchmarks.html`, `diagnostics.html`, `roadmap.html`, `about.html` — generated
- `spec.md` — a copy of `docs/SPEC.md`
- `benchmarks/data.json` — the 13 October 2026 report, eighteen workloads; `benchmarks/src/` holds the sources
- `diagnostics/` — the GG0301 example and its `gg check` output
- `style.css`, `app.js` — shared by every page (dark and light theme, code tabs, spec contents)
- `llms.txt`, `robots.txt`, `sitemap.xml`, `_headers`
- `assets/` — logo and favicon

## Playground

`playground.html` compiles and runs Greengold in the browser.

* **Front end:** Pyodide in a Web Worker runs `greengold/` (`playground/worker.js`). `playground/gg-bundle.zip` holds `greengold/` and `llvmlite.ir`; rebuild it with `python tools/build_playground.py` whenever the compiler changes, then commit it (a test checks it). Pyodide loads from the jsDelivr CDN.
* **Editor:** `playground/editor.js` adds closing brackets and quotes, indentation, Tab and Shift+Tab, Ctrl+/ comments, and word completion to the textarea; `playground/highlight.js` colors the source and the compiler output (same token classes as `tools/build_site.py`, so change both together).
* **Run:** the front end writes LLVM IR for `wasm32-wasi`; `playground/toolchain.js` compiles it with clang and lld as WebAssembly (Ben Smith's builds, `playground/llvm-glue.js`, see `playground/NOTICE.md`) and links it with the wasi-libc files in `playground/wasi/` (committed, about 1 MB); `playground/runner.js` runs the result with a small WASI host. The page ends a program after 10 seconds.
* **Self-hosting the toolchain:** run `python tools/fetch_llvm.py` before publishing. It checks the SHA-256 of the files, splits `clang` in two (Pages allows 25 MiB per file), and writes `playground/llvm/` (about 51 MB, git-ignored, so deploy with `npx wrangler pages deploy website`, or remove the line from `.gitignore` to commit it). Cloudflare compresses `.wasm`, so visitors download about 20 MB, once. Without `playground/llvm/` the page falls back to binji.github.io/wasm-clang, which is not compressed (about 50 MB) and is not yours to depend on.
