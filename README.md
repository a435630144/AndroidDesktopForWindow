# DesktopOrganizer

*一款免费、开源的 Windows 桌面整理工具——安卓式图标网格、弹簧动效与原生质感的小组件，把你的 Windows 桌面变成手机桌面。*

[English](README_EN.md) | 简体中文

> 🚧 **项目处于活跃开发中**（v4 已交付，v5 方案已签收正在实施：网格自适应 / iOS 局部让位 / 小组件跨度化 / 文件夹弹窗重做 / 分页）。问题反馈与想法欢迎通过 Issues 讨论，实施计划见 [指导文档_网格与交互_v5.md](指导文档_网格与交互_v5.md)。

![release](https://img.shields.io/badge/release-v4.0-blue) ![platform](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white) ![architecture](https://img.shields.io/badge/architecture-x64-lightgrey) ![python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-6.10-41CD52?logo=qt&logoColor=white) ![tests](https://img.shields.io/badge/tests-28%2B%20passing-brightgreen) ![license](https://img.shields.io/badge/license-GPLv3-blue)

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
| 🧩 桌面小组件 | 时钟 / 便签（可编辑）/ 桌面面板（搜索 · 快捷文件夹 · 磁盘 · 最近下载 · 天气）；支持**锚定（非悬浮）**模式，融入网格成为一等公民 |
| 🪄 全量接管 | 隐藏原生图标、按桌面文件夹克隆渲染，彻底掌控位置与样式（路线 A）；也可切回仅动效模式 |
| 🖥️ 自绘右键菜单 | 整理模式下桌面右键不丢失：新建文件夹/文本文档、重新扫描、图标大小、显示/个性化设置 |
| 🛡️ BandGuard 守护 | Win+D 显示桌面、explorer 崩溃重启后自动重挂 |
| ⏱️ 托盘常驻 | 暂停自动创建/恢复原生、重新扫描、面板开关、开机自启、设置 |

## 🛠️ 技术栈与依赖版本

| 依赖 | 版本 | 用途 |
|---|---|---|
| Windows | 10 / 11（开发目标 Win11 @125% DPI） | 目标系统，x64 |
| Python | ≥ 3.12（开发用 3.13.12） | 运行时 |
| PySide6 | **6.10.3**（`requirements.txt` 锁 `==6.10.*`） | 唯一第三方运行时依赖 |
| PyInstaller | 6.x | 打包便携版（仅构建需要） |
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
git clone https://github.com/a435630144/AndroidDesktopForWindow.git
cd AndroidDesktopForWindow

# 安装依赖（仅 PySide6）
pip install -r requirements.txt

# 运行
python main.py
```

运行时数据在 `%APPDATA%\DesktopOrganizer\state.json`（布局、设置、小组件显隐）。
自检：`python src/selftest.py`（attached / native_icons_hidden / 克隆条目数）。

> ⚠️ **首次使用建议**：先在托盘图标右键熟悉「暂停自动创建/恢复原生」入口——整理模式会接管桌面图标显示，随时可一键恢复原生桌面。

## 📁 项目结构

```
AndroidDesktopForWindow/
├── main.py                  # 入口：单实例 → 托盘 → 主窗口 → BandGuard
├── requirements.txt         # PySide6==6.10.*
├── assets/                  # 应用图标
├── src/
│   ├── win32_layer.py       # ★ 桌面层挂载 + 原生图标隐藏/恢复 + z-order 工具
│   ├── band_guard.py        # ★ Win+D / explorer 重启守护
│   ├── grid_flow.py         # ★ 图标网格让位引擎（纯逻辑，零 Qt 依赖，可单测）
│   ├── desktop_window.py    # ★ 主窗口：网格/拖拽/框选/文件夹/原生图标同步
│   ├── iconwidget.py        # ★ 图标部件：多属性弹簧动效 + 拖动 payload 协议
│   ├── folder_popup.py      # 文件夹弹窗：液态玻璃 + zoom 涌现动画
│   ├── effects.py           # 动效工具箱：玻璃背板/弹簧曲线/reduced-motion
│   ├── theme.py             # 设计 tokens（深色 + GLASS 玻璃参数）
│   ├── storage.py           # state.json 布局/设置持久化 + 桌面克隆播种
│   ├── appsource.py         # 桌面文件扫描/克隆/稳定 id/图标提取
│   ├── widget_base.py       # 小组件基类（interactive 焦点策略 + 锚定/悬浮双形态）
│   ├── widget_layer.py      # 小组件注册与默认落位
│   ├── widgets_clock.py     # 时钟（纯展示，NOACTIVATE）
│   ├── widgets_notes.py     # 便签（interactive，可输入）
│   ├── widgets_panel.py     # 桌面面板（搜索/文件夹/磁盘/下载/天气）
│   └── settings_dialog.py / add_apps_dialog.py / tray.py / autostart.py …
├── scripts/
│   ├── build_portable.ps1   # PyInstaller onedir → zip
│   └── installer.iss        # Inno Setup 6 安装包
└── tests/
    ├── smoke_test.py        # 无头逻辑回归（存储/克隆/布局）
    └── test_grid_flow.py    # 网格让位引擎单测（28 条）
```

## 🧪 测试

```powershell
python tests/smoke_test.py      # 无头逻辑回归
python tests/test_grid_flow.py  # 让位引擎单测（28 条断言）
```

`tools/` 下另有运行态探针（probe14–16：动效可视化、让位精度、接管模式实机验证）与打包版验证（`verify_frozen.py`）。**探针安全铁律：只读枚举用户窗口、绝不移动/关闭任何用户窗口**（见 DEVLOG §7.2）。

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
| [DEVLOG.md](DEVLOG.md) | **开发日志（权威文档）**：架构决策、踩坑台账、测试体系、打包交付、已知坑速查表 |
| [指导文档_网格与交互_v5.md](指导文档_网格与交互_v5.md) | **当前阶段方案**：网格自适应 / iOS 局部让位 / 组件跨度化 / 文件夹弹窗重做的算法设计与 M1–M7 实施计划（含 AI 交接说明） |
| [design.md](design.md) | 手机桌面化设计文档（实时让位 + 锚定小组件） |
| [DESKBOX_REFERENCE.md](DESKBOX_REFERENCE.md) | DeskBox 调研报告与本项目可借鉴点 |

## 🗺️ 路线图（v5，方案已签收）

- [ ] **M1** 网格自适应：GridMetrics 按视口 ÷ 图标大小自动算行列，四边等距精确铺满
- [ ] **M2** `reflow_moves` 位移清单：只有新旧位置之间的图标动，空格精确落点
- [ ] **M3** 小组件跨度化：`WIDGET_CATALOG` 以格跨度为一等公民，碰撞 = 视觉边界
- [ ] **M4** 位移引擎统一：去全量重建化，位置变化一律弹簧动画
- [ ] **M5** 文件夹弹窗重做：幕布 + 桌面带内最顶 + 重命名 + 背景色 + 「＋」添加
- [ ] **M6** 分页：图标多到放不下时页点 + 滚轮翻页（iOS 风）
- [ ] **M7** 全量回归 + 打包 v5
- [ ] 后续：整理模式原生能力补齐（F2 重命名 / Delete 回收站 / 剪贴板）、Ctrl+Z 撤销、多显示器、组件目录扩充

## ⚠️ 已知限制

- 多显示器：本期仅主屏（v5 规划中）
- 跨页拖动：分页上线前禁止（v5 M6）
- 图标上限：单页网格容量内（分页后解除）
- 杀软误报：见上文打包说明

## 📄 许可证

本项目基于 **[GPL-3.0](LICENSE)** 许可证开源——与 DeskBox 同款：任何基于本项目的衍生作品必须同样以 GPL-3.0 开源，防止闭源套壳。
