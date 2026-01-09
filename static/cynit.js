(function () {
  function qs(sel) { return document.querySelector(sel); }

  const btnTools  = qs("#btn-tools");
  const menuTools = qs("#menu-tools");

  const btnBeheer  = qs("#btn-beheer");
  const menuBeheer = qs("#menu-beheer");

  function closeMenu(menu, btn) {
    if (!menu || !btn) return;
    menu.classList.remove("open");
    btn.setAttribute("aria-expanded", "false");
  }

  function closeAll() {
    closeMenu(menuTools, btnTools);
    closeMenu(menuBeheer, btnBeheer);
  }

  // Positioneer dropdown onder knop, rekening houdend met scroll
  function positionUnder(menu, btn, alignRight = false) {
    if (!menu || !btn) return;

    const rect = btn.getBoundingClientRect();
    const top  = rect.bottom + window.scrollY + 10;

    menu.style.top = top + "px";

    if (alignRight) {
      // rechts uitlijnen op knop
      const right = (window.innerWidth - rect.right) + 16;
      menu.style.right = right + "px";
      menu.style.left  = "auto";
    } else {
      const left = rect.left + window.scrollX;
      menu.style.left  = left + "px";
      menu.style.right = "auto";
    }
  }

  function toggle(menu, btn, alignRight = false) {
    if (!menu || !btn) return;

    const isOpen = menu.classList.contains("open");
    closeAll();

    if (!isOpen) {
      menu.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      positionUnder(menu, btn, alignRight);
    }
  }

  if (btnTools && menuTools) {
    btnTools.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggle(menuTools, btnTools, false);
    });
  }

  if (btnBeheer && menuBeheer) {
    btnBeheer.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggle(menuBeheer, btnBeheer, true);
    });
  }

  // Klik buiten -> sluiten
  document.addEventListener("click", (e) => {
    const t = e.target;
    const clickedTools  = menuTools && menuTools.contains(t);
    const clickedBeheer = menuBeheer && menuBeheer.contains(t);
    const clickedBtn    = (btnTools && btnTools.contains(t)) || (btnBeheer && btnBeheer.contains(t));
    if (!clickedTools && !clickedBeheer && !clickedBtn) closeAll();
  });

  // ESC -> sluiten
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAll();
  });

  // Herpositioneer bij resize/scroll als menu open staat
  window.addEventListener("resize", () => {
    if (menuTools && btnTools && menuTools.classList.contains("open")) positionUnder(menuTools, btnTools, false);
    if (menuBeheer && btnBeheer && menuBeheer.classList.contains("open")) positionUnder(menuBeheer, btnBeheer, true);
  });
  window.addEventListener("scroll", () => {
    if (menuTools && btnTools && menuTools.classList.contains("open")) positionUnder(menuTools, btnTools, false);
    if (menuBeheer && btnBeheer && menuBeheer.classList.contains("open")) positionUnder(menuBeheer, btnBeheer, true);
  }, { passive: true });

})();
