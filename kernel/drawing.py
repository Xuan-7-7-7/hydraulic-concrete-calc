"""截面配筋图 SVG 生成（纯字符串，零第三方依赖）。

坐标体系：构件轮廓按真实 mm 值等比缩放绘制（板厚方向按制图惯例放大），
钢筋位置全部由 c/cs、直径、根数、间距等真实参数推出，非示意。

表达参照教材《水工钢筋混凝土结构学》第3章出图惯例：
  · 标注 = 文字 + 水平基线 + 斜引出线指向钢筋（图3-22、图3-23）
  · 梁：轮廓 + 箍筋（内缩保护层 c）+ 纵筋圆点 + b/h/as 尺寸
  · 板（纵剖面，同图3-23(b)）：受力筋底线带端部弯折、分布筋 Φ6@250 圆点、
    板厚（右）与跨度（下）尺寸；厚度方向放大绘制（制图惯例）。
"""

import math

from .singly_rect import Mu_of_rho

BAR = "#155e94"       # 纵筋/受力筋
STIRRUP = "#ef6c00"   # 箍筋
OUTLINE = "#37474f"   # 构件轮廓
DIM = "#90a4ae"       # 尺寸线
TEXT = "#455a64"      # 文字

_CLEAR = 25           # 梁内纵筋净距（构造）
_DIST_DIA = 6         # 板构造分布筋直径
_DIST_SPACING = 250   # 板构造分布筋间距（图3-23：Φ6@250）
_MAX_BARS = 60        # 纵筋逐根绘制上限（病态根数 → 百万级循环会阻塞事件循环）
_MAX_LINES = 120      # 分布筋/网格线数上限（病态跨度同理）


def _oversize_note(b, h, total):
    """病态输入的兜底图：只画截面轮廓 + 说明，不逐根绘制。"""
    w, ht = 320, 150
    return (f'<svg viewBox="0 0 {w} {ht}" width="100%" '
            f'style="max-width:{w}px;height:auto" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<rect x="24" y="18" width="{w - 48}" height="72" fill="white" '
            f'stroke="{OUTLINE}" stroke-width="2"/>'
            f'<text x="{w / 2}" y="118" font-size="13" text-anchor="middle" '
            f'font-family="system-ui, sans-serif" fill="#b71c1c">'
            f'根数过多（合计 {total} 根，{b:g}×{h:g}），未绘制配筋</text></svg>')


def _circle(cx, cy, r_mm, s, dx, dy, fill=BAR, min_px=2.0, animate=False, idx=0):
    r = max(r_mm * s, min_px)
    if animate:
        return (f'<circle cx="{dx + cx * s:.1f}" cy="{dy + cy * s:.1f}" '
                f'r="{r:.1f}" fill="{fill}" stroke="{OUTLINE}" stroke-width="0.8" '
                f'class="nz-dot" style="--i:{idx}"/>')
    return (f'<circle cx="{dx + cx * s:.1f}" cy="{dy + cy * s:.1f}" '
            f'r="{r:.1f}" fill="{fill}" stroke="{OUTLINE}" stroke-width="0.8"/>')


def _line(x1, y1, x2, y2, s, dx, dy, stroke=DIM, width=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{dx + x1 * s:.1f}" y1="{dy + y1 * s:.1f}" '
            f'x2="{dx + x2 * s:.1f}" y2="{dy + y2 * s:.1f}" '
            f'stroke="{stroke}" stroke-width="{width}"{d}/>')


def _text(x, y, s, dx, dy, txt, size=12, anchor="middle", color=TEXT, weight="normal"):
    return (f'<text x="{dx + x * s:.1f}" y="{dy + y * s:.1f}" font-size="{size}" '
            f'font-family="system-ui, sans-serif" text-anchor="{anchor}" '
            f'fill="{color}" font-weight="{weight}">{txt}</text>')


def _arrow_head(x, y, s, dx, dy, direction):
    """尺寸箭头（小三角），direction: left/right/up/down。"""
    L, W = 8, 3.2
    x, y = dx + x * s, dy + y * s
    pts = {
        "right": f"{x},{y} {x - L},{y - W} {x - L},{y + W}",
        "left":  f"{x},{y} {x + L},{y - W} {x + L},{y + W}",
        "down":  f"{x},{y} {x - W},{y - L} {x + W},{y - L}",
        "up":    f"{x},{y} {x - W},{y + L} {x + W},{y + L}",
    }[direction]
    return f'<polygon points="{pts}" fill="{DIM}"/>'


