// Greengold site behaviour: theme, menu, copy buttons, code tabs, spec contents, reveal.

(function () {
  const root = document.documentElement;
  root.classList.remove("no-js");

  // Theme toggle. The initial theme is set by an inline script in <head>.
  const themeButton = document.querySelector(".theme-toggle");
  if (themeButton) {
    themeButton.addEventListener("click", () => {
      const current = root.getAttribute("data-theme") ||
        (window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark");
      const next = current === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("gg-theme", next); } catch (e) { /* storage unavailable */ }
    });
  }

  // Mobile menu.
  const menuToggle = document.querySelector(".menu-toggle");
  const siteNav = document.getElementById("site-nav");
  if (menuToggle && siteNav) {
    menuToggle.addEventListener("click", () => {
      const open = siteNav.classList.toggle("open");
      menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && siteNav.classList.contains("open")) {
        siteNav.classList.remove("open");
        menuToggle.setAttribute("aria-expanded", "false");
        menuToggle.focus();
      }
    });
  }

  // Copy buttons copy the text of the code panel they belong to.
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      const area = document.createElement("textarea");
      area.value = text;
      area.setAttribute("readonly", "");
      area.style.position = "fixed";
      area.style.left = "-9999px";
      document.body.appendChild(area);
      area.select();
      const ok = document.execCommand("copy");
      document.body.removeChild(area);
      if (ok) resolve(); else reject(new Error("copy failed"));
    });
  }

  document.querySelectorAll(".copy").forEach((button) => {
    const label = button.querySelector(".label");
    button.addEventListener("click", () => {
      let text = button.getAttribute("data-copy");
      if (!text) {
        const panel = button.closest(".code");
        const visible = panel && (panel.querySelector(".code-panel:not([hidden]) pre") || panel.querySelector("pre"));
        text = visible ? visible.innerText.replace(/\n$/, "") : "";
      }
      copyText(text).then(() => {
        button.classList.add("done");
        if (label) label.textContent = "Copied";
        window.setTimeout(() => {
          button.classList.remove("done");
          if (label) label.textContent = "Copy";
        }, 1400);
      }).catch(() => {});
    });
  });

  // The About email card copies the address instead of opening a mail client.
  document.querySelectorAll(".contact[data-copy]").forEach((button) => {
    const label = button.querySelector("span");
    const original = label ? label.textContent : "";
    button.addEventListener("click", () => {
      copyText(button.getAttribute("data-copy") || "").then(() => {
        button.classList.add("done");
        if (label) label.textContent = "Copied";
        window.setTimeout(() => {
          button.classList.remove("done");
          if (label) label.textContent = original;
        }, 1400);
      }).catch(() => {});
    });
  });

  // Tabbed code windows.
  document.querySelectorAll("[data-tabs]").forEach((box) => {
    const tabs = Array.from(box.querySelectorAll(".code-tab"));
    const panels = Array.from(box.querySelectorAll(".code-panel"));
    const file = box.querySelector(".code-file");
    function select(index, focus) {
      tabs.forEach((tab, i) => {
        const on = i === index;
        tab.setAttribute("aria-selected", on ? "true" : "false");
        tab.tabIndex = on ? 0 : -1;
        panels[i].hidden = !on;
        if (on && file) file.textContent = tab.getAttribute("data-file") || "";
        if (on && focus) tab.focus();
      });
    }
    tabs.forEach((tab, i) => {
      tab.addEventListener("click", () => select(i, false));
      tab.addEventListener("keydown", (event) => {
        if (event.key === "ArrowRight") select((i + 1) % tabs.length, true);
        if (event.key === "ArrowLeft") select((i - 1 + tabs.length) % tabs.length, true);
      });
    });
  });

  // Spec contents: highlight the section in view and filter by text.
  const toc = document.querySelector(".spec-toc");
  if (toc) {
    if (toc.tagName === "DETAILS" && window.matchMedia("(max-width: 1020px)").matches) toc.open = false;
    const links = Array.from(toc.querySelectorAll("a[href^='#']"));
    const targets = links
      .map((link) => document.getElementById(decodeURIComponent(link.getAttribute("href").slice(1))))
      .filter(Boolean);
    const byId = new Map(links.map((link) => [decodeURIComponent(link.getAttribute("href").slice(1)), link]));
    let activeLink = null;

    function update() {
      let current = targets[0];
      const limit = window.innerHeight * 0.3;
      for (const target of targets) {
        if (target.getBoundingClientRect().top - limit <= 0) current = target;
        else break;
      }
      const link = current && byId.get(current.id);
      if (link && link !== activeLink) {
        if (activeLink) activeLink.classList.remove("active");
        link.classList.add("active");
        activeLink = link;
        const box = toc.getBoundingClientRect();
        const r = link.getBoundingClientRect();
        if (getComputedStyle(toc).position === "sticky" && (r.top < box.top || r.bottom > box.bottom)) {
          link.scrollIntoView({ block: "nearest" });
        }
      }
    }

    let ticking = false;
    window.addEventListener("scroll", () => {
      if (!ticking) {
        window.requestAnimationFrame(() => { update(); ticking = false; });
        ticking = true;
      }
    }, { passive: true });
    update();

    const search = toc.querySelector(".toc-search");
    if (search) {
      search.addEventListener("input", () => {
        const q = search.value.trim().toLowerCase();
        toc.querySelectorAll("li").forEach((li) => {
          const text = li.textContent.toLowerCase();
          li.classList.toggle("hidden", q !== "" && !text.includes(q));
        });
      });
    }

    toc.querySelectorAll("a").forEach((link) => {
      link.addEventListener("click", () => {
        if (toc.tagName === "DETAILS" && window.matchMedia("(max-width: 1020px)").matches) toc.open = false;
      });
    });
  }

  // Fade sections in as they scroll into view.
  const reveals = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && reveals.length) {
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("in");
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: "0px 0px -8% 0px" });
    reveals.forEach((el) => observer.observe(el));
    // Never leave content hidden if the observer does not fire (print, odd embeds).
    window.addEventListener("load", () => {
      window.setTimeout(() => reveals.forEach((el) => el.classList.add("in")), 2500);
    });
  } else {
    reveals.forEach((el) => el.classList.add("in"));
  }
})();
