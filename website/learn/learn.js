(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var H = window.GGHighlight;

  // ---- interface strings ----
  var UI = {
    tr: {
      title: "Greengold Öğren", lede: "Sıfırdan başlayıp standart kütüphaneye kadar. Kodu tarayıcıda yaz, çalıştır, alıştırmayı çöz.",
      pickPath: "Yolunu seç", beginner: "Yeni başlıyorum", dev: "Başka bir dil biliyorum",
      pathNote: "Programcı yolunda 'programlamaya giriş' dersleri atlanır.", skipped: "atlandı",
      run: "Çalıştır", stop: "Durdur", reset: "Sıfırla", check: "Kontrol et", hint: "İpucu", solution: "Çözümü göster",
      tryIt: "Dene", exercise: "Alıştırma", openEx: "Editörde aç", quiz: "Soru", next: "Sonraki", prev: "Önceki", done: "Tamamlandı",
      loading: "Yükleniyor…", ready: "Hazır", building: "Derleniyor…", running: "Çalışıyor…", couldNotBuild: "Derlenemedi.",
      correct: "Doğru!", wrong: "Çıktı beklenenle aynı değil.", expected: "Beklenen", got: "Senin çıktın", answer: "Doğru cevap",
      contents: "İçindekiler", badges: "Rozetler", progress: "İlerleme", lessons: "ders",
      b_first_run: "İlk program", b_first_ex: "İlk alıştırma", b_ex10: "10 alıştırma", b_quiz5: "5 doğru cevap", b_chapter: "Bölüm bitirildi",
      cont: "Kaldığın yerden devam et", start: "Başla", review: "Önce şunu bitirmeni öneririz", stopped: "Durduruldu.", tooLong: "Program çok uzun sürdü.", exit: "çıkış kodu"
    },
    en: {
      title: "Learn Greengold", lede: "From zero to the standard library. Write code in the browser, run it, solve the exercises.",
      pickPath: "Choose your path", beginner: "I'm new to programming", dev: "I know another language",
      pathNote: "The programmer path skips the 'introduction to programming' lessons.", skipped: "skipped",
      run: "Run", stop: "Stop", reset: "Reset", check: "Check", hint: "Hint", solution: "Show solution",
      tryIt: "Try it", exercise: "Exercise", openEx: "Open in editor", quiz: "Question", next: "Next", prev: "Previous", done: "Completed",
      loading: "Loading…", ready: "Ready", building: "Building…", running: "Running…", couldNotBuild: "Could not build.",
      correct: "Correct!", wrong: "The output is not what was expected.", expected: "Expected", got: "Your output", answer: "Correct answer",
      contents: "Contents", badges: "Badges", progress: "Progress", lessons: "lessons",
      b_first_run: "First program", b_first_ex: "First exercise", b_ex10: "10 exercises", b_quiz5: "5 correct answers", b_chapter: "Chapter finished",
      cont: "Continue where you left off", start: "Start", review: "We suggest finishing this first", stopped: "Stopped.", tooLong: "The program ran too long.", exit: "exit code"
    }
  };

  // ---- persisted state ----
  var store = {
    get: function (k, d) { try { var v = localStorage.getItem("gg-learn-" + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
    set: function (k, v) { try { localStorage.setItem("gg-learn-" + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } }
  };
  var lang = store.get("lang", /^tr/i.test(navigator.language || "") ? "tr" : "en");
  var level = store.get("level", null);                       // "beginner" | "dev" | null
  var progress = store.get("progress", { lessons: {}, exercises: {}, quiz: {}, ran: false });
  function T(k) { return UI[lang][k] || k; }
  function save() { store.set("progress", progress); }

  // ---- tiny text formatting: `code` and **bold** ----
  function inline(s) {
    return H.esc(s).replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  }
  function el(tag, cls, html) { var e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }

  // ---- compiler pipeline (the playground's workers) ----
  var ready = false, seq = 0, pending = {}, toolchain = null, runner = null, running = false, killTimer = null;
  var LIMIT_MS = 10000, LIMIT_CHARS = 200000;
  var worker = new Worker("../playground/worker.js");
  worker.onmessage = function (ev) {
    var m = ev.data;
    if (m.type === "status") setStatus(m.text, "busy", m.percent);
    else if (m.type === "ready") { ready = true; setStatus(T("ready") + " · gg " + m.version, "ok"); }
    else if (m.type === "fatal") setStatus(m.text, "bad");
    else if (pending[m.id]) { var p = pending[m.id]; delete pending[m.id]; m.type === "result" ? p.ok(m.result) : p.err(m.text); }
  };
  function call(fn) {
    var args = Array.prototype.slice.call(arguments, 1);
    return new Promise(function (ok, err) { var id = ++seq; pending[id] = { ok: ok, err: err }; worker.postMessage({ id: id, fn: fn, args: args }); });
  }
  function whenReady() {
    return new Promise(function (ok) { (function wait() { ready ? ok() : setTimeout(wait, 100); })(); });
  }

  // Compile and run `src`; resolves {ok, built, stdout, stderr, code, note}. `live(text, fd)` receives output as it comes.
  var stopRun = function () {};
  function execute(src, live) {
    var result = { ok: false, built: false, stdout: "", stderr: "", code: null, note: "", buildText: "" };
    return whenReady().then(function () { return call("build", src, false); }).then(function (json) {
      var r = JSON.parse(json);
      if (!r.ok) { result.buildText = r.text; return null; }
      if (!toolchain) toolchain = new Worker("../playground/toolchain.js");
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
      if (!built) return result;
      result.built = true;
      setStatus(T("running"), "busy");
      return new Promise(function (ok) {
        function end(note) {
          clearTimeout(killTimer);
          if (runner) { runner.terminate(); runner = null; }
          result.note = note || ""; ok(result);
        }
        stopRun = function () { end(T("stopped")); };
        runner = new Worker("../playground/runner.js");
        killTimer = setTimeout(function () { end(T("tooLong")); }, LIMIT_MS);
        runner.onmessage = function (m) {
          var d = m.data;
          if (d.type === "out") {
            if (d.fd === 1) result.stdout += d.text; else result.stderr += d.text;
            if (result.stdout.length + result.stderr.length > LIMIT_CHARS) { end("output limit"); return; }
            live(d.text, d.fd);
          } else if (d.type === "done") { result.code = d.code; result.ok = d.code === 0; end(""); }
          else if (d.type === "error") { result.stderr += d.text; end(""); }
        };
        runner.postMessage({ wasm: built.wasm, stdin: "" }, [built.wasm]);
      });
    });
  }

  // ---- lab (editor + output) ----
  var editor = $("lab-editor"), hl = $("lab-hl"), gutter = $("lab-gutter"), out = $("lab-out");
  var statusEl = $("lab-status"), verdict = $("lab-verdict"), bar = $("lab-progress");
  var currentStarter = "", currentExercise = null;
  function setStatus(t, kind, pct) {
    statusEl.textContent = t; statusEl.dataset.kind = kind || "";
    var m = pct != null ? [0, pct] : (kind === "busy" ? /(\d{1,3})%/.exec(t) : null);
    bar.hidden = !m; if (m) bar.firstElementChild.style.width = Math.min(100, +m[1]) + "%";
  }
  function paint() {
    var n = editor.value.split("\n").length, s = "";
    for (var i = 1; i <= n; i++) s += i + "\n";
    gutter.textContent = s;
    hl.innerHTML = H.source(editor.value) + "\n";
    gutter.scrollTop = hl.scrollTop = editor.scrollTop; hl.scrollLeft = editor.scrollLeft;
  }
  editor.addEventListener("input", paint);
  editor.addEventListener("scroll", paint);
  window.GGEditor.attach(editor);
  function setCode(src, exercise) {
    editor.value = src; currentStarter = src; currentExercise = exercise || null;
    out.textContent = ""; verdict.hidden = true; paint();
    Array.prototype.forEach.call(document.querySelectorAll(".exercise"), function (e) {
      e.classList.toggle("active", !!exercise && e.dataset.id === exercise.id);
    });
  }
  function norm(s) { return s.replace(/\r/g, "").split("\n").map(function (l) { return l.replace(/\s+$/, ""); }).join("\n").replace(/\n+$/, ""); }

  function runLab(check) {
    if (running) return;
    running = true; $("lab-run").hidden = true; $("lab-stop").hidden = false;
    out.textContent = ""; verdict.hidden = true;
    setStatus(T("building"), "busy");
    execute(editor.value, function (text, fd) {
      var s = document.createElement("span");
      if (fd === 2) s.innerHTML = H.terminal(text); else s.textContent = text;
      out.appendChild(s); out.scrollTop = out.scrollHeight;
    }).then(function (r) {
      if (!r.built) { out.innerHTML = H.terminal(r.buildText); setStatus(T("couldNotBuild"), "bad"); if (check) show(false, T("couldNotBuild")); return; }
      if (r.ok) { progress.ran = true; save(); }
      setStatus(r.note || (T("exit") + " " + r.code), r.ok ? "ok" : "bad");
      if (check && currentExercise) grade(r);
    }).catch(function (e) { out.textContent = String(e); setStatus(String(e), "bad"); })
      .then(function () { running = false; $("lab-run").hidden = false; $("lab-stop").hidden = true; });
  }
  function show(ok, html) { verdict.className = "lab-verdict " + (ok ? "ok" : "bad"); verdict.innerHTML = html; verdict.hidden = false; }
  function grade(r) {
    var ex = currentExercise, want = norm(ex.expected.join("\n")), got = norm(r.stdout);
    if (r.ok && want === got) {
      progress.exercises[ex.id] = true; save();
      show(true, "✓ " + T("correct")); refresh();
    } else {
      show(false, T("wrong") + "<pre>" + T("expected") + ":\n" + H.esc(want) + "\n\n" + T("got") + ":\n" + H.esc(got) + "</pre>");
    }
  }
  $("lab-run").addEventListener("click", function () { runLab(false); });
  $("lab-stop").addEventListener("click", function () { stopRun(); });
  $("lab-reset").addEventListener("click", function () { setCode(currentStarter, currentExercise); });
  editor.addEventListener("keydown", function (e) { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runLab(!!currentExercise); } });

  // ---- content ----
  var manifest = null, cache = {}, titles = {}, currentLesson = null;
  function lessonIds() { var ids = []; manifest.chapters.forEach(function (c) { c.lessons.forEach(function (l) { ids.push(l); }); }); return ids; }
  function skipped(ch) { return !!ch.only && !!level && ch.only !== level; }
  // The lessons in order, leaving out chapters the chosen path skips.
  function pathIds() {
    var ids = [];
    manifest.chapters.forEach(function (c) { if (!skipped(c)) c.lessons.forEach(function (l) { ids.push(l); }); });
    return ids;
  }
  function nextToDo() {
    var ids = pathIds();
    for (var i = 0; i < ids.length; i++) if (!progress.lessons[ids[i]]) return ids[i];
    return null;
  }
  // The first unfinished lesson before `id` on the path, or null: a suggestion, never a lock.
  function missingBefore(id) {
    var ids = pathIds(), at = ids.indexOf(id);
    for (var i = 0; i < at; i++) if (!progress.lessons[ids[i]]) return ids[i];
    return null;
  }
  function loadLesson(id) {
    var key = lang + "/" + id;
    if (cache[key]) return Promise.resolve(cache[key]);
    return fetch("content/" + key + ".json").then(function (r) { if (!r.ok) throw new Error(key); return r.json(); }).then(function (d) { cache[key] = d; return d; });
  }
  function loadTitles() {
    return Promise.all(lessonIds().map(function (id) { return loadLesson(id).then(function (d) { titles[id] = d.title; }); }));
  }

  function side(activeId) {
    var s = $("learn-side"), html = "";
    html += '<div class="learn-tools"><div class="pg-seg" role="radiogroup" aria-label="Language">' +
      ["tr", "en"].map(function (l) { return '<button type="button" role="radio" aria-checked="' + (l === lang) + '" data-lang="' + l + '">' + l.toUpperCase() + "</button>"; }).join("") + "</div></div>";
    html += '<a href="#/">' + T("contents") + "</a>";
    var next = nextToDo();
    manifest.chapters.forEach(function (ch, ci) {
      var sk = skipped(ch), open = activeId ? ch.lessons.indexOf(activeId) >= 0 : ch.lessons.indexOf(next) >= 0;
      var doneN = ch.lessons.filter(function (l) { return progress.lessons[l]; }).length;
      html += '<details class="chapter' + (sk ? " skipped" : "") + '"' + (open ? " open" : "") + "><summary>" + H.esc(ch.title[lang]) +
        (sk ? " · " + T("skipped") : "") + ' <span class="count">' + doneN + "/" + ch.lessons.length + "</span></summary><ul>";
      ch.lessons.forEach(function (id) {
        var cls = (!sk && id === next ? "next" : "");
        html += '<li><a href="#/' + id + '"' + (id === activeId ? ' aria-current="page"' : "") + (cls ? ' class="' + cls + '"' : "") + '><span class="tick">' +
          (progress.lessons[id] ? "✓" : (cls ? "→" : "")) + "</span>" + H.esc(titles[id] || id) + "</a></li>";
      });
      html += "</ul></details>";
    });
    s.innerHTML = html;
    Array.prototype.forEach.call(s.querySelectorAll("[data-lang]"), function (b) {
      b.addEventListener("click", function () { lang = b.dataset.lang; store.set("lang", lang); loadTitles().then(route); });
    });
  }

  function badges() {
    var ex = Object.keys(progress.exercises).length;
    var qz = Object.keys(progress.quiz).filter(function (k) { return progress.quiz[k]; }).length;
    var chapterDone = manifest.chapters.some(function (c) { return c.lessons.every(function (l) { return progress.lessons[l]; }); });
    var list = [["b_first_run", progress.ran], ["b_first_ex", ex >= 1], ["b_ex10", ex >= 10], ["b_quiz5", qz >= 5], ["b_chapter", chapterDone]];
    return '<div class="badges" aria-label="' + T("badges") + '">' + list.map(function (b) { return '<span class="badge' + (b[1] ? " on" : "") + '">' + T(b[0]) + "</span>"; }).join("") + "</div>";
  }

  function home() {
    currentLesson = null;
    $("learn").classList.add("no-lab"); $("learn-lab").hidden = true;
    var main = $("learn-main"), total = lessonIds().length, done = lessonIds().filter(function (l) { return progress.lessons[l]; }).length;
    var html = "<h1>" + T("title") + "</h1><p>" + T("lede") + "</p>";
    html += "<h3>" + T("pickPath") + '</h3><div class="pathpick">' +
      ["beginner", "dev"].map(function (l) { return '<button type="button" class="btn ' + (level === l ? "btn-primary" : "btn-ghost") + '" data-level="' + l + '">' + T(l) + "</button>"; }).join("") +
      "</div><p>" + T("pathNote") + "</p>";
    var nx = nextToDo();
    if (nx) html += '<p><a class="btn btn-primary" href="#/' + nx + '">' + (done ? T("cont") : T("start")) + ": " + H.esc(titles[nx] || nx) + "</a></p>";
    html += "<h3>" + T("progress") + ": " + done + "/" + total + " " + T("lessons") + "</h3>" + badges();
    manifest.chapters.forEach(function (ch) {
      html += '<div class="chapter-card"><h3>' + H.esc(ch.title[lang]) + (skipped(ch) ? " · " + T("skipped") : "") + "</h3>" +
        ch.lessons.map(function (id) { return '<a href="#/' + id + '">' + (progress.lessons[id] ? "✓ " : "") + H.esc(titles[id] || id) + "</a>"; }).join("") + "</div>";
    });
    main.innerHTML = html;
    Array.prototype.forEach.call(main.querySelectorAll("[data-level]"), function (b) {
      b.addEventListener("click", function () { level = b.dataset.level; store.set("level", level); route(); });
    });
    side(null);
  }

  function lesson(id) {
    if (lessonIds().indexOf(id) < 0) { location.hash = "#/"; return; }
    loadLesson(id).then(function (d) {
      currentLesson = id;
      $("learn").classList.remove("no-lab"); $("learn-lab").hidden = false;
      $("lab-run").textContent = T("run"); $("lab-stop").textContent = T("stop"); $("lab-reset").textContent = T("reset");
      var main = $("learn-main"); main.innerHTML = "";
      main.appendChild(el("h1", "", H.esc(d.title)));
      var miss = missingBefore(id);
      if (miss && !skipped(manifest.chapters.filter(function (c) { return c.lessons.indexOf(id) >= 0; })[0])) {
        main.appendChild(el("p", "notice", T("review") + ': <a href="#/' + miss + '">' + H.esc(titles[miss] || miss) + "</a>"));
      }
      var firstCode = null, startEx = null;
      d.blocks.forEach(function (b) {
        if (b.t === "p") main.appendChild(el("p", "", inline(b.text)));
        else if (b.t === "h") main.appendChild(el("h3", "", inline(b.text)));
        else if (b.t === "code") {
          var src = b.code.join("\n"), box = el("div", "lesson-code");
          box.appendChild(el("pre", "", H.source(src)));
          if (b.output) box.appendChild(el("pre", "expect", H.esc(b.output.join("\n"))));
          if (b.run) {
            var btn = el("button", "btn btn-ghost try", T("tryIt")); btn.type = "button";
            btn.addEventListener("click", function () { setCode(src, null); runLab(false); });
            box.appendChild(btn);
            if (firstCode === null) firstCode = src;
          }
          main.appendChild(box);
        } else if (b.t === "exercise") {
          exercise(main, b);
          if (!startEx || (progress.exercises[startEx.id] && !progress.exercises[b.id])) startEx = b;   // first exercise not yet solved
        }
        else if (b.t === "quiz") quiz(main, b);
      });
      var ids = lessonIds(), i = ids.indexOf(id), nav = el("div", "lesson-nav");
      if (i > 0) { var prev = el("a", "btn btn-ghost", "← " + T("prev")); prev.href = "#/" + ids[i - 1]; nav.appendChild(prev); } else nav.appendChild(el("span"));
      var fin = el("button", "btn btn-primary", (progress.lessons[id] ? "✓ " : "") + T("done")); fin.type = "button";
      fin.addEventListener("click", function () {
        progress.lessons[id] = true; save();
        if (i < ids.length - 1) location.hash = "#/" + ids[i + 1]; else location.hash = "#/";
      });
      nav.appendChild(fin);
      main.appendChild(nav);
      // the editor opens with the exercise (the first one not yet solved), or with the first example
      if (startEx) setCode(startEx.starter.join("\n"), startEx);
      else setCode(firstCode || "fn main():\n    print(\"\")\n", null);
      side(id);
      window.scrollTo(0, 0);
    }).catch(function (e) { $("learn-main").textContent = String(e); });
  }

  function exercise(main, b) {
    var box = el("div", "exercise" + (progress.exercises[b.id] ? " done" : "")); box.dataset.id = b.id;
    box.innerHTML = "<h4>" + T("exercise") + (progress.exercises[b.id] ? " ✓" : "") + "</h4><p>" + inline(b.prompt) + "</p>";
    var row = el("div", "row");
    var edit = el("button", "btn btn-ghost", T("openEx")); edit.type = "button";
    edit.addEventListener("click", function () { setCode(b.starter.join("\n"), b); editor.focus(); });
    var check = el("button", "btn btn-primary", T("check")); check.type = "button";
    check.addEventListener("click", function () {
      if (!currentExercise || currentExercise.id !== b.id) setCode(b.starter.join("\n"), b);
      runLab(true);
    });
    row.appendChild(edit); row.appendChild(check); box.appendChild(row);
    if (b.hint) box.appendChild(el("details", "", "<summary>" + T("hint") + "</summary><p>" + inline(b.hint) + "</p>"));
    if (b.solution) {
      var d2 = el("details", "", "<summary>" + T("solution") + "</summary>"), code = el("div", "lesson-code");
      code.appendChild(el("pre", "", H.source(b.solution.join("\n"))));
      d2.appendChild(code); box.appendChild(d2);
    }
    main.appendChild(box);
  }

  function quiz(main, b) {
    var box = el("div", "quiz" + (progress.quiz[b.id] ? " done" : ""));
    box.innerHTML = "<h4>" + T("quiz") + "</h4><p>" + inline(b.q) + "</p>";
    var res = el("div", "why");
    b.options.forEach(function (o, i) {
      var label = el("label", "", '<input type="radio" name="' + b.id + '"> <span>' + inline(o) + "</span>");
      label.querySelector("input").addEventListener("change", function () {
        var ok = i === b.answer;
        progress.quiz[b.id] = ok || progress.quiz[b.id] || false; save();
        res.innerHTML = '<span class="' + (ok ? "good" : "bad") + '">' + (ok ? "✓ " + T("correct") : "✗ " + T("answer") + ": " + inline(b.options[b.answer])) + "</span> " + inline(b.why || "");
        if (ok) box.classList.add("done");
      });
      box.appendChild(label);
    });
    box.appendChild(res); main.appendChild(box);
  }

  function refresh() { if (manifest && currentLesson) side(currentLesson); }

  function route() {
    var id = (location.hash.match(/^#\/(.*)$/) || [])[1];
    if (!id) home(); else lesson(id);
  }
  window.addEventListener("hashchange", route);

  setStatus(T("loading"), "busy");
  fetch("content/manifest.json").then(function (r) { return r.json(); }).then(function (m) { manifest = m; return loadTitles(); }).then(route)
    .catch(function (e) { $("learn-main").textContent = String(e); });
})();
