/* CyNiT Hub - main.js (v2)
   - Dropdown menus (Tools/Beheer/Theme)
   - Theme toggle (/theme/toggle?back=...)
   - Optional Theme picker menu
   - Optional WYSIWYG Theme Editor helpers (data-attributes)
   - Keeps JWT helpers (issuer->subject sync, copy token)
*/
(function () {
  "use strict";

  // -----------------------
  // Helpers
  // -----------------------
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  function currentBackUrl() {
    // preserve path + query + hash
    const p = window.location.pathname || "/";
    const s = window.location.search || "";
    const h = window.location.hash || "";
    return encodeURIComponent(p + s + h);
  }

  // -----------------------
  // Dropdown engine (generic)
  // -----------------------
  const DROPDOWN_PAIRS = [];

  function closeMenu(menu, btn) {
    if (!menu) return;
    menu.classList.remove("open");
    if (btn) btn.setAttribute("aria-expanded", "false");
  }

  function closeAll(exceptMenu) {
    for (const pair of DROPDOWN_PAIRS) {
      if (exceptMenu && pair.menu === exceptMenu) continue;
      closeMenu(pair.menu, pair.btn);
    }
  }

  function positionUnder(menu, btn, alignRight) {
    if (!menu || !btn) return;

    const rect = btn.getBoundingClientRect();
    // Menu is position: fixed (your css), so use viewport coords
    const top = rect.bottom + 10;

    menu.style.top = Math.max(8, top) + "px";

    if (alignRight) {
      // keep some padding from right edge
      const right = Math.max(8, (window.innerWidth - rect.right + 14));
      menu.style.right = right + "px";
      menu.style.left = "auto";
    } else {
      const left = Math.max(8, rect.left);
      menu.style.left = left + "px";
      menu.style.right = "auto";
    }
  }

  function toggleMenu(menu, btn, alignRight) {
    if (!menu || !btn) return;
    const isOpen = menu.classList.contains("open");
    closeAll(menu);
    if (!isOpen) {
      menu.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      positionUnder(menu, btn, alignRight);
    } else {
      closeMenu(menu, btn);
    }
  }

  function registerDropdown(btnSel, menuSel, alignRight) {
    const btn = qs(btnSel);
    const menu = qs(menuSel);
    if (!btn || !menu) return;

    DROPDOWN_PAIRS.push({ btn, menu, alignRight: !!alignRight });

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleMenu(menu, btn, !!alignRight);
    });

    // clicks inside menu shouldn't close it
    menu.addEventListener("click", (e) => {
      e.stopPropagation();
    });
  }

  // Core dropdowns
  registerDropdown("#btn-tools", "#menu-tools", false);
  registerDropdown("#btn-beheer", "#menu-beheer", true);

  // Optional Theme dropdown (if you add it later)
  // - button id: btn-theme
  // - menu id: menu-theme
  registerDropdown("#btn-theme", "#menu-theme", true);

  // Close on outside click
  document.addEventListener("click", (e) => {
    const t = e.target;

    const clickedInAnyMenu = DROPDOWN_PAIRS.some(p => p.menu && p.menu.contains(t));
    const clickedInAnyBtn  = DROPDOWN_PAIRS.some(p => p.btn && p.btn.contains(t));

    if (!clickedInAnyMenu && !clickedInAnyBtn) closeAll();
  });

  // Close on ESC
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAll();
  });

  // Reposition open menus on resize/scroll
  function repositionOpenMenus() {
    for (const p of DROPDOWN_PAIRS) {
      if (p.menu && p.btn && p.menu.classList.contains("open")) {
        positionUnder(p.menu, p.btn, p.alignRight);
      }
    }
  }
  window.addEventListener("resize", repositionOpenMenus, { passive: true });
  window.addEventListener("scroll", repositionOpenMenus, { passive: true });

  // -----------------------
  // Theme toggle button (footer/header icon)
  // -----------------------
  function bindThemeToggle(btnId) {
    const btn = qs(btnId);
    if (!btn) return;

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      // navigate (server handles cookie/file + redirect)
      const back = currentBackUrl();
      window.location.href = `/theme/toggle?back=${back}`;
    });
  }

  // If you place a theme toggle icon in footer:
  // <button id="btn-theme-toggle" class="iconbtn">🌙</button>
  bindThemeToggle("#btn-theme-toggle");

  // If you place a theme toggle icon in header:
  bindThemeToggle("#btn-theme-toggle-top");

  // -----------------------
  // Optional: Theme picker in dropdown
  // - anchors can simply be href="/theme/set?name=Dark&back=..."
  // - OR data-theme-name attribute to auto-wire
  // -----------------------
  (function bindThemePicker() {
    const menu = qs("#menu-theme");
    if (!menu) return;

    qsa("[data-theme-name]", menu).forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        const name = (el.getAttribute("data-theme-name") || "").trim();
        if (!name) return;
        const back = currentBackUrl();
        window.location.href = `/theme/set?name=${encodeURIComponent(name)}&back=${back}`;
      });
    });
  })();

  // -----------------------
  // Optional: WYSIWYG Theme Editor helpers
  // (only activates if elements exist)
  //
  // Convention (suggested for your future theme_editor.html):
  // - Preview container: #theme-preview (contains sample panels/toolcards)
  // - Inputs:
  //    <input data-theme-var="--bg" ...>
  //    <input data-theme-var="--text" ...>
  //    <input data-theme-var="--accent" ...>
  // - If you want to apply vars to preview only:
  //    preview.style.setProperty(var, value)
  // - If you want to generate CSS text output:
  //    textarea#theme-css-out
  // -----------------------
  (function themeEditorWysiwyg() {
    const root = qs("[data-theme-editor='1']");
    if (!root) return;

    const preview = qs("#theme-preview", root) || qs("#theme-preview");
    const cssOut  = qs("#theme-css-out", root) || qs("#theme-css-out");

    function rebuildCss() {
      if (!cssOut) return;

      const vars = {};
      qsa("[data-theme-var]", root).forEach((inp) => {
        const v = (inp.getAttribute("data-theme-var") || "").trim();
        if (!v) return;
        vars[v] = (inp.value || "").trim();
      });

      const lines = [];
      lines.push(":root{");
      for (const k of Object.keys(vars)) {
        lines.push(`  ${k}: ${vars[k]};`);
      }
      lines.push("}");
      cssOut.value = lines.join("\n");
    }

    function applyPreviewVar(varName, value) {
      if (!preview) return;
      preview.style.setProperty(varName, value);
    }

    function onInput(e) {
      const inp = e.target;
      const varName = (inp.getAttribute("data-theme-var") || "").trim();
      if (!varName) return;

      const val = (inp.value || "").trim();
      applyPreviewVar(varName, val);
      rebuildCss();
    }

    // Bind inputs
    qsa("[data-theme-var]", root).forEach((inp) => {
      inp.addEventListener("input", onInput);
      inp.addEventListener("change", onInput);

      // init preview
      const varName = (inp.getAttribute("data-theme-var") || "").trim();
      if (varName && preview) applyPreviewVar(varName, (inp.value || "").trim());
    });

    // Optional: advanced toggle
    const advToggle = qs("#toggle-advanced", root) || qs("#toggle-advanced");
    const advBlock  = qs("#advanced-block", root) || qs("#advanced-block");
    if (advToggle && advBlock) {
      function applyAdv() {
        advBlock.style.display = advToggle.checked ? "block" : "none";
      }
      advToggle.addEventListener("change", applyAdv);
      applyAdv();
    }

    // Optional: delete theme buttons
    qsa("[data-action='delete-theme']", root).forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.preventDefault();
        const name = (btn.getAttribute("data-theme-name") || "").trim();
        if (!name) return;
        if (!confirm(`Theme verwijderen: "${name}" ?`)) return;

        // If your form uses hidden input:
        const hid = qs("input[name='delete_theme']", root);
        if (hid) hid.value = name;

        const form = btn.closest("form");
        if (form) form.submit();
      });
    });

    rebuildCss();
  })();

  // -----------------------
  // JWT page helpers (keep)
  // -----------------------
  document.addEventListener("DOMContentLoaded", function () {
    // issuer -> subject sync
    const issuerInput = document.getElementById("issuer");
    const subjectInput = document.getElementById("subject");
    if (issuerInput && subjectInput) {
      function syncSubject() { subjectInput.value = issuerInput.value; }
      issuerInput.addEventListener("input", syncSubject);
      syncSubject();
    }

    // Copy token button
    const copyBtn = document.getElementById("copyBtn");
    const tokenText = document.getElementById("tokenText");
    if (copyBtn && tokenText) {
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText((tokenText.textContent || "").trim());
          const old = copyBtn.textContent;
          copyBtn.textContent = "Gekopieerd ✔";
          copyBtn.disabled = true;
          setTimeout(() => { copyBtn.textContent = old || "Kopieer token"; copyBtn.disabled = false; }, 2000);
        } catch (e) {
          alert("Kopiëren mislukt: " + (e && e.message ? e.message : e));
        }
      });
    }
  });
})();
