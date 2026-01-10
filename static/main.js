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

  function positionUnder(menu, btn, alignRight = false) {
    const rect = btn.getBoundingClientRect();
    menu.style.top = (rect.bottom + 10) + "px";

    if (alignRight) {
      menu.style.right = (window.innerWidth - rect.right + 14) + "px";
      menu.style.left = "auto";
    } else {
      menu.style.left = rect.left + "px";
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

  document.addEventListener("click", (e) => {
    const t = e.target;
    const inMenu = (menuTools && menuTools.contains(t)) || (menuBeheer && menuBeheer.contains(t));
    const inBtn  = (btnTools && btnTools.contains(t)) || (btnBeheer && btnBeheer.contains(t));
    if (!inMenu && !inBtn) closeAll();
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAll();
  });

  window.addEventListener("resize", () => {
    if (menuTools && btnTools && menuTools.classList.contains("open")) positionUnder(menuTools, btnTools, false);
    if (menuBeheer && btnBeheer && menuBeheer.classList.contains("open")) positionUnder(menuBeheer, btnBeheer, true);
  });
})();
