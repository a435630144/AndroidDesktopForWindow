# -*- coding: utf-8 -*-
"""内置组件包（v10 C1，反馈 8：按 docs/组件开发指南.md 的模块化布局重组）。

一个组件一个目录，目录里三件套：
  <name>.py   组件类 + model/layout/draw（纯搬迁，逻辑零改动）
  draw.py     模块级 draw_preview（组件库预览与桌面渲染复用同一个 draw）
  __init__.py 只做 re-export，让旧导入路径换成 `from .widgets.<name> import ...`

**注册（span/分类/settings 声明）不在这里**——单一真相源是
`src/widget_registry.py`，本包只解决"文件放哪、import 怎么写"。
"""
# clock 是第一个搬进来的；其余组件在 v10 C1 逐卡跟进，一次提交一个。