def _dim_h(x1, x2, y_mm, s, dx, dy, txt, text_above=True):
    """水平尺寸线：主线上两箭头 + 端部界线 + 居中文字（mm 坐标输入）。"""
    out = [_line(x1, y_mm, x2, y_mm, s, dx, dy),
           _arrow_head(x1, y_mm, s, dx, dy, "left"),
           _arrow_head(x2, y_mm, s, dx, dy, "right"),
           _line(x1, y_mm - 6 / s, x1, y_mm + 6 / s, s, dx, dy),
           _line(x2, y_mm - 6 / s, x2, y_mm + 6 / s, s, dx, dy)]
    ty = y_mm - (10 / s if text_above else -16 / s)
    out.append(_text((x1 + x2) / 2, ty, s, dx, dy, txt, size=12))
    return "".join(out)


def _dim_v(y1, y2, x_mm, s, dx, dy, txt, side="right"):
    """竖直尺寸线：文字水平放在线旁。"""
    out = [_line(x_mm, y1, x_mm, y2, s, dx, dy),
           _arrow_head(x_mm, y1, s, dx, dy, "up"),
           _arrow_head(x_mm, y2, s, dx, dy, "down"),
           _line(x_mm - 6 / s, y1, x_mm + 6 / s, y1, s, dx, dy),
           _line(x_mm - 6 / s, y2, x_mm + 6 / s, y2, s, dx, dy)]
    tx = dx + x_mm * s + (8 if side == "right" else -8)
    anchor = "start" if side == "right" else "end"
    out.append(f'<text x="{tx:.1f}" y="{dy + (y1 + y2) / 2 * s + 4:.1f}" font-size="12" '
               f'font-family="system-ui, sans-serif" text-anchor="{anchor}" '
               f'fill="{TEXT}">{txt}</text>')
    return "".join(out)


def _leader(x0, y0, x1, y1, txt, size=13):
    """教材式引出线标注：文字 + 水平基线 + 斜线指向 (x1, y1)（均为像素坐标）。"""
    w = _text_w(txt, size)
    return "".join([
        f'<text x="{x0:.1f}" y="{y0:.1f}" font-size="{size}" '
        f'font-family="system-ui, sans-serif" font-weight="bold" fill="{BAR}">{txt}</text>',
        f'<line x1="{x0:.1f}" y1="{y0 + 3.5:.1f}" x2="{x0 + w:.1f}" y2="{y0 + 3.5:.1f}" '
        f'stroke="{BAR}" stroke-width="1.1"/>',
        f'<line x1="{x0 + w:.1f}" y1="{y0 + 3.5:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
        f'stroke="{BAR}" stroke-width="1.1"/>',
    ])


def _text_w(txt, size):
    """文字宽度估算：CJK 全角按 1.0×size，ASCII 按 0.62×size，外加 6px 余量。"""
    return sum(size * (1.0 if ord(ch) > 0x2E7F else 0.62) for ch in txt) + 6


