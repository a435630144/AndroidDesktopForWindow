# -*- coding: utf-8 -*-
"""设计 tokens：对标腾讯桌面整理的深色半透明面板风格（Windows 11）。

桌面带上的全部视觉元素（图标网格、文件夹、弹窗、小组件、桌面面板）
统一从这里取色 / 取字 / 取圆角，保证整体观感一致：

  - 表面：近黑深灰 + 高不透明度，壁纸若隐若现
  - 边框：白色低透明度细线，界定面板边界
  - 文字：三级层级（主 / 次 / 弱）
  - 强调：Windows 11 蓝（#4CC2FF），仅用于选中 / 进度 / 交互反馈
  - 字体：Microsoft YaHei UI（Win11 中文 UI 字体）
"""
from PySide6.QtGui import QColor, QFont

# ---------- 表面 ----------
SURFACE = QColor(30, 30, 36, 226)          # 主面板底（半透明，透出壁纸）
SURFACE_POPUP = QColor(28, 28, 34, 240)    # 弹窗底（更实，保证可读）
SURFACE_RAISED = QColor(255, 255, 255, 14)  # 面板内嵌元素（输入框 / 卡片）
BORDER = QColor(255, 255, 255, 26)         # 面板描边
BORDER_STRONG = QColor(255, 255, 255, 40)  # 强描边（选中态）

# ---------- 文字 ----------
TEXT = QColor(242, 243, 245)               # 主文字
TEXT_DIM = QColor(168, 173, 181)            # 次文字
TEXT_FAINT = QColor(120, 126, 135)          # 弱文字（占位 / 注释）

# ---------- 强调 ----------
ACCENT = QColor(76, 194, 255)              # Windows 11 蓝
ACCENT_SOFT = QColor(76, 194, 255, 46)     # 选中底色
ACCENT_BORDER = QColor(76, 194, 255, 130)  # 选中描边
DANGER = QColor(232, 88, 88)               # 关闭按钮悬停

# ---------- 状态 ----------
HOVER = QColor(255, 255, 255, 20)          # 悬停底色
HOVER_BORDER = QColor(255, 255, 255, 36)

# ---------- 图标标签 ----------
LABEL_SIZE = 11
LABEL_COLOR = QColor(244, 245, 247)
LABEL_SHADOW = QColor(0, 0, 0, 190)

# ---------- 文件夹（安卓风深色圆角方形） ----------
FOLDER_BG = QColor(48, 48, 56, 205)
FOLDER_BORDER = QColor(255, 255, 255, 34)

# ---------- 圆角 ----------
RADIUS_PANEL = 14
RADIUS_CARD = 12
RADIUS_ITEM = 10

# ---------- 液态玻璃（苹果 Liquid Glass 风格 tokens） ----------
# 用于文件夹弹窗等浮层：背后内容模糊透出 + tint + 边缘高光。
# 实现见 src/effects.py（抓屏 -> 高斯模糊 -> 自绘，不用 acrylic API——
# acrylic 与 Qt 的 WA_TranslucentBackground+WS_EX_LAYERED 组合冲突）。
GLASS_RADIUS = 20            # 玻璃大圆角（液态感）
GLASS_TINT_ALPHA = 150       # 玻璃 tint 不透明度（中部）
GLASS_SPECULAR = 135         # 顶部高光峰值 alpha（液态玻璃的灵魂）
GLASS_BORDER = 52            # 玻璃描边 alpha

# ---------- 字体 ----------
FONT_FAMILIES = ["Microsoft YaHei UI", "Segoe UI", "Microsoft YaHei"]


def ui_font(pixel_size: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(pixel_size)
    f.setBold(bold)
    return f


def rgba(color: QColor) -> str:
    return "rgba(%d, %d, %d, %d)" % (color.red(), color.green(), color.blue(), color.alpha())


# ---------- 常用 QSS（QWidget 系组件用） ----------
INPUT_QSS = (
    "QLineEdit{background: %s; color: rgb(242,243,245); border: 1px solid %s;"
    " border-radius: 10px; padding: 8px 12px 8px 34px; font-family: %s; font-size: 13px;}"
    "QLineEdit:focus{border: 1px solid %s;}"
) % (rgba(SURFACE_RAISED), rgba(BORDER), ", ".join('"%s"' % f for f in FONT_FAMILIES), rgba(ACCENT_BORDER))

LIST_QSS = (
    "QListWidget{background: %s; border: 1px solid %s; border-radius: 10px;"
    " color: rgb(242,243,245); font-family: %s; font-size: 13px; outline: none;}"
    "QListWidget::item{padding: 6px 8px; border-radius: 8px;}"
    "QListWidget::item:hover{background: %s;}"
    "QListWidget::item:selected{background: %s; color: rgb(242,243,245);}"
) % (rgba(SURFACE_RAISED), rgba(BORDER), ", ".join('"%s"' % f for f in FONT_FAMILIES),
     rgba(HOVER), rgba(ACCENT_SOFT))

BUTTON_QSS = (
    "QPushButton{background: %s; color: rgb(242,243,245); border: 1px solid %s;"
    " border-radius: 8px; padding: 6px 16px; font-family: %s; font-size: 13px;}"
    "QPushButton:hover{background: %s;}"
    "QPushButton:pressed{background: %s;}"
) % (rgba(SURFACE_RAISED), rgba(BORDER), ", ".join('"%s"' % f for f in FONT_FAMILIES),
     rgba(HOVER), rgba(ACCENT_SOFT))

CHECKBOX_QSS = (
    "QCheckBox{color: rgb(242,243,245); font-family: %s; font-size: 13px;}"
    "QCheckBox::indicator{width: 16px; height: 16px; border-radius: 4px;"
    " border: 1px solid %s; background: %s;}"
    "QCheckBox::indicator:checked{background: %s; border: 1px solid %s;}"
) % (", ".join('"%s"' % f for f in FONT_FAMILIES), rgba(BORDER_STRONG),
     rgba(SURFACE_RAISED), rgba(ACCENT), rgba(ACCENT))

SLIDER_QSS = (
    "QSlider::groove:horizontal{height: 4px; background: %s; border-radius: 2px;}"
    "QSlider::handle:horizontal{width: 16px; height: 16px; margin: -6px 0;"
    " border-radius: 8px; background: rgb(76,194,255);}"
) % rgba(SURFACE_RAISED)

SPIN_QSS = (
    "QSpinBox{background: %s; color: rgb(242,243,245); border: 1px solid %s;"
    " border-radius: 8px; padding: 4px 6px; font-family: %s; font-size: 13px;}"
) % (rgba(SURFACE_RAISED), rgba(BORDER), ", ".join('"%s"' % f for f in FONT_FAMILIES))

DIALOG_QSS = "QDialog{background: rgb(34, 34, 40);}"

MENU_QSS = (
    "QMenu{background: rgb(38, 38, 44); color: rgb(242,243,245);"
    " border: 1px solid rgba(255,255,255,26); border-radius: 10px; padding: 6px;"
    " font-family: %s; font-size: 13px;}"
    "QMenu::item{padding: 6px 24px 6px 16px; border-radius: 6px;}"
    "QMenu::item:selected{background: rgba(76,194,255,46);}"
    "QMenu::separator{height: 1px; background: rgba(255,255,255,20); margin: 4px 8px;}"
) % ", ".join('"%s"' % f for f in FONT_FAMILIES)
