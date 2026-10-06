"""配筋图几何精度校验：SVG 像素解码回 mm，断言与设计参数一致（±容差）。"""

import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel.drawing import BAR, beam_svg, slab_svg


def _rects(svg):
    return [(float(m[0]), float(m[1]), float(m[2]), float(m[3]))
            for m in re.findall(
                r'<rect x="([-\d.]+)" y="([-\d.]+)" width="([\d.]+)" height="([\d.]+)"', svg)]


def _circles(svg):
    return [(float(m[0]), float(m[1]), float(m[2]))
            for m in re.findall(
                r'<circle cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"', svg)]


def test_beam_geometry_3_1():
    """例3-1：b=200,h=400,cs=45，3Φ16 单层——解码回 mm 校验。"""
    svg = beam_svg(200, 400, 45, [(16, 3)], label="3Φ16", stirrup_c=35)
    rx, ry, rw, rh = _rects(svg)[0]                 # 外轮廓
    s = rw / 200.0
    assert abs(rw / rh - 200 / 400) < 0.01, "宽高比例应等于 b:h"
    cs_ = _circles(svg)
    assert len(cs_) == 3
    xs = sorted((cx - rx) / s for cx, _, _ in cs_)          # → mm
    bottoms = sorted(400 - (cy - ry) / s for _, cy, _ in cs_)  # 距底 mm
    assert all(abs(a - b) < 0.8 for a, b in zip(xs, (59, 100, 141))), xs
    assert all(abs(v - 53) < 0.8 for v in bottoms), bottoms   # cs+d/2=45+8
    spacing = xs[1] - xs[0]
    assert abs(spacing - 41) < 0.6, spacing                    # d+净距=16+25
    assert abs(sum(xs) / 3 - 100) < 1.0, "钢筋行应关于截面中线对称"
    # 箍筋内缩 = 保护层 c=35（不是 cs=45）
    stirrup = _rects(svg)[1]
    assert abs((stirrup[0] - rx) / s - 35) < 0.8, "箍筋应内缩 c=35"
    # 教材式引出线：粗体标注 + ≥2 条主色引线 + b/h 尺寸
    assert 'font-weight="bold"' in svg and ">3Φ16<" in svg
    n_leader = len(re.findall(rf'<line[^>]*stroke="{BAR}"', svg))
    assert n_leader >= 2, f"引出线（基线+斜线）缺失: {n_leader}"
    assert ">b=200<" in svg and ">h=400<" in svg


def test_beam_double_layer_centroid():
    """双层布筋：两层形心应落在 as = cs+35（式3-20b）。"""
    svg = beam_svg(250, 550, 45, [(20, 3), (20, 2)], stirrup_c=35)
    rx, ry, rw, rh = _rects(svg)[0]
    s = rw / 250.0
    cs_ = _circles(svg)
    assert len(cs_) == 5
    from_bottom = sorted({round(550 - (cy - ry) / s, 1) for _, cy, _ in cs_})
    assert len(from_bottom) == 2, from_bottom
    b0, b1 = from_bottom
    assert abs(b0 - (45 + 20 / 2)) < 1.2, f"底层圆心 {b0} ≠ cs+d/2=55"
    assert abs(b1 - (45 + 70 - 20 / 2)) < 1.2, f"上层圆心 {b1} ≠ cs+70-d/2=105"
    centroid = (b0 + b1) / 2
    assert abs(centroid - (45 + 35)) < 1.2, f"形心 {centroid} 应=cs+35=80"


