"""选筋建议：由计算 As 推荐实配方案（附录C 表C-1/表C-2），支持题目约束过滤。

梁（例3-1做法）：单层布筋，排布宽度 = 2×侧保护层 + n·d + (n-1)×净距 ≤ b
板（表C-2算法）：每米板宽 As = A_d×1000/s，间距取表C-2 系列。
约束参数（均为可选，默认=原行为）：
  dias      —— 允许直径列表（题目限定“采用Φ18~Φ25”时传入子集）
  allow_double —— 单层排不下时给双层方案行
  s_range   —— 板允许间距区间 (min, max)
  total_b   —— 板按板宽给总根数列（None 表示不给）
"""

import math

from . import spec_data
from .drawing import split_layers

SIDE_COVER = spec_data.construction("beam_side_cover_mm")        # 侧保护层 45mm
CLEAR_SPACING = spec_data.construction("beam_min_clear_spacing_mm")  # 净距 25mm

SLAB_SPACINGS = (70, 75, 80, 85, 90, 95, 100, 110, 120, 125, 130, 140, 150,
                 160, 170, 180, 190, 200, 220, 240, 250, 260, 280, 300, 320, 330)
BEAM_DIAS = (12, 14, 16, 18, 20, 22, 25)
SLAB_DIAS = (6, 8, 10, 12, 14)


def beam_bar_options(As, b, max_show=4, dias=None, allow_double=False):
    """梁布筋建议，按富余率升序返回至多 max_show 组。"""
    dias = tuple(dias) if dias else BEAM_DIAS
    opts = []
    for d in dias:
        A = spec_data.bar_area(d)
        n_min = max(2, math.ceil(As / A - 1e-9))
        n_max = int((b - 2 * SIDE_COVER + CLEAR_SPACING) // (d + CLEAR_SPACING))
        if n_max < n_min:
            continue
        for n in range(n_min, min(n_max, n_min + 2) + 1):
            width = 2 * SIDE_COVER + n * d + (n - 1) * CLEAR_SPACING
            An = spec_data.bar_area_n(d, n)      # 表C-1 多根列（教材手算查表习惯）
            opts.append({"id": "tmp", "dia": f"Φ{d}", "cnt": f"{n}根",
                         "area": f"{An:.0f} mm²",
                         "margin": f"{An / As:.2f}",
                         "fit": f"{width:.0f} ≤ {b:.0f} ✓"})
    if not opts and allow_double:
        # 双层方案：总根数均分两排，逐层校验排布宽度——同样要满足两侧保护层
        # （例3-1 排布宽度算法：2×45+n·d+(n-1)×25 ≤ b）
        for d in dias:
            A = spec_data.bar_area(d)
            n_total = max(4, math.ceil(As / A - 1e-9))
            layers = split_layers(d, n_total, b, SIDE_COVER + 10)
            widths = [n * d + (n - 1) * CLEAR_SPACING for _, n in layers]
            if any(w > b - 2 * SIDE_COVER for w in widths):
                continue
            An = spec_data.bar_area_n(d, n_total)
            opts.append({"id": "tmp", "dia": f"Φ{d}", "cnt": f"{n_total}根",
                         "area": f"{An:.0f} mm²",
                         "margin": f"{An / As:.2f}",
                         "fit": "双层 " + "/".join(f"{w:.0f}" for w in widths)
                                + f" ≤ {b:.0f} ✓"})
    opts.sort(key=lambda o: (float(o["margin"]), int(o["dia"][1:])))
    for idx, o in enumerate(opts):
        o["id"] = f"b{idx}"          # 排序后统一编号，保证全局唯一
    return opts[:max_show]


def slab_bar_options(As, max_show=5, dias=None, s_range=None, total_b=None):
    """板选筋建议：直径@间距（间距取表C-2 系列），按富余率升序。"""
    dias = tuple(dias) if dias else SLAB_DIAS
    opts = []
    for d in dias:
        A = spec_data.bar_area(d)
        s_max = A * 1000.0 / As
        for s in SLAB_SPACINGS:
            if s_range and not (s_range[0] <= s <= s_range[1]):
                continue
            if s <= s_max * (1 + 1e-9):
                provided = A * 1000.0 / s
                row = {"id": "tmp", "spec": f"Φ{d}@{s}",
                       "area": f"{provided:.0f} mm²/m",
                       "margin": f"{provided / As:.2f}"}
                if total_b:
                    row["total"] = f"{max(2, round(total_b / s))}根"
                opts.append(row)
    opts.sort(key=lambda o: (float(o["margin"]), -int(o["spec"].split("@")[1])))
    for idx, o in enumerate(opts):
        o["id"] = f"s{idx}"          # 统一编号，保证全局唯一
    return opts[:max_show]
