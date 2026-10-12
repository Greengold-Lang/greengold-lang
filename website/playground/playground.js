(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var editor = $("pg-editor"), out = $("pg-out"), status = $("pg-status"), gutter = $("pg-gutter");
  var runOut = $("pg-runout"), runBtn = $("pg-run"), stopBtn = $("pg-stop"), hl = $("pg-hl");
  var release = false, H = window.GGHighlight;
  var LIMIT_MS = 10000, LIMIT_CHARS = 200000;
  var toolchain = null, runner = null, killTimer = null, running = false;
  var examples = {}, seq = 0, pending = {}, ready = false, timer = null, version = 0;

  var worker = new Worker("playground/worker.js");
  worker.onmessage = function (ev) {
    var m = ev.data;
    if (m.type === "status") setStatus(m.text, "busy");
    else if (m.type === "ready") { ready = true; setStatus("Ready · gg " + m.version, "ok"); check(); }
    else if (m.type === "fatal") setStatus("Could not load the compiler: " + m.text, "bad");
    else if (pending[m.id]) { var p = pending[m.id]; delete pending[m.id]; m.type === "result" ? p.ok(m.result) : p.err(m.text); }
  };
  function call(fn) {
    var args = Array.prototype.slice.call(arguments, 1);
    return new Promise(function (ok, err) { var id = ++seq; pending[id] = { ok: ok, err: err }; worker.postMessage({ id: id, fn: fn, args: args }); });
  }
  function setStatus(t, kind) { status.textContent = t; status.dataset.kind = kind || ""; }
  function esc(s) { return H.esc(s); }

  function lines() {
    var n = editor.value.split("\n").length, s = "";
    for (var i = 1; i <= n; i++) s += i + "\n";
    gutter.textContent = s;
    hl.innerHTML = H.source(editor.value) + "\n";   // the colored copy under the transparent textarea
    sync();
  }
  function sync() {
    gutter.scrollTop = hl.scrollTop = editor.scrollTop;
    hl.scrollLeft = editor.scrollLeft;
  }

  function show(text, ok) {
    if (ok) { out.innerHTML = '<span class="pg-ok">No errors.</span>'; return; }
    out.innerHTML = H.terminal(text);
  }

  function check() {
    if (!ready) return;
    var v = ++version;
    setStatus("Checking…", "busy");
    var t0 = performance.now();
    call("check", editor.value).then(function (json) {
      if (v !== version) return;
      var d = JSON.parse(json);
      show(d.text, d.ok);
      var n = d.summary.errors, w = d.summary.warnings;
      setStatus((n ? n + " error" + (n > 1 ? "s" : "") : "ok") + (w ? ", " + w + " warning" + (w > 1 ? "s" : "") : "") +
        " · " + Math.round(performance.now() - t0) + " ms", n ? "bad" : "ok");
    }).catch(function (e) { setStatus("Internal error: " + e, "bad"); });
  }
  function later() { clearTimeout(timer); timer = setTimeout(check, 350); }

  // ---- Run: front end (Pyodide) -> LLVM IR -> clang + lld (WebAssembly) -> the program, in a worker ----
  function tab(name) {
    ["diag", "output"].forEach(function (n) {
      $("pg-tab-" + n).setAttribute("aria-selected", String(n === name));
      (n === "diag" ? out : runOut).hidden = n !== name;
    });
  }
  $("pg-tab-diag").addEventListener("click", function () { tab("diag"); });
  $("pg-tab-output").addEventListener("click", function () { tab("output"); });

  function say(text, cls, colored) {
    var span = document.createElement("span");
    if (cls) span.className = cls;
    if (colored) span.innerHTML = H.terminal(text) + (/\n$/.test(text) ? "\n" : ""); else span.textContent = text;
    runOut.appendChild(span);
    runOut.scrollTop = runOut.scrollHeight;
  }
  function finish(note, kind) {
    if (!running) return;
    running = false;
    clearTimeout(killTimer);
    runBtn.hidden = false; stopBtn.hidden = true;
    if (runner) { runner.terminate(); runner = null; }
    if (note) say("\n" + note + "\n", "pg-note");
    setStatus(note || "Done", kind || "ok");
  }
  function run() {
    if (running || !ready) return;
    running = true;
    runBtn.hidden = true; stopBtn.hidden = false;
    runOut.textContent = "";
    tab("output");
    setStatus("Building…", "busy");
    var t0 = performance.now();
    call("build", editor.value, release).then(function (json) {
      var r = JSON.parse(json);
      if (!r.ok) {
        runOut.innerHTML = H.terminal(r.text);
        finish("Could not build.", "bad");
        return null;
      }
      if (!toolchain) toolchain = new Worker("playground/toolchain.js");
      return new Promise(function (ok, fail) {
        toolchain.onmessage = function (m) {
          if (m.data.type === "status") setStatus(m.data.text, "busy");
          else if (m.data.type === "built") ok(m.data);
          else if (m.data.type === "error") fail(m.data.text);
        };
        toolchain.onerror = function (e) { fail("Toolchain error: " + (e.message || e)); };
        toolchain.postMessage({ type: "build", ir: r.ir });
      });
    }).then(function (built) {
      if (!built || !running) return;
      var buildMs = Math.round(performance.now() - t0), t1 = performance.now();
      setStatus("Running…", "busy");
      runner = new Worker("playground/runner.js");
      killTimer = setTimeout(function () { finish("Stopped: the program ran longer than " + LIMIT_MS / 1000 + " s.", "bad"); }, LIMIT_MS);
      var shown = 0;
      runner.onmessage = function (m) {
        var d = m.data;
        if (d.type === "out") {
          shown += d.text.length;
          if (shown > LIMIT_CHARS) { finish("Stopped: more than " + LIMIT_CHARS / 1000 + "k characters of output.", "bad"); return; }
          say(d.text, "", d.fd === 2);
        } else if (d.type === "done") {
          finish("exit code " + d.code + " · build " + buildMs + " ms · run " + Math.round(performance.now() - t1) + " ms",
            d.code === 0 ? "ok" : "bad");
        } else if (d.type === "error") {
          finish(d.text, "bad");
        }
      };
      runner.postMessage({ wasm: built.wasm, stdin: $("pg-stdin").value }, [built.wasm]);
    }).catch(function (e) { runOut.textContent = String(e); finish("Build failed.", "bad"); });
  }
  runBtn.addEventListener("click", run);
  stopBtn.addEventListener("click", function () { finish("Stopped.", "bad"); });
  editor.addEventListener("keydown", function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); run(); }
  });
  function onLink(pane) {
    return function (e) {
      var a = e.target.closest("a");
      if (!a) return;
      e.preventDefault();
      if (a.dataset.line) {
        var ls = editor.value.split("\n"), pos = 0, n = +a.dataset.line - 1;
        for (var i = 0; i < n && i < ls.length; i++) pos += ls[i].length + 1;
        editor.focus();
        editor.setSelectionRange(pos + (+a.dataset.col - 1), pos + (ls[n] || "").length);
      } else if (a.dataset.explain) {
        call("explain", a.dataset.explain).then(function (t) { pane.innerHTML = "<pre>" + H.esc(t) + "</pre>"; });
      }
    };
  }
  runOut.addEventListener("click", onLink(runOut));
  out.addEventListener("click", onLink(out));

  // Debug / Release
  Array.prototype.forEach.call(document.querySelectorAll("#pg-mode button"), function (b) {
    b.addEventListener("click", function () {
      release = b.dataset.mode === "release";
      Array.prototype.forEach.call(document.querySelectorAll("#pg-mode button"), function (o) {
        o.setAttribute("aria-checked", String(o === b));
      });
    });
  });

  function put(src) { editor.value = src; lines(); saveHash(); check(); }

  editor.addEventListener("input", function () { lines(); later(); saveHash(); });
  editor.addEventListener("scroll", sync);
  editor.addEventListener("keydown", function (e) {
    if (e.key === "Tab") {
      e.preventDefault();
      editor.setRangeText("    ", editor.selectionStart, editor.selectionEnd, "end");
      editor.dispatchEvent(new Event("input"));
    }
  });

  $("pg-format").addEventListener("click", function () { call("format", editor.value).then(put); });
  $("pg-fix").addEventListener("click", function () {
    call("fix", editor.value, false).then(function (json) {
      var r = JSON.parse(json);
      put(r.source);
      if (r.applied.length) setStatus("Applied " + r.applied.length + " fix" + (r.applied.length > 1 ? "es" : ""), "ok");
    });
  });
  $("pg-fixlikely").addEventListener("click", function () {
    call("fix", editor.value, true).then(function (json) { put(JSON.parse(json).source); });
  });
  $("pg-share").addEventListener("click", function () {
    saveHash();
    if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(
      function () { setStatus("Link copied", "ok"); }, function () { setStatus("Copy the address bar", ""); });
  });
  $("pg-examples").addEventListener("change", function (e) {
    if (examples[e.target.value]) put(examples[e.target.value]);
  });

  function saveHash() {
    try { history.replaceState(null, "", "#code=" + encodeURIComponent(btoa(unescape(encodeURIComponent(editor.value))))); } catch (e) { /* too long to share */ }
  }
  function loadHash() {
    var m = /^#code=(.+)$/.exec(location.hash);
    if (!m) return null;
    try { return decodeURIComponent(escape(atob(decodeURIComponent(m[1])))); } catch (e) { return null; }
  }

  fetch("playground/examples.json").then(function (r) { return r.json(); }).then(function (ex) {
    examples = ex;
    var sel = $("pg-examples");
    Object.keys(ex).forEach(function (k) { var o = document.createElement("option"); o.value = k; o.textContent = k + ".gg"; sel.appendChild(o); });
    var shared = loadHash();
    editor.value = shared !== null ? shared : ex.hello;
    lines();
    check();
  });
  setStatus("Loading…", "busy");
})();
