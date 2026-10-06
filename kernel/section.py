"""截面几何：as 与 h0 的确定（式 3-20）。

cs 的取法（教材 3.4 节）：
  梁：cs = c + 箍筋直径（箍筋直径预估计入 construction.stirrup_dia_assumed_mm，一般 10mm）
  板：cs = c（板中纵向受力钢筋为最外层钢筋）
as 的取法：
  单层：as = cs + d/2
  双层：as = cs + 35（式 3-20b，层间净距 35mm）
h0 = h - as
"""


def cs_beam(c, stirrup_dia=10.0):
    """梁截面设计时最外层纵筋外表面至构件表面的距离 cs。"""
    return c + stirrup_dia


def cs_slab(c):
    """板中纵向受力钢筋为最外层钢筋，cs = c。"""
    return c


def effective_depth(h, cs, bar_dia=0.0, layers=1, layer_gap=35.0):
    """按式(3-20)计算受拉钢筋合力点至截面受拉边缘的距离 as 及有效高度 h0。

    layers=1: as = cs + d/2（需给 bar_dia）
    layers=2: as = cs + layer_gap（式3-20b，与直径无关，教材例3-3取法）
    返回 (as, h0)。
    """
    if layers == 1:
        as_ = cs + bar_dia / 2.0
    elif layers == 2:
        as_ = cs + layer_gap
    else:
        raise ValueError("单筋矩形截面仅支持单层(layers=1)或双层(layers=2)受拉钢筋布置")
    return as_, h - as_
