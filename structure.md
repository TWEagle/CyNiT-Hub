CyNiT-Hub/
|-- beheer/
|   |-- editors/
|   |   |-- hub_editor.py
|   |   |-- theme_editor.py
|   |   \-- tools_editor.py
|   |-- beheer_routes.py
|   \-- main_layout.py
|-- config/
|   |-- beheer.json
|   |-- hub_settings.json
|   |-- i18n_builder.json
|   |-- i18n_modes.json
|   |-- settings.json
|   |-- theme.json
|   |-- tools.json
|   |-- useful_links.json
|   |-- voica1_messages.md
|   \-- voica1.json
|-- docs/
|   |-- help/
|   \-- todo.md
|-- images/
|   |-- logo_crash.png
|   |-- logo.ico
|   \-- logo.png
|-- logs/
|   \-- master-start.md
|-- static/
|   |-- css/
|   |   |-- i18n_builder.css
|   |   |-- main.css
|   |   \-- useful_links.css
|   |-- js/
|   |   |-- i18n_builder.js
|   |   \-- main.js
|   \-- vendor/
|       |-- codemirror/
|       |   |-- lang-css/
|       |   |   \-- index.js
|       |   |-- lang-html/
|       |   |   \-- index.js
|       |   |-- lang-json/
|       |   |   \-- index.js
|       |   |-- lang-markdown/
|       |   |   \-- index.js
|       |   |-- lang-xml/
|       |   |   \-- index.js
|       |   |-- language/
|       |   |   \-- index.js
|       |   |-- state/
|       |   |   \-- index.js
|       |   \-- view/
|       |       \-- index.js
|       |-- tinymce/
|       |   |-- icons/
|       |   |   \-- default/
|       |   |       \-- icons.min.js
|       |   |-- langs/
|       |   |   \-- README.md
|       |   |-- models/
|       |   |   \-- dom/
|       |   |       \-- model.min.js
|       |   |-- plugins/
|       |   |   |-- accordion/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- advlist/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- anchor/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- autolink/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- autoresize/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- autosave/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- charmap/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- code/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- codesample/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- directionality/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- emoticons/
|       |   |   |   |-- js/
|       |   |   |   |   |-- emojiimages.js
|       |   |   |   |   |-- emojiimages.min.js
|       |   |   |   |   |-- emojis.js
|       |   |   |   |   \-- emojis.min.js
|       |   |   |   \-- plugin.min.js
|       |   |   |-- fullscreen/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- help/
|       |   |   |   |-- js/
|       |   |   |   |   \-- i18n/
|       |   |   |   |       \-- keynav/
|       |   |   |   |           |-- ar.js
|       |   |   |   |           |-- bg_BG.js
|       |   |   |   |           |-- bg-BG.js
|       |   |   |   |           |-- ca.js
|       |   |   |   |           |-- cs.js
|       |   |   |   |           |-- da.js
|       |   |   |   |           |-- de.js
|       |   |   |   |           |-- el.js
|       |   |   |   |           |-- en.js
|       |   |   |   |           |-- es.js
|       |   |   |   |           |-- eu.js
|       |   |   |   |           |-- fa.js
|       |   |   |   |           |-- fi.js
|       |   |   |   |           |-- fr_FR.js
|       |   |   |   |           |-- fr-FR.js
|       |   |   |   |           |-- he_IL.js
|       |   |   |   |           |-- he-IL.js
|       |   |   |   |           |-- hi.js
|       |   |   |   |           |-- hr.js
|       |   |   |   |           |-- hu_HU.js
|       |   |   |   |           |-- hu-HU.js
|       |   |   |   |           |-- id.js
|       |   |   |   |           |-- it.js
|       |   |   |   |           |-- ja.js
|       |   |   |   |           |-- kk.js
|       |   |   |   |           |-- ko_KR.js
|       |   |   |   |           |-- ko-KR.js
|       |   |   |   |           |-- ms.js
|       |   |   |   |           |-- nb_NO.js
|       |   |   |   |           |-- nb-NO.js
|       |   |   |   |           |-- nl.js
|       |   |   |   |           |-- pl.js
|       |   |   |   |           |-- pt_BR.js
|       |   |   |   |           |-- pt_PT.js
|       |   |   |   |           |-- pt-BR.js
|       |   |   |   |           |-- pt-PT.js
|       |   |   |   |           |-- ro.js
|       |   |   |   |           |-- ru.js
|       |   |   |   |           |-- sk.js
|       |   |   |   |           |-- sl_SI.js
|       |   |   |   |           |-- sl-SI.js
|       |   |   |   |           |-- sv_SE.js
|       |   |   |   |           |-- sv-SE.js
|       |   |   |   |           |-- th_TH.js
|       |   |   |   |           |-- th-TH.js
|       |   |   |   |           |-- tr.js
|       |   |   |   |           |-- uk.js
|       |   |   |   |           |-- vi.js
|       |   |   |   |           |-- zh_CN.js
|       |   |   |   |           |-- zh_TW.js
|       |   |   |   |           |-- zh-CN.js
|       |   |   |   |           \-- zh-TW.js
|       |   |   |   \-- plugin.min.js
|       |   |   |-- image/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- importcss/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- insertdatetime/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- licensekeymanager/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- link/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- lists/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- media/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- nonbreaking/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- pagebreak/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- preview/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- quickbars/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- save/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- searchreplace/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- table/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- visualblocks/
|       |   |   |   \-- plugin.min.js
|       |   |   |-- visualchars/
|       |   |   |   \-- plugin.min.js
|       |   |   \-- wordcount/
|       |   |       \-- plugin.min.js
|       |   |-- skins/
|       |   |   |-- content/
|       |   |   |   |-- dark/
|       |   |   |   |   |-- content.js
|       |   |   |   |   \-- content.min.css
|       |   |   |   |-- default/
|       |   |   |   |   |-- content.js
|       |   |   |   |   \-- content.min.css
|       |   |   |   |-- document/
|       |   |   |   |   |-- content.js
|       |   |   |   |   \-- content.min.css
|       |   |   |   |-- tinymce-5/
|       |   |   |   |   |-- content.js
|       |   |   |   |   \-- content.min.css
|       |   |   |   |-- tinymce-5-dark/
|       |   |   |   |   |-- content.js
|       |   |   |   |   \-- content.min.css
|       |   |   |   \-- writer/
|       |   |   |       |-- content.js
|       |   |   |       \-- content.min.css
|       |   |   \-- ui/
|       |   |       |-- oxide/
|       |   |       |   |-- content.inline.js
|       |   |       |   |-- content.inline.min.css
|       |   |       |   |-- content.js
|       |   |       |   |-- content.min.css
|       |   |       |   |-- skin.js
|       |   |       |   |-- skin.min.css
|       |   |       |   |-- skin.shadowdom.js
|       |   |       |   \-- skin.shadowdom.min.css
|       |   |       |-- oxide-dark/
|       |   |       |   |-- content.inline.js
|       |   |       |   |-- content.inline.min.css
|       |   |       |   |-- content.js
|       |   |       |   |-- content.min.css
|       |   |       |   |-- skin.js
|       |   |       |   |-- skin.min.css
|       |   |       |   |-- skin.shadowdom.js
|       |   |       |   \-- skin.shadowdom.min.css
|       |   |       |-- tinymce-5/
|       |   |       |   |-- content.inline.js
|       |   |       |   |-- content.inline.min.css
|       |   |       |   |-- content.js
|       |   |       |   |-- content.min.css
|       |   |       |   |-- skin.js
|       |   |       |   |-- skin.min.css
|       |   |       |   |-- skin.shadowdom.js
|       |   |       |   \-- skin.shadowdom.min.css
|       |   |       \-- tinymce-5-dark/
|       |   |           |-- content.inline.js
|       |   |           |-- content.inline.min.css
|       |   |           |-- content.js
|       |   |           |-- content.min.css
|       |   |           |-- skin.js
|       |   |           |-- skin.min.css
|       |   |           |-- skin.shadowdom.js
|       |   |           \-- skin.shadowdom.min.css
|       |   |-- themes/
|       |   |   \-- silver/
|       |   |       \-- theme.min.js
|       |   |-- license.md
|       |   |-- notices.txt
|       |   |-- tinymce.d.ts
|       |   \-- tinymce.min.js
|       |-- tiptap/
|       |   |-- core/
|       |   |   \-- index.js
|       |   |-- ext-image/
|       |   |   \-- index.js
|       |   |-- ext-link/
|       |   |   |-- index.js
|       |   |   \-- linkify.js
|       |   |-- ext-placeholder/
|       |   |   \-- index.js
|       |   |-- pm/
|       |   |-- prosemirror/
|       |   |   |-- commands.js
|       |   |   |-- history.js
|       |   |   |-- model.js
|       |   |   |-- schema-basic.js
|       |   |   |-- schema-list.js
|       |   |   |-- state.js
|       |   |   |-- transform.js
|       |   |   \-- view.js
|       |   \-- starter-kit/
|       |       \-- index.js
|       \-- wkhtmltox/
|           |-- bin/
|           |   |-- libwkhtmltox.a
|           |   |-- wkhtmltoimage.exe
|           |   |-- wkhtmltopdf.exe
|           |   \-- wkhtmltox.dll
|           \-- include/
|               \-- wkhtmltox/
|                   |-- dllbegin.inc
|                   |-- dllend.inc
|                   |-- image.h
|                   \-- pdf.h
|-- tmp/
|   \-- cert_viewer/
|-- tools/
|   |-- __init__.py
|   |-- cert_viewer.py
|   |-- convert_to_ico.py
|   |-- i18n_builder.py
|   |-- jwt_ui.py
|   |-- tree_exporter.py
|   |-- useful_links.py
|   \-- voica1.py
|-- userdata/
|   \-- i18n_builder/
|       |-- backups/
|       |   \-- autosave_html/
|       |       |-- autosave_html__SNAP_20260115-162207.html
|       |       |-- autosave_html__SNAP_20260115-162749.html
|       |       |-- autosave_html__SNAP_20260115-162801.html
|       |       \-- autosave_html__SNAP_20260115-163907.html
|       |-- published/
|       \-- templates/
|           |-- base.html
|           |-- blank.html
|           |-- dark_solid.html
|           |-- page.html
|           |-- print.html
|           \-- report.html
|-- .gitignore
|-- master.py
|-- package-lock.json
|-- package.json
|-- run.ps1
|-- structure.md
|-- todo.md
|-- tree.ps1
|-- wsgi_accesslog.py
|-- wsgi_prod.py
\-- wsgi.py
