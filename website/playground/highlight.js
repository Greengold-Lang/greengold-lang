// Colors for the playground: Greengold source (editor) and compiler output (diagnostics, runtime errors).
// Same token rules and classes as tools/build_site.py, so the editor matches the code blocks on the rest of the site.
(function (global) {
  "use strict";
  function set(words) { var o = {}; words.split(" ").forEach(function (w) { o[w] = true; }); return o; }
  var KEYWORDS = set("fn struct impl enum feature match if elif else then return fixed const for in while break continue pass " +
    "defer and or not test require import type comptime hot extern unsafe trust soa copy lend consume read exclusive let step " +
    "as tied to private public overflow wrapping ref mut self var");
  var CONSTANTS = set("true false null");
  var TYPES = set("i8 i16 i32 i64 isize u8 u16 u32 u64 usize f32 f64 bool str string int uint float double void");
  var TOKEN = /(#.*$)|([f$]?"(?:\\.|[^"\\])*"?)|('(?:\\.|[^'\\])*')|(\b(?:0x[0-9a-fA-F_]+|0b[01_]+|\d[\d_]*(?:\.\d[\d_]*)?(?:[eE][+-]?\d+)?)\b)|([A-Za-z_][A-Za-z0-9_]*)|(=>|->|\.\.=|\.\.|[+\-*\/%]=|==|!=|<=|>=|=)/g;

  function esc(s) { return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }
  function span(cls, text) { return '<span class="' + cls + '">' + esc(text) + "</span>"; }

  // Names the file declares as types (`struct point:`, `enum shape:`, ...), so they are colored even in lowercase.
  var DECL = /\b(?:struct|enum|feature|union|type|impl)\s+([A-Za-z_][A-Za-z0-9_]*)/g;
  function declared(src) {
    var names = {}, m;
    DECL.lastIndex = 0;
    while ((m = DECL.exec(src)) !== null) names[m[1]] = true;
    return names;
  }

  function line(src, names) {
    var out = "", pos = 0, m;
    TOKEN.lastIndex = 0;
    while ((m = TOKEN.exec(src)) !== null) {
      out += esc(src.slice(pos, m.index));
      var text = m[0], cls = "";
      if (m[1] !== undefined) cls = "tok-comment";
      else if (m[2] !== undefined || m[3] !== undefined) cls = "tok-str";
      else if (m[4] !== undefined) cls = "tok-num";
      else if (m[6] !== undefined) cls = "tok-op";
      else if (m[5] !== undefined) {
        var rest = src.slice(m.index + text.length);
        if (KEYWORDS[text]) cls = "tok-kw";
        else if (CONSTANTS[text]) cls = "tok-num";
        else if (TYPES[text] || (names && names[text]) || (/^[A-Z]/.test(text) && (text.length === 1 || /[a-z]/.test(text)))) cls = "tok-type";
        else if (rest.charAt(0) === "(" || (rest.charAt(0) === "[" && /^\[[A-Za-z0-9_, \[\]]*\]\(/.test(rest))) cls = "tok-fn";
      }
      out += cls ? span(cls, text) : esc(text);
      pos = m.index + text.length;
      if (text.length === 0) TOKEN.lastIndex++;
    }
    return out + esc(src.slice(pos));
  }

  function source(src) {
    var names = declared(src);
    return src.split("\n").map(function (l) { return line(l, names); }).join("\n");
  }

  // Compiler output as the terminal shows it. Locations (`main.gg:5:9`) and codes (`GG0203`) become links.
  function terminal(text) {
    return text.replace(/\n+$/, "").split("\n").map(function (raw) {
      var m;
      if (/^Error:/.test(raw)) return span("t-err", "error:") + esc(raw.slice(6));
      if (/^Runtime error:/.test(raw)) return span("t-err", "Runtime error:") + esc(raw.slice(14));
      if ((m = /^(\s*)--> (\S+?):(\d+):(\d+)(\s+)(GG\d+)(.*)$/.exec(raw))) {
        return esc(m[1]) + span("t-gutter", "-->") + ' <a href="#" class="t-loc" data-line="' + m[3] + '" data-col="' + m[4] + '">' +
          esc(m[2] + ":" + m[3] + ":" + m[4]) + "</a>" + m[5] + '<a href="#" class="t-label" data-explain="' + m[6] + '">' + m[6] + "</a>" +
          span("t-dim", m[7]);
      }
      if ((m = /^(\s*)--> (\S+?):(\d+):(\d+)(.*)$/.exec(raw))) {
        return esc(m[1]) + span("t-gutter", "-->") + ' <a href="#" class="t-loc" data-line="' + m[3] + '" data-col="' + m[4] + '">' +
          esc(m[2] + ":" + m[3] + ":" + m[4]) + "</a>" + esc(m[5]);
      }
      if (/^\s*= help:/.test(raw)) return esc(raw).replace("= help:", span("t-help", "= help:"));
      if (raw.indexOf("= fix (verified):") >= 0) return esc(raw).replace("= fix (verified):", span("t-ok", "= fix (verified):"));
      if (raw.indexOf("= fix (likely):") >= 0) return esc(raw).replace("= fix (likely):", span("t-label", "= fix (likely):"));
      if (raw.indexOf("= fix (manual):") >= 0) return esc(raw).replace("= fix (manual):", span("t-dim", "= fix (manual):"));
      if ((m = /^(\s*\d*\s*\|)(.*)$/.exec(raw))) {
        var rest = m[2], c;
        if (/^\s*\^/.test(rest)) {
          c = /^(\s*)(\^+)(.*)$/.exec(rest);
          return span("t-gutter", m[1]) + esc(c[1]) + span("t-caret", c[2]) + span("t-label", c[3]);
        }
        return span("t-gutter", m[1]) + line(rest);
      }
      if (/^\d+ errors? found/.test(raw)) return span("t-err", raw);
      if (/^`gg fix/.test(raw)) return span("t-dim", raw);
      return esc(raw);
    }).join("\n");
  }

  global.GGHighlight = { source: source, terminal: terminal, esc: esc, keywords: Object.keys(KEYWORDS).concat(Object.keys(CONSTANTS)),
    types: Object.keys(TYPES) };
})(window);
