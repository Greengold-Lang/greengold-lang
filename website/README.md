# Greengold website

Static site in this directory: HTML, CSS, and JavaScript. Cloudflare Pages publishes this folder with an empty build command.

## Cloudflare Pages

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
- `benchmarks/data.json` — the 9 October 2026 report, seventeen workloads; `benchmarks/src/` holds the sources
- `diagnostics/` — the GG0301 example and its `gg check` output
- `style.css`, `app.js` — shared by every page (dark and light theme, code tabs, spec contents)
- `llms.txt`, `robots.txt`, `sitemap.xml`, `_headers`
- `assets/` — logo and favicon

## Playground

`playground.html` runs the compiler front end in the browser (Pyodide, in a Web Worker). `playground/gg-bundle.zip` holds `greengold/` and `llvmlite.ir`; rebuild it with `python tools/build_playground.py` whenever the compiler changes, then commit it. Pyodide itself loads from the jsDelivr CDN. Running programs would need LLVM in WebAssembly and is not part of the playground yet.
