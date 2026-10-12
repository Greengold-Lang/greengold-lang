// Runs the Greengold front end off the main thread and reports start-up progress as a percentage.
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

var py = null;

// Start-up has three parts: downloading the runtime (counted in bytes, 0 to 85%), unpacking the compiler (85 to 93%),
// and starting it (93 to 100%). The sizes are what the CDN serves for the files fetched through fetch().
var RUNTIME_BYTES = 12536000, loaded = 0, shown = -1;
function progress(pct, label) {
  pct = Math.max(0, Math.min(100, Math.round(pct)));
  if (pct === shown && !label) return;
  shown = pct;
  postMessage({ type: "status", text: (label || "Starting the compiler…") + " " + pct + "%", percent: pct });
}

var realFetch = self.fetch;
self.fetch = function (input, init) {
  return realFetch(input, init).then(function (res) {
    if (!res.body || res.url.indexOf("pyodide") < 0) return res;
    var counted = res.body.pipeThrough(new TransformStream({
      transform: function (chunk, controller) {
        loaded += chunk.byteLength;
        progress(85 * Math.min(1, loaded / RUNTIME_BYTES));
        controller.enqueue(chunk);
      },
    }));
    return new Response(counted, { status: res.status, statusText: res.statusText, headers: res.headers });
  });
};

var ready = (async function () {
  progress(0);
  py = await loadPyodide();
  self.fetch = realFetch;
  progress(85, "Loading the compiler…");
  var zip = await (await fetch("gg-bundle.zip", { cache: "no-cache" })).arrayBuffer();
  py.unpackArchive(zip, "zip", { extractDir: "/lib" });
  progress(93, "Loading the compiler…");
  py.runPython("import sys; sys.path.insert(0, '/lib')");
  py.runPython("from greengold import web");
  progress(100, "Ready");
  postMessage({ type: "ready", version: py.runPython("web.version()") });
})().catch(function (e) { postMessage({ type: "fatal", text: String(e) }); });

onmessage = async function (ev) {
  var id = ev.data.id, fn = ev.data.fn, args = ev.data.args;
  try {
    await ready;
    var f = py.runPython("web." + fn);
    var result = f.apply(null, args);
    if (f.destroy) f.destroy();
    postMessage({ type: "result", id: id, result: result });
  } catch (e) {
    postMessage({ type: "error", id: id, text: String(e) });
  }
};