def beam_svg(b, h, cs, layers, label=None, clear=_CLEAR, out_w=320, out_h=330,
             stirrup_c=None, comp=None, comp_as=None, animate=False):
    """梁截面配筋图。layers: [(直径, 根数), ...] 自底层向上。

    精度约定：
      · 底层圆心 = h − cs − d/2；双层时上层圆心 = h − (cs + 70 − d/2)，
        使两层形心恰在 as = cs+35（式3-20b）。
      · 箍筋内缩 = 保护层 c（stirrup_c，缺省退回 cs）。
      · 每层按净距 clear 居中排布（与例3-1 排布宽度验算一致）。
      · comp=(直径, 根数) 时在顶部绘制单层受压钢筋，圆心距顶边 = comp_as
        （a′s，教材双筋截面图3-5 式样），并加 a′s 尺寸与「nΦd」引出标注。
      · animate=True 时加画出动画类（nz-draw 描边 + nz-dot 弹入 stagger），
        CSS 在 main.py；默认 False 时输出与原来逐字节一致。
    """
    layers = list(layers)
    total = sum(int(n) for _, n in layers)
    if total > _MAX_BARS:
        return _oversize_note(b, h, total)
    pad_l, pad_r, pad_t, pad_b = 56, 74, 44, 50
    s = min((out_w - pad_l - pad_r) / b, (out_h - pad_t - pad_b) / h)
    dx, dy = pad_l, pad_t
    w = pad_l + b * s + pad_r
    ht = pad_t + h * s + pad_b
    p = [f'<svg viewBox="0 0 {w:.0f} {ht:.0f}" width="100%" '
         f'style="max-width:{w:.0f}px;height:auto" '
         f'xmlns="http://www.w3.org/2000/svg">']
    # 轮廓与箍筋（animate 时 pathLength=1 供 stroke-dashoffset 描边动画）
    pl = ' pathLength="1"' if animate else ""
    cls_o = ' class="nz-draw"' if animate else ""
    p.append(f'<rect x="{dx}" y="{dy}" width="{b * s:.1f}" height="{h * s:.1f}" '
             f'fill="white" stroke="{OUTLINE}" stroke-width="2"{pl}{cls_o}/>')
    si = stirrup_c if stirrup_c is not None else cs
    r = min(2.5 * 10 * s, 12)
    stir_cls = ' class="nz-draw nz-stirrup"' if animate else ""
    p.append(f'<rect x="{dx + si * s:.1f}" y="{dy + si * s:.1f}" '
             f'width="{(b - 2 * si) * s:.1f}" height="{(h - 2 * si) * s:.1f}" rx="{r:.1f}" '
             f'fill="none" stroke="{STIRRUP}" stroke-width="1.2"{pl}{stir_cls}/>')
    # 纵筋
    layers = list(layers)
    if len(layers) == 1 and layers[0][1] >= 4:
        d0, n0 = layers[0]
        if n0 * d0 + (n0 - 1) * clear > b - 2 * cs:
            # 兜底：调用方传入排不下的单层时自动均分两排（钢筋绝不允许画出截面）
            layers = split_layers(d0, n0, b, cs)
    centers = []
    idx = 0
    for li, (d, n) in enumerate(layers):
        if len(layers) >= 2:
            y_from_bottom = (cs + d / 2) if li == 0 else (cs + 70 - d / 2)
        else:
            y_from_bottom = cs + d / 2
        y_mm = h - y_from_bottom
        row_w = n * d + (n - 1) * clear
        x0 = (b - row_w) / 2 + d / 2
        for i in range(n):
            x_mm = x0 + i * (d + clear)
            p.append(_circle(x_mm, y_mm, d / 2, s, dx, dy, animate=animate, idx=idx))
            centers.append((x_mm, y_mm, d))
            idx += 1
    # 标注：教材式引出线指向底层左端钢筋
    if label and centers:
        first = next(c for c in centers if abs(c[1] - (h - (cs + layers[0][0] / 2))) < 1e-6)
        tx, ty = dx - 6, dy - 10
        tgt_x = dx + (first[0] - first[2] / 2 * 0.8) * s
        tgt_y = dy + (first[1] - first[2] / 2) * s - 1.5
        p.append(_leader(tx, ty, tgt_x, tgt_y, label))
    # 受压钢筋（双筋复核）：顶部单层，圆心距顶边 = a′s
    if comp:
        d_c, n_c = comp
        y_from_top = comp_as if comp_as is not None else cs + d_c / 2
        row_w_c = n_c * d_c + (n_c - 1) * clear
        xc0 = (b - row_w_c) / 2 + d_c / 2
        comp_centers = []
        for i in range(n_c):
            x_mm = xc0 + i * (d_c + clear)
            p.append(_circle(x_mm, y_from_top, d_c / 2, s, dx, dy, animate=animate, idx=idx))
            comp_centers.append((x_mm, y_from_top, d_c))
            idx += 1
        # 标注：截面右上引出线指向最右受压筋（文字右移，避开受拉筋标注）
        last = comp_centers[-1]
        tx, ty = dx + b * s + 30, dy - 26
        tgt_x = dx + (last[0] + last[2] / 2 * 0.8) * s
        tgt_y = dy + (last[1] + last[2] / 2) * s + 1.5
        p.append(_leader(tx, ty, tgt_x, tgt_y, f"{n_c}Φ{d_c}"))
    # 尺寸：b（下）、h（右）、as（左）、a′s（左，双筋）
    y_dim = h + 22 / s
    p.append(_dim_h(0, b, y_dim, s, dx, dy, f"b={b:g}"))
    p.append(_dim_v(0, h, b + 26 / s, s, dx, dy, f"h={h:g}", side="right"))
    as_val = (cs + layers[0][0] / 2) if len(layers) == 1 else (cs + 35)
    p.append(_dim_v(h - as_val, h, -26 / s, s, dx, dy,
                    f'a<tspan font-size="9" dy="3">s</tspan>', side="left"))
    if comp and comp_as is not None:
        p.append(_dim_v(0, comp_as, -26 / s, s, dx, dy,
                        f'a′<tspan font-size="9" dy="3">s</tspan>', side="left"))
    p.append("</svg>")
    return "".join(p)


