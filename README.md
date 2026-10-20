# DesktopOrganizer

*一款免费、开源的 Windows 桌面整理工具——安卓式图标网格、弹簧动效与原生质感的小组件，把你的 Windows 桌面变成手机桌面。*

[English](README_EN.md) | 简体中文

> 🚧 **项目处于活跃开发中**：当前版本 **v7a**（安装包 2.0.0，v7 迭代的第一个包），51 个测试文件全绿；**v7 正在实施**（尺寸两层解耦 / 双布局并存 / 拖拽与命中系统重做 / 文件夹与浮层细节），B1 尺寸地基已交付。问题与想法欢迎 Issues —— 当前规格见 [docs/指导文档_v7.md](docs/指导文档_v7.md)，实施计划见 [docs/实施计划_v7.md](docs/实施计划_v7.md)。

[![release](https://img.shields.io/badge/release-v2.0.0-blue)](https://github.com/a435630144/PhoneDesktopForWindow/releases) ![platform](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white) ![architecture](https://img.shields.io/badge/architecture-x64-lightgrey) ![python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-6.10-41CD52?logo=qt&logoColor=white) ![tests](https://img.shields.io/badge/tests-51%20files%20passing-brightgreen) [![license](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

---

一个类「腾讯桌面整理」的第三方桌面美化整理软件（Demo）。它在本机桌面之上挂载一层自有网格，把原生图标替换为完全可控的渲染层：位置、动效、文件夹、小组件，全部由你定义。

---

## ✨ 功能特性

| 模块 | 说明 |
|---|---|
| 🧭 图标网格 | 安卓式网格布局，列数/图标尺寸/DPI 全感知，单击选中、双击打开、拖动移动 |
| 🤏 滑动让位 | 拖动图标时相邻图标弹性滑动让位（真弹簧物理曲线），落点精确到目标格，可取消滑回 |
| 📂 拖拽合并 | 图标拖到图标上悬停即合并成文件夹；文件夹弹窗为液态玻璃材质 + 涌现开合动画，成员可拖出/移出 |
| 🖱️ 批量操作 | 橡皮筋框选 + 多选整体拖动 |
| 🧩 桌面小组件 | 时钟 / 便签（可编辑）/ 桌面面板（搜索 · 快捷文件夹 · 磁盘 · 最近下载 · 天气）；支持**锚定（非悬浮）**模式，融入网格成为一等公民，可拖拽缩放、与图标互相让位 |
| 🔀 双模式 | **整理模式**（隐藏原生图标、接管桌面渲染）/ **原生模式**（无界自由摆放）：一键切换，两种布局**各自独立保存**，互不清空 |
| 📑 分页 | 图标溢出自动分页，页点 + 滚轮翻页，拖到屏幕边缘翻页 |
| 🔄 桌面同步 | 监听桌面目录增删改（1s debounce），新文件自动入场、删除项自动清理 |
| 🪄 全量接管 | 隐藏原生图标、按桌面文件夹克隆渲染，彻底掌控位置与样式（路线 A）；也可切回仅动效模式 |
| 🖥️ 自绘右键菜单 | 整理模式下桌面右键不丢失：新建文件夹/文本文档、重新扫描、图标大小、显示/个性化设置 |
| 🛡️ BandGuard 守护 | Win+D 显示桌面、explorer 崩溃重启后自动重挂 |
| ⏱️ 托盘常驻 | 暂停自动创建/恢复原生、重新扫描、面板开关、开机自启、设置 |

## 🛠️ 技术栈与依赖版本

| 依赖 | 版本 | 用途 |
|---|---|---|
| Windows | 10 / 11（开发目标 Win11 @125% DPI） | 目标系统，x64 |
| Python | ≥ 3.12（开发用 3.13.12） | 运行时 |
| PySide6 | `>=6.6, <6.11`（开发锁定 6.10.3） | 唯一第三方运行时依赖 |
| PyInstaller | `>=6.0` | 打包便携版（仅构建需要） |
| Pillow | `>=10.0` | 图标生成工具（tools/make_icon.py） |
| Inno Setup | 6.7.3+ | 制作安装包（仅构建需要） |

- **纯 Win32 API** 桌面层挂载（`SetWindowPos` + `WorkerW`/`Progman` 桌面带、逐像素 alpha 命中测试、分层窗口穿透）
- **零 Qt Designer**：UI 全代码绘制，设计 tokens 集中在 `src/theme.py`
- 动效体系：`effects.spring_curve()` 自定义缓动（阻尼谐振子解析解），非 OutBack/OutCubic 近似

## 🚀 快速开始

### 环境要求

- Windows 10 / Windows 11（开发目标：Win11 @125% DPI）
- Python 3.12+（开发使用 3.13）

### 安装与运行

```powershell
git clone https://github.com/a435630144/PhoneDesktopForWindow.git
cd PhoneDesktopForWindow

# 安装依赖（仅 PySide6）
pip install -r requirements.txt

# 运行
python main.py
```

运行时数据在 `%APPDATA%\DesktopOrganizer\state.json`（布局、设置、小组件显隐）。
自检：`python main.py --selftest`（启动 → 截图 → 退出，产出 `selftest_report.txt`；打包后的 exe 同样支持 `--selftest`）。

> ⚠️ **首次使用建议**：先在托盘图标右键熟悉「暂停自动创建/恢复原生」入口——整理模式会接管桌面图标显示，随时可一键恢复原生桌面。

## 📁 项目结构

```
PhoneDesktopForWindow/
├── main.py                  # 入口：崩溃钩子 → 单实例 → 托盘 → 主窗口 → BandGuard
├── requirements.txt         # PySide6==6.10.*
├── assets/                  # 应用图标
├── docs/                    # 规格与计划（见「文档索引」）
│   ├── 指导文档_v7.md / 实施计划_v7.md
│   ├── DESKBOX_REFERENCE.md
│   └── archive/             # 已完结迭代的规格（冻结，仅供回溯）
├── src/
│   ├── 核心机制 ★
│   │   ├── win32_layer.py    # 桌面层挂载 + 原生图标隐藏/恢复 + z-order 工具
│   │   ├── band_guard.py     # Win+D / explorer 重启守护
│   │   ├── desktop_window.py # 主窗口：网格/拖拽/框选/文件夹/原生图标同步
│   │   └── iconwidget.py     # 图标部件：多属性弹簧动效 + 拖动 payload 协议
│   ├── 纯逻辑（零 Qt 依赖，可单测）
│   │   ├── grid_flow.py      # 让位引擎（reflow_moves / displace_cells）
│   │   ├── grid_metrics.py   # 网格度量（origin / cols / rows）
│   │   ├── grid_sizing.py    # cell 尺寸与图标档位（v7 改造中）
│   │   ├── drag_merge.py     # 合并 / 挤走几何判定
│   │   └── widget_catalog.py # 组件跨度目录
│   ├── UI 部件
│   │   ├── folder_popup.py / folder_tint.py    # 文件夹弹窗与图标底色
│   │   ├── widget_base.py / widget_layer.py    # 组件基类与注册
│   │   └── widgets_clock.py / widgets_notes.py / widgets_panel.py
│   └── 基础设施
│       ├── storage.py / paths.py / version.py
│       ├── appsource.py / desktop_watch.py / shell_new.py
│       ├── effects.py / theme.py
│       └── settings_dialog.py / add_apps_dialog.py / tray.py / autostart.py
│           / single_instance.py / selftest.py
├── scripts/
│   ├── build_portable.ps1   # PyInstaller onedir → zip（需 pwsh 7）
│   ├── installer.iss        # Inno Setup 6 安装包（必须 UTF-8 BOM）
│   └── check_docs.py        # 文档一致性自检（死链/重复章节/文档与代码数值漂移）
├── tests/                   # 49 个独立可跑脚本（无 pytest），判据看退出码
│   ├── smoke_test.py        # 无头逻辑回归（存储/克隆/布局）
│   └── test_*.py            # 每条契约一份：让位引擎、双模式、命中、弹窗、组件…
└── tools/                   # 运行态探针 probe*.py + 打包验证 verify_*.py
```

## 🧪 测试

```powershell
# 无头逻辑回归
python tests/smoke_test.py

# 全量单测：49 个独立脚本，无 pytest；判据只看退出码
Get-ChildItem tests/test_*.py | ForEach-Object {
    python $_.FullName
    if ($LASTEXITCODE -ne 0) { "FAILED: $($_.Name)" }
}
```

> 每个测试脚本自带 `check()` + 汇总 + 退出码。**输出文案各文件不统一**（`ALL PASSED` / `ALL xxx PASSED` / `ALL PASS`），所以别用 grep 固定文案判通过——曾经因此把 41 个全绿文件误报成失败（DEVLOG §7.3）。

`tools/` 下另有运行态探针（probe5–probe23：动效可视化、让位精度、接管模式、层序、鼠标命中）与打包版验证（`verify_frozen.py` / `verify_live.py`）。**探针安全铁律：只读枚举用户窗口、绝不移动/关闭任何用户窗口**（见 DEVLOG §7.2）。

## 📦 打包

```powershell
# 便携版（PyInstaller onedir + zip）
pwsh -File scripts/build_portable.ps1

# 安装版（Inno Setup 6，含安装向导/桌面快捷方式/卸载入口）
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" scripts/installer.iss
```

> ⚠️ PyInstaller 产物可能被 Windows Defender / 第三方杀软**误报**，需加白名单或代码签名；分发时优先用安装包形态。

## 📚 文档索引

| 文档 | 内容 |
|---|---|
| [docs/README.md](docs/README.md) | **文档地图**：三层结构（入口 / 规格 / 归档）、文档生命周期规则与提交前自检 |
| [DEVLOG.md](DEVLOG.md) | **开发日志（权威账本）**：架构决策、Day 1–16 时间线、踩坑台账、测试体系、打包交付 |
| [HANDOVER.md](HANDOVER.md) | **接手手册**：模块地图、核心机制、安全铁律、开放项、**§10 文档更新标准**、接手检查清单 |
| [docs/指导文档_v7.md](docs/指导文档_v7.md) | **当前规格**：v7 —— 尺寸两层模型 / 双布局并存 / 拖拽与命中 / 文件夹与浮层（21 项反馈 → A–G 归组） |
| [docs/实施计划_v7.md](docs/实施计划_v7.md) | **当前实施计划**：B1 拆 T1–T15，每卡含文件 / 签名 / 验证命令 / 预期红 |
| [docs/反馈研判_v7_1.md](docs/反馈研判_v7_1.md) | **v7a 实机 17 项反馈的研判**：哪些是尚未开工的批次、哪些是真 bug、批次重组与 3 个待拍板决策 |
| [docs/DESKBOX_REFERENCE.md](docs/DESKBOX_REFERENCE.md) | 竞品 DeskBox 调研与可借鉴点分级清单 |
| [docs/archive/](docs/archive/README.md) | **归档区**：Phase 1 / v5 / v6g 的规格与计划（已冻结，仅供回溯） |

## 🗺️ 路线图

**已交付**（版本短标签见 `src/version.py`，界面右键菜单底部可看构建时刻）：

| 版本 | 内容 | 安装包 |
|---|---|---|
| v5 | 网格自适应 / iOS 局部让位 / 组件跨度化 / 文件夹弹窗重做 / 分页 | 1.3.0 |
| v6 → v6g | 双模式（整理 / 原生）/ 组件入网格 / 桌面目录同步 / 壁纸保留 / Win+D 守护，以及 14 项实机反馈修复 | 1.7.0 |

**v7 实施中**（规格 [docs/指导文档_v7.md](docs/指导文档_v7.md)，计划 [docs/实施计划_v7.md](docs/实施计划_v7.md)）：

- [x] **B1** 尺寸地基：`cell_from_native` 由原生图标推导格子、档位只改格内占比（`icon_fit`）、行数=纯裁剪、网格原点可手动定位（源码 `v7a`，待出包）
- [x] **B2** 双布局并存：网格与无界各自保存，切换零换算零清空（含图标尺寸单源，`icon_px` 退役）
- [ ] **B3** 拖拽：组件 hover 按 frame 判定 / 中心合并 · 外环让位双区模型 / 提示时机
- [ ] **B4** 命中系统：组件与弹窗补逐像素 `WM_NCHITTEST`，透明区不再吞点击
- [ ] **B5** 文件夹与视觉细节：图标比例、弹窗贴边、编辑控制点
- [ ] **B6** 浮层与分页：自定义新增分页、下拉弹层配色
- [ ] **v7.1**（延后）：组件中心 / 组件商店（模块化组件生态）

更远：整理模式原生能力补齐（F2 重命名 / Delete 回收站 / 剪贴板）、Ctrl+Z 撤销、多显示器。

## ⚠️ 已知限制

- 多显示器：本期仅主屏
- 跨页拖动：受当前页容量限制，需先翻页
- 第三方动态壁纸（如 Wallpaper Engine）：未专门适配
- 杀软误报：见上文打包说明

## 📄 许可证

本项目基于 **[GPL-3.0](LICENSE)** 许可证开源——与 DeskBox 同款：任何基于本项目的衍生作品必须同样以 GPL-3.0 开源，防止闭源套壳。