def test_beam_doubly_comp_bars():
    """双筋复核（例3-8 式样）：6Φ20 双层 + 3Φ18 受压筋，圆心距顶边 = a′s = 49mm。"""
    svg = beam_svg(250, 600, 40, [(20, 3), (20, 3)], label="6Φ20（双层）",
                   comp=(18, 3), comp_as=49)
    rx, ry, rw, rh = _rects(svg)[0]
    s = rw / 250.0
    assert abs(rw / rh - 250 / 600) < 0.01
    cs_ = _circles(svg)
    assert len(cs_) == 9, f"6 受拉 + 3 受压 = 9 根，实得 {len(cs_)}"
    from_top = sorted(round((cy - ry) / s, 1) for _, cy, _ in cs_)
    # 受压筋一行 3 根：距顶 49mm
    comp_row = [v for v in from_top if v < 100]
    assert len(comp_row) == 3 and all(abs(v - 49) < 0.8 for v in comp_row), comp_row
    # 受拉双层：距底 50/100 → 形心 75（= as）
    from_bottom = sorted({round(600 - v, 1) for v in from_top if v > 400})
    assert len(from_bottom) == 2, from_bottom
    assert abs(from_bottom[0] - 50) < 1.0 and abs(from_bottom[1] - 100) < 1.0, from_bottom
    assert abs(sum(from_bottom) / 2 - 75) < 1.0, "受拉两层形心应 = as = 75"
    # 受压筋行居中：x 关于截面中线对称，净距 = 25
    xs = sorted((cx - rx) / s for cx, cy, _ in cs_ if (cy - ry) / s < 100)
    assert len(xs) == 3 and abs(sum(xs) / 3 - 125) < 1.0, xs
    assert abs((xs[1] - xs[0]) - (18 + 25)) < 0.6, xs
    # 标注与尺寸：受压筋 nΦd 引出 + a′s 尺寸线
    assert ">3Φ18<" in svg, "受压筋标注缺失"
    assert 'a′<tspan' in svg, "a′s 尺寸线缺失"
    assert ">b=250<" in svg and ">h=600<" in svg


def test_beam_doubly_no_comp_unchanged():
    """comp=None 时与单筋图完全一致（不引入任何受压筋元素）。"""
    svg_a = beam_svg(250, 600, 40, [(20, 3), (20, 3)], label="6Φ20（双层）")
    svg_b = beam_svg(250, 600, 40, [(20, 3), (20, 3)], label="6Φ20（双层）",
                     comp=None, comp_as=None)
    assert svg_a == svg_b
    assert len(_circles(svg_a)) == 6


def test_beam_draw_animation_classes():
    """画出动画：animate=True 加 nz-draw/pathLength 与 nz-dot stagger；默认输出逐字节不变。"""
    plain = beam_svg(250, 600, 40, [(20, 3), (20, 3)], label="6Φ20（双层）",
                     comp=(18, 3), comp_as=49)
    anim = beam_svg(250, 600, 40, [(20, 3), (20, 3)], label="6Φ20（双层）",
                    comp=(18, 3), comp_as=49, animate=True)
    # 默认（不传/False）与历史输出逐字节一致：无任何动画类
    assert "nz-" not in plain and 'pathLength' not in plain
    # 动画版：轮廓+箍筋描边、9 根钢筋点带序号（stagger 上限封顶）
    assert anim.count('class="nz-draw"') == 1
    assert 'class="nz-draw nz-stirrup"' in anim
    assert anim.count('pathLength="1"') == 2
    assert anim.count('class="nz-dot"') == 9
    assert '--i:0' in anim and '--i:8' in anim
    # 几何不变：动画版与静态版解出的钢筋坐标一致
    assert _circles(anim) == _circles(plain)
    # 板图：受力筋折线描边 + 分布筋弹入；默认同样逐字节不变
    s_plain = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=2800, b_mm=1000)
    s_anim = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=2800, b_mm=1000,
                      animate=True)
    assert "nz-" not in s_plain
    assert s_anim.count('class="nz-draw"') == 1
    assert 'class="nz-draw nz-stirrup"' in s_anim
    assert s_anim.count('class="nz-dot"') >= 4