def slab_svg(h, as_, dia, spacing, label=None, l0_mm=None, b_mm=None,
             out_w=360, animate=False):
    """板配筋图（教材图3-23(b) 式样：上平面网格 + 下纵剖面）。

    平面片段：受力筋横线（间距=配筋间距，跨板宽）+ 分布筋竖线（Φ6@250 构造）
              + 左端折断波浪线 + 板宽尺寸（b_mm 给出时）。
    纵剖面：受力筋底线带端部弯折、分布筋圆点、板厚（右）、跨度 l0（下，
            未给 l0 或过短时不出跨度尺寸，避免出现臆造数值）。
    标注：受力筋 label 上方引出线、Φ6@250 下方引出线（文字+基线+斜线）。
    厚度方向放大绘制（板类制图惯例）；SVG 容器自适应宽度。
    """
    L = float(l0_mm) if l0_mm and l0_mm > 3 * h else 3000.0
    show_len = bool(l0_mm and l0_mm > 3 * h)   # 未给 l0 时不出跨度尺寸（示意布局）
    pad_l, pad_r = 78, 66
    s_x = (out_w - pad_l - pad_r) / L
    h_px = 26.0
    s_y = h_px / h
    x0, x1 = pad_l, pad_l + L * s_x
    # 纵向布局（px）
    y_plan0, plan_h = 10.0, 40.0
    y_lab = 64.0                          # 受力筋标注行
    y_sec0 = y_lab + 12                   # 剖面上边
    y_sec1 = y_sec0 + h_px                # 剖面下边
    y_line = y_sec1 - as_ * s_y           # 受力筋底线
    y_hook = y_sec0 + 18 * s_y            # 弯折顶部
    y_dist_lab = y_sec1 + 16              # 分布筋标注行
    y_len = y_sec1 + 34                   # 跨度尺寸线
    ht = (y_len + 30) if show_len else (y_dist_lab + 26)
    w = out_w
    p = [f'<svg viewBox="0 0 {w:.0f} {ht:.0f}" width="100%" '
         f'style="max-width:{w:.0f}px;height:auto" '
         f'xmlns="http://www.w3.org/2000/svg">']

    def line(x1_, y1_, x2_, y2_, stroke=BAR, width=1.0):
        return (f'<line x1="{x1_:.1f}" y1="{y1_:.1f}" x2="{x2_:.1f}" y2="{y2_:.1f}" '
                f'stroke="{stroke}" stroke-width="{width}"/>')

    # ---- 纵剖面（先画，保证 outline 序号在前）
    pl = ' pathLength="1"' if animate else ""
    cls_o = ' class="nz-draw"' if animate else ""
    p.append(f'<rect x="{x0:.1f}" y="{y_sec0:.1f}" width="{x1 - x0:.1f}" '
             f'height="{h_px:.1f}" fill="white" stroke="{OUTLINE}" stroke-width="2"{pl}{cls_o}/>')
    toe = 40 * s_x
    stir_cls = ' class="nz-draw nz-stirrup"' if animate else ""
    p.append(f'<path d="M {x0 + toe:.1f} {y_hook:.1f} L {x0:.1f} {y_hook:.1f} '
             f'L {x0:.1f} {y_line:.1f} L {x1:.1f} {y_line:.1f} '
             f'L {x1:.1f} {y_hook:.1f} L {x1 - toe:.1f} {y_hook:.1f}" '
             f'fill="none" stroke="{BAR}" stroke-width="2.4"{pl}{stir_cls}/>')
    # 分布筋圆点（剖面内，受力筋上方）
    xs = []
    x = x0 + 130 * s_x
    while x <= x1 - 130 * s_x + 1e-6 and len(xs) < _MAX_LINES:
        xs.append(x)
        x += _DIST_SPACING * s_x
    for k, xi in enumerate(xs):
        if animate:
            p.append(f'<circle cx="{xi:.1f}" cy="{y_line - 5:.1f}" r="2.3" fill="{BAR}" '
                     f'stroke="{OUTLINE}" stroke-width="0.8" class="nz-dot" '
                     f'style="--i:{k}"/>')
        else:
            p.append(f'<circle cx="{xi:.1f}" cy="{y_line - 5:.1f}" r="2.3" fill="{BAR}" '
                     f'stroke="{OUTLINE}" stroke-width="0.8"/>')

    # ---- 平面网格片段（上）
    p.append(f'<rect x="{x0:.1f}" y="{y_plan0:.1f}" width="{x1 - x0:.1f}" '
             f'height="{plan_h:.1f}" fill="white" stroke="{OUTLINE}" stroke-width="1.4"/>')
    xb = x0 + (x1 - x0) * 0.26           # 折断线位置（左侧省略）
    zig = [f"M {xb:.1f} {y_plan0 + 2:.1f}"]
    for k, dy in enumerate((8, 15, 22, 29, 36)):
        zig.append(f"L {xb + (5 if k % 2 == 0 else -5):.1f} {y_plan0 + dy:.1f}")
    zig.append(f"L {xb:.1f} {y_plan0 + plan_h - 2:.1f}")
    p.append(f'<path d="{" ".join(zig)}" fill="none" stroke="{OUTLINE}" '
             f'stroke-width="1.2"/>')
    wy = (plan_h - 6) / (b_mm or 1000)                # 宽度方向比例尺 px/mm
    yy = y_plan0 + 3
    yy_step = spacing * wy
    while yy_step > 0 and yy <= y_plan0 + plan_h - 3 + 1e-9 \
            and (yy - y_plan0 - 3) / yy_step < _MAX_LINES:   # 严格按 @spacing 布线
        p.append(line(xb + 7, yy, x1 - 1, yy, stroke=BAR, width=1))
        yy += yy_step
    xx = xb + 7
    xx_step = _DIST_SPACING * s_x
    kx = 0
    while xx_step > 0 and xx <= x1 - 1 and kx < _MAX_LINES:   # 分布筋竖线 @250
        p.append(line(xx, y_plan0 + 1, xx, y_plan0 + plan_h - 1, stroke=BAR, width=1))
        xx += xx_step
        kx += 1

    # ---- 标注（教材式引出线：先定目标、再摆文字——短而陡，且不蹭圆点）
    if label and xs:
        # 受力筋：目标取中部两圆点的间隙中点，文字置于目标左上方（斜线约45°）
        mid = len(xs) // 2
        gap_x = (xs[mid] + xs[mid + 1]) / 2 if mid + 1 < len(xs) else xs[mid]
        tw = len(label) * (13 * 0.60) + 6
        lx = max(4.0, gap_x - tw - 30)
        p.append(_leader(lx, y_lab, gap_x, y_line + 1, label))
    elif label:
        p.append(_leader(max(4.0, x0 - 68), y_lab, x0 + (x1 - x0) * 0.30,
                         y_line + 1, label))
    if xs:
        # 分布筋：文字锚在左下角，短线向右上指向第一个圆点（同教材图3-23(b)）
        tw2 = 7 * (12 * 0.60) + 6
        lx2 = 6.0
        target = next((x for x in xs if x > lx2 + tw2 + 12), xs[0])
        p.append(_leader(lx2, y_dist_lab, target, y_line - 8.5,
                         f"Φ{_DIST_DIA}@{_DIST_SPACING}", size=12))
    # ---- 尺寸
    if b_mm:
        p.append(_dim_v(y_plan0, y_plan0 + plan_h, x1 + 14, 1, 0, 0,
                        f"{b_mm:g}", side="right"))
    p.append(_dim_v(y_sec0, y_sec1, x1 + 14, 1, 0, 0, f"{h:g}", side="right"))
    if show_len:
        p.append(_dim_h(x0, x1, y_len, 1, 0, 0, f"{L:g}", text_above=False))
    p.append("</svg>")
    return "".join(p)


