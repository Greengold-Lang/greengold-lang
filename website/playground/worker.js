// Runs Pyodide and the Greengold front end off the main thread.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let py = null;
const ready = (async () => {
  postMessage({ type: "status", text: "Loading Python…" });
  py = await loadPyodide();
  postMessage({ type: "status", text: "Loading the compiler…" });
  const zip = await (await fetch("gg-bundle.zip", { cache: "no-cache" })).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/lib" });
  py.runPython("import sys; sys.path.insert(0, '/lib')");
  py.runPython("from greengold import web");
  postMessage({ type: "ready", version: py.runPython("web.version()") });
})().catch((e) => postMessage({ type: "fatal", text: String(e) }));

onmessage = async (ev) => {
  const { id, fn, args } = ev.data;
  try {
    await ready;
    const f = py.runPython(`web.${fn}`);
    const result = f(...args);
    f.destroy && f.destroy();
    postMessage({ type: "result", id, result });
  } catch (e) {
    postMessage({ type: "error", id, text: String(e) });
  }
};
