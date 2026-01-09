document.addEventListener("click", (e) => {
  const btn = document.getElementById("toolsBtn");
  const menu = document.getElementById("toolsMenu");

  if (!btn || !menu) return;

  if (btn.contains(e.target)) {
    menu.style.display = menu.style.display === "block" ? "none" : "block";
    return;
  }

  if (!menu.contains(e.target)) {
    menu.style.display = "none";
  }
});
