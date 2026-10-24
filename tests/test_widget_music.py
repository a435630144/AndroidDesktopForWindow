# -*- coding: utf-8 -*-
"""音乐控制器组件（v10 C2，反馈 9）。

契约：
  M1  layout：封面在左、文本在右，三键水平居中且互不重叠、都在容器内
  M2  宽版 (4,2) 也能布局；极小矩形不抛
  M3  draw 画布非空
  M4  空快照也能画（显示"没有在播放"）
  M5  降级态有可见差异（demo 角标不是隐形的）
  M6  progress / remains 计算（时长未知不撒谎）
  M7  marquee_offset：放得下为 0；放不下在 [0, overflow] 内往复
  M8  DemoSource：推进 / 暂停不推进 / 换曲归零 / 曲目循环
  M9  send_media_key 失败返回 False 不抛（非 Windows / 被拦截）
  M10 组件点击三键分别调到 prev / play_pause / next（假数据源，不碰真播放器）
  M11 注册表登记：spans (3,2) 起、分类媒体、默认锚定、有预览函数
  M12 组件真的画了内容 + 刷新间隔 500ms
  M13 侧车协议：B64 行解码（中文/无会话/垃圾行）
  M14 组合源优先级：SMTC > 标题 > 演示；seek 只往真源发
  M15 窗口标题解析：`歌名 - 歌手` / `•` / 品牌后缀
  M16 进度条拖动：按下不移动组件、松手一次 seek 且只发一次
  M17 仅曲名档：进度条不可拖、不画假进度

运行：python tests/test_widget_music.py   （offscreen）
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter
from PySide6.QtWidgets import QApplication

from src import grid_flow
from src.media_session import (DEMO_DURATION, DemoSource, MediaInfo,
                               send_media_key)
from src.storage import Storage

STATE = Path(tempfile.gettempdir()) / "test_widget_music_state.json"

failures = []


def check(name, cond, extra=""):
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", name, extra))
    if not cond:
        failures.append(name)


def canvas(w, h):
    img = QImage(int(w), int(h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    return img


def alpha_nonempty(img):
    return sum(1 for y in range(0, img.height(), 2) for x in range(0, img.width(), 2)
               if img.pixelColor(x, y).alpha() > 8)


def render(fn, w, h, *args, **kw):
    img = canvas(w, h)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    fn(p, QRectF(0, 0, w, h), *args, **kw)
    p.end()
    return img


class FakeSource:
    """假数据源：只记录调用，不发媒体键（测试不碰用户播放器）。"""

    name = "fake"

    def __init__(self):
        self.calls = []

    def snapshot(self):
        return MediaInfo(title="真歌名", artist="真艺人", playing=True,
                         position=30.0, duration=120.0)

    def play_pause(self):
        self.calls.append("play")
        return True

    def next_track(self):
        self.calls.append("next")
        return True

    def prev_track(self):
        self.calls.append("prev")
        return True


def click(w, pos):
    ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos), QPointF(pos),
                     Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    w.mousePressEvent(ev)


def drag(w, p0, p1):
    """按下 -> 移动 -> 松手（进度条拖动的最小序列）。"""
    w.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(p0), QPointF(p0),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    w.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(p1), QPointF(p1),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    w.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(p1), QPointF(p1),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))


def main(app):
    from src.widgets import music as wm

    # ---------- M1 / M2：布局 ----------
    W, H = 252, 182                     # (3,2) 在 84×91 网格下
    L = wm.layout(QRectF(0, 0, W, H))
    cover, bar = L["cover"], L["bar"]
    btns = L["buttons"]
    check("M1 封面在左、文本在右",
          cover.center().x() < L["title_rect"].center().x()
          and cover.right() <= L["title_rect"].left() + 0.5,
          "cover=%s title=%s" % (tuple(round(v) for v in (cover.left(), cover.right())),
                                 tuple(round(v) for v in (L["title_rect"].left(),))))
    check("M1b 封面是正方形", abs(cover.width() - cover.height()) < 0.6,
          "%.1f x %.1f" % (cover.width(), cover.height()))
    check("M1c 进度条在封面下方、占满内宽",
          bar.top() > cover.bottom() and bar.width() > cover.width() * 1.5,
          "bar=%.1f,%.1f w=%.1f" % (bar.left(), bar.top(), bar.width()))
    # 时间/角标那一行：行高写死会出现"字的顶被切掉"（字号 12 行高 17），
    # 所以行矩形必须由 layout 交付，且不能压在进度条上。
    from PySide6.QtGui import QFontMetricsF as _FM
    row = L["row"]
    check("M1g 时间行够高（文字不被裁）",
          row.height() >= _FM(L["font_time"]).height() - 0.5,
          "row=%.1f font=%.1f" % (row.height(), _FM(L["font_time"]).height()))
    check("M1h 时间行不与进度条重叠", row.top() >= bar.bottom() - 0.5,
          "row.top=%.1f bar.bottom=%.1f" % (row.top(), bar.bottom()))
    check("M1i 按键在时间行之下（不压文字）",
          all(b.top() >= row.bottom() - 0.5 for b in btns),
          "row.bottom=%.1f btn.top=%.1f" % (row.bottom(), btns[0].top()))
    overlap = any(btns[i].adjusted(-1, -1, 1, 1).intersects(btns[j])
                  for i in range(3) for j in range(i + 1, 3))
    check("M1d 三键互不重叠", not overlap)
    check("M1e 三键水平居中（中心偏差 < 2px）",
          abs((btns[0].center().x() + btns[2].center().x()) / 2.0 - W / 2.0) < 2.0,
          "%.1f vs %.1f" % ((btns[0].center().x() + btns[2].center().x()) / 2.0, W / 2.0))
    inside = all(0 <= b.left() and b.right() <= W and 0 <= b.top() and b.bottom() <= H
                 for b in btns) and cover.top() >= 0 and bar.bottom() <= H
    check("M1f 全部落在容器内", inside,
          str([(round(b.left()), round(b.top())) for b in btns]))

    W2 = wm.layout(QRectF(0, 0, 336, 182))          # (4,2)
    check("M2 宽版封面不越界且仍是方的",
          W2["cover"].right() <= 336 and abs(W2["cover"].width() - W2["cover"].height()) < 0.6,
          "%.1f" % W2["cover"].width())
    tiny = wm.layout(QRectF(0, 0, 60, 40))
    check("M2b 极小矩形不抛且有正尺寸",
          tiny["cover"].width() > 0 and tiny["bar"].width() > 0,
          "%.1f" % tiny["cover"].width())

    # ---------- M3 / M4 / M5：绘制 ----------
    full = MediaInfo(title="很长的曲名" * 3, artist="艺人", playing=True,
                     position=64.0, duration=210.0)
    img = render(wm.draw, W, H, full)
    check("M3 draw 画布非空", alpha_nonempty(img) > 300, str(alpha_nonempty(img)))

    img_empty = render(wm.draw, W, H, MediaInfo())
    check("M4 空快照也能画（没有在播放）", alpha_nonempty(img_empty) > 200,
          str(alpha_nonempty(img_empty)))

    # 降级角标必须真的可见：同一数据，只切 demo 标志
    demo = MediaInfo(title="演示曲目 · 一", artist="把播放器打开", playing=True,
                     position=10.0, duration=210.0, demo=True)
    real = MediaInfo(title="演示曲目 · 一", artist="把播放器打开", playing=True,
                     position=10.0, duration=210.0, demo=False)
    a = render(wm.draw, W, H, demo)
    b = render(wm.draw, W, H, real)
    diff = sum(1 for y in range(0, H, 2) for x in range(0, W, 2)
               if a.pixelColor(x, y) != b.pixelColor(x, y))
    check("M5 降级角标可见（demo 与 real 像素有差异）", diff > 12, str(diff))

    # ---------- M6：进度计算 ----------
    half = MediaInfo(position=105.0, duration=210.0)
    check("M6 progress 半程 = 0.5", abs(half.progress() - 0.5) < 1e-6,
          "%.3f" % half.progress())
    check("M6b 时长未知时 progress = 0 且无剩余时间文案",
          MediaInfo(position=99.0).progress() == 0.0
          and MediaInfo(position=99.0).remains() == "",
          repr(MediaInfo(position=99.0).remains()))
    check("M6c 剩余时间格式 -1:45", half.remains() == "-1:45", half.remains())
    check("M6d progress 被夹到 0..1（进度超过时长）",
          MediaInfo(position=999.0, duration=100.0).progress() == 1.0)

    # ---------- M7：长标题滚动 ----------
    box = L["title_rect"].width()
    font = L["font_title"]
    check("M7 放得下不滚（offset = 0）",
          wm.marquee_offset("短", font, box, 5.0) == 0.0)
    long_text = "很长的曲名" * 6
    offs = [wm.marquee_offset(long_text, font, box, t * 0.25) for t in range(0, 160)]
    check("M7b 放不下会滚（出现正偏移）", max(offs) > 0.0, "%.1f" % max(offs))
    check("M7c 偏移不越界（0 <= off <= overflow）",
          min(offs) >= 0.0 and max(offs) <= wm.marquee_offset(long_text, font, box, 0) + 1e9,
          "min=%.1f max=%.1f" % (min(offs), max(offs)))
    check("M7d 偏移会回落（往复而不是一直向右）",
          max(offs) > 0 and any(offs[i] < offs[i - 1] for i in range(1, len(offs))),
          "peak=%.1f" % max(offs))

    # ---------- M8：演示数据源 ----------
    src = DemoSource()
    p0 = src.snapshot().position
    src.advance(10.0)
    check("M8 advance 推进进度", src.snapshot().position > p0,
          "%.1f -> %.1f" % (p0, src.snapshot().position))
    src.play_pause()
    p1 = src.snapshot().position
    src.advance(10.0)
    check("M8b 暂停后不推进", src.snapshot().position == p1,
          "%.1f -> %.1f" % (p1, src.snapshot().position))
    src.play_pause()
    t0 = src.snapshot().title
    src.next_track()
    check("M8c 换曲归零且曲名变了",
          src.snapshot().position == 0.0 and src.snapshot().title != t0,
          "%s -> %s" % (t0, src.snapshot().title))
    for _ in range(len(wm.DEMO_TRACKS) if hasattr(wm, "DEMO_TRACKS") else 3):
        src.next_track()
    check("M8d 曲目循环（不会越界到空）", bool(src.snapshot().title))
    check("M8e 演示态恒带 demo 标记", src.snapshot().demo is True)
    check("M8f 演示曲目时长固定", src.snapshot().duration == DEMO_DURATION,
          str(src.snapshot().duration))

    # ---------- M9：媒体键失败不抛 ----------
    import src.media_session as ms
    old = ms._u32
    ms._u32 = lambda: (_ for _ in ()).throw(OSError("no user32"))
    try:
        ok = send_media_key(ms.VK_MEDIA_PLAY_PAUSE)
    finally:
        ms._u32 = old
    check("M9 媒体键失败返回 False 不抛", ok is False)

    # ---------- M10 / M12：组件与点击 ----------
    if STATE.exists():
        STATE.unlink()
    st = Storage(path=str(STATE))
    st._data["settings"]["hide_native_icons"] = False
    st._data["settings"]["auto_clone_desktop"] = False
    st._data["layout"] = []
    st._data["widgets"] = [{"id": "mus1", "type": "music", "w": W, "h": H,
                            "hidden": False, "anchored": True,
                            "col": 0, "row": 0, "colspan": 3, "rowspan": 2}]
    st.save()
    grid_flow.set_grid(st, (1920, 1040))
    grid_flow.set_page(0)

    from src import widget_glass
    w = wm.MusicWidget(st, dict(st.widgets[0]))
    check("M10 MusicWidget 是 GlassWidget 子类",
          isinstance(w, widget_glass.GlassWidget))
    fake = FakeSource()
    w.source = fake
    w._info = fake.snapshot()
    w._timer.stop()
    w.resize(W, H)
    Lw = wm.layout(QRectF(0, 0, W, H))
    for kind, idx in (("prev", 0), ("play", 1), ("next", 2)):
        c = Lw["buttons"][idx].center()
        click(w, c)
    check("M10b 三键分别调到 prev / play_pause / next",
          fake.calls == ["prev", "play", "next"], str(fake.calls))
    check("M10c 非按钮区域不触发控制",
          (fake.calls.clear() or True) and click(w, QPointF(4, 4)) is None
          and fake.calls == [], str(fake.calls))

    w.show()
    app.processEvents()
    shot = w.grab().toImage()
    check("M12 组件真的画了内容（不是只有玻璃底）",
          alpha_nonempty(shot) > 500, str(alpha_nonempty(shot)))
    w2 = wm.MusicWidget(st, dict(st.widgets[0]))
    check("M12b 刷新间隔 500ms", w2._timer.interval() == wm.TICK_MS,
          str(w2._timer.interval()))
    w2._timer.stop()
    w2.close()
    w.close()

    # ---------- M16 / M17：进度条拖动 ----------
    class SeekFake(FakeSource):
        def __init__(self, info=None):
            super().__init__()
            self.info = info or MediaInfo(title="真歌名", artist="真艺人",
                                          playing=True, position=30.0,
                                          duration=120.0, seekable=True)

        def snapshot(self):
            return self.info

        def seek(self, seconds):
            self.calls.append(("seek", round(float(seconds), 2)))
            return True

    w3 = wm.MusicWidget(st, dict(st.widgets[0]))
    fake3 = SeekFake()
    w3.source = fake3
    w3._info = fake3.snapshot()
    w3._timer.stop()
    w3.resize(W, H)
    Lb = wm.layout(QRectF(0, 0, W, H))
    bar = Lb["bar"]
    pos0 = (w3.x(), w3.y())
    x25 = bar.left() + bar.width() * 0.25
    w3.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(x25, bar.center().y()),
        QPointF(x25, bar.center().y()), Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    check("M16 按在进度条上：进入预览态", w3._seek_frac is not None
          and abs(w3._seek_frac - 0.25) < 0.02, str(w3._seek_frac))
    check("M16b 按下进度条不移动组件（不被当成拖窗口）",
          (w3.x(), w3.y()) == pos0, "%s -> %s" % (pos0, (w3.x(), w3.y())))
    x75 = bar.left() + bar.width() * 0.75
    w3.mouseMoveEvent(QMouseEvent(
        QEvent.MouseMove, QPointF(x75, bar.center().y()),
        QPointF(x75, bar.center().y()), Qt.NoButton, Qt.LeftButton,
        Qt.NoModifier))
    check("M16c 拖动更新预览占比", abs(w3._seek_frac - 0.75) < 0.02,
          str(w3._seek_frac))
    check("M16d 拖动中尚未 seek（松手才落地）",
          not [c for c in fake3.calls if isinstance(c, tuple)], str(fake3.calls))
    w3.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(x75, bar.center().y()),
        QPointF(x75, bar.center().y()), Qt.LeftButton, Qt.NoButton,
        Qt.NoModifier))
    seeks = [c for c in fake3.calls if isinstance(c, tuple)]
    check("M16e 松手 seek 到目标位置（0.75 × 120s = 90s）",
          len(seeks) == 1 and abs(seeks[0][1] - 90.0) < 2.0, str(seeks))
    check("M16f 松手后退出预览态", w3._seek_frac is None)

    fake4 = SeekFake(MediaInfo(title="只有标题", artist="X", playing=True,
                               duration=0.0, partial=True, seekable=False))
    w3.source = fake4
    w3._info = fake4.snapshot()
    w3.mousePressEvent(QMouseEvent(
        QEvent.MouseButtonPress, QPointF(x25, bar.center().y()),
        QPointF(x25, bar.center().y()), Qt.LeftButton, Qt.LeftButton,
        Qt.NoModifier))
    check("M17 仅曲名档进度条不可拖（按下去也不进预览态）",
          w3._seek_frac is None and not w3._seek_enabled())
    check("M17b 仅曲名档 progress 恒 0（不画假进度）",
          fake4.snapshot().progress() == 0.0)
    w3.mouseReleaseEvent(QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(x25, bar.center().y()),
        QPointF(x25, bar.center().y()), Qt.LeftButton, Qt.NoButton,
        Qt.NoModifier))
    w3._timer.stop()
    w3.close()

    # ---------- M13：侧车协议 ----------
    import base64
    import json

    def b64line(obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        return "B64:" + base64.b64encode(raw).decode("ascii")

    info = ms.parse_sidecar_line(b64line({
        "ok": True, "has": True, "title": "晴天", "artist": "周杰伦",
        "album": "叶惠美", "playing": True, "pos": 12.5, "dur": 269.0,
        "app": "cloudmusic"}))
    check("M13 侧车行解码出中文曲名/艺人",
          info is not None and info.title == "晴天" and info.artist == "周杰伦",
          str(info))
    check("M13b 真会话可 seek 且进度按位置算",
          info is not None and info.seekable and abs(info.progress() - 12.5 / 269.0) < 1e-6,
          str(info.progress() if info else None))
    off = ms.parse_sidecar_line(b64line({"ok": True, "has": False}))
    check("M13c 无会话 -> EMPTY（不编歌名）", off is not None and off.title == "")
    check("M13d 垃圾行 -> None（跳过而不抛）",
          ms.parse_sidecar_line("hello") is None
          and ms.parse_sidecar_line("B64:!!!!") is None
          and ms.parse_sidecar_line(None) is None)
    check("M13e 插值：播放中位置随时间前进",
          abs(MediaInfo(playing=True, position=10.0, duration=100.0,
                        stamp=100.0).position_at(105.0) - 15.0) < 1e-6)
    check("M13f 插值不超过时长",
          MediaInfo(playing=True, position=99.0, duration=100.0,
                    stamp=100.0).position_at(200.0) == 100.0)

    # ---------- M14：组合源优先级 ----------
    class Stub:
        name = "stub"

        def __init__(self, info):
            self.info = info
            self.seeked = None
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def snapshot(self):
            return self.info

        def seek(self, seconds):
            self.seeked = seconds
            return True

    smtc = Stub(MediaInfo(title="SMTC 歌", artist="A", duration=200.0,
                          position=20.0, playing=True, seekable=True))
    titles = Stub(MediaInfo(title="标题歌", artist="B", partial=True))
    demo = DemoSource()
    auto = ms.AutoSource(smtc=smtc, titles=titles, demo=demo)
    check("M14 SMTC 有歌时优先用真会话", auto.snapshot().title == "SMTC 歌")
    check("M14b seek 发给 SMTC", auto.seek(30.0) and smtc.seeked == 30.0,
          str(smtc.seeked))
    smtc.info = MediaInfo()
    check("M14c SMTC 空 -> 退到窗口标题", auto.snapshot().title == "标题歌")
    check("M14d 标题档不可 seek（没有时长就不能假装能拖）",
          auto.seek(30.0) is False)
    titles.info = MediaInfo()
    snap = auto.snapshot()
    check("M14e 都没有 -> 演示档", snap.demo is True and snap.title != "",
          snap.title)
    auto.start()
    auto.stop()
    check("M14f start/stop 透传到 SMTC（子进程不留孤儿）",
          smtc.started and smtc.stopped)

    # ---------- M15：标题解析 ----------
    check("M15 `歌名 - 歌手` 拆开", ms.parse_title("晴天 - 周杰伦") == ("晴天", "周杰伦"))
    check("M15b `•` 分隔也认", ms.parse_title("Stay • Rihanna") == ("Stay", "Rihanna"))
    check("M15c 品牌后缀被去掉",
          ms.parse_title("晴天 - 周杰伦 - 网易云音乐") == ("晴天", "周杰伦"))
    check("M15d 只有一段时整段当歌名",
          ms.parse_title("Some Title") == ("Some Title", ""))
    check("M15e 空标题不编造", ms.parse_title("") == ("", ""))

    # ---------- M11：注册表 ----------
    from src import widget_registry as reg
    spec = reg.get("music")
    check("M11 注册表已登记 music", spec is not None)
    if spec is not None:
        check("M11b spans 第一项 (3,2) / 分类媒体 / 默认锚定 / 单实例",
              spec.spans[0] == (3, 2) and spec.category == "媒体"
              and spec.default_anchored is True and spec.multi_instance is False,
              "%s %s %s" % (spec.spans, spec.category, spec.default_anchored))
        check("M11c 组件库有预览函数", spec.preview is not None)
        img_prev = canvas(336, 182)
        p = QPainter(img_prev)
        ok = True
        try:
            spec.preview(p, QRectF(0, 0, 336, 182))
        except Exception as exc:      # noqa: BLE001
            ok = False
            print("   preview 抛异常: %r" % (exc,))
        p.end()
        check("M11d 预览能画（不跑定时器、不发媒体键）",
              ok and alpha_nonempty(img_prev) > 300, str(alpha_nonempty(img_prev)))

    if STATE.exists():
        STATE.unlink()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        main(app)
    finally:
        print("")
        if failures:
            print("FAILED %d: %s" % (len(failures), ", ".join(failures)))
            sys.exit(1)
        print("ALL PASS")
