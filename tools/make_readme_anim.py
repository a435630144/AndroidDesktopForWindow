# -*- coding: utf-8 -*-
"""把「文件夹展开」和「分页翻页」录成 GIF（输出到 `docs/images/`）。

    08-folder-open.gif   点开文件夹：玻璃从图标处涌出、成员就位
    09-paging.gif        桌面分页：左右滑动切换，页点跟着走

## 为什么是"真实素材 + HTML 时间轴"

静态图证明不了"这玩意会动"，而直接拿 Qt 逐帧渲染动画又很难控制时间
（`QPropertyAnimation` 起停、成员错峰入场、动画被中断时的中间态，每一步
都要在脚本里复刻一遍产品逻辑，出错时还不好判断是产品 bug 还是脚本 bug）。

这里换一种拆法：

  * **素材**仍然来自真实控件——文件夹图标、展开后的玻璃弹窗、三页桌面，
    全部走 `tools/shot_readme.py` 的离屏渲染（`attach_to_desktop` 换 noop、
    玻璃背板喂假壁纸，绝不碰用户桌面）；
  * **时间轴**交给 HTML：每一帧只看一个参数 `t`（秒），状态是 `t` 的纯函数，
    所以任意一帧都能单独重放、单独核对；
  * 逐帧用 headless Edge 截图，Pillow 合成 GIF（统一调色板，避免整屏闪烁）。

跑法：

    python tools/make_readme_anim.py                # 两个都出
    python tools/make_readme_anim.py --only folder  # 只出一个
"""
from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from PySide6.QtCore import Qt                       # noqa: E402
from PySide6.QtGui import QImage, QPainter           # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

import shot_readme as sm                             # noqa: E402

OUT_DIR = ROOT / "docs" / "images"
PG_W, PG_H = 660, 321      # 分页动图画布（关掉 dither 后这个尺寸只有 ~1.2MB）
BUILD = ROOT / "tools" / "_anim"        # 中间产物（.gitignore 里排除）

# headless 浏览器：Windows 上一定有 Edge，Chrome 作为兜底
BROWSERS = [
    r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Microsoft/Edge/Application/msedge.exe",
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
]

# 第二/三页用的程序池（第一页复用 shot_readme.DEMO_APPS）。
# 路径同样必须**绝对**且真实存在，否则图标退成字母占位块。
_A = "C:/Windows/System32/"
DEMO_MORE = [
    ("画图", _A + "mspaint.exe"),
    ("写字板", _A + "write.exe"),
    ("注册表编辑器", _A + "regedit.exe"),
    ("事件查看器", _A + "eventvwr.exe"),
    ("性能监视器", _A + "perfmon.exe"),
    ("资源监视器", _A + "resmon.exe"),
    ("服务", _A + "services.msc"),
    ("设备管理器", _A + "devmgmt.msc"),
    ("磁盘管理", _A + "diskmgmt.msc"),
    ("系统配置", _A + "msconfig.exe"),
    ("画图 3D", _A + "mspaint.exe"),
    ("碎片整理", _A + "dfrgui.exe"),
]


# ---------------------------------------------------------------- 素材

def _app(name, exe):
    return {"name": name, "target": exe, "kind": "app"}


def _save_qimg(img: QImage, path: Path, quality=-1):
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "JPG" if path.suffix.lower() in (".jpg", ".jpeg") else "PNG"
    ok = img.save(str(path), fmt, quality) if quality > 0 else img.save(str(path))
    if not ok:
        raise RuntimeError("保存失败：%s" % path)
    return path


def build_wall():
    """假壁纸（660 × 400 @DPR2）。"""
    return _save_qimg(sm._blank(660, 400), BUILD / "wall.png")


def build_folder_assets():
    """文件夹图标 + 展开后的弹窗，返回几何信息。"""
    four = sm._folder_entry("anim_fd", "系统工具", sm._FOLDER_FULL[:4], "#39649F")
    nine = sm._folder_entry("anim_fd9", "系统工具", sm._FOLDER_FULL, "#39649F")
    st = sm._storage(layout=[four, nine])

    icon = sm._render_icon(four, 128)
    icon.save(str(BUILD / "icon_folder.png"))
    iw = icon.deviceIndependentSize().width()
    ih = icon.deviceIndependentSize().height()

    popup, pm = sm._render_popup(st, nine)
    pm.save(str(BUILD / "popup9.png"))
    pw = pm.deviceIndependentSize().width()
    ph = pm.deviceIndependentSize().height()
    popup.close()
    return {"icon": (iw, ih), "popup": (pw, ph)}