def split_layers(dia, n_total, b, cs, clear=_CLEAR):
    """按梁宽判断单/双层布置：单层排得下用单层，否则均分两排。

    返回 [(直径, 根数), ...]（底层在前）。
    """
    per_layer_max = max(2, int((b - 2 * (cs + 10) + clear) // (dia + clear)))
    if n_total <= per_layer_max:
        return [(dia, n_total)]
    n1 = math.ceil(n_total / 2)
    n2 = n_total - n1
    return [(dia, n1), (dia, n2)] if n2 else [(dia, n1)]


def rho_sweep_svg(rho_now, b, h0, fc, fy, xi_b, rho_min, rho_max, gamma_d,
                  w=560, h=190):
    """破坏形态扫描图：M′ 随配筋率 ρ 的曲线 + 少筋/适筋/超筋三区着色 + 当前点。

    M′(ρ) = Mu_of_rho(ρ)/γd，顶点在 ρ = fc/fy，过顶点后下降（超筋脆性特征）。
    rho_now 为当前设计配筋率（超筋无解时传 None，不画当前点）。
    """
    rho_peak = fc / fy
    x_max = max(1.8 * rho_max, 1.15 * (rho_now or 0.0), 0.55 * rho_peak)
    x_max = min(x_max, 1.3 * rho_peak)
    n = 48
    pts, m_top = [], 0.0
    for i in range(n + 1):
        r = x_max * i / n
        m = Mu_of_rho(r, b, h0, fc, fy) / gamma_d / 1e6      # kN·m
        pts.append((r, m))
        m_top = max(m_top, m)
    m_top *= 1.06
    pl, pr, pt, pb = 44, 12, 16, 30
    sx = (w - pl - pr) / x_max
    sy = (h - pt - pb) / m_top
    X = lambda r: pl + r * sx
    Y = lambda m: pt + (m_top - m) * sy

    def region(x1, x2, color, name):
        return (f'<rect x="{X(x1):.1f}" y="{pt}" width="{(x2-x1)*sx:.1f}" '
                f'height="{h-pt-pb}" fill="{color}"/>'
                + (f'<text x="{X((x1+x2)/2):.1f}" y="{pt+18:.1f}" font-size="12" '
                   f'font-family="system-ui, sans-serif" text-anchor="middle" '
                   f'fill="#78909c">{name}</text>' if (x2-x1)*sx > 30 else ""))

    p = [f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px;height:auto" '
         f'xmlns="http://www.w3.org/2000/svg">']
    p.append(region(0, rho_min, "#fdecea", "少筋"))
    p.append(region(rho_min, rho_max, "#e8f5e9", "适筋"))
    p.append(region(rho_max, x_max, "#fff3e0", "超筋"))
    for rv, lab in ((rho_min, f"ρmin={rho_min*100:.2f}%"), (rho_max, f"ρmax={rho_max*100:.2f}%")):
        p.append(f'<line x1="{X(rv):.1f}" y1="{pt}" x2="{X(rv):.1f}" y2="{h-pb}" '
                 f'stroke="#90a4ae" stroke-width="1" stroke-dasharray="4 3"/>')
        p.append(f'<text x="{X(rv):.1f}" y="{h-pb+13:.1f}" font-size="10.5" '
                 f'font-family="system-ui, sans-serif" text-anchor="middle" fill="#78909c">{lab}</text>')
    p.append(f'<polyline points="{" ".join(f"{X(r):.1f},{Y(m):.1f}" for r, m in pts)}" '
             f'fill="none" stroke="{BAR}" stroke-width="2"/>')
    # 轴与单位
    p.append(f'<line x1="{pl}" y1="{pt}" x2="{pl}" y2="{h-pb}" stroke="{DIM}" stroke-width="1"/>')
    p.append(f'<line x1="{pl}" y1="{h-pb}" x2="{w-pr}" y2="{h-pb}" stroke="{DIM}" stroke-width="1"/>')
    p.append(f'<text x="4" y="{pt+4:.1f}" font-size="10.5" font-family="system-ui, sans-serif" '
             f'fill="{TEXT}">M′/kN·m</text>')
    p.append(f'<text x="{w-pr:.1f}" y="{h-6:.1f}" font-size="10.5" font-family="system-ui, sans-serif" '
             f'text-anchor="end" fill="{TEXT}">ρ = As/(b·h₀)</text>')
    # 当前点
    if rho_now and 0 < rho_now < x_max:
        m_now = Mu_of_rho(rho_now, b, h0, fc, fy) / gamma_d / 1e6
        cx, cy = X(rho_now), Y(m_now)
        p.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="4.2" fill="#e65100" '
                 f'stroke="#fff" stroke-width="1.4"/>')
        anchor = "end" if cx > w - 130 else "start"
        dx = -8 if anchor == "end" else 8
        p.append(f'<text x="{cx+dx:.1f}" y="{cy-8:.1f}" font-size="11.5" '
                 f'font-family="system-ui, sans-serif" font-weight="bold" text-anchor="{anchor}" '
                 f'fill="#e65100">当前 ρ={rho_now*100:.2f}%</text>')
    p.append("</svg>")
    return "".join(p)
