// Runs one compiled program with a small WASI host: stdout and stderr stream back to the page, stdin comes from the
// page, and there is no file system. The page ends this worker when the program runs too long.
// Messages in: {wasm, stdin, args}. Messages out: out {fd, text}, done {code}, error {text}.
var ENOSYS = 52, EBADF = 8, ENOENT = 44;

onmessage = async function (ev) {
  var stdin = new TextEncoder().encode(ev.data.stdin || ""), stdinAt = 0;
  var args = ["main"].concat(ev.data.args || []);
  var enc = new TextEncoder(), decoders = [null, new TextDecoder(), new TextDecoder()];
  var mem = null;
  function view() { return new DataView(mem.buffer); }
  function bytes() { return new Uint8Array(mem.buffer); }
  function ExitCode(code) { this.code = code; }

  var wasi = {
    args_sizes_get: function (countPtr, sizePtr) {
      var size = 0; args.forEach(function (a) { size += enc.encode(a).length + 1; });
      view().setUint32(countPtr, args.length, true); view().setUint32(sizePtr, size, true); return 0;
    },
    args_get: function (argvPtr, bufPtr) {
      args.forEach(function (a, i) {
        view().setUint32(argvPtr + 4 * i, bufPtr, true);
        var b = enc.encode(a); bytes().set(b, bufPtr); bytes()[bufPtr + b.length] = 0; bufPtr += b.length + 1;
      });
      return 0;
    },
    environ_sizes_get: function (countPtr, sizePtr) { view().setUint32(countPtr, 0, true); view().setUint32(sizePtr, 0, true); return 0; },
    environ_get: function () { return 0; },
    fd_write: function (fd, iovs, n, writtenPtr) {
      if (fd !== 1 && fd !== 2) return EBADF;
      var total = 0, v = view(), text = "";
      for (var i = 0; i < n; i++) {
        var ptr = v.getUint32(iovs + 8 * i, true), len = v.getUint32(iovs + 8 * i + 4, true);
        text += decoders[fd].decode(bytes().subarray(ptr, ptr + len), { stream: true });
        total += len;
      }
      if (text) postMessage({ type: "out", fd: fd, text: text });
      v.setUint32(writtenPtr, total, true);
      return 0;
    },
    fd_read: function (fd, iovs, n, readPtr) {
      if (fd !== 0) return EBADF;
      var v = view(), got = 0;
      for (var i = 0; i < n && stdinAt < stdin.length; i++) {
        var ptr = v.getUint32(iovs + 8 * i, true), len = v.getUint32(iovs + 8 * i + 4, true);
        var take = Math.min(len, stdin.length - stdinAt);
        bytes().set(stdin.subarray(stdinAt, stdinAt + take), ptr); stdinAt += take; got += take;
      }
      v.setUint32(readPtr, got, true);
      return 0;
    },
    fd_fdstat_get: function (fd, ptr) {
      if (fd > 2) return EBADF;
      var v = view();                          // a character device that only writes (reads for stdin): a terminal
      v.setUint8(ptr, 2); v.setUint16(ptr + 2, 0, true);
      v.setBigUint64(ptr + 8, fd === 0 ? 2n : 64n, true); v.setBigUint64(ptr + 16, 0n, true);
      return 0;
    },
    fd_prestat_get: function () { return EBADF; },
    fd_prestat_dir_name: function () { return EBADF; },
    fd_close: function () { return 0; },
    fd_seek: function () { return 70; },       // ESPIPE
    path_open: function () { return ENOENT; },
    clock_time_get: function (id, precision, ptr) {
      var ns = id === 0 ? BigInt(Date.now()) * 1000000n : BigInt(Math.round(performance.now() * 1e6));
      view().setBigUint64(ptr, ns, true);
      return 0;
    },
    clock_res_get: function (id, ptr) { view().setBigUint64(ptr, 1000n, true); return 0; },
    random_get: function (ptr, len) { crypto.getRandomValues(bytes().subarray(ptr, ptr + len)); return 0; },
    poll_oneoff: function () { return ENOSYS; },
    proc_exit: function (code) { throw new ExitCode(code); },
    sched_yield: function () { return 0; },
  };
  // Anything else a program imports answers "not implemented" rather than failing to start.
  var imports = { wasi_unstable: new Proxy(wasi, { get: function (t, k) { return k in t ? t[k] : function () { return ENOSYS; }; } }) };
  imports.wasi_snapshot_preview1 = imports.wasi_unstable;

  try {
    var inst = (await WebAssembly.instantiate(ev.data.wasm, imports)).instance;
    mem = inst.exports.memory;
    inst.exports._start();
    postMessage({ type: "done", code: 0 });
  } catch (e) {
    if (e instanceof ExitCode) postMessage({ type: "done", code: e.code });
    else postMessage({ type: "error", text: e instanceof WebAssembly.RuntimeError ? "trap: " + e.message : String(e) });
  }
};
