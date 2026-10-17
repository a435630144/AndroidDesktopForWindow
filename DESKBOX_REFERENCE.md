# DeskBox 调研报告与本项目可借鉴点

> 调研对象：[Tianyu199509/DeskBox](https://github.com/Tianyu199509/DeskBox)（~4.8k★，GPL-3.0，C# / WinUI 3 / .NET 10 Native AOT + Rust 原生 Shell 层）
> 定位（官方原文）：*"A free, open-source, local-first Windows desktop organizer with native-feeling WinUI 3 widgets."*
> 调研日期：2026-10-18

---

## 1. 一句话结论

DeskBox 是 **Stardock Fences 的现代开源替代品**，走的是"**真实文件夹背书的 widget**"路线；我们走的是"**安卓式图标网格 + 拖拽合并文件夹**"路线。两者目标用户重叠，但**产品模型不同**，不建议整体转向，应**分层借鉴**：交互细节与工程质量全盘吸收，数据模型与架构按 Demo 体量选择性吸收。

---

## 2. 模型对照

| 维度 | DeskBox | DesktopOrganizer（本项目） | 借鉴价值 |
|---|---|---|---|
| 基本单元 | Widget（格子），每个格子可**绑定一个真实文件夹**（受管 or 映射，不移动文件） | 单一大网格，桌面文件克隆进来，靠**拖拽合并**形成文件夹 | ★★★ 文件夹绑定真实目录是刚需 |
| 布局 | 图标视图 / 列表视图，widget 可缩到 50×50，多 widget 自由摆放 | 单一固定网格，列数/图标大小可调 | ★★ 多格子更自由，但 Demo 阶段成本高 |
| 排序 | 手动排序（重启后恢复）+ 规则排序 | 仅按 col/row 手工摆放，无规则排序 | ★★★ 规则排序 + 手动顺序持久化必做 |
| 堆叠 | Stack：手动堆叠或自动分组（独立开关），展开为 3×3 / 5×5 popover，**共享网格图标尺寸/密度/选择/滚轮行为，且不超出屏幕边缘** | 文件夹弹窗（液态玻璃） | ★★★ 弹窗「继承网格设置 + 屏幕边缘保护」两条直接对齐我们的 FolderPopup |
| 分组 | 多个 widget 合成 group，标题/滚轮/Ctrl+Tab 切换，成员可脱离 | 无 | ★ 暂缓 |
| 材质 | Mica / Acrylic（Win11），Win10 自动回退 | 自绘液态玻璃（抓屏 + 高斯模糊），**刻意不用 acrylic**（与分层窗口冲突，DEVLOG 4.6 已实测否决） | ★ 无——我们已用更可控方案 |
| 拖放 | 支持从 Explorer / 微信 / 浏览器拖入；**遵循 Windows 默认 copy-or-move 决策**（含跨卷、修饰键建快捷方式）；**原生 drop 镜像 + 目标描述**；拖到应用快捷方式磁贴上用该应用打开；远程 URL 可下载导入 | 内部网格拖动 + 跨窗口拖入（`M:` payload） | ★★★ 原生 drop 镜像 + 修饰键提示是观感差距最大的地方 |
| 文件迁移 | **copy-first 迁移**：预览、分阶段进度、校验、可续传重试；**源永不自动删除** | 无（当前是「克隆」语义） | ★★★ 与我们的克隆模型天然契合，直接补 |
| 唤起 | 托盘 / F7 / 双击 Ctrl / Alt+Space / Win+Space / 单击 Win / 自定义热键（PowerToys 式录制）/ 双击桌面空白处 | 托盘 + 双击空白处 | ★★★ 全局热键成本低收益高 |
| Quick Reveal | 临时置顶显示所有 widget 而不改变桌面层行为，**保留首次激活点击** | 无 | ★★ 与我们的 BandGuard 重挂思路一致 |
| 搜索 | 复用 **Everything 的本地索引（IPC）**，不自建索引；多源分级增量返回 | 无 | ★★ 可选依赖，Demo 阶段可跳 |
| 胶囊模式 | widget 收起为智能胶囊，点击/悬停展开，可排成可移动有序栏；**折叠时隐藏敏感文本** | 无 | ★★ 「悬停展开 + 交互挂起」是很好的小组件模式 |
| 多显示器 | Widget 归属显示器；热插拔宽限期后比例迁移；换机/改缩放按 reference frame 重排；Ctrl+拖标题整屏搬移 | 单屏假设 | ★ 单屏 Demo 暂缓，但「缩放变化时布局重排」与我们刚做的 DPI 感知直接相关 |
| 数据存储 | `%LocalAppData%\DeskBox\data`；新用户受管存储优先选非系统盘（如 `D:\DeskBox\user`），否则 `%UserProfile%\DeskBox` | `%APPDATA%\DesktopOrganizerDemo\state.json` | ★★ 备份/恢复可后置 |
| 卸载 | 清除 LocalAppData 与恢复目录，**受管存储里的用户文件永远保留** | 无卸载策略 | ★★★ 与即将做的安装包强相关，必须写进 Inno 脚本 |
| 性能模式 | Balanced / Resource saver / Custom，可单独关文字跑马灯、黑胶旋转等连续动画；隐藏 widget 释放可重建 UI 面 | 无显式策略，`reduced_motion()` 读系统动画开关 | ★★ reduced-motion 已有，补「隐藏时释放位图」即可 |

---

## 3. 建议落地的功能（按优先级）

### P0 — 直接补体验短板（1~2 天）

1. **文件夹绑定真实目录（map existing folder）**
   增加一种 folder 类型：`{"type":"folder","target":"C:\\...\\下载"}`，打开 FolderPopup 时**实时** `iterdir()` 该目录而非读克隆快照。这样「映射现有文件夹」零迁移成本，且文件增删即时反映——正好解决你反馈的"加载的文件不完整/缺很多"的结构性成因。
2. **规则排序 + 手动顺序持久化**
   排序维度：名称 / 类型 / 修改时间 / 大小，升降序；手动拖动后写入 `order` 字段并持久化（DeskBox 明确"manual order is restored after restart"）。
3. **原生拖放镜像 + 修饰键提示**
   拖出时用 Shell 的 drop image（`IDropTargetHelper` / `SHDoDragDrop` 等价路径），而不是自绘 QDrag pixmap；修饰键 Ctrl/Shift 时给出 copy/move/shortcut 的目标描述。这是与商业软件观感差距最大的一项。
4. **卸载保留用户数据**
   Inno 脚本只删 `%APPDATA%\DesktopOrganizerDemo` 中的程序状态，**克隆/映射的用户文件一律不碰**（对齐 DeskBox 的"managed storage 永远保留"）。

### P1 — 交互增强（3~5 天）

5. **全局唤起热键**：双击 Ctrl / Alt+Space / Win+Space / F7，PowerToys 式录制（`RegisterHotKey` + 低层钩子）；**预留组合键先警告系统副作用再允许启用**（DeskBox 的做法，避免抢 Win+D 这类）。
6. **Quick Reveal**：临时把整理层抬到最前且保留首次点击，不动桌面层挂载状态。
7. **FolderPopup 继承网格设置 + 屏幕边缘保护**：图标尺寸/密度/滚轮缩放与主网格一致；展开 popover 时按 3×3/5×5 自适应并钳制在屏幕内。
8. **Stack（堆叠）**：手动把若干文件叠成一个 stack，展开为 popover。这是比"文件夹"更轻的聚合，自动分组做成**独立 opt-in 开关**（DeskBox 特意强调 separate opt-in switch，值得抄这个谨慎）。
9. **Capsule 模式的简化版**：小组件收起为胶囊，悬停展开，**交互进行中（拖拽/菜单/编辑）挂起不收起**——这条交互细节非常苹果，直接进 widget_base。

### P2 — 架构与工程质量（长期）

10. **copy-first 迁移**：把桌面文件搬进受管存储前先复制、预览、校验、可续传，源不自动删除。
11. **启动时序**：DeskBox "Startup waits for Explorer's desktop icon host to stabilize before attaching desktop-layer widgets"——我们已有 BandGuard，可加一条"等 SHELLDLL_DefView 稳定后再挂载"，减少开机竞态。
12. **契约化文档**：DeskBox 把「widget Z 序生命周期」「文件拖拽堆叠契约」标为 `[重要勿删]` 的 living contract，并把踩坑编号登记（zorder 坑 #6/#10）。建议 DEVLOG 第 4 节升级为同款契约制：每个坑一个编号、一条规则、一个断言。
13. **回调帧隔离**：DeskBox 修复拖拽冻结的核心是「回调帧内禁止同步重操作」（14 个 subclass proc + IDropTarget 四方法 + 托盘命令全覆盖，违规计数进诊断包）。我们的 `_drag_active` 卡死（DEVLOG 4.3）与 paintEvent 重入崩溃（6.A1）本质同类——建议引入 `CallbackDepth` 雷达，在 WM_NCHITTEST / paintEvent / 托盘回调里断言。
14. **性能模式**：隐藏 widget 时释放 `QPixmap` 缓存（可重建面），文字跑马灯等连续动画可单独关闭。

---

## 4. 不建议照搬的部分

| DeskBox 做法 | 不搬的原因 |
|---|---|
| Rust 原生 Shell 层（shortcut / 回收站 / 音量 / Quick Access ABI） | Demo 阶段用 `ctypes + shell32` 已覆盖 80% 需求；Rust 引入双工具链，违背"零第三方依赖" |
| .NET 10 Native AOT + Windows App SDK 2.5.1 | 打包体积与构建复杂度对 Demo 是净负担；PyInstaller onedir 已够 |
| 12 语言本地化 | Demo 单语言；但**建议现在就把字符串收敛到 `theme.py`/资源表**，留出 i18n 缝 |
| 依赖 Everything 做搜索 | 需用户另装软件；可做成"检测到 Everything 才启用 IPC，否则退回内置扫描" |
| WebDAV 云备份 + Credential Manager | 超出 Demo 范围；先做本地备份/恢复 |
| 多显示器全量方案（归属/宽限期/reference frame） | 单屏 Demo 暂缓；但「缩放变化时布局重排」要留接口 |
| Settings Coordinators / View Eviction 等治理结构 | 220 个 passthrough 的规模问题，我们没有 |

---

## 5. 给本项目的三条硬结论

1. **产品定位要对齐 DeskBox 的"不替代 Explorer"**：我们的双桌面模式（整理模式隐藏原生图标）与这条相悖。建议增加第三种模式——**叠加模式**：不隐藏 `SHELLDLL_DefView`，整理层只承载 widget/文件夹，桌面文件仍归 Explorer 管。这能一次性消掉"隐藏原生图标后桌面空白"的风险（DEVLOG 4.5 那类事故的根因）。
2. **文件夹必须能绑定真实目录**，否则"文件不全"的抱怨会反复出现——克隆是快照，绑定才是真相。
3. **工程质量要向 DeskBox 的契约制看齐**：拖拽冻结、Z 序坑、回调帧隔离这三类问题他们用编号化契约 + 诊断包治理，我们有同源问题但只靠 DEVLOG 散文记录。

---

*附：DeskBox 仓库结构（备查）*

```text
src\DeskBox            WinUI 3 应用（widget shell / services / views）
src\DeskBox.Updater    更新器辅助程序
native                 Rust 原生层：Shell ABI + 缩略图代理
tests\DeskBox.Tests    服务 / 策略 / AOT 契约测试
scripts                构建、发布、审计、内存测量
installer              x64/ARM64 Inno Setup
docs\architecture      架构现状 + Native ABI 契约 + AOT 阶段
docs\releases          各版本发布文案与测试清单
```
