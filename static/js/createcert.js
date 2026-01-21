// static/js/createcert.js
(function () {
  function qs(sel) { return document.querySelector(sel); }
  function qsa(sel) { return Array.from(document.querySelectorAll(sel)); }

  async function copyTextFromSelector(sel) {
    const el = qs(sel);
    if (!el) return false;
    const v = (el.value !== undefined) ? el.value : el.textContent;
    if (!v) return false;

    try {
      await navigator.clipboard.writeText(v);
      return true;
    } catch (e) {
      // fallback
      try {
        el.focus();
        el.select && el.select();
        document.execCommand("copy");
        return true;
      } catch (e2) {
        return false;
      }
    }
  }

  qsa("[data-copy]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const sel = btn.getAttribute("data-copy");
      const ok = await copyTextFromSelector(sel);
      const old = btn.textContent;
      btn.textContent = ok ? "Copied ✓" : "Copy failed";
      setTimeout(() => (btn.textContent = old), 900);
    });
  });
})();
