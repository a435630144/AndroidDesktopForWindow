# DesktopOrganizer

*A free, open-source Windows desktop organizer — Android-style icon grid, spring-physics animations and native-feeling desktop widgets that turn your Windows desktop into a phone home screen.*

English | [简体中文](README.md)

> 🚧 **Under active development** (v4 delivered; v5 plan signed off and in progress: adaptive grid / iOS-style local reflow / widget span model / folder popup redesign / paging). Bug reports, ideas and discussions are welcome via Issues. See the [v5 plan doc](指导文档_网格与交互_v5.md) (Chinese).

[![release](https://img.shields.io/badge/release-v0.1.4-blue)](https://github.com/a435630144/PhoneDesktopForWindow/releases) ![platform](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white) ![architecture](https://img.shields.io/badge/architecture-x64-lightgrey) ![python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-6.10-41CD52?logo=qt&logoColor=white) ![tests](https://img.shields.io/badge/tests-28%2B%20passing-brightgreen) [![license](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

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
| 🧩 Desktop widgets | Clock / Sticky notes (editable) / Desktop panel (search · quick folders · disks · recent downloads · weather); supports **anchored (non-floating)** mode where widgets join the grid as first-class citizens |
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
cd AndroidDesktopForWindow

# Install dependencies (PySide6 only)
pip install -r requirements.txt

# Run
python main.py
```

Runtime data lives in `%APPDATA%\DesktopOrganizer\state.json` (layout, settings, widget visibility).
Self-check: `python src/selftest.py` (attached / native_icons_hidden / cloned entry count).

> ⚠️ **First-run advice**: familiarize yourself with the tray menu's "Pause auto-creation / restore native" entry — organizer mode takes over desktop icon rendering and can restore the native desktop at any time with one click.

## 📁 Project Structure

```
AndroidDesktopForWindow/
├── main.py                  # Entry: single instance → tray → main window → BandGuard
├── requirements.txt         # PySide6==6.10.*
├── assets/                  # App icon
├── src/
│   ├── win32_layer.py       # ★ Desktop-band mounting + native icon hide/restore + z-order utils
│   ├── band_guard.py        # ★ Win+D / explorer restart guardian
│   ├── grid_flow.py         # ★ Icon-grid reflow engine (pure logic, zero Qt deps, unit-testable)
│   ├── desktop_window.py    # ★ Main window: grid/drag/marquee/folder/native-icon sync
│   ├── iconwidget.py        # ★ Icon widget: multi-property spring animations + drag payload protocol
│   ├── folder_popup.py      # Folder popup: liquid glass + zoom emergence animation
│   ├── effects.py           # Animation toolbox: glass backdrop/spring curve/reduced-motion
│   ├── theme.py             # Design tokens (dark + GLASS parameters)
│   ├── storage.py           # state.json persistence + desktop clone seeding
│   ├── appsource.py         # Desktop file scan/clone/stable id/icon extraction
│   ├── widget_base.py       # Widget base class (interactive focus policy + anchored/floating modes)
│   ├── widget_layer.py      # Widget registry and default placement
│   ├── widgets_clock.py     # Clock (display-only, NOACTIVATE)
│   ├── widgets_notes.py     # Sticky notes (interactive, editable)
│   ├── widgets_panel.py     # Desktop panel (search/folders/disks/downloads/weather)
│   └── settings_dialog.py / add_apps_dialog.py / tray.py / autostart.py …
├── scripts/
│   ├── build_portable.ps1   # PyInstaller onedir → zip
│   └── installer.iss        # Inno Setup 6 installer
└── tests/
    ├── smoke_test.py        # Headless logic regression (storage/clone/layout)
    └── test_grid_flow.py    # Grid reflow engine unit tests (28 assertions)
```

## 🧪 Testing

```powershell
python tests/smoke_test.py      # Headless logic regression
python tests/test_grid_flow.py  # Reflow engine unit tests (28 assertions)
```

`tools/` also contains runtime probes (probe14–16: animation visualization, reflow precision, takeover-mode verification) and packaged-build verification (`verify_frozen.py`). **Probe safety rule: user windows are read-only enumerated — never moved or closed** (see DEVLOG §7.2).

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
| [DEVLOG.md](DEVLOG.md) | **Development log (authoritative)**: architecture decisions, pitfall ledger, test system, packaging & delivery, known-issues cheat sheet |
| [指导文档_网格与交互_v5.md](指导文档_网格与交互_v5.md) | **Current-stage plan**: adaptive grid / iOS-style local reflow / widget span model / folder popup redesign — algorithm design and M1–M7 implementation plan (includes an AI handover guide) |
| [design.md](design.md) | Phone-home-screen design doc (live reflow + anchored widgets) |
| [DESKBOX_REFERENCE.md](DESKBOX_REFERENCE.md) | DeskBox research report and lessons applicable to this project |

## 🗺️ Roadmap (v5, plan signed off)

- [ ] **M1** Adaptive grid: GridMetrics derives columns/rows from viewport ÷ icon size, evenly centered to fill the work area
- [ ] **M2** `reflow_moves` displacement list: only icons between old and new positions move; empty cells are exact landing spots
- [ ] **M3** Widget span model: `WIDGET_CATALOG` treats grid span as first-class; collision = visual bounds
- [ ] **M4** Unified displacement engine: remove full rebuilds; all position changes become spring animations
- [ ] **M5** Folder popup redesign: scrim + top of desktop band + rename + background color + "+" add panel
- [ ] **M6** Paging: page dots + wheel paging when icons overflow one screen (iOS-style)
- [ ] **M7** Full regression + package v5
- [ ] Later: native desktop capability parity (F2 rename / Delete to recycle bin / clipboard), Ctrl+Z undo, multi-monitor, expanded widget catalog

## ⚠️ Known Limitations

- Multi-monitor: primary screen only this iteration (planned for v5)
- Cross-page dragging: disabled until paging ships (v5 M6)
- Icon capacity: limited to one screen's grid capacity (lifted with paging)
- Antivirus false positives: see packaging notes above

## 📄 License

This project is open-sourced under the **[GPL-3.0](LICENSE)** license — same as DeskBox: any derivative work must also be released under GPL-3.0, preventing closed-source forks.