def build_pages():
    """三页桌面（1440 × 700 逻辑渲染，落盘前缩到 1320 宽）。"""
    from src import grid_flow
    from src.desktop_window import DesktopWindow

    rpp = grid_flow.rows_per_page()
    rows = max(1, min(3, rpp))
    pool = list(sm.DEMO_APPS) + DEMO_MORE
    # 三页刻意用不同数量：满页 / 中间页 / 只剩几个
    plan = [rows * 4, rows * 3 + 1, rows * 2]

    layout = []
    for page, count in enumerate(plan):
        for i in range(count):
            name, exe = pool[(page * 7 + i) % len(pool)]
            layout.append({
                "id": "pg%d_%d" % (page, i), "type": "app",
                "col": 1 + i % 4, "row": page * rpp + i // 4,
                "app": _app(name, exe),
            })
    # 用便签而不是时钟：三页是**分别渲染**的，时钟会各自读到不同时刻，
    # 滑动的两帧之间时间会跳（02:28 → 02:29）。便签是静态文本，没有这个问题。
    widgets = [{"id": "pg_notes", "type": "notes", "anchored": True,
                "col": 6, "row": 1, "colspan": 4, "rowspan": 4,
                "settings": {"bg_alpha": 0.93},
                "text": "本周\n· 桌面图标全收进网格\n· 小组件钉在桌面上\n"
                        "· 文件夹按项目分\n· 换一个喜欢的皮肤"}]
    st = sm._storage(layout=layout, widgets=widgets)

    from src.widget_layer import WidgetLayer
    layer = WidgetLayer(st)
    win = DesktopWindow(st)
    win.attached = True
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.setGeometry(0, 0, sm.W, sm.H)
    win._update_grid_metrics()
    win.rebuild()
    win.show()
    QApplication.processEvents()

    out = []
    for page in range(len(plan)):
        win.goto_page(page, animate=False)
        QApplication.processEvents()
        img = sm._blank(sm.W, sm.H)
        p = QPainter(img)
        win.render(p, win.rect().topLeft(), win.rect(), QWidget.DrawChildren)
        p.end()
        sm._draw_widgets(img, layer, st)
        small = img.scaled(PG_W * 2, PG_H * 2, Qt.KeepAspectRatio,
                           Qt.SmoothTransformation)
        out.append(_save_qimg(small, BUILD / ("page%d.jpg" % page), 94))
    sm._close_all(list(layer.widgets.values()), win)
    return out, {"rpp": rpp, "rows": rows, "plan": plan}


# ---------------------------------------------------------------- HTML

def _b64(path: Path) -> str:
    mime = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return "data:%s;base64,%s" % (mime, base64.b64encode(path.read_bytes()).decode())


_PRELUDE = """<!doctype html><html><head><meta charset="utf-8">
<style>
  html,body{margin:0;padding:0;overflow:hidden;background:#0b0d13}
  #stage{position:relative;width:%(W)dpx;height:%(H)dpx;overflow:hidden}
  #wall{position:absolute;left:0;top:0;width:100%%;height:100%%}
  .ico{position:absolute;left:0;top:0;transform-origin:0 0}
  #badge{position:absolute;right:14px;bottom:10px;padding:5px 12px;border-radius:999px;
         background:rgba(8,10,16,.34);color:rgba(255,255,255,.72);
         font:12px/1.5 "Microsoft YaHei UI","Microsoft YaHei",sans-serif;
         letter-spacing:.2px;backdrop-filter:blur(2px)}
</style></head><body><div id="stage">
<img id="wall" src="%(wall)s">
%(badge)s
"""

def _badge(text):
    """左上角小角标。默认不画——半透明黑底压在壁纸亮区像一块污渍，
    而 README 每张图下面本来就有说明文字。"""
    if not text:
        return ""
    return '<div id="badge">%s</div>' % text


_JS_COMMON = """
const T = parseFloat(new URLSearchParams(location.search).get('t') || '0');
function clamp(v, a, b){ return v < a ? a : (v > b ? b : v); }
function seg(t, t0, t1){ return clamp((t - t0) / (t1 - t0), 0, 1); }
function easeOut(t){ return 1 - Math.pow(1 - t, 3); }
function easeInOut(t){
  return t < .5 ? 4*t*t*t : 1 - Math.pow(-2*t + 2, 3) / 2;
}
/* 欠阻尼弹簧（与 src/effects.spring_curve 同族）：z 越小越弹。
   z==1 是临界阻尼，解析解里 wd=0 会让 sin/cos 那项除零变 NaN（弹窗会
   卡在上一帧、然后突然消失），必须单独走 1-e^{-ωt}(1+ωt)。 */
function spring(t, z){
  if (t <= 0) return 0;
  if (t >= 1) return 1;
  const w = 9.0;
  if (z >= 0.999) return 1 - Math.exp(-w*t) * (1 + w*t);
  const wd = w * Math.sqrt(1 - z*z);
  return 1 - Math.exp(-z*w*t) * (Math.cos(wd*t) + (z*w/wd)*Math.sin(wd*t));
}
"""


