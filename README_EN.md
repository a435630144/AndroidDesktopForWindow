# 掌镜桌面 (ZhangJing Desktop)

*A free, open-source Windows desktop organizer — Android-style icon grid, spring-physics animations and native-feeling desktop widgets that turn your Windows desktop into a phone home screen.*

English | [简体中文](README.md)

> 🚧 **Under active development**: current version **v10a** (installer 5.0.0, first package of the v10 line) with **89 test files / 2308 assertions green**. v10 brings a **widget store** (gitee first, github fallback, sha256 verification; Local / Store tabs in the widget library, first batch: world clock & countdown), an **English UI** (auto / 中文 / English, applied instantly), a **bilingual + refreshed installer**, plus v9's **per-widget appearance settings** (background / opacity / text / accent colour), a **widget plugin platform** (drop in a folder or a zip — see [docs/组件开发指南.md](docs/组件开发指南.md)) and a **phone-style input mode** (single tap launches / long-press menu / multi-select with batch actions / swipe to flip pages). Bug reports and ideas are welcome via Issues.

[![release](https://img.shields.io/badge/release-v5.0.0-blue)](https://github.com/a435630144/PhoneDesktopForWindow/releases) ![platform](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white) ![architecture](https://img.shields.io/badge/architecture-x64-lightgrey) ![python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-6.10-41CD52?logo=qt&logoColor=white) ![tests](https://img.shields.io/badge/tests-89%20files%20passing-brightgreen) [![license](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

---

A third-party desktop organizer and beautifier for Windows with a **phone-style UI and interaction model**: it mounts its own grid layer above the native desktop and replaces native icons with a fully controlled rendering layer — positions, animations, folders and widgets are all yours to define.

Despite the name, this is **far past the prototype stage**: installer, tray residency, crash logging, single-instance guard, auto re-attach watchdog, **89 test files / 2308 assertions**. The product is called **掌镜桌面** (ZhangJing Desktop). The exe name and data dir remain `PhoneDesktop` so existing users' data paths stay valid.

<p align="center"><img src="docs/images/01-desktop.png" width="900" alt="The desktop: Android-style icon grid with anchored widgets"></p>

---

## ✨ Features

| Module | Description |
|---|---|
| 🧭 Icon grid | Android-style grid layout with column count / icon size / DPI awareness; click to select, double-click to open, drag to move |
| 🤏 Slide-to-rearrange | Neighboring icons elastically slide aside while you drag (true spring physics curve), snap precisely to the target cell, and slide back on cancel |
| 📂 Drag-to-merge | Drag an icon onto another to merge into a folder; folder popup uses liquid-glass material with an emergence open/close animation; members can be dragged out / removed |
| 🖱️ Batch operations | Rubber-band multi-select + whole-group dragging |
| 🧩 Desktop widgets | Clock / Sticky notes (editable) / Desktop panel (search · quick folders · disks · recent downloads · weather) / **System monitor** (CPU · memory · disk) / **To-do list** (multi-instance) / **Calendar** (month view with remembered month) / **Weather** (live with cache fallback) / **Music** (controls whatever is playing on this PC, player-agnostic); supports **anchored (non-floating)** mode where widgets join the grid as first-class citizens, with drag-resize and icon mutual displacement |
| 🧩 Widget library | A page inside the settings panel: browse widgets by category, search, and see four-state cards (not added / hidden / on desktop / added) with **live previews rendered by the very same `draw()`** used on the desktop; import or uninstall third-party widget zips, and appearance edits apply immediately |
| 🔀 Two modes | **Organizer mode** (native icons hidden, desktop rendering taken over) / **native mode** (free-floating): one-click switch, and each mode **keeps its own layout** independently |
| 🚀 Dock | A row of app shortcuts, bottom by default (top / left / right, toggleable): spring-scaled hover, drop to append, drag to reorder, drag out to remove; the **grid automatically yields the strip and recomputes columns/rows** |
| 📑 Paging | Automatic paging when icons overflow; page dots + wheel paging, drag to the screen edge to flip. Flips are **whole-page carousel slides** (icons and widgets share one spring scalar, 420 ms critically damped — no leftovers, no drift) |
| 🔄 Desktop sync | Watches the desktop folder (1 s debounce): new files enter automatically, deleted items are cleaned up |
| 🪄 Full takeover | Hides native icons and re-renders from the desktop folder clone, giving complete control over position and style (Route A); can also switch back to effects-only mode |
| 🖥️ Custom desktop context menu | No more losing right-click in organizer mode: new folder/text file, rescan, icon size, display/personalization settings |
| 🛡️ BandGuard daemon | Survives Win+D (show desktop) and explorer restarts — automatically re-mounts |
| ⏱️ System tray | Pause auto-creation / restore native, rescan, panel toggle, autostart, settings |

## 📸 Screenshots

> Every image below is rendered off-screen from the **real widgets** by [`tools/shot_readme.py`](tools/shot_readme.py) — the grid, the glass widgets and the context menus all go through the same drawing code the product runs. No mock-ups. The two animated clips are recorded frame by frame from that same material by [`tools/make_readme_anim.py`](tools/make_readme_anim.py) (HTML timeline + headless screenshots + Pillow).

**Eight desktop widgets**: clock / sticky notes / system monitor / to-do / calendar / weather / desktop panel / music — one glass material and one typographic scale, sized by grid span

<p align="center"><img src="docs/images/02-widgets.png" width="900" alt="The eight desktop widgets"></p>

**Per-widget appearance**: the same clock in three skins. Background colour, opacity, text colour, accent colour and corner radius are all configurable; leave a field empty to follow the theme. The fields apply to every widget, including third-party plugins

<p align="center"><img src="docs/images/03-style.png" width="820" alt="Per-widget appearance settings"></p>

**Widget library**: now a page inside the settings panel — four-state cards with live previews, plus an "Import widget…" button at the footer that takes a ready-made zip; no restart needed

<p align="center"><img src="docs/images/04-widget-center.png" width="900" alt="Widget library inside the settings panel"></p>

**Layout &amp; paging**: columns, icon size, grid origin and flip direction are adjustable, and "per-page auto-arrange" lets each page decide whether it auto-packs or stays free-form

<p align="center"><img src="docs/images/05-settings.png" width="900" alt="Layout and grid settings"></p>

**Phone input mode**: with Settings ▸ Mode ▸ Input set to "Phone", a single tap launches, holding for 450 ms opens the menu, and continuing to drag after the hold turns into a drag. Multi-select puts a checkmark on each icon; right-click opens the batch menu (merge into folder / move to page / delete selected); swiping on empty space flips pages

<p align="center"><img src="docs/images/06-mobile.png" width="900" alt="Phone input mode: multi-select and batch menu"></p>

**Android-style folders**: the icon itself shows up to four member thumbnails (layout adapts to 1 / 2 / 3 / 4 members); tapping opens a glass popup whose grid shrinks with the member count and paginates horizontally once a page is full. Members can be dragged out, desktop icons can be dragged in

<p align="center"><img src="docs/images/07-folder.png" width="900" alt="Android-style folders: thumbnails and the expanded glass popup"></p>

<p align="center"><img src="docs/images/08-folder-open.gif" width="640" alt="Opening a folder: the glass sheet springs out from the icon"></p>

**Android-style paging**: overflowing icons paginate automatically; swipe left/right to flip, with the page dots following along. The wheel and dragging to the screen edge flip too, and each page can independently opt in or out of auto-arrange

<p align="center"><img src="docs/images/09-paging.gif" width="640" alt="Desktop paging: swipe to flip"></p>

## 🛠️ Tech Stack & Dependency Versions

| Dependency | Version | Purpose |
|---|---|---|
| Windows | 10 / 11 (developed on Win11 @125% DPI) | Target OS, x64 |
| Python | ≥ 3.12 (developed on 3.13.12) | Runtime |
| PySide6 | `>=6.6, <6.11` (developed on 6.10.3) | The only third-party runtime dependency |
| PyInstaller | `>=6.0` | Portable build (build-time only) |
| Pillow | `>=10.0` | Icon generation tool (tools/make_icon.py) |
| Inno Setup | 6.7.3+ | Installer build (build-time only) |

- **Pure Win32 API** desktop-layer mounting (`SetWindowPos` + `WorkerW`/`Progman` desktop band, per-pixel alpha hit-testing, layered-window click-through)
- **Zero Qt Designer**: all UI is code-drawn, design tokens centralized in `src/theme.py`
- Animation system: `effects.spring_curve()` custom easing (analytic damped-harmonic-oscillator solution) — not OutBack/OutCubic approximations

## 🚀 Quick Start

### Requirements

- Windows 10 / Windows 11 (developed on Win11 @125% DPI)
- Python 3.12+ (developed on 3.13)

### Install & Run

```powershell
git clone https://github.com/a435630144/PhoneDesktopForWindow.git
cd PhoneDesktopForWindow

# Install dependencies (PySide6 only)
pip install -r requirements.txt

# Run
python main.py
```

Runtime data lives in `%APPDATA%\PhoneDesktop\state.json` (layout, settings, widget visibility).
Self-check: `python main.py --selftest` (launch → screenshot → exit, writes `selftest_report.txt`; the packaged exe accepts `--selftest` too).

> ⚠️ **First-run advice**: familiarize yourself with the tray menu's "Pause auto-creation / restore native" entry — organizer mode takes over desktop icon rendering and can restore the native desktop at any time with one click.

## 📁 Project Structure

```
PhoneDesktopForWindow/
├── main.py                  # Entry: crash hook → single instance → tray → main window → BandGuard
├── requirements.txt         # PySide6==6.10.*
├── assets/                  # App icon
├── docs/                    # User-facing docs
│   ├── 组件开发指南.md        # Widget plugin SDK guide for external developers (Chinese)
│   ├── release_notes/        # Per-release notes
│   └── images/               # README screenshots (script-generated)
├── src/
│   ├── Core mechanics ★
│   │   ├── win32_layer.py    # Desktop-band mounting + native icon hide/restore + z-order utils
│   │   ├── band_guard.py     # Win+D / explorer restart guardian
│   │   ├── desktop_window.py # Main window: grid/drag/marquee/folder/native-icon sync
│   │   └── iconwidget.py     # Icon widget: spring animations + drag payload protocol
│   ├── Pure logic (zero Qt deps, unit-testable)
│   │   ├── grid_flow.py      # Reflow engine (reflow_moves / displace_cells)
│   │   ├── grid_metrics.py   # Grid metrics (origin / cols / rows)
│   │   ├── grid_sizing.py    # Cell size & icon tiers (being reworked in v7)
│   │   ├── drag_merge.py     # Merge / push-away geometry
│   │   └── widget_catalog.py # Widget span catalog
│   ├── UI parts
│   │   ├── folder_popup.py / folder_tint.py    # Folder popup & icon tint
│   │   ├── widget_base.py / widget_layer.py    # Widget base & registry
│   │   ├── dock.py             # Dock (pure inset/hit_index + DockWindow)
│   │   └── widgets/           # Built-in widgets, one directory per widget (clock/notes/panel/monitor/todo/calendar/weather/music)
│   └── Infrastructure
│       ├── storage.py / paths.py / version.py
│       ├── appsource.py / desktop_watch.py / shell_new.py
│       ├── effects.py / theme.py
│       └── settings_dialog.py / add_apps_dialog.py / tray.py / autostart.py
│           / single_instance.py / selftest.py
├── scripts/
│   ├── build_portable.ps1   # PyInstaller onedir → zip (needs pwsh 7)
│   ├── installer.iss        # Inno Setup 6 installer (must be UTF-8 BOM)
│   └── check_docs.py        # Docs consistency check (dead links / duplicate sections / doc-vs-code drift)
├── tests/                   # 89 standalone scripts (no pytest); judge by exit code
│   ├── smoke_test.py        # Headless logic regression (storage/clone/layout)
│   └── test_*.py            # One per contract: reflow, dual mode, hit-testing, popup, widgets…
└── tools/                   # Runtime probes probe*.py + packaged-build verification verify_*.py
```

## 🧪 Testing

```powershell
# Headless logic regression
python tests/smoke_test.py

# Full suite: 89 standalone scripts, no pytest; judge by exit code only
Get-ChildItem tests/test_*.py | ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { "FAILED: $($_.Name)" }
}
```

> Each script ships its own `check()` + summary + exit code. **The closing text differs per file** (`ALL PASSED` / `ALL xxx PASSED` / `ALL PASS`), so never grep for a fixed string to judge success — doing so once mis-reported 41 green files as failures.

`tools/` also contains runtime probes (probe5–probe23: animation visualization, reflow precision, takeover mode, z-order, mouse hit-testing) and packaged-build verification (`verify_frozen.py` / `verify_live.py`). **Probe safety rule: user windows are read-only enumerated — never moved or closed**.

## 📦 Packaging

```powershell
# Portable build (PyInstaller onedir + zip)
pwsh -File scripts/build_portable.ps1

# Installer build (Inno Setup 6, with wizard / desktop shortcut / uninstaller)
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" scripts/installer.iss
```

> ⚠️ PyInstaller output may be **flagged by Windows Defender / third-party antivirus**; add an exclusion or code-sign the binaries. For distribution, prefer the installer package.

## 📚 Documentation

| Document | Contents |
|---|---|
| [docs/组件开发指南.md](docs/组件开发指南.md) | **Widget plugin development guide** (Chinese): build an installable, configurable desktop widget without touching the main program |
| [docs/release_notes/](docs/release_notes/) | Per-release notes |
| [docs/images/](docs/images/) | README screenshots (rendered from real widgets by `tools/shot_readme.py` and friends) |

> Development-process documents (dev log, iteration specs & plans, feedback triage) are kept locally only and are not committed to this repository.

## 📜 Changelog

> Ordered by **installer version**, newest first; the parenthesised tag is the internal build label (see `src/version.py`, also shown at the bottom of the right-click menu). More detail in [`docs/release_notes/`](docs/release_notes/).

### 5.0.1 (v10b) · Fixes the UI language not taking effect · Responsive widget library → [notes](docs/release_notes/5.0.1.md)

- **Fixes the mixed-language UI**: the v10a (5.0.0) packages shipped without the translation dictionaries, so lookups fell back to raw keys like `settings.title` across the interface; this build bundles the tables and adds two regression contracts (frozen-build lookup + packaging), and the self-test now reports table sizes and sample strings
- **Responsive widget library**: two columns only when they fit — a narrow window collapses to a single wider column, no horizontal scrollbar; the Local and Store tabs share the same rules, and the settings window minimum width drops to 600

### 5.0.0 (v10a) · Widget store · English UI · Bilingual installer · Renamed to PhoneDesktop → [notes](docs/release_notes/5.0.0.md)

- **Widget store**: widgets are no longer bundled wholesale — download what you need, gitee first with github / jsDelivr fallback, every package sha256-verified; the widget library splits into **Local / Store** tabs; first batch ships **world clock** and **countdown**; the 8 built-in seed widgets keep working offline and the store never overwrites built-ins
- **English UI**: Settings ▸ General ▸ Interface language (auto / 中文 / English), applied instantly; covers all six settings pages, tray menu & bubbles, desktop context menu, widget library, widget settings and the version string
- **Bilingual installer**: Chinese wizard (self-maintained overlay) + English counterpart, 120% wizard scale, refreshed installer icon and product image
- **Renamed to PhoneDesktop**: exe name, install directory and the `%APPDATA%` data directory all change together; existing data is **migrated automatically on first launch**
- **9 field reports closed**: widget interaction blind spots / Dock drag-in + its own settings page (icon size / corner radius / opacity / hover magnification / drop indicator) / Dock position switch not taking effect / new widgets default to grid mode / dual-mode rename / removed the useless "Restore widgets" button / widget **fill ratio** (no longer fully filled by default) / resize guide lines moved to the card edge / desktop panel rework / **Dock default corner radius shrunk to 12 px** (0–26 adjustable, clamped to half the thickness)

### 4.0.0 (v9a) · Per-widget appearance · Widget plugin platform · Dual input modes → [notes](docs/release_notes/4.0.0.md)

- **Per-widget appearance**: background / opacity / text colour / accent / radius, injected at registration so widgets need zero changes; the library preview uses the very same `draw()` as the desktop
- **Widget plugin platform**: drop in a folder or a zip ([widget plugin guide](docs/组件开发指南.md)); `widget_plugin` validates manifests, blocks zip-slip and isolates namespaces; preview debugger + packaging script + one-click import
- **Widget library merged into the settings panel**: the standalone window's "covered and unclickable" bug disappears structurally; per-page auto-arrange rules, cross-page drops no longer snap back
- **Phone-style interaction**: tap to launch / 450 ms long-press menu / slide-after-long-press becomes a drag / multi-select with batch actions / swipe on empty space to flip pages
- Clock and notes rewritten on the glass base class; widget "hide" and "close" merged into a single "close"

### 3.0.0 (v8a) · Widget library + four new widgets

- Widget registry declared once via `WidgetSpec` (spans / category / form / settings / preview); glass card base class (static glass, no live blur)
- **System monitor** (CPU · memory · disk) / **To-do list** (multi-instance) / **Calendar** (month view with remembered month) / **Weather** (Open-Meteo, live → cache → empty fallback)
- Widget settings dialog driven by `FieldSpec`; dedicated widget library window (categories + search + four-state cards + live preview reusing the desktop `draw()`)

### 2.1.3 (v7e) · 8 field reports + visual batch

- Dwell/push timings moved earlier (450/700→350/470 ms, edge flip 600→360 ms); no bounce on release in free mode; widget context menu follows the mode; widget coords recomputed when switching back to grid
- Auto-arrange truly packs; popup icons 40–56 px with single-point drawing; round edit handles with ≥22 px hit area; widgets-only returns the desktop to the system; dirty-region repaint for a steady 60 fps

### 2.1.2 (v7d) · 10 field reports

- Slider dead-touch debounce / self-drawn row-column Stepper / folder full-page paging / two-level centering of the 3×3 popup / widget span collision / collision preview when dragging out of a folder / two-zone merge decision / edge-hover paging / widgets-only mode / auto-dissolve single-icon folders

### 2.1.1 (v7c) · 4 field reports

- Standalone folder forms for "add app / change colour" (16 presets + auto + custom) / collision shape synced after manual widget resize / single-source default icon size / grid debug readout moved into settings

### 2.1.0 (v7b) · All 17 field reports after v7a closed

- Coexisting dual layouts (grid and free-floating each persist their own; switching never converts or clears) / chained drag displacement into the animation list / the widget's rectangular territory no longer swallows clicks
- Solid combo popup / folder name + size + corner entries / single-icon sizing / takeover by default + widgets mode

### 2.0.0 (v7a) · Two-layer sizing

- `cell_from_native` derives cells from the native icon size, `solve_dims` solves the rest; tiers only change the in-cell ratio (`icon_fit`); row count = pure cropping
- Grid origin is manually placeable

### 1.7.0 (v6g) · Field-reported fixes

- Desktop vanishing after Win+D / preview stacking while dragging a widget / merge hint pushed away / folder popup running off-screen; plus the `app: null` crash and crash-logger ordering

### 1.6.0 (v6c–v6f) · Five rounds of field reports

- Desktop band layer system / registry reverse-reading diagram / eight-handle resize / the real cause of the glass background, 28 fixes in total

### 1.4.0 (v6) · Dual modes & desktop sync

- Dual modes (organizer / native) / widgets in the grid / popup coverage / arrow badge + settings consolidation / redesigned settings + automatic desktop folder sync / wallpaper preserved / Win+D and explorer-restart guardian

### 1.3.0 (v5) · Adaptive grid

- Adaptive GridMetrics / `reflow_moves` displacement list / widget span model / folder popup redesign / paging

## ⚠️ Known Limitations

- Multi-monitor: primary screen only
- Cross-page dragging: limited to the current page's capacity; flip first
- Third-party live wallpapers (e.g. Wallpaper Engine): not specifically adapted
- Antivirus false positives: see packaging notes above

## 📄 License

This project is open-sourced under the **[GPL-3.0](LICENSE)** license: any derivative work must also be released under GPL-3.0, preventing closed-source forks.

## ❤️ Sponsor the Author

If this project helps you, consider buying the author a coffee via Alipay:

<p align="center"><img src="docs/images/sponsor_alipay.jpg" width="320" alt="Alipay QR code"></p>

<p align="center">Scan with Alipay · thank you for the support</p>
