# CyNiT-Hub – TODO

Laatste status:
- Layout + header titles OK
- Tools editor (Stap A) OK: visueel + tabel, toggles, accent modes + widths, globale UI toggles
- tools.json structuur OK: { "tools": [...], "ui": {...} }

---

## 1) Beheer: Hub settings editor (Stap 2)
Doel: centrale hub-config beheren via UI (tools.json → ui).

### Must-have
- [ ] /beheer/hub: hub editor pagina (GET/POST)
- [ ] ui.flask_app_name **forced** aanwezig + configureert `app.config["FLASK_APP_NAME"]` bij startup
- [ ] ui.brand_tools / ui.brand_beheer
- [ ] ui.logo_src / ui.favicon_ico
- [ ] ui.home_columns (1..6)
- [ ] ui.card_bg / ui.card_round
- [ ] ui.button_bg / ui.button_rounded

### Nice-to-have
- [ ] Live preview (zonder refresh) van branding (header tekst) en toggles
- [ ] Reset-to-default knop

---

## 2) Beheer: Theme editor
Doel: theme-variabelen beheren zonder code edit.

### Must-have
- [ ] /beheer/theme: editor (GET/POST)
- [ ] Opslaan in `config/theme.json` of (als jij wil) in `tools.json -> ui`
- [ ] Basiskleuren: bg/tekst/muted/border/shadow
- [ ] Optioneel: presets (Dark, AMOLED, “CyNiT classic”)

### Nice-to-have
- [ ] Preview palette + kleine live sample card
- [ ] Export/Import theme (copy/paste JSON)

---

## 3) Beheer: Config editor
Doel: generieke JSON editor voor bestanden in `/config`.

### Must-have
- [ ] /beheer/config: lijst van config files (whitelist)
- [ ] File viewer/editor (textarea) met save
- [ ] Validatie (JSON parse) + duidelijke error

### Nice-to-have
- [ ] “Pretty print” knop
- [ ] Backups (auto save .bak met timestamp)

---

## 4) Beheer: Logs viewer
Doel: snel fouten zien zonder console.

### Must-have
- [ ] /beheer/logs: tonen van recente logs (tail)
- [ ] Filter: level (INFO/WARN/ERROR) + search
- [ ] Clear knop (optioneel)

### Nice-to-have
- [ ] Auto-refresh toggle
- [ ] Download logs

---

## 5) Integratie “oude tools” (migratieplan)
Doel: oude CyNiT Tools modules in deze hub trekken zonder herschrijven.

### Must-have
- [ ] Inventaris: welke tools gaan erin (lijst)
- [ ] Per tool check:
  - [ ] Heeft tool `register_web_routes(app)`?
  - [ ] Heeft tool eigen templates/static nodig?
  - [ ] Heeft tool eigen config files nodig?
- [ ] Compat layer:
  - [ ] Tools krijgen `render_page()` layout gratis
  - [ ] Tool routes blijven gelijk (web_path)

### Nice-to-have
- [ ] “Legacy tool wrapper” helper:
  - [ ] standaard error page in CyNiT style
  - [ ] standaard panel + status badges

---

## 6) Security / deployment readiness
(alleen als je richting “deelbaar” gaat)

- [ ] debug=False in prod
- [ ] configurable host/port
- [ ] basic auth / AAD (indien nodig)
- [ ] CSRF bescherming voor editors (optioneel)
- [ ] gunicorn/waitress run script

---

## 7) Quality-of-life
- [ ] Search in tools dropdown
- [ ] Favorites / pin tools
- [ ] Sort tools (alfabetisch + drag/drop)
- [ ] “Hidden” duidelijker label (home vs dropdown)

---

## Notes
- tools.json blijft **single source of truth**:
  - tools[]: per tool settings
  - ui: globale hub settings
