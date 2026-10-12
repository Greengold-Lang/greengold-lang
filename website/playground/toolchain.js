// Compiles LLVM IR to a runnable WebAssembly module in the browser: clang (IR -> object) and lld (link with wasi-libc).
// The two tools are WebAssembly builds by Ben Smith (github.com/binji/wasm-clang, Apache-2.0), run through his glue
// code in llvm-glue.js. Messages in: {type: "build", ir}. Messages out: status, built {wasm}, or error {text}.
importScripts("llvm-glue.js");

var SIZES = { clang: 31214472, lld: 19490094 };            // bytes, uncompressed: for the progress figure
var FALLBACK = "https://binji.github.io/wasm-clang/";      // used when ./llvm/ was not deployed
var WASI_FILES = ["crt1.o", "libc.a", "libc.imports", "libclang_rt.builtins-wasm32.a"];

var api = null, modules = {}, log = "", loading = null;

function status(text) { postMessage({ type: "status", text: text }); }

function concat(chunks, total) {
  var out = new Uint8Array(total), at = 0;
  chunks.forEach(function (c) { out.set(c, at); at += c.length; });
  return out;
}

async function fetchBytes(url, onBytes) {
  var res = await fetch(url, { cache: "force-cache" });
  if (!res.ok) throw new Error(url + ": " + res.status);
  var reader = res.body.getReader(), chunks = [], got = 0;
  for (;;) {
    var r = await reader.read();
    if (r.done) break;
    chunks.push(r.value);
    got += r.value.length;
    onBytes(r.value.length);
  }
  return concat(chunks, got);
}

async function haveLocalCopy() {
  try { return (await fetch("llvm/memfs.wasm", { method: "HEAD" })).ok; } catch (e) { return false; }
}

async function load() {
  var local = await haveLocalCopy();
  var total = SIZES.clang + SIZES.lld, loaded = 0;
  function progress(n) {
    loaded += n;
    status("Downloading the compiler (first Run only): " + Math.min(99, Math.round(100 * loaded / total)) + "% of ~" +
      Math.round(total / 1048576) + " MB");
  }
  var memfs, clangBytes, lldBytes;
  if (local) {
    memfs = await fetchBytes("llvm/memfs.wasm", function () {});
    clangBytes = concat([await fetchBytes("llvm/clang.0.wasm", progress), await fetchBytes("llvm/clang.1.wasm", progress)], SIZES.clang);
    lldBytes = await fetchBytes("llvm/lld.wasm", progress);
  } else {
    memfs = await fetchBytes(FALLBACK + "memfs", function () {});
    clangBytes = await fetchBytes(FALLBACK + "clang", progress);
    lldBytes = await fetchBytes(FALLBACK + "lld", progress);
  }
  status("Preparing the compiler…");
  modules.memfs = await WebAssembly.compile(memfs);
  modules.clang = await WebAssembly.compile(clangBytes);
  modules.lld = await WebAssembly.compile(lldBytes);
  api = new API({
    readBuffer: async function () { return new Uint8Array(1024); },   // an empty tar: no sysroot to unpack
    compileStreaming: async function (name) { return modules[name]; },
    hostWrite: function (s) { log += s; },
    memfs: "memfs", clang: "clang", lld: "lld", sysroot: "none.tar",
  });
  await api.ready;
  for (var i = 0; i < WASI_FILES.length; i++) {
    var name = WASI_FILES[i];
    api.memfs.addFile(name, new Uint8Array(await (await fetch("wasi/" + name)).arrayBuffer()));
  }
}

function clean(s) { return s.replace(/\x1b\[[0-9;]*m/g, ""); }

async function build(ir) {
  if (!loading) loading = load();
  await loading;
  log = "";
  var t0 = performance.now();
  api.memfs.addFile("main.ll", ir);
  status("Compiling…");
  try {
    await api.run(await api.getModule("clang"), "clang", "-cc1", "-emit-obj", "-disable-free", "-triple",
      "wasm32-unknown-wasi", "-O2", "-o", "main.o", "-x", "ir", "main.ll");
  } catch (e) { return { ok: false, text: "LLVM: " + clean(log).trim() }; }
  status("Linking…");
  try {
    await api.run(await api.getModule("lld"), "wasm-ld", "--no-threads", "--allow-undefined-file=libc.imports",
      "-z", "stack-size=1048576", "crt1.o", "main.o", "libc.a", "libclang_rt.builtins-wasm32.a", "-o", "main.wasm");
  } catch (e) { return { ok: false, text: "Linker: " + clean(log).trim() }; }
  var wasm = api.memfs.getFileContents("main.wasm");
  return { ok: true, wasm: wasm, ms: Math.round(performance.now() - t0) };
}

onmessage = function (ev) {
  if (ev.data.type !== "build") return;
  build(ev.data.ir).then(function (r) {
    if (r.ok) postMessage({ type: "built", wasm: r.wasm.buffer.slice(r.wasm.byteOffset, r.wasm.byteOffset + r.wasm.byteLength), ms: r.ms });
    else postMessage({ type: "error", text: r.text });
  }, function (e) {
    loading = null;
    postMessage({ type: "error", text: "Could not load the compiler: " + e });
  });
};
