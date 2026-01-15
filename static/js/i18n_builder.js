
/* --------------------------------------------------------------------------
 * i18n Builder — UI bootstrapping & editors orchestration
 * Works with: /i18n/i18n_builder.json + /i18n/i18n_modes.json
 * Editors: Tiptap (markdown), TinyMCE (html), CodeMirror 6 (css/json/xml/raw)
 * Includes:
 *  - Autosave (localStorage)
 *  - Auto snapshots to /i18n/snapshot every 60s + on mode switch + on unload
 *  - Status indicator + spinner during snapshotting
 *  - Live HTML preview & live CSS injection
 *  - ZIP export (JS-only, store mode)
 *  - CM6 only (no CM5 fallback), local ESM imports with cache-buster
 * -------------------------------------------------------------------------- */
(() => {
  const state = {
    config: null,
    modes: null,
    currentMode: null,
    editors: {
      tiptap: null,
      tinymce: null,
      codemirror: null,
    },
    elements: {},
    autosaveKey: 'i18n_builder_autosave_v1',
    styleNodeId: 'i18n-live-style',
    _snapshotTimer: null,
  };

  const SNAPSHOT_INTERVAL_MS = 60_000; // 60 sec

  // ---------------------------- Helpers ------------------------------------
  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const wait = ms => new Promise(res => setTimeout(res, ms));

  async function loadJSON(url) {
    const res = await fetch(url, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Kon JSON niet laden: ${url}`);
    return res.json();
  }

  function importFresh(url) {
    try {
      const v = (state?.config?.version) || Date.now();
      const sep = url.includes('?') ? '&' : '?';
      return import(`${url}${sep}v=${v}`);
    } catch {
      return import(url);
    }
  }

  function saveAutosave(payload) {
    try { localStorage.setItem(state.autosaveKey, JSON.stringify(payload)); }
    catch (e) { console.warn('Autosave faalde', e); }
  }
  function loadAutosave() {
    try {
      const raw = localStorage.getItem(state.autosaveKey);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }
  function debounce(fn, ms = 300) {
    let t;
    return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
  }
  function ensureStyleNode() {
    let node = document.getElementById(state.styleNodeId);
    if (!node) {
      node = document.createElement('style');
      node.id = state.styleNodeId;
      document.head.appendChild(node);
    }
    return node;
  }
  function blobDownload(name, blob) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = name; a.click();
    URL.revokeObjectURL(url);
  }
  function fmtTime(ts = Date.now()) {
    const d = new Date(ts);
    const p = n => String(n).padStart(2, '0');
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
  function updateStatus(message, kind = 'info') {
    if (!state.elements.status) return;
    state.elements.status.textContent = message;
    state.elements.status.dataset.kind = kind;
    const el = state.elements.status;
    el.style.opacity = '1';
    clearTimeout(el._fade);
    el._fade = setTimeout(() => { el.style.opacity = '0.75'; }, 2000);
  }
  function showSpinner() {
    if (!state.elements.spinner) return;
    state.elements.spinner.style.visibility = 'visible';
    state.elements.spinner.style.opacity = '1';
  }
  function hideSpinner() {
    if (!state.elements.spinner) return;
    state.elements.spinner.style.opacity = '0';
    clearTimeout(state.elements.spinner._hideTimer);
    state.elements.spinner._hideTimer = setTimeout(() => {
      state.elements.spinner.style.visibility = 'hidden';
    }, 250);
  }

  function extForMode(mode) {
    switch (mode) {
      case 'markdown': return 'md';
      case 'html':     return 'html';
      case 'css':      return 'css';
      case 'json':     return 'json';
      case 'xml':      return 'xml';
      case 'raw':      return 'txt';
      default:         return 'txt';
    }
  }

  async function postSnapshot() {
    try {
      showSpinner();
      const mode = state.currentMode ?? state.modes?.default_mode ?? 'markdown';
      const content = getCurrentContent();
      const ext = extForMode(mode);
      const filename = `autosave_${mode}.${ext}`;
      const r = await fetch('/i18n/snapshot', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename, content })
      });
      if (r.ok) updateStatus(`Snapshot • ${fmtTime()}`, 'ok');
      else      updateStatus(`Snapshot mislukt (${r.status})`, 'warn');
    } catch (e) {
      console.debug('Snapshot mislukte (genegeerd):', e?.message ?? e);
      updateStatus('Snapshot mislukt', 'warn');
    } finally {
      hideSpinner();
    }
  }

  // Minimaal ZIP (store-only)
  async function makeZip(files) {
    const encoder = new TextEncoder();
    const fileRecords = [];
    let offset = 0;
    const fileParts = [];
    const crc32 = (str) => {
      let c = 0 ^ (-1);
      for (let i = 0; i < str.length; i++) {
        c = (c >>> 8) ^ table[(c ^ str.charCodeAt(i)) & 0xFF];
      }
      return (c ^ (-1)) >>> 0;
    };
    const table = (() => {
      let c, table = [];
      for (let n = 0; n < 256; n++) {
        c = n;
        for (let k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320 ^ (c >>> 1)) : (c >>> 1);
        table[n] = c >>> 0;
      }
      return table;
    })();
    function u32(n) { const b = new Uint8Array(4);
      b[0]=n & 0xFF; b[1]=(n>>>8)&0xFF; b[2]=(n>>>16)&0xFF; b[3]=(n>>>24)&0xFF; return b; }
    function u16(n) { const b = new Uint8Array(2);
      b[0]=n & 0xFF; b[1]=(n>>>8)&0xFF; return b; }

    for (const f of files) {
      const nameBytes = encoder.encode(f.name);
      const contentBytes = (f.binary instanceof Uint8Array) ? f.binary : encoder.encode(f.content ?? '');
      const crc = f.content ? crc32(f.content) : 0;
      const LFH = [
        u32(0x04034b50), u16(20), u16(0), u16(0), u16(0), u16(0),
        u32(crc), u32(contentBytes.length), u32(contentBytes.length),
        u16(nameBytes.length), u16(0)
      ];
      fileParts.push(...LFH, nameBytes, contentBytes);
      fileRecords.push({ nameBytes, crc, size: contentBytes.length, offset });
      offset += 30 + nameBytes.length + contentBytes.length;
    }
    const centralDirParts = [];
    let centralDirSize = 0;
    for (const r of fileRecords) {
      const CDH = [
        u32(0x02014b50), u16(20), u16(20), u16(0), u16(0), u16(0), u16(0),
        u32(r.crc), u32(r.size), u32(r.size),
        u16(r.nameBytes.length), u16(0), u16(0), u16(0), u16(0), u32(0), u32(r.offset)
      ];
      centralDirParts.push(...CDH, r.nameBytes);
      centralDirSize += 46 + r.nameBytes.length;
    }
    const centralDirStart = offset;
    const EOCD = [
      u32(0x06054b50), u16(0), u16(0),
      u16(fileRecords.length), u16(fileRecords.length),
      u32(centralDirSize), u32(centralDirStart),
      u16(0)
    ];
    const totalSize = offset + centralDirSize + 22;
    const out = new Uint8Array(totalSize);
    let ptr = 0;
    for (const part of fileParts)       { out.set(part, ptr); ptr += part.length; }
    for (const part of centralDirParts) { out.set(part, ptr); ptr += part.length; }
    for (const part of EOCD)            { out.set(part, ptr); ptr += part.length; }
    return new Blob([out], { type: 'application/zip' });
  }

  // ---------------------------- Editors init -------------------------------
  async function initTiptap(container, placeholderText) {
    const base = state.config.ui.editors.tiptap.path;
    const modules = state.config.ui.editors.tiptap.modules;
    const [{ Editor }, StarterKit, Link, Image, Placeholder] = await Promise.all([
      importFresh(`/${base}/${modules.core}`),
      importFresh(`/${base}/${modules.starterkit}`),
      importFresh(`/${base}/${modules.link}`),
      importFresh(`/${base}/${modules.image}`),
      importFresh(`/${base}/${modules.placeholder}`)
    ]);
    const editor = new Editor({
      element: container,
      extensions: [
        StarterKit.default ? StarterKit.default : StarterKit,
        (Link.default ?? Link),
        (Image.default ?? Image),
        (Placeholder.default ?? Placeholder).configure({
          placeholder: placeholderText ?? 'Start met typen...'
        })
      ],
      content: '',
      onUpdate: debounce(({ editor }) => {
        updateStatus('Wijzigingen…', 'typing');
        handleContentChanged(editor.getHTML());
      }, 200)
    });
    return editor;
  }

  async function initTinyMCE(textarea) {
    const conf = state.config.ui.editors.tinymce.config ?? {};
    const basePath = state.config.ui.editors.tinymce.path;
    if (!window.tinymce) {
      await importFresh(`/${basePath}/tinymce.min.js`);
    }
    const darkDefault = (state.config.ui?.dark_default ??
                         state.config.features?.dark_mode_default ?? true);

    return new Promise((resolve) => {
      window.tinymce.init({
        target: textarea,
        skin: darkDefault ? "oxide-dark" : "oxide",
        content_css: darkDefault ? "dark" : "default",
        menubar: conf.menubar ?? false,
        plugins: conf.plugins ?? 'lists link image code table autosave',
        toolbar: conf.toolbar ?? 'undo redo bold italic underline alignleft aligncenter alignright bullist numlist code',
        height: conf.height ?? 600,
        setup: (ed) => {
          ed.on('Change KeyUp SetContent', debounce(() => {
            updateStatus('Wijzigingen…', 'typing');
            handleContentChanged(ed.getContent());
          }, 200));
          ed.on('Init', () => resolve(ed));
        },
        base_url: `/${basePath}`,
        suffix: '.min'
      });
    });
  }

  async function initCodeMirror(container, syntax = 'plaintext') {
    const base = state.config.ui.editors.codemirror.path; // 'static/vendor/codemirror'
    // Pure CM6 met lokale mapstructuur
    const viewMod  = await importFresh(`/${base}/view/index.js`);
    const stateMod = await importFresh(`/${base}/state/index.js`);
    const langSupport = await loadCM6LanguageForSyntax(base, syntax); // kan null zijn

    const { EditorView } = viewMod;
    const { EditorState } = stateMod;

    const extensions = [];
    if (langSupport) extensions.push(langSupport);
    extensions.push(
      EditorView.updateListener.of(
        debounce((v) => {
          if (v.docChanged) {
            updateStatus('Wijzigingen…', 'typing');
            handleContentChanged(v.state.doc.toString());
          }
        }, 120)
      )
    );

    const view = new EditorView({
      parent: container,
      state: EditorState.create({ doc: '', extensions })
    });
    return view;
  }

  async function loadCM6LanguageForSyntax(base, syntax) {
    try {
      switch (syntax) {
        case 'markdown': return (await importFresh(`/${base}/lang-markdown/index.js`)).markdown();
        case 'html':     return (await importFresh(`/${base}/lang-html/index.js`)).html();
        case 'css':      return (await importFresh(`/${base}/lang-css/index.js`)).css();
        case 'json':     return (await importFresh(`/${base}/lang-json/index.js`)).json();
        case 'xml':      return (await importFresh(`/${base}/lang-xml/index.js`)).xml();
        default:         return null;
      }
    } catch (e) {
      console.warn('Kon CM6 language niet laden, val terug op plain.', e);
      return null;
    }
  }

  // ---------------------------- Content plumbing ---------------------------
  function handleContentChanged(content) {
    const modeDef = state.modes.modes[state.currentMode];
    if (modeDef) {
      if (state.currentMode === 'html' && state.config.features.live_preview) {
        const ifr = state.elements.preview;
        if (ifr) {
          const doc = ifr.contentDocument ?? ifr.contentWindow?.document;
          if (doc) {
            doc.open();
            doc.write(content ?? '');
            doc.close();
          }
        }
      }
      if (state.currentMode === 'css' && state.config.features.live_css_apply) {
        const node = ensureStyleNode();
        node.textContent = content ?? '';
      }
    }
    // Autosave payload
    const payload = { mode: state.currentMode, content, ts: Date.now() };
    saveAutosave(payload);
    updateStatus(`Autosave • ${fmtTime(payload.ts)}`, 'autosave');
  }

  function getCurrentContent() {
    switch (state.currentMode) {
      case 'markdown':
        if (state.editors.tiptap) return state.editors.tiptap.getHTML();
        return '';
      case 'html':
        if (state.editors.tinymce) return state.editors.tinymce.getContent();
        return '';
      default: {
        const cm = state.editors.codemirror;
        if (!cm) return '';
        if (cm.state && cm.update) {
          // CM6
          return cm.state.doc.toString();
        }
        // (geen CM5 meer)
        return '';
      }
    }
  }

  function setCurrentContent(content) {
    switch (state.currentMode) {
      case 'markdown':
        if (state.editors.tiptap) state.editors.tiptap.commands.setContent(content ?? '');
        break;
      case 'html':
        if (state.editors.tinymce) state.editors.tinymce.setContent(content ?? '');
        break;
      default: {
        const cm = state.editors.codemirror;
        if (!cm) return;
        if (cm.state && cm.update) {
          // CM6
          cm.dispatch({ changes: { from: 0, to: cm.state.doc.length, insert: content ?? '' } });
        }
      }
    }
  }

  // ---------------------------- UI build -----------------------------------
  function buildUI() {
    state.elements.container = $('.i18n-builder-container') ?? document.body;

    // Header bar (status + spinner links) en switcher (rechts)
    const statusWrap = document.createElement('div');
    statusWrap.style.display = 'flex';
    statusWrap.style.justifyContent = 'space-between';
    statusWrap.style.alignItems = 'center';
    statusWrap.style.gap = '10px';
    statusWrap.style.marginBottom = '8px';

    const leftGroup = document.createElement('div');
    leftGroup.style.display = 'flex';
    leftGroup.style.alignItems = 'center';
    leftGroup.style.gap = '8px';

    // Status text
    state.elements.status = document.createElement('div');
    state.elements.status.className = 'i18n-status';
    state.elements.status.style.fontSize = '12px';
    state.elements.status.style.opacity = '0.75';
    state.elements.status.style.userSelect = 'none';
    state.elements.status.textContent = 'Gereed';
    leftGroup.appendChild(state.elements.status);

    // Spinner (CSS-only, inline styles)
    state.elements.spinner = document.createElement('div');
    state.elements.spinner.className = 'i18n-spinner';
    Object.assign(state.elements.spinner.style, {
      width: '14px',
      height: '14px',
      border: '2px solid rgba(66,133,244,0.25)',
      borderTopColor: '#4285f4',
      borderRadius: '50%',
      animation: 'i18n_spin 0.8s linear infinite',
      visibility: 'hidden',
      opacity: '0',
      transition: 'opacity 0.2s ease',
    });
    if (!document.getElementById('i18n_spin_keyframes')) {
      const k = document.createElement('style');
      k.id = 'i18n_spin_keyframes';
      k.textContent = `@keyframes i18n_spin { from { transform: rotate(0deg);} to { transform: rotate(360deg);} }`;
      document.head.appendChild(k);
    }
    leftGroup.appendChild(state.elements.spinner);
    statusWrap.appendChild(leftGroup);

    // Mode Switcher rechts
    state.elements.switcher = document.createElement('div');
    state.elements.switcher.className = 'i18n-mode-switcher';
    statusWrap.appendChild(state.elements.switcher);

    state.elements.container.appendChild(statusWrap);

    // Editor wrapper
    state.elements.editorWrapper = document.createElement('div');
    state.elements.editorWrapper.className = 'editor-wrapper';
    state.elements.container.appendChild(state.elements.editorWrapper);

    // Per-editor containers
    state.elements.tiptapHost = document.createElement('div');
    state.elements.tiptapHost.className = 'tiptap-editor';
    state.elements.tiptapHost.style.display = 'none';

    state.elements.tinymceArea = document.createElement('textarea');
    state.elements.tinymceArea.style.display = 'none';

    state.elements.cmHost = document.createElement('div');
    state.elements.cmHost.className = 'codemirror-host';
    state.elements.cmHost.style.display = 'none';

    state.elements.editorWrapper.appendChild(state.elements.tiptapHost);
    state.elements.editorWrapper.appendChild(state.elements.tinymceArea);
    state.elements.editorWrapper.appendChild(state.elements.cmHost);

    // Preview (for HTML)
    if (state.config.features.live_preview) {
      state.elements.preview = document.createElement('iframe');
      state.elements.preview.id = 'i18n-live-preview';
      state.elements.preview.style.width = '100%';
      state.elements.preview.style.minHeight = '300px';
      state.elements.preview.style.background = '#fff';
      state.elements.preview.style.border = '0';
      state.elements.preview.style.marginTop = '10px';
      state.elements.container.appendChild(state.elements.preview);
    }

    // Export panel
    const panel = document.createElement('div');
    panel.className = 'i18n-export-panel';
    const btnExport = document.createElement('button');
    btnExport.className = 'i18n-btn'; btnExport.textContent = 'Export ZIP';
    btnExport.addEventListener('click', onExportZip);

    const btnRestore = document.createElement('button');
    btnRestore.className = 'i18n-btn'; btnRestore.textContent = 'Herstel Autosave';
    btnRestore.addEventListener('click', onRestoreAutosave);

    panel.appendChild(btnExport);
    panel.appendChild(btnRestore);
    state.elements.container.appendChild(panel);

    // Dropzone
    if (state.config.features.drag_drop_upload) {
      const dz = document.createElement('div');
      dz.className = 'i18n-dropzone';
      dz.textContent = 'Sleep bestanden hierheen om te importeren…';
      dz.addEventListener('dragover', (e) => { e.preventDefault(); dz.classList.add('hover'); });
      dz.addEventListener('dragleave', () => dz.classList.remove('hover'));
      dz.addEventListener('drop', onDropFiles);
      state.elements.container.appendChild(dz);
    }

    // Build switcher tabs
    const modeKeys = Object.keys(state.modes.modes);
    for (const key of modeKeys) {
      const def = state.modes.modes[key];
      const tab = document.createElement('div');
      tab.className = 'i18n-mode-tab';
      tab.dataset.mode = key;
      tab.textContent = def.label ?? key;
      tab.addEventListener('click', () => switchMode(key));
      state.elements.switcher.appendChild(tab);
    }
  }

  async function switchMode(modeKey) {
    if (state.currentMode === modeKey) return;

    // Hide all editors
    state.elements.tiptapHost.style.display   = 'none';
    state.elements.tinymceArea.style.display  = 'none';
    state.elements.cmHost.style.display       = 'none';

    // Update active tab
    $$('.i18n-mode-tab', state.elements.switcher).forEach(t => {
      t.classList.toggle('active', t.dataset.mode === modeKey);
    });

    state.currentMode = modeKey;
    const modeDef = state.modes.modes[modeKey];
    const editorType = modeDef.wysiwyg;

    // Initialize editor if needed
    if (editorType === 'tiptap') {
      state.elements.tiptapHost.style.display = '';
      if (!state.editors.tiptap) {
        state.editors.tiptap = await initTiptap(state.elements.tiptapHost, 'Schrijf je Markdown…');
      }
    } else if (editorType === 'tinymce') {
      state.elements.tinymceArea.style.display = '';
      if (!state.editors.tinymce) {
        state.editors.tinymce = await initTinyMCE(state.elements.tinymceArea);
      }
    } else {
      // CodeMirror
      state.elements.cmHost.style.display = '';
      if (!state.editors.codemirror) {
        state.editors.codemirror = await initCodeMirror(state.elements.cmHost, modeDef.syntax ?? 'plaintext');
      } else {
        // (optioneel) reconfigure taal extensie; simpel gehouden
      }
    }

    // Set template content if empty, else restore autosave per mode
    await wait(10);
    const stored = loadAutosave();
    if (stored && stored.mode === modeKey && stored.content) {
      setCurrentContent(stored.content);
    } else {
      const tpl = state.config.templates?.[modeKey];
      const cur = getCurrentContent();
      if (tpl && (!cur || cur.trim() === '')) {
        setCurrentContent(tpl);
      }
    }

    // Sync preview & css + status
    handleContentChanged(getCurrentContent());
    updateStatus(`Mode: ${modeKey}`, 'info');

    // Snapshot bij mode-wissel
    postSnapshot().catch(() => {});
  }

  async function onExportZip() {
    const files = [];
    const ts = new Date().toISOString().replace(/[:.]/g, '-');
    const baseName = `i18n_export_${ts}`;

    // Capture current content in a file per mode
    for (const key of Object.keys(state.modes.modes)) {
      let ext = key;
      if (key === 'markdown') ext = 'md';
      if (key === 'raw')      ext = 'txt';
      await switchMode(key);
      const content = getCurrentContent();
      files.push({ name: `${baseName}.${ext}`, content });
    }
    // switch back
    await switchMode(state.modes.default_mode ?? 'markdown');

    const zip = await makeZip(files);
    blobDownload(`${baseName}.zip`, zip);
    updateStatus('ZIP geëxporteerd', 'ok');
  }

  function onRestoreAutosave() {
    const stored = loadAutosave();
    if (!stored) return;
    if (stored.mode && stored.mode !== state.currentMode) {
      switchMode(stored.mode).then(() => setCurrentContent(stored.content ?? ''));
    } else {
      setCurrentContent(stored.content ?? '');
    }
    updateStatus('Autosave hersteld', 'ok');
  }

  async function onDropFiles(e) {
    e.preventDefault();
    e.currentTarget.classList.remove('hover');
    const files = e.dataTransfer.files;
    if (!files || !files.length) return;
    for (const f of files) {
      const text = await f.text();
      setCurrentContent(text);
    }
    updateStatus('Bestand(en) geïmporteerd', 'ok');
  }

  // ---------------------------- Bootstrap ----------------------------------
  async function boot() {
    // Load configs: eerst /i18n/... (geserveerd door Flask vanuit /config), dan fallbacks
    async function loadWithFallback(candidates) {
      for (const url of candidates) {
        try {
          const res = await fetch(url, { cache: 'no-store' });
          if (res.ok) return await res.json();
        } catch (_) { /* try next */ }
      }
      throw new Error('Geen geldige config gevonden: ' + candidates.join(', '));
    }

    state.config = await loadWithFallback([
      '/i18n/i18n_builder.json',
      '/static/config/i18n_builder.json',
      'i18n_builder.json'
    ]);
    state.modes = await loadWithFallback([
      '/i18n/i18n_modes.json',
      '/static/config/i18n_modes.json',
      'i18n_modes.json'
    ]);

    // Build UI
    buildUI();

    // Start in default mode
    const def = state.modes.default_mode ?? 'markdown';
    await switchMode(def);

    // Periodiek snapshotten
    if (!state._snapshotTimer) {
      state._snapshotTimer = setInterval(() => {
        postSnapshot().catch(() => {});
      }, SNAPSHOT_INTERVAL_MS);
    }

    // Laatste snapshot bij afsluiten
    window.addEventListener('beforeunload', () => {
      try {
        if (navigator.sendBeacon) {
          const mode = state.currentMode ?? state.modes?.default_mode ?? 'markdown';
          const ext = extForMode(mode);
          const filename = `autosave_${mode}.${ext}`;
          const content = getCurrentContent() ?? '';
          const payload = new Blob([JSON.stringify({ filename, content })], { type: 'application/json' });
          navigator.sendBeacon('/i18n/snapshot', payload);
          return;
        }
      } catch {}
      postSnapshot().catch(() => {});
    });

    updateStatus('Gereed', 'info');
  }

  document.addEventListener('DOMContentLoaded', () => {
    boot().catch(err => {
      console.error('i18n_builder boot error:', err);
      const c = document.body;
      const pre = document.createElement('pre');
      pre.textContent = `i18n_builder kon niet starten:\n${err?.message ?? err}`;
      c.appendChild(pre);
    });
  });
})();
