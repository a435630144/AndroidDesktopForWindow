# -*- coding: utf-8 -*-
"""组件预览调试器（v9 V3，`docs/组件开发指南.md` §6）。

用法：
    python tools/widget_dev.py examples/widgets/hello
    python tools/widget_dev.py path/to/hello.zip

它做三件事：
  1. **校验** manifest + 模块，把错误直接打在窗口里（不要求你先会看 traceback）；
  2. **真机预览**：按 manifest 的每种跨度实例化组件，看清真实的玻璃底、
     字号、留白（组件库缩略图看不出这些）；
  3. **热重载**：改完 `widget.py` 点「重新加载」，不用重启调试器。

两个必须知道的行为：
  - 预览时会把 `attach_to_desktop` 换成空实现：调试窗口是普通窗口，
    组件若挂到桌面带（Progwall 之上）会被它压在下面，看起来"没显示"。
  - 需要临时 Storage 时写到系统临时目录，**不会**碰你真实的 state.json。
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from src import grid_flow
from src import widget_plugin
from src import widget_style
from src.storage import Storage


def _noop_attach(*_a, **_k):
    return False


def load_target(path: Path):
    """返回 (spec, folder, error_text)。zip 会先解到临时目录再校验。"""
    if path.suffix.lower() == ".zip":
        try:
            spec = widget_plugin.import_zip(path)
        except Exception as exc:      # noqa: BLE001
            return None, None, "%s: %s\n\n%s" % (type(exc).__name__, exc,
                                                 traceback.format_exc())
        return spec, widget_plugin.plugin_root() / spec.type, ""
    try:
        spec = widget_plugin.build_spec(path)
    except Exception as exc:          # noqa: BLE001
        return None, None, "%s: %s\n\n%s" % (type(exc).__name__, exc,
                                             traceback.format_exc())
    return spec, path, ""


class DevWindow(QWidget):
    def __init__(self, target: Path):
        super().__init__()
        self.target = target
        self.spec = None
        self.widget = None
        self.setWindowTitle("组件调试 · %s" % target.name)
        self.resize(560, 420)
        self.setStyleSheet("QWidget{background:#1b1d23; color:#F2F3F5;}"
                           " QPlainTextEdit{font-family: Consolas, monospace;"
                           " font-size: 12px;}")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        self.title = QLabel("")
        self.title.setStyleSheet("font-size: 15px; font-weight: 600;")
        root.addWidget(self.title)

        row = QHBoxLayout()
        row.addWidget(QLabel("跨度"))
        self.cmb_span = QComboBox()
        self.cmb_span.currentIndexChanged.connect(lambda _i: self.apply_span())
        row.addWidget(self.cmb_span)
        self.btn_reload = QPushButton("重新加载")
        self.btn_reload.clicked.connect(self.reload)
        row.addWidget(self.btn_reload)
        row.addStretch(1)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        self.reload()

    # ---------- 动作 ----------
    def reload(self):
        if self.widget is not None:
            try:
                self.widget.close()
                self.widget.deleteLater()
            except RuntimeError:
                pass
            self.widget = None
        spec, folder, err = load_target(self.target)
        if err:
            self.spec = None
            self.title.setText("❌ 校验失败")
            self.status.setText("按下面的报错改，改完点「重新加载」")
            self.log.setPlainText(err)
            self.cmb_span.clear()
            return

        self.spec = spec
        self.title.setText("%s  ·  %s（%s）" % (spec.name, spec.type,
                                               spec.version or "未标版本"))
        self.status.setText("分类 %s · 跨度 %s · %s · %s"
                            % (spec.category,
                               " / ".join("%d×%d" % s for s in spec.spans),
                               "锚定" if spec.default_anchored else "悬浮",
                               "多实例" if spec.multi_instance else "单实例"))
        notes = ["✅ 校验通过，已实例化真实组件（拖动/右键/设置都可用）"]
        if not callable(spec.preview):
            notes.append("· 没有 draw_preview()：组件库会用兜底卡（名字 + 说明）")
        if spec.interactive:
            notes.append("· interactive=true：组件会接受键盘焦点")
        self.log.setPlainText("\n".join(notes))

        self.cmb_span.blockSignals(True)
        self.cmb_span.clear()
        for cs, rs in spec.spans:
            self.cmb_span.addItem("%d × %d" % (cs, rs))
        self.cmb_span.blockSignals(False)
        self._spawn()

    def _temp_storage(self):
        path = Path(tempfile.gettempdir()) / "deskorg_widget_dev_state.json"
        st = Storage(str(path))
        st._data["settings"]["show_widgets"] = True
        return st

    def _spawn(self):
        if self.spec is None:
            return
        st = self._temp_storage()
        entry = {"id": "dev_preview", "type": self.spec.type, "hidden": False,
                 "anchored": False, "x": 80, "y": 80, "w": 240, "h": 240,
                 "settings": {}}
        st.widgets.append(entry)
        try:
            self.widget = self.spec.factory(st, entry)
        except Exception as exc:      # noqa: BLE001
            self.log.setPlainText("实例化失败：%s: %s\n\n%s"
                                  % (type(exc).__name__, exc, traceback.format_exc()))
            self.widget = None
            return
        self.widget.show()
        self.apply_span()

    def apply_span(self):
        if self.widget is None or self.spec is None:
            return
        idx = max(0, self.cmb_span.currentIndex())
        spec_span = self.spec.spans[min(idx, len(self.spec.spans) - 1)]
        cw, ch = grid_flow.cell_size(self.widget.storage) if hasattr(
            self.widget, "storage") else (120, 120)
        w, h = int(cw * spec_span[0]), int(ch * spec_span[1])
        # 放到控制窗口右侧，避免互相遮挡
        self.widget.setGeometry(self.x() + self.width() + 24, self.y() + 40,
                                max(120, w), max(80, h))
        self.widget.update()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.widget is not None:
            self.apply_span()


def main(argv):
    target = Path(argv[1]) if len(argv) > 1 else Path("examples/widgets/hello")
    if not target.exists():
        print("找不到目标：%s" % target)
        return 2

    app = QApplication(argv)
    # 预览窗口是普通窗口：组件挂到桌面带会被它压住（见模块 docstring）
    from src import widget_base
    widget_base.attach_to_desktop = _noop_attach
    try:
        import src.win32_layer as wl
        wl.attach_to_desktop = _noop_attach
    except Exception:      # noqa: BLE001
        pass

    win = DevWindow(target)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