def write_folder_html(geo, wall):
    iw, ih = geo["icon"]
    pw, ph = geo["popup"]

    # 图标网格：2 列 × 3 行（第 2 列第 2 行留给文件夹）
    cards = [
        ("记事本", sm.DEMO_APPS[0][1]), ("计算器", sm.DEMO_APPS[1][1]),
        ("命令提示符", sm.DEMO_APPS[2][1]), None,
        ("放大镜", sm.DEMO_APPS[4][1]), ("屏幕键盘", sm.DEMO_APPS[5][1]),
    ]
    cell_w, cell_h = 110, 108
    x0, y0 = 26, 22
    small_w = int(iw * 0.58)
    icons, folder_at = [], None
    for i, card in enumerate(cards):
        gx = x0 + (i % 2) * cell_w
        gy = y0 + (i // 2) * cell_h
        if card is None:
            folder_at = (gx, gy)
            continue
        icons.append('<img class="ico" src="%s" style="left:%dpx;top:%dpx;width:%dpx">'
                     % (_icon_b64(card[0], card[1]), gx, gy, small_w))

    fx, fy = folder_at
    icon_w = iw * 0.66
    icon_h = ih * 0.66
    # 弹窗落位：贴着图标列右侧；缩放锚点 = 文件夹中心
    px, py = 292, 26
    ax, ay = fx + icon_w / 2, fy + icon_h * 0.45

    html = _PRELUDE % {"W": 660, "H": 400, "wall": wall, "badge": _badge("")}
    html += "".join(icons)
    html += ('<img id="fd" src="%s" style="position:absolute;left:0;top:0;'
             'width:%.1fpx;transform-origin:50%% 50%%">\n'
             % (_b64(BUILD / "icon_folder.png"), icon_w))
    html += ('<img id="pp" src="%s" style="position:absolute;left:0;top:0;'
             'width:%.1fpx;transform-origin:0 0">\n'
             % (_b64(BUILD / "popup9.png"), pw))
    html += "</div><script>" + _JS_COMMON + """
const fd = document.getElementById('fd');
const pp = document.getElementById('pp');

const ICON_X = %(fx).1f, ICON_Y = %(fy).1f;
const PP_X = %(px).1f, PP_Y = %(py).1f;
const AX = %(ax).1f, AY = %(ay).1f;

/* 时间轴（秒）：按下 0-0.18 / 涌出 0.14-0.86 / 停留 / 收 2.25-2.95 */
function render(t){
  // ① 文件夹图标按下回弹：压到 0.88 再弹回（欠阻尼，一次极小过冲）
  const down = spring(seg(t, 0.00, 0.14), 0.7);
  const up   = spring(seg(t, 0.14, 0.30), 0.55);
  const iscale = 1 - 0.12 * down * (1 - up);
  fd.style.transform = 'translate(' + ICON_X + 'px,' + ICON_Y + 'px) scale(' + iscale + ')';

  // ② 弹窗从图标中心涌出：位置与尺寸同时插值，进度 1 时正好落到最终矩形
  const open  = Math.min(1, spring(seg(t, 0.14, 0.86), 0.85));
  const close = Math.min(1, spring(seg(t, 2.25, 2.95), 1.0));
  const prog  = open * (1 - close);
  const s = 0.52 + 0.48 * prog;
  pp.style.transform = 'translate(' + (AX - (AX - PP_X) * s) + 'px,'
                     + (AY - (AY - PP_Y) * s) + 'px) scale(' + s + ')';
  pp.style.opacity = clamp(prog * 2.0, 0, 1);
}
render(T);
</script></body></html>
""" % {"fx": fx, "fy": fy, "px": px, "py": py, "ax": ax, "ay": ay}
    path = BUILD / "folder.html"
    path.write_text(html, encoding="utf-8")
    return path


_ICON_B64 = {}


def _icon_b64(name, exe):
    """单个应用图标的 base64（缓存，同一张 HTML 里不重复编码）。"""
    if exe in _ICON_B64:
        return _ICON_B64[exe]
    pm = sm._render_icon({"id": "x", "type": "app", "app": _app(name, exe)}, 96)
    tmp = BUILD / ("ic%d.png" % len(_ICON_B64))
    pm.save(str(tmp))
    _ICON_B64[exe] = _b64(tmp)
    return _ICON_B64[exe]


def write_paging_html(pages):
    thumbs = "".join(
        '<img class="pg" src="%s" style="width:%dpx;height:%dpx;flex:none">'
        % (_b64(p), PG_W, PG_H) for p in pages)
    html = _PRELUDE % {"W": PG_W, "H": PG_H, "wall": _b64(BUILD / "wall.png"),
                       "badge": _badge("")}
    html += ('<div id="track" style="position:absolute;left:0;top:0;height:%dpx;'
             'display:flex;will-change:transform">%s</div>\n' % (PG_H, thumbs))

    html += "</div><script>" + _JS_COMMON + """
const track = document.getElementById('track');

/* 关键帧 [时间, 页号]：停 → 下一页 → 停 → 下一页 → 回翻 → 回首页 */
const KEYS = [[0, 0], [0.70, 0], [1.25, 1], [1.95, 1], [2.50, 2],
              [3.20, 2], [3.75, 1], [4.20, 1], [4.70, 0]];

function pageAt(t){
  for (let i = 1; i < KEYS.length; i++){
    if (t <= KEYS[i][0]){
      const [t0, p0] = KEYS[i-1], [t1, p1] = KEYS[i];
      const k = seg(t, t0, t1);
      return p0 + (p1 - p0) * easeInOut(k);
    }
  }
  return KEYS[KEYS.length-1][1];
}

function render(t){
  const p = pageAt(t);
  track.style.transform = 'translateX(' + (-p * 520) + 'px)';
}
render(T);
</script></body></html>
"""
    path = BUILD / "paging.html"
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------- 截帧与合成

def _browser():
    for exe in BROWSERS:
        if Path(exe).exists():
            return exe
    raise RuntimeError("找不到可用的 Chromium 内核浏览器（Edge / Chrome）")


def _file_url(p: Path) -> str:
    return "file:///" + str(p).replace("\\", "/")


def shoot(html: Path, size, n: int, seconds: float, tag: str):
    exe = _browser()
    profile = Path(tempfile.gettempdir()) / "shot_readme_profile"
    frames = []
    dur = seconds / n
    for i in range(n):
        t = i * dur
        out = BUILD / ("f_%s_%03d.png" % (tag, i))
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--no-first-run", "--no-default-browser-check",
               "--force-device-scale-factor=1",
               "--user-data-dir=" + str(profile),
               "--window-size=%d,%d" % size,
               "--screenshot=" + str(out),
               "--virtual-time-budget=1500",
               _file_url(html) + "?t=%.3f" % t]
        r = subprocess.run(cmd, capture_output=True, timeout=120)
        if not out.exists():
            raise RuntimeError("截图失败（t=%.2f）：%s"
                               % (t, r.stderr.decode("utf-8", "ignore")[-400:]))
        frames.append(out)
    return frames, int(round(dur * 1000))