def test_slab_textbook_style():
    """板图（教材图3-23(b) 纵剖面式）：受力筋折线、分布筋@250、l0 与板厚尺寸。"""
    svg = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=2800, b_mm=1000)
    # 教材式双向标注
    assert ">Φ10@170<" in svg and ">Φ6@250<" in svg
    assert 'font-weight="bold"' in svg
    # 受力筋：连续折线（6 个顶点：弯折-底线-弯折）
    m = re.search(r'<path d="M ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+) '
                  r'L ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+) L ([\d.]+) ([\d.]+) '
                  r'L ([\d.]+) ([\d.]+)"', svg)
    assert m, "受力筋折线缺失"
    pts = [(float(m.group(i)), float(m.group(i + 1))) for i in range(1, 12, 2)]
    y_line = pts[2][1]
    assert abs(y_line - pts[3][1]) < 0.1, "底线应水平"
    assert pts[0][0] > pts[2][0] and pts[4][0] > pts[2][0], "两端弯折应从板端向内"
    # 底线位置反解 as_（板厚方向 s_y = 26/h）
    rx, ry, rw, rh = _rects(svg)[0]
    s_y = rh / 100.0
    as_dec = 100 - (y_line - ry) / s_y
    assert abs(as_dec - 30) < 1.5, f"底线对应 as={as_dec} ≠ 30"
    # 分布筋圆点：间距解码 = 250mm（跨度方向 s_x = rw/L）
    s_x = rw / 2800.0
    xs = sorted(cx for cx, _, _ in _circles(svg))
    assert len(xs) >= 3, "分布筋圆点太少"
    gaps = [b - a for a, b in zip(xs, xs[1:])]
    assert all(abs(g / s_x - 250) < 4 for g in gaps), [g / s_x for g in gaps]
    # 跨度、板厚与板宽尺寸 + 平面网格（教材图3-23(b)）+ 响应式宽度
    assert ">2800<" in svg and ">100<" in svg and ">1000<" in svg
    assert len(_rects(svg)) >= 2, "应有剖面 + 平面两个框"
    assert svg.count(f'stroke="{BAR}"') >= 10, "平面网格线数量不足"
    assert 'width="100%"' in svg and "max-width" in svg


def test_slab_without_l0():
    """未给 l0 时不出跨度尺寸（也不得出现臆造的默认 3000），但基本元素仍在。"""
    svg = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=None)
    assert "<path" in svg and ">Φ6@250<" in svg
    assert ">2800<" not in svg
    assert ">3000<" not in svg, "无 l0 时不应画出臆造的 3000 跨度尺寸"
    # 尺寸行不画时，底部布局应收紧（不保留跨度尺寸的空白）
    hts = [float(m.group(1)) for m in re.finditer(r'viewBox="0 0 [\d.]+ ([\d.]+)"', svg)]
    svg_with = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=2800)
    ht_with = float(re.search(r'viewBox="0 0 [\d.]+ ([\d.]+)"', svg_with).group(1))
    assert hts and hts[0] < ht_with, "无跨度尺寸时图高应更紧凑"


def test_slab_leader_aim_and_plan_spacing():
    """受力筋引线应指底线（非分布筋点高），平面横线严格按 @间距 布线。"""
    svg = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=2800, b_mm=1000)
    # 引线：label 后第一行是基线、第二条是斜线，终点=(x2,y2)
    m = re.search(
        r'>Φ10@170</text><line[^>]*/><line x1="[\d.]+" y1="[\d.]+" '
        r'x2="([\d.]+)" y2="([\d.]+)"', svg)
    assert m, "受力筋引线结构缺失"
    ty = float(m.group(2))
    # 底线 y=94.2、圆点 cy=89.2：终点必须落底线附近且明显低于圆点
    assert 94.0 <= ty <= 96.0, f"引线终点 y={ty}，应指向底线≈94.2 而非圆点89.2"
    # 平面横线间距 = spacing × 板宽比例尺(34px/1000mm) = 170×0.034
    rows = re.findall(
        r'<line x1="([\d.]+)" y1="([\d.]+)" x2="([\d.]+)" y2="([\d.]+)"', svg)
    ys = sorted({float(a[1]) for a in rows
                 if a[1] == a[3] and 10 <= float(a[1]) <= 50
                 and float(a[0]) < 300 and float(a[2]) - float(a[0]) > 50})
    gaps = [b - a for a, b in zip(ys, ys[1:])]
    assert len(gaps) >= 5, f"平面横线过少: {len(ys)}"
    expect = 170 * (40 - 6) / 1000
    assert all(abs(g - expect) < 0.2 for g in gaps), (gaps, expect)


