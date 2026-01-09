(function () {
  function qs(sel) { return document.querySelector(sel); }
  function qsa(sel) { return Array.from(document.querySelectorAll(sel)); }

  // ===== Dropdown handling (Tools + Beheer) =====
  const btnTools = qs("#btn-tools");
  const menuTools = qs("#menu-tools");
  const btnBeheer = qs("#btn-beheer");
  const menuBeheer = qs("#menu-beheer");

  function closeAll() {
    if (menuTools) menuTools.classList.remove("open");
    if (menuBeheer) menuBeheer.classList.remove("open");
    if (btnTools) btnTools.setAttribute("aria-expanded", "false");
    if (btnBeheer) btnBeheer.setAttribute("aria-expanded", "false");
  }

  function toggle(menu, btn) {
    if (!menu || !btn) return;
    const isOpen = menu.classList.contains("open");
    closeAll();
    if (!isOpen) {
      menu.classList.add("open");
      btn.setAttribute("aria-expanded", "true");
      const rect = btn.getBoundingClientRect();
      menu.style.left = rect.left + "px";
      menu.style.top = (rect.bottom + 8) + "px";
    }
  }

  if (btnTools) btnTools.addEventListener("click", (e) => {
    e.stopPropagation();
    toggle(menuTools, btnTools);
  });

  if (btnBeheer) btnBeheer.addEventListener("click", (e) => {
    e.stopPropagation();
    toggle(menuBeheer, btnBeheer);
    if (menuBeheer) {
      menuBeheer.style.left = "";
      menuBeheer.style.top = (btnBeheer.getBoundingClientRect().bottom + 8) + "px";
    }
  });

  document.addEventListener("click", () => closeAll());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeAll();
  });

  // ===== Tools editor helpers =====
  const addBtn = qs("#btn-add-tool");
  const tbody = qs("#tooltable-body");
  const rowCountEl = qs("#row_count");

  function bindColorPickers() {
    qsa('input[type="color"][data-bind="accent"]').forEach(cp => {
      cp.addEventListener("input", () => {
        const tr = cp.closest("tr");
        if (!tr) return;
        const idx = tr.getAttribute("data-index");
        const textInp = tr.querySelector(`input[name="accent_${idx}"]`);
        if (textInp) textInp.value = cp.value;
      });
    });
  }

  function reindexRows() {
    if (!tbody || !rowCountEl) return;
    const rows = Array.from(tbody.querySelectorAll("tr.toolrow"));
    rows.forEach((tr, newIdx) => {
      const oldIdx = tr.getAttribute("data-index");
      tr.setAttribute("data-index", String(newIdx));

      tr.querySelectorAll("input, button").forEach(el => {
        if (el.name) {
          el.name = el.name.replace(`_${oldIdx}`, `_${newIdx}`);
        }
      });

      const del = tr.querySelector('input[name^="deleted_"]');
      if (del) del.name = `deleted_${newIdx}`;

      const orig = tr.querySelector('input[name^="orig_"]');
      if (orig) orig.name = `orig_${newIdx}`;
    });
    rowCountEl.value = String(rows.length);
  }

  function attachRowActions() {
    if (!tbody) return;
    tbody.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-action]");
      if (!btn) return;

      const action = btn.getAttribute("data-action");
      const tr = btn.closest("tr.toolrow");
      if (!tr) return;

      if (action === "delete") {
        const idx = tr.getAttribute("data-index");
        const delInp = tr.querySelector(`input[name="deleted_${idx}"]`);
        if (delInp) delInp.value = "1";
        tr.style.display = "none";
        tr.classList.add("deleted");
        return;
      }

      if (action === "up") {
        const prev = tr.previousElementSibling;
        if (prev) tbody.insertBefore(tr, prev);
        reindexRows();
        bindColorPickers();
        return;
      }

      if (action === "down") {
        const next = tr.nextElementSibling;
        if (next) tbody.insertBefore(next, tr);
        reindexRows();
        bindColorPickers();
        return;
      }
    });
  }

  function addRow() {
    if (!tbody || !rowCountEl) return;
    const idx = Number(rowCountEl.value || "0");

    const tr = document.createElement("tr");
    tr.className = "toolrow";
    tr.setAttribute("data-index", String(idx));
    tr.innerHTML = `
      <td class="col-move">
        <button type="button" class="mini" data-action="up">↑</button>
        <button type="button" class="mini" data-action="down">↓</button>
        <input type="hidden" name="deleted_${idx}" value="0">
        <input type="hidden" name="orig_${idx}" value='{}'>
      </td>

      <td class="col-enabled">
        <label class="switch">
          <input type="checkbox" name="enabled_${idx}" checked>
          <span class="slider"></span>
        </label>
      </td>

      <td class="col-icon">
        <input class="inp inp-icon" name="icon_${idx}" value="🧩">
      </td>

      <td class="col-name">
        <input class="inp" name="name_${idx}" value="Nieuwe tool">
      </td>

      <td class="col-id">
        <input class="inp inp-id" name="id_${idx}" value="new_tool_${idx+1}">
      </td>

      <td class="col-path">
        <input class="inp inp-path" name="web_path_${idx}" value="/new-tool-${idx+1}">
      </td>

      <td class="col-script">
        <input class="inp inp-script" name="script_${idx}" value="" placeholder="voica1.py">
      </td>

      <td class="col-type">
        <input class="inp inp-type" name="type_${idx}" value="web" placeholder="web">
      </td>

      <td class="col-accent">
        <div class="accentbox">
          <input class="inp inp-accent" name="accent_${idx}" value="#00f700">
          <input type="color" class="colorpick" value="#00f700" data-bind="accent">
        </div>
      </td>

      <td class="col-desc">
        <input class="inp" name="description_${idx}" value="">
      </td>

      <td class="col-del">
        <button type="button" class="mini danger" data-action="delete">✖</button>
      </td>
    `;
    tbody.appendChild(tr);
    rowCountEl.value = String(idx + 1);
    bindColorPickers();
  }

  if (addBtn) addBtn.addEventListener("click", () => addRow());

  // init
  bindColorPickers();
  attachRowActions();
})();
