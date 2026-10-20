# DesktopOrganizer

*A free, open-source Windows desktop organizer — Android-style icon grid, spring-physics animations and native-feeling desktop widgets that turn your Windows desktop into a phone home screen.*

English | [简体中文](README.md)

> 🚧 **Under active development**: current version **v7a** (installer 2.0.0, first package of the v7 line) with all 49 test files green; **v7 is in implementation** (two-layer sizing / coexisting dual layouts / drag & hit-testing rework / folder & overlay polish), B1 sizing foundation is delivered. Bug reports and ideas are welcome via Issues — current spec: [docs/指导文档_v7.md](docs/指导文档_v7.md), plan: [docs/实施计划_v7.md](docs/实施计划_v7.md) (both Chinese).

[![release](https://img.shields.io/badge/release-v2.0.0-blue)](https://github.com/a435630144/PhoneDesktopForWindow/releases) ![platform](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white) ![architecture](https://img.shields.io/badge/architecture-x64-lightgrey) ![python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-6.10-41CD52?logo=qt&logoColor=white) ![tests](https://img.shields.io/badge/tests-49%20files%20passing-brightgreen) [![license](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

---

A third-party desktop organizer / beautifier for Windows (demo), in the spirit of Tencent Desktop Manager. It mounts its own grid layer above the native desktop and replaces native icons with a fully controlled rendering layer: positions, animations, folders, and widgets are all yours to define.

---

## ✨ Features

| Module | Description |
|---|---|
| 🧭 Icon grid | Android-style grid layout with column count / icon size / DPI awareness; click to select, double-click to open, drag to move |
| 🤏 Slide-to-rearrange | Neighboring icons elastically slide aside while you drag (true spring physics curve), snap precisely to the target cell, and slide back on cancel |
| 📂 Drag-to-merge | Drag an icon onto another to merge into a folder; folder popup uses liquid-glass material with an emergence open/close animation; members can be dragged out / removed |
| 🖱️ Batch operations | Rubber-band multi-select + whole-group dragging |
| 🧩 Desktop widgets | Clock / Sticky notes (editable) / Desktop panel (search · quick folders · disks · recent downloads · weather); supports **anchored (non-floating)** mode where widgets join the grid as first-class citizens, with drag-resize and icon mutual displacement |
| 🔀 Two modes | **Organizer mode** (native icons hidden, desktop rendering taken over) / **native mode** (free-floating): one-click switch, and each mode **keeps its own layout** independently |
| 📑 Paging | Automatic paging when icons overflow; page dots + wheel paging, drag to the screen edge to flip |
| 🔄 Desktop sync | Watches the desktop folder (1 s debounce): new files enter automatically, deleted items are cleaned up |
| 🪄 Full takeover | Hides native icons and re-renders from the desktop folder clone, giving complete control over position and style (Route A); can also switch back to effects-only mode |
| 🖥️ Custom desktop context menu | No more losing right-click in organizer mode: new folder/text file, rescan, icon size, display/personalization settings |
| 🛡️ BandGuard daemon | Survives Win+D (show desktop) and explorer restarts — automatically re-mounts |
| ⏱️ System tray | Pause auto-creation / restore native, rescan, panel toggle, autostart, settings |

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

Runtime data lives in `%APPDATA%\DesktopOrganizer\state.json` (layout, settings, widget visibility).
Self-check: `python main.py --selftest` (launch → screenshot → exit, writes `selftest_report.txt`; the packaged exe accepts `--selftest` too).

> ⚠️ **First-run advice**: familiarize yourself with the tray menu's "Pause auto-creation / restore native" entry — organizer mode takes over desktop icon rendering and can restore the native desktop at any time with one click.

## 📁 Project Structure

```
PhoneDesktopForWindow/
├── main.py                  # Entry: crash hook → single instance → tray → main window → BandGuard
├── requirements.txt         # PySide6==6.10.*
├── assets/                  # App icon
├── docs/                    # Specs & plans (see Documentation)
│   ├── 指导文档_v7.md / 实施计划_v7.md
│   ├── DESKBOX_REFERENCE.md
│   └── archive/             # Specs of finished iterations (frozen, reference only)
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
│   │   └── widgets_clock.py / widgets_notes.py / widgets_panel.py
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
├── tests/                   # 49 standalone scripts (no pytest); judge by exit code
│   ├── smoke_test.py        # Headless logic regression (storage/clone/layout)
│   └── test_*.py            # One per contract: reflow, dual mode, hit-testing, popup, widgets…
└── tools/                   # Runtime probes probe*.py + packaged-build verification verify_*.py
```

## 🧪 Testing

```powershell
# Headless logic regression
python tests/smoke_test.py

# Full suite: 49 standalone scripts, no pytest; judge by exit code only
Get-ChildItem tests/test_*.py | ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { "FAILED: $($_.Name)" }
}
```

> Each script ships its own `check()` + summary + exit code. **The closing text differs per file** (`ALL PASSED` / `ALL xxx PASSED` / `ALL PASS`), so never grep for a fixed string to judge success — doing so once mis-reported 41 green files as failures (DEVLOG §7.3).

`tools/` also contains runtime probes (probe5–probe23: animation visualization, reflow precision, takeover mode, z-order, mouse hit-testing) and packaged-build verification (`verify_frozen.py` / `verify_live.py`). **Probe safety rule: user windows are read-only enumerated — never moved or closed** (see DEVLOG §7.2).

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
| [docs/README.md](docs/README.md) | **Documentation map**: three layers (entry / specs / archive), doc lifecycle rules and the pre-commit self-check |
| [DEVLOG.md](DEVLOG.md) | **Development log (authoritative ledger)**: architecture decisions, Day 1–16 timeline, pitfall ledger, test system, packaging & delivery |
| [HANDOVER.md](HANDOVER.md) | **Handover manual**: module map, core mechanics, safety rules, open items, **§10 documentation standards**, takeover checklist |
| [docs/指导文档_v7.md](docs/指导文档_v7.md) | **Current spec** (Chinese): v7 — two-layer sizing / coexisting dual layouts / drag & hit-testing / folder & overlays |
| [docs/实施计划_v7.md](docs/实施计划_v7.md) | **Current implementation plan** (Chinese): B1 split into T1–T15 |
| [docs/DESKBOX_REFERENCE.md](docs/DESKBOX_REFERENCE.md) | DeskBox research report and lessons applicable to this project (Chinese) |
| [docs/archive/](docs/archive/README.md) | **Archive**: Phase 1 / v5 / v6g specs and plans (frozen, reference only) |

## 🗺️ Roadmap

**Delivered** (short version tag lives in `src/version.py`; the build timestamp is shown at the bottom of the right-click menu):

| Version | Highlights | Installer |
|---|---|---|
| v5 | Adaptive grid / iOS-style local reflow / widget span model / folder popup redesign / paging | 1.3.0 |
| v6 → v6g | Two modes (organizer / native) / widgets in grid / desktop folder sync / wallpaper preserved / Win+D guardian, plus 14 field-reported fixes | 1.7.0 |

**v7 in progress** (spec: [docs/指导文档_v7.md](docs/指导文档_v7.md), plan: [docs/实施计划_v7.md](docs/实施计划_v7.md)):

- [x] **B1** Sizing foundation: `cell_from_native` derives cells from the native icon size, tiers only change in-cell ratio (`icon_fit`), row count = pure cropping, grid origin is manually placeable (source `v7a`, not built yet)
- [ ] **B2** Coexisting layouts: grid and free-floating each persist their own layout; switching never converts or clears
- [ ] **B3** Dragging: widget hover judged by frame / center-merge vs outer-ring push-away zones / hint timing
- [ ] **B4** Hit-testing: per-pixel `WM_NCHITTEST` for widgets and popups so transparent areas stop swallowing clicks
- [ ] **B5** Folder & visual polish: icon proportions, popup edge placement, edit handles
- [ ] **B6** Overlays & paging: custom page creation, combo popup styling
- [ ] **v7.1** (deferred): widget hub / widget store (modular ecosystem)

Further out: native capability parity (F2 rename / Delete to recycle bin / clipboard), Ctrl+Z undo, multi-monitor.

## ⚠️ Known Limitations

- Multi-monitor: primary screen only
- Cross-page dragging: limited to the current page's capacity; flip first
- Third-party live wallpapers (e.g. Wallpaper Engine): not specifically adapted
- Antivirus false positives: see packaging notes above

## 📄 License

This project is open-sourced under the **[GPL-3.0](LICENSE)** license — same as DeskBox: any derivative work must also be released under GPL-3.0, preventing closed-source forks.