def test_slab_leaders_avoid_dots():
    """受力筋引线落点应在两圆点间隙内（不蹭点）且短陡；分布筋标注锚在左下角。"""
    svg = slab_svg(100, 30, 10, 170, label="Φ10@170", l0_mm=2800, b_mm=1000)
    m = re.search(
        r'>Φ10@170</text><line[^>]*/><line x1="([\d.]+)" y1="([\d.]+)" '
        r'x2="([\d.]+)" y2="([\d.]+)"', svg)
    assert m, "受力筋引线结构缺失"
    jx, jy = float(m.group(1)), float(m.group(2))   # 基线接点
    tx, ty = float(m.group(3)), float(m.group(4))   # 落点
    dots = [float(x) for x in re.findall(r'<circle cx="([\d.]+)" cy="89', svg)]
    assert dots, "圆点缺失"
    assert min(abs(tx - d) for d in dots) > 4, f"引线落点 {tx} 距圆点过近: {dots}"
    assert abs(tx - jx) <= 1.5 * abs(ty - jy) + 1e-6, "引线过平（教材为短陡线）"
    i2 = svg.index(">Φ6@250</text>")
    x2 = float(re.findall(r'<text x="([\d.]+)"', svg[:i2])[-1])  # 最后一个=text自身
    assert x2 < 60, f"分布筋标注应锚在左下角，实际 x={x2}"


def test_beam_double_rows_fit_section():
    """回归：双层方案按两排绘制且全部圆点在截面内（14Φ14@b=250 溢出事故）。"""
    svg = beam_svg(250, 500, 45, [(14, 7), (14, 7)], stirrup_c=35)
    rx, ry, rw, rh = _rects(svg)[0]
    scale = rw / 250.0
    cs_ = _circles(svg)
    assert len(cs_) == 14
    for cx, cy, _ in cs_:
        x = (cx - rx) / scale
        y_fb = 500 - (cy - ry) / (rh / 500.0)
        assert 0 <= x <= 250 and 0 <= y_fb <= 500
    rows = sorted({round(500 - (cy - ry) / (rh / 500.0), 1) for _, cy, _ in cs_})
    assert len(rows) == 2, rows


def test_beam_autosplit_single_overflow():
    """兜底：调用方误传排不下的单层（14Φ14@b=250）自动均分两排，不出截面。"""
    svg = beam_svg(250, 500, 45, [(14, 14)], stirrup_c=35)
    rx, ry, rw, _ = _rects(svg)[0]
    scale = rw / 250.0
    cs_ = _circles(svg)
    assert len(cs_) == 14
    for cx, _, _ in cs_:
        x = (cx - rx) / scale
        assert -0.5 <= x <= 250.5


def test_beam_oversize_guard():
    """病态根数（10^6 根）不逐根绘制：毫秒级返回兜底图，绝不阻塞事件循环。"""
    import time
    from kernel import drawing
    t0 = time.perf_counter()
    svg = beam_svg(250, 500, 35, [(20, 10**6)], label="1000000Φ20")
    assert time.perf_counter() - t0 < 0.5
    assert "<circle" not in svg and "未绘制" in svg
    assert drawing._MAX_BARS < 10**6


def test_slab_oversize_guard():
    """病态跨度/板宽不死循环：分布筋点与网格线数量受上限约束。"""
    import time
    from kernel import drawing
    t0 = time.perf_counter()
    svg = slab_svg(120, 29, 8, 120, l0_mm=10**9, b_mm=1000)
    assert time.perf_counter() - t0 < 0.5
    assert svg.count("<circle") <= drawing._MAX_LINES
    svg2 = slab_svg(120, 29, 8, 1, l0_mm=3780, b_mm=10**9)
    assert svg2.count("<line") <= 2 * drawing._MAX_LINES + 20
