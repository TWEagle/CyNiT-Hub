function bindDropdown(buttonId, menuId) {
  const btn = document.getElementById(buttonId);
  const menu = document.getElementById(menuId);
  if (!btn || !menu) return;

  document.addEventListener("click", (e) => {
    // click on button => toggle
    if (btn.contains(e.target)) {
      const open = menu.style.display === "block";
      // close all dropdowns first
      document.querySelectorAll(".dropdown").forEach(d => d.style.display = "none");
      menu.style.display = open ? "none" : "block";
      return;
    }

    // click outside => close
    if (!menu.contains(e.target)) {
      menu.style.display = "none";
    }
  });
}

window.addEventListener("DOMContentLoaded", () => {
  bindDropdown("toolsBtn", "toolsMenu");
  bindDropdown("beheerBtn", "beheerMenu");
});
