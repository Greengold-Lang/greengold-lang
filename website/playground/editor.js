// IDE-style editing for the playground's textarea: closing brackets and quotes, indentation, comment toggling, and
// word completion. Edits go through execCommand("insertText") where the browser allows it, so Undo and Redo keep working.
(function (global) {
  "use strict";
  var OPEN = { "(": ")", "[": "]", "{": "}", '"': '"', "'": "'" };
  var CLOSE = { ")": 1, "]": 1, "}": 1, '"': 1, "'": 1 };
  var QUOTE = { '"': 1, "'": 1 };
  var INDENT = "    ";
  var BUILTINS = ("print input panic require List HashMap HashSet Box Optional Result Ok Err Valid None Shared Arc string " +
    "Self clone push pop len insert remove swap reserve clear get contains to_string as_str wrapping_add checked_add " +
    "saturating_add print_err std").split(" ");

  function attach(ta) {
    var busy = false, tabFree = false;
    var box = ta.parentNode, pop = document.createElement("ul");
    pop.className = "pg-complete"; pop.setAttribute("role", "listbox"); pop.hidden = true;
    box.appendChild(pop);
    var items = [], sel = 0, plen = 0;

    // ---- text helpers ----
    function lineStart(p) { return ta.value.lastIndexOf("\n", p - 1) + 1; }
    function lineEnd(p) { var i = ta.value.indexOf("\n", p); return i < 0 ? ta.value.length : i; }
    function word(c) { return c !== undefined && /[A-Za-z0-9_]/.test(c); }

    // Whether `pos` is inside a string (and which quote) or a comment, judged from the start of its line.
    function context(pos) {
      var line = ta.value.slice(lineStart(pos), pos), q = "", i, c;
      for (i = 0; i < line.length; i++) {
        c = line.charAt(i);
        if (q) { if (c === "\\") i++; else if (c === q) q = ""; }
        else if (c === "#") return { str: "", comment: true };
        else if (QUOTE[c]) q = c;
      }
      return { str: q, comment: false };
    }

    function insert(text) {
      busy = true;
      var ok = false;
      try { ok = document.execCommand("insertText", false, text); } catch (e) { ok = false; }
      busy = false;
      if (!ok) { ta.setRangeText(text, ta.selectionStart, ta.selectionEnd, "end"); ta.dispatchEvent(new Event("input", { bubbles: true })); }
    }
    function remove() {
      busy = true;
      var ok = false;
      try { ok = document.execCommand("delete"); } catch (e) { ok = false; }
      busy = false;
      if (!ok) { ta.setRangeText("", ta.selectionStart, ta.selectionEnd, "end"); ta.dispatchEvent(new Event("input", { bubbles: true })); }
    }
    function replace(a, b, text, selA, selB) {
      ta.setSelectionRange(a, b);
      if (text === "") remove(); else insert(text);
      if (selA !== undefined) ta.setSelectionRange(selA, selB === undefined ? selA : selB);
    }

    // ---- completion list ----
    function closePop() { pop.hidden = true; items = []; }
    function candidates(prefix) {
      var seen = {}, out = [];
      function add(w, kind) { if (w.length > prefix.length && w.indexOf(prefix) === 0 && !seen[w]) { seen[w] = 1; out.push({ w: w, kind: kind }); } }
      global.GGHighlight.keywords.forEach(function (w) { add(w, "keyword"); });
      global.GGHighlight.types.forEach(function (w) { add(w, "type"); });
      BUILTINS.forEach(function (w) { add(w, "builtin"); });
      var m, re = /[A-Za-z_][A-Za-z0-9_]*/g, text = ta.value, at = ta.selectionStart;
      while ((m = re.exec(text)) !== null) { if (m.index + m[0].length !== at) add(m[0], "name"); }
      out.sort(function (a, b) { return a.w.length - b.w.length || (a.w < b.w ? -1 : 1); });
      return out.slice(0, 8);
    }
    function coords(pos) {
      var cs = getComputedStyle(ta), fs = parseFloat(cs.fontSize), lh = parseFloat(cs.lineHeight) || fs * 1.55;
      var probe = coords.cv || (coords.cv = document.createElement("canvas").getContext("2d"));
      probe.font = cs.fontSize + " " + cs.fontFamily;
      var cw = probe.measureText("M").width, ls = lineStart(pos);
      var row = ta.value.slice(0, ls).split("\n").length - 1, col = pos - ls;
      return { x: parseFloat(cs.paddingLeft) + col * cw - ta.scrollLeft, y: parseFloat(cs.paddingTop) + (row + 1) * lh - ta.scrollTop, lh: lh };
    }
    function render() {
      pop.innerHTML = "";
      items.forEach(function (it, i) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        li.setAttribute("aria-selected", String(i === sel));
        li.innerHTML = "<span><b>" + it.w.slice(0, plen) + "</b>" + it.w.slice(plen) + '</span><span class="pg-kind">' + it.kind + "</span>";
        li.addEventListener("mousedown", function (e) { e.preventDefault(); sel = i; accept(); });
        pop.appendChild(li);
      });
      var p = coords(ta.selectionStart), top = p.y + 4;
      pop.hidden = false;
      var h = pop.offsetHeight;
      if (top + h > box.clientHeight && p.y - p.lh - 4 - h > 0) top = p.y - p.lh - 4 - h;
      pop.style.top = Math.max(0, top) + "px";
      pop.style.left = Math.max(0, Math.min(p.x, box.clientWidth - pop.offsetWidth - 4)) + "px";
    }
    function suggest() {
      var s = ta.selectionStart;
      if (s !== ta.selectionEnd) return closePop();
      var m = /[A-Za-z_][A-Za-z0-9_]*$/.exec(ta.value.slice(lineStart(s), s));
      var c = context(s);
      if (!m || m[0].length < 2 || c.str || c.comment || word(ta.value.charAt(s))) return closePop();
      items = candidates(m[0]);
      if (!items.length) return closePop();
      plen = m[0].length; sel = 0;
      render();
    }
    function accept() {
      var it = items[sel], s = ta.selectionStart;
      closePop();
      if (it) replace(s - plen, s, it.w);
    }

    // ---- typing (beforeinput: also fires for mobile keyboards) ----
    ta.addEventListener("beforeinput", function (e) {
      if (busy) return;
      var s = ta.selectionStart, en = ta.selectionEnd, v = ta.value, t = e.inputType, ch = e.data, next = v.charAt(s), prev = v.charAt(s - 1);

      if (t === "insertText" && ch && ch.length === 1) {
        var c = context(s);
        if (s === en && CLOSE[ch] && next === ch && (!QUOTE[ch] || c.str === ch)) {     // type over a closing character
          e.preventDefault(); ta.setSelectionRange(s + 1, s + 1); return;
        }
        if (OPEN[ch]) {
          if (s !== en) {                                                             // wrap the selection
            e.preventDefault();
            var inner = v.slice(s, en);
            replace(s, en, ch + inner + OPEN[ch], s + 1, s + 1 + inner.length);
            return;
          }
          var pair = !c.comment && !word(next) && (!QUOTE[ch] || (!c.str && !(ch === "'" && word(prev))));
          if (pair) { e.preventDefault(); replace(s, s, ch + OPEN[ch], s + 1); }
        }
        return;
      }

      if (t === "deleteContentBackward" && s === en && s > 0) {
        if (OPEN[prev] && OPEN[prev] === next) {                                      // delete an empty pair
          e.preventDefault(); replace(s - 1, s + 1, ""); return;
        }
        var ls = lineStart(s), before = v.slice(ls, s);
        if (before.length > 0 && /^ +$/.test(before)) {                               // delete one indent step
          e.preventDefault();
          var n = before.length % INDENT.length || INDENT.length;
          replace(s - n, s, "");
        }
        return;
      }

      if (t === "insertLineBreak" || t === "insertParagraph") {
        e.preventDefault();
        var start = lineStart(s), line = v.slice(start, s), indent = /^ */.exec(line)[0];
        var colon = /:\s*$/.test(line) && !context(s).comment && s === en;
        var between = s === en && OPEN[prev] && OPEN[prev] === next && !QUOTE[prev];
        if (between) {
          var mid = "\n" + indent + INDENT;
          replace(s, en, mid + "\n" + indent, s + mid.length);
        } else {
          insert("\n" + indent + (colon ? INDENT : ""));
        }
      }
    });

    ta.addEventListener("input", function () { if (busy) closePop(); else suggest(); });
    ta.addEventListener("blur", closePop);
    ta.addEventListener("scroll", closePop);
    ta.addEventListener("click", closePop);

    // ---- keys ----
    function blockLines() {
      var s = ta.selectionStart, en = ta.selectionEnd;
      var a = lineStart(s), b = en > s && ta.value.charAt(en - 1) === "\n" ? en - 1 : en;
      return { a: a, b: lineEnd(b) };
    }
    function reindent(outdent) {
      var r = blockLines(), lines = ta.value.slice(r.a, r.b).split("\n");
      var out = lines.map(function (l) {
        if (!outdent) return l.length ? INDENT + l : l;
        var k = 0; while (k < INDENT.length && l.charAt(k) === " ") k++;
        return l.slice(k);
      }).join("\n");
      replace(r.a, r.b, out, r.a, r.a + out.length);
    }
    function toggleComment() {
      var r = blockLines(), lines = ta.value.slice(r.a, r.b).split("\n");
      var all = lines.every(function (l) { return !l.trim() || /^\s*#/.test(l); });
      var out = lines.map(function (l) {
        if (!l.trim()) return l;
        return all ? l.replace(/^(\s*)# ?/, "$1") : l.replace(/^(\s*)/, "$1# ");
      }).join("\n");
      replace(r.a, r.b, out, r.a, r.a + out.length);
    }

    ta.addEventListener("keydown", function (e) {
      var open = !pop.hidden;
      if (open) {
        if (e.key === "ArrowDown") { e.preventDefault(); sel = (sel + 1) % items.length; render(); return; }
        if (e.key === "ArrowUp") { e.preventDefault(); sel = (sel + items.length - 1) % items.length; render(); return; }
        if ((e.key === "Enter" && !e.ctrlKey && !e.metaKey) || e.key === "Tab") { e.preventDefault(); accept(); return; }
        if (e.key === "Escape") { e.preventDefault(); closePop(); return; }
      }
      if (e.key === "Escape") { tabFree = true; return; }           // Esc, then Tab, moves focus out of the editor
      var free = tabFree; tabFree = false;
      if (e.key === "Tab" && !e.ctrlKey && !e.altKey && !e.metaKey) {
        if (free) return;
        e.preventDefault();
        var s = ta.selectionStart, en = ta.selectionEnd;
        if (e.shiftKey || (s !== en && ta.value.slice(s, en).indexOf("\n") >= 0)) { reindent(e.shiftKey); return; }
        insert(INDENT.slice(0, INDENT.length - (s - lineStart(s)) % INDENT.length));
        return;
      }
      if ((e.ctrlKey || e.metaKey) && e.key === "/") { e.preventDefault(); toggleComment(); }
    });
  }

  global.GGEditor = { attach: attach };
})(window);
