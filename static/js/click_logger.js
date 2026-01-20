(function () {
  function safe(s, maxLen) {
    try {
      return (s || "").toString().replace(/\s+/g, " ").trim().slice(0, maxLen || 180);
    } catch (e) {
      return "";
    }
  }

  function pickText(el) {
    return safe(
      (el.getAttribute && (el.getAttribute("aria-label") || el.getAttribute("title"))) ||
        el.title ||
        el.innerText ||
        el.textContent ||
        "",
      180
    );
  }

  function payloadFrom(ev) {
    const t = ev.target;
    if (!t) return null;

    const el = t.closest
      ? t.closest("a,button,input,select,textarea,label,.toolcard,.iconbtn,[role='button']")
      : t;
    if (!el) return null;

    const tag = (el.tagName || "").toLowerCase();
    const href = tag === "a" && el.getAttribute ? el.getAttribute("href") || "" : "";

    return {
      path: location.pathname + location.search,
      href: href,
      tag: tag,
      id: el.id || "",
      cls: safe(el.className || "", 180),
      text: pickText(el),
      ts: Date.now(),
    };
  }

  function send(data) {
    try {
      const body = JSON.stringify(data);
      if (navigator.sendBeacon) {
        const blob = new Blob([body], { type: "application/json" });
        navigator.sendBeacon("/_log/click", blob);
        return;
      }
      fetch("/_log/click", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body,
        keepalive: true,
      }).catch(() => {});
    } catch (e) {}
  }

  // capture phase: logt ook als je meteen navigeert
  document.addEventListener(
    "click",
    function (ev) {
      const data = payloadFrom(ev);
      if (!data) return;
      send(data);
    },
    true
  );
})();
