# DesktopOrganizer

*一款把 Windows 桌面变成手机桌面的桌面美化整理工具——安卓式图标网格、弹簧动效与原生质感的小组件。*

[English](README_EN.md) | 简体中文

> 🚧 **项目处于活跃开发中**：当前版本 **v9a**（安装包 4.0.0，v9 迭代第一个包），**86 个测试文件 / 约 2000 条断言全绿**；v7 的 39 条实机反馈与 v8 的组件中心全部闭环。v9 首批带来**全组件外观自定义**（背景色/透明度/文字色/强调色）、**组件插件平台**（写一个目录或 zip 就能装进桌面，见 [docs/组件开发指南.md](docs/组件开发指南.md)）、**组件库并入设置面板**、**每页独立排序规则**，以及**手机式双交互**（单击启动 / 长按菜单 / 多选批量 / 滑动翻页）。问题与想法欢迎 Issues —— 当前规格见 [docs/指导文档_v9.md](docs/指导文档_v9.md)，实施计划见 [docs/实施计划_v9.md](docs/实施计划_v9.md)。

[![release](https://img.shields.io/badge/release-v4.0.0-blue)](https://github.com/a435630144/PhoneDesktopForWindow/releases) ![platform](https://img.shields.io/badge/Windows-10%2F11-0078D6?logo=windows&logoColor=white) ![architecture](https://img.shields.io/badge/architecture-x64-lightgrey) ![python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white) ![PySide6](https://img.shields.io/badge/PySide6-6.10-41CD52?logo=qt&logoColor=white) ![tests](https://img.shields.io/badge/tests-79%20files%20passing-brightgreen) [![license](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

---

一款**界面语言与操作逻辑都走手机路线**的第三方桌面美化整理软件：它在桌面之上挂载一层自有网格，把原生图标替换为完全可控的渲染层——位置、动效、文件夹、小组件，全部由你定义。

开发深度上它**早已不是原型 Demo**：安装包 + 托盘常驻 + 崩溃日志 + 单实例 + 自动重挂守护，**86 个测试文件 / 约 2000 条断言**，外加完整的开发日志与接手手册（见 [DEVLOG.md](DEVLOG.md) / [HANDOVER.md](HANDOVER.md)）。v10 起产品名统一为 **PhoneDesktop**（exe 名、安装目录、`%APPDATA%` 数据目录一起改；老用户的数据目录在首次启动时**一次性自动迁移**，布局与设置不丢）。

<p align="center"><img src="docs/images/01-desktop.png" width="900" alt="桌面总览：安卓式网格图标 + 锚定小组件"></p>

---

## ✨ 功能特性

| 模块 | 说明 |
|---|---|
| 🧭 图标网格 | 安卓式网格布局，列数/图标尺寸/DPI 全感知，单击选中、双击打开、拖动移动 |
| 🤏 滑动让位 | 拖动图标时相邻图标弹性滑动让位（真弹簧物理曲线），落点精确到目标格，可取消滑回 |
| 📂 拖拽合并 | 图标拖到图标上悬停即合并成文件夹；文件夹弹窗为液态玻璃材质 + 涌现开合动画，成员可拖出/移出 |
| 🖱️ 批量操作 | 橡皮筋框选 + 多选整体拖动 |
| 🧩 桌面小组件 | 时钟 / 便签（可编辑）/ 桌面面板（搜索 · 快捷文件夹 · 磁盘 · 最近下载 · 天气）/ **系统监控**（CPU · 内存 · 磁盘）/ **待办清单**（可多实例）/ **日历**（月视图，翻月记忆）/ **天气**（实时 + 缓存降级）/ **音乐**（控制本机正在播放，不挑播放器）；支持**锚定（非悬浮）**模式，融入网格成为一等公民，可拖拽缩放、与图标互相让位 |
| 🧩 组件库 | 设置面板里的独立分页：按分类浏览、搜索、四态卡片（未添加 / 已隐藏 / 显示中 / 已添加）与**实时预览**（预览与桌面渲染同一个 `draw()`）；支持导入 / 卸载第三方组件 zip，改了外观也能立即生效 |
| 🔀 双模式 | **整理模式**（隐藏原生图标、接管桌面渲染）/ **原生模式**（无界自由摆放）：一键切换，两种布局**各自独立保存**，互不清空 |
| 🚀 Dock 栏 | 底部一排应用快捷方式（可切顶部/左侧/右侧、可关闭）：hover 弹簧放大、拖入追加、拖动排序、拖出移除；开启后**网格自动让出条带并重算行列** |
| 📑 分页 | 图标溢出自动分页，页点 + 滚轮翻页，拖到屏幕边缘翻页；翻页是**整页轮播式平移**（图标与组件同一个弹簧标量，420ms 临界阻尼，无残留无错位） |
| 🔄 桌面同步 | 监听桌面目录增删改（1s debounce），新文件自动入场、删除项自动清理 |
| 🪄 全量接管 | 隐藏原生图标、按桌面文件夹克隆渲染，彻底掌控位置与样式（路线 A）；也可切回仅动效模式 |
| 🖥️ 自绘右键菜单 | 整理模式下桌面右键不丢失：新建文件夹/文本文档、重新扫描、图标大小、显示/个性化设置 |
| 🛡️ BandGuard 守护 | Win+D 显示桌面、explorer 崩溃重启后自动重挂 |
| ⏱️ 托盘常驻 | 暂停自动创建/恢复原生、重新扫描、面板开关、开机自启、设置 |

## 📸 界面一览

> 下面每一张都由 [`tools/shot_readme.py`](tools/shot_readme.py) 从**真实控件离屏渲染**生成——桌面网格、玻璃组件、右键菜单走的是产品里同一份绘制代码，不是设计稿；两段动图由 [`tools/make_readme_anim.py`](tools/make_readme_anim.py) 用同一批素材逐帧录制（HTML 时间轴 + headless 截图 + Pillow 合成）。

**八种小组件**：时钟 / 便签 / 系统监控 / 待办清单 / 日历 / 天气 / 桌面面板 / 音乐，同一套玻璃材质与排版，尺寸跟着跨度自适应

<p align="center"><img src="docs/images/02-widgets.png" width="900" alt="八种桌面小组件"></p>

**外观自定义**：同一个时钟三种皮肤。背景色、不透明度、文字色、强调色、圆角都能单独调，留空即跟随主题；字段对所有组件统一生效（包括自己写的插件组件）

<p align="center"><img src="docs/images/03-style.png" width="820" alt="组件外观自定义"></p>

**组件库**：已经长在设置面板里，四态卡片 + 实时预览；页脚的「导入组件…」可以直接吃别人打好的 zip，装完不用重启

<p align="center"><img src="docs/images/04-widget-center.png" width="900" alt="设置面板里的组件库"></p>

**布局与分页**：列数、图标尺寸、网格原点、翻页方向都能调；「分页自动排列」可以逐页决定哪一页走自动排列、哪一页保持自由摆放

<p align="center"><img src="docs/images/05-settings.png" width="900" alt="布局与网格设置"></p>

**手机习惯**：设置 ▸ 模式 ▸ 交互方式切过去之后，单击直接启动、按住 450 ms 出菜单、按住后继续滑就变成拖动；多选后图标左上角打钩，右键出批量菜单（合并为文件夹 / 移动到分页 / 删除选中）；空白处左右滑直接翻页

<p align="center"><img src="docs/images/06-mobile.png" width="900" alt="手机交互模式：多选与批量菜单"></p>

**安卓式文件夹**：图标里直接就是成员缩略（1 / 2 / 3 / 4 个自动换排布），点开是玻璃弹窗；格子按成员数收缩、超过一页就左右翻页，成员能拖出、也能把桌面图标拖进去

<p align="center"><img src="docs/images/07-folder.png" width="900" alt="安卓式文件夹：图标缩略与展开后的玻璃弹窗"></p>

<p align="center"><img src="docs/images/08-folder-open.gif" width="640" alt="点开文件夹：玻璃从图标处涌出，成员依次就位"></p>

**安卓式分页**：图标溢出自动分页，左右滑动切换、页点跟着走；滚轮和拖到屏幕边缘也能翻页，每页还能各自决定走不走自动排列

<p align="center"><img src="docs/images/09-paging.gif" width="640" alt="桌面分页：左右滑动切换"></p>

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
│   │   ├── dock.py             # Dock 栏（纯函数 inset/hit_index + DockWindow）
│   │   └── widgets/           # 内置组件一组件一目录（clock/notes/panel/monitor/todo/calendar/weather/music）
│   └── 基础设施
│       ├── storage.py / paths.py / version.py
│       ├── media_session.py    # 播放会话抽象（媒体键 + 演示态降级）
│       ├── appsource.py / desktop_watch.py / shell_new.py
│       ├── effects.py / theme.py
│       └── settings_dialog.py / add_apps_dialog.py / tray.py / autostart.py
│           / single_instance.py / selftest.py
├── scripts/
│   ├── build_portable.ps1   # PyInstaller onedir → zip（需 pwsh 7）
│   ├── installer.iss        # Inno Setup 6 安装包（必须 UTF-8 BOM）
│   └── check_docs.py        # 文档一致性自检（死链/重复章节/文档与代码数值漂移）
├── tests/                   # 86 个独立可跑脚本（无 pytest），判据看退出码
│   ├── smoke_test.py        # 无头逻辑回归（存储/克隆/布局）
│   └── test_*.py            # 每条契约一份：让位引擎、双模式、命中、弹窗、组件…
└── tools/                   # 运行态探针 probe*.py + 打包验证 verify_*.py
```

## 🧪 测试

```powershell
# 无头逻辑回归
python tests/smoke_test.py

# 全量单测：86 个独立脚本，无 pytest；判据只看退出码
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
| v7a | 尺寸两层模型（`cell_from_native` + `solve_dims`）+ 网格原点可手动定位 | 2.0.0 |
| v7b | **v7a 实机 17 项反馈全部闭环**：双布局并存 / 拖拽连锁避让 / 组件透明区命中 / 下拉浮层实心 / 文件夹文件名+尺寸+右上角入口 / 单图标尺寸 / 启动即接管+小组件模式 | 2.1.0 |
| v7c | **v7b 之后的 4 项反馈闭环**：文件夹「添加应用 / 换颜色」改独立表单（16 预设+自动+自定义，换色不再重建成员）/ 组件手动改尺寸后碰撞形状同步（含四角双向步进）/ 图标默认「中」双源合并 / 网格调试信息移入设置面板 | 2.1.1 |
| v7d | **v7c 之后的 10 项反馈闭环**：滑条断触防抖 / 行列 Stepper 自绘步进器 / 文件夹满页分页 / 3×3 弹窗两级居中 / 组件 span 碰撞 / 文件夹内拖出碰撞预览 / 入夹双区判定 / 边缘悬停翻页 / 仅小组件模式 / 单图标自动解散文件夹 | 2.1.2 |
| v7e | **v7d 之后的 8 项反馈闭环 + B5 视觉批次**：推让/提示节拍两头提前（450/700→350/470，翻页 600→360）/ 无界松手不回弹 / 组件右键菜单随模式 / 无界→网格组件坐标回算 / 自动排列真正密排 / 弹窗图标 40–56 与绘制单点 / 控制点改圆球 + ≥22px 命中区 / 仅小组件归还原生桌面 / 脏区重绘守 60fps（`frame_stats` 可读） | 2.1.3 |
| v9a | **v9 首批：外观自定义 + 组件插件平台 + 双交互**：全组件统一外观（背景色/透明度/文字色/强调色/圆角，注册时自动注入，组件零改动）/ 时钟便签玻璃化重写 / 每页独立排序规则（跨页拖动不再回弹）/ 组件库并入设置面板（独立窗口带来的"被压住 + 点不动"从结构上消失）/ 组件开发标准文档 + `widget_plugin`（manifest 校验、zip-slip 防护、命名空间隔离）+ 预览调试器 + 打包脚本 + 组件库一键导入 / **手机式交互**（单击启动、长按 450ms 菜单、长按后滑动转拖动、多选空心圆与对钩、批量合并文件夹/移动分页/删除、空白滑动翻页）/ 组件「隐藏」「关闭」合并为「关闭」 | 4.0.0 |
| v8a | **v8 首批：组件库 + 四个新组件**：组件注册表单点化（`WidgetSpec` 一处声明跨度/分类/形态/设置/预览）/ 玻璃卡片基类（静态玻璃，不做实时模糊）/ 系统监控（CPU·内存·磁盘，纯 Win32 无新依赖）/ 待办清单（多实例）/ 日历（月视图，翻月记忆）/ 天气（Open-Meteo，实时 / 缓存 / 空 三级降级）/ 组件设置弹窗（`FieldSpec` 驱动）/ 独立组件库窗口（四态卡片 + 实时预览） | 3.0.0 |

**v7 已交付**（规格 [docs/指导文档_v7.md](docs/指导文档_v7.md)，计划 [docs/实施计划_v7.md](docs/实施计划_v7.md)）：

- [x] **B1** 尺寸地基：`cell_from_native` 由原生图标推导格子、档位只改格内占比（`icon_fit`）、行数=纯裁剪、网格原点可手动定位
- [x] **B2** 双布局并存：网格与无界各自保存，切换零换算零清空（含图标尺寸单源，`icon_px` 退役）
- [x] **B3** 拖拽：预览避让的连锁结果一并进动画清单（布局为唯一真相），组件落定无条件重排
- [x] **B4** 命中系统：组件矩形领地内不再吞点击（alpha=2 全窗填充 + `WM_NCHITTEST`→`HTCLIENT`）；逐像素 `AlphaMask` 经评估**不再需要**
- [x] **B5** 文件夹与视觉细节：弹窗图标比例（`popup_metrics` 与桌面档位解耦）/ 弹窗贴边与两级居中 / 编辑控制点改圆球 + 放大命中区（v7e 完成）
- [x] **B6** 浮层与分页：下拉弹层实心（`ui_choice.ComboBox`）、分页入口两模式可用

**v9 实施中**（规格 [docs/指导文档_v9.md](docs/指导文档_v9.md)，计划 [docs/实施计划_v9.md](docs/实施计划_v9.md)）：

- [x] **V1** 外观自定义：样式层 `widget_style` + 全组件统一注入 + 时钟便签玻璃化
- [x] **V2** 两个 BUG（组件库被压住 / 自动排布跨页回弹）+ 每页排序规则 + 组件库融入设置页
- [x] **V3** 组件开发标准：[组件开发指南](docs/组件开发指南.md) + `widget_plugin` + 预览调试器 + zip 打包/导入
- [x] **V4** 双交互逻辑：Windows 习惯 / 手机习惯（长按菜单、多选批量、滑动翻页）
- [x] **V5** 回归 + 门禁 + 出包 v9a

**v8 已交付**（规格 [docs/指导文档_v8.md](docs/指导文档_v8.md)，计划 [docs/实施计划_v8.md](docs/实施计划_v8.md)）：

- [x] **C1** 组件注册表：`WidgetSpec` 单点声明，`WIDGET_TYPES` / `WIDGET_NAMES` / `WIDGET_CATALOG` 全部退化为派生（旧调用点一行未改）
- [x] **C2** 玻璃卡片基类 `GlassWidget`：静态玻璃（竖向渐变 tint + 顶部 specular + 圆角裁剪），**不做实时高斯模糊**——常驻组件每帧抓桌面会推翻 v7 的 60fps
- [x] **C3** 组件库窗口：分类 + 搜索 + 四态卡片 + 实时预览（**预览与桌面复用同一个 `draw()`**）
- [x] **C4–C7** 四个新组件：系统监控 / 待办清单 / 日历 / 天气（model → layout → draw → widget 四层分离，前两层可单测）
- [x] **C8** 组件设置：`FieldSpec` 声明式表单，右键菜单"有声明才出现"（不出灰项）
- [x] **C9** 回归 + 门禁 + 出包 v8a

- [ ] **v7.1**（延后）：组件商店（在线安装组件包，模块化组件生态）

更远：整理模式原生能力补齐（F2 重命名 / Delete 回收站 / 剪贴板）、Ctrl+Z 撤销、多显示器。

## ⚠️ 已知限制

- 多显示器：本期仅主屏
- 跨页拖动：受当前页容量限制，需先翻页
- 第三方动态壁纸（如 Wallpaper Engine）：未专门适配
- 杀软误报：见上文打包说明

## 📄 许可证

本项目基于 **[GPL-3.0](LICENSE)** 许可证开源——与 DeskBox 同款：任何基于本项目的衍生作品必须同样以 GPL-3.0 开源，防止闭源套壳。