def compose(frames, out: Path, duration_ms: int, colors: int = 255):
    """统一调色板合成 GIF——逐帧各自量化会让整屏随帧闪。"""
    from PIL import Image
    imgs = [Image.open(f).convert("RGB") for f in frames]
    pal = imgs[0].quantize(colors=colors, method=Image.MEDIANCUT)
    qs = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im in imgs]
    out.parent.mkdir(parents=True, exist_ok=True)
    qs[0].save(str(out), save_all=True, append_images=qs[1:],
               duration=duration_ms, loop=0, optimize=True, disposal=1)
    kb = out.stat().st_size / 1024
    print("  -> %s（%d 帧 × %dms，%.0f KB）"
          % (out.relative_to(ROOT), len(qs), duration_ms, kb))
    return out


# ---------------------------------------------------------------- 场景

def scene_folder():
    BUILD.mkdir(parents=True, exist_ok=True)
    geo = build_folder_assets()
    wall = _b64(build_wall())
    html = write_folder_html(geo, wall)
    frames, dur = shoot(html, (660, 400), 62, 3.10, "fd")
    return compose(frames, OUT_DIR / "08-folder-open.gif", dur)


def scene_paging():
    BUILD.mkdir(parents=True, exist_ok=True)
    build_wall()
    pages, meta = build_pages()
    print("     桌面每页 %d 行，三页图标数 %s" % (meta["rows"], meta["plan"]))
    html = write_paging_html(pages)
    frames, dur = shoot(html, (PG_W, PG_H), 48, 4.80, "pg")
    return compose(frames, OUT_DIR / "09-paging.gif", dur, colors=192)


SCENES = [
    ("folder", "文件夹展开", scene_folder),
    ("paging", "桌面分页", scene_paging),
]


def main(argv):
    sm._qapp()
    sm._isolate()       # 只读：不挂桌面带、不抓真实屏幕
    want = None
    if "--only" in argv:
        want = argv[argv.index("--only") + 1]
    for key, title, fn in SCENES:
        if want and key != want:
            continue
        print("[%s] %s" % (key, title))
        fn()
    print("完成。中间产物在 %s" % BUILD.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    os.environ.pop("QT_QPA_PLATFORM", None)
    sys.exit(main(sys.argv))
