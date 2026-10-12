(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var editor = $("pg-editor"), out = $("pg-out"), status = $("pg-status"), gutter = $("pg-gutter");
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
  function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }

  function lines() {
    var n = editor.value.split("\n").length, s = "";
    for (var i = 1; i <= n; i++) s += i + "\n";
    gutter.textContent = s;
    gutter.scrollTop = editor.scrollTop;
  }

  function show(text, ok) {
    if (ok) { out.innerHTML = '<span class="pg-ok">No errors.</span>'; return; }
    out.innerHTML = esc(text)
      .replace(/(main\.gg):(\d+):(\d+)/g, '<a href="#" data-line="$2" data-col="$3">$1:$2:$3</a>')
      .replace(/\b(GG\d{4})\b/g, '<a href="#" data-explain="$1">$1</a>');
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

  function put(src) { editor.value = src; lines(); saveHash(); check(); }

  editor.addEventListener("input", function () { lines(); later(); saveHash(); });
  editor.addEventListener("scroll", function () { gutter.scrollTop = editor.scrollTop; });
  editor.addEventListener("keydown", function (e) {
    if (e.key === "Tab") {
      e.preventDefault();
      editor.setRangeText("    ", editor.selectionStart, editor.selectionEnd, "end");
      editor.dispatchEvent(new Event("input"));
    }
  });

  out.addEventListener("click", function (e) {
    var a = e.target.closest("a");
    if (!a) return;
    e.preventDefault();
    if (a.dataset.line) {
      var ls = editor.value.split("\n"), pos = 0, n = +a.dataset.line - 1;
      for (var i = 0; i < n; i++) pos += ls[i].length + 1;
      editor.focus();
      editor.setSelectionRange(pos + (+a.dataset.col - 1), pos + ls[n].length);
    } else if (a.dataset.explain) {
      call("explain", a.dataset.explain).then(function (t) { out.innerHTML = "<pre>" + esc(t) + "</pre>"; });
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
