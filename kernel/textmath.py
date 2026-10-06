"""数学排版辅助（纯字符串，零依赖）：HTML 分式/根号/上下标 与 纯文本计算书格式。"""

import math


def fmt(x, sig=4):
    """按有效数字格式化，常规量级不用科学计数法，并去掉尾零。"""
    if x is None:
        return "—"
    if x == 0:
        return "0"
    a = abs(x)
    if a >= 1e6 or a < 1e-4:
        return f"{x:.{sig}g}"
    digits_before = int(math.floor(math.log10(a))) + 1
    decimals = max(0, sig - digits_before)
    s = f"{x:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


HTML_KW = dict(sanitize=False)


def frac(num, den):
    """上下结构的分式（HTML）。"""
    return (f'<span style="display:inline-block;vertical-align:middle;text-align:center;'
            f'line-height:1.18;margin:0 3px;">'
            f'<span style="display:block;border-bottom:1.3px solid currentColor;'
            f'padding:0 5px 1px;">{num}</span>'
            f'<span style="display:block;padding:1px 5px 0;">{den}</span></span>')


def sqrt_(inner):
    """带顶线的根号（HTML）。"""
    return (f'<span style="white-space:nowrap;">√<span style="border-top:1.3px solid '
            f'currentColor;padding:0 3px;">{inner}</span></span>')


def html_block(lines):
    """多行公式排版：每行独立成块，行距舒展。"""
    return "".join(f'<div style="margin:6px 0;">{l}</div>' for l in lines)


def kpi_row(items):
    """仪表盘式大数字摘要行：items = [(说明, 数值, 单位[, 悬停释义])]。

    第 4 项是鼠标悬停才出现的释义气泡（.nz-tip，样式在 main.py）：
    不占版面、不改动任何数值与排版，只为解释"这个数是什么、怎么来的"。
    """
    cells = []
    for it in items:
        cap, val, unit = it[0], it[1], it[2]
        tip = it[3] if len(it) > 3 else ""
        attr = f' class="nz-tip" data-tip="{tip}"' if tip else ""
        cells.append(
            f'<div{attr}><div style="font-size:12px;color:#78909c;margin-bottom:2px;">{cap}</div>'
            f'<div style="font-size:24px;font-weight:700;color:#155e94;line-height:1.15;">{val}'
            f'<span style="font-size:13px;font-weight:500;color:#546e7a;">　{unit}</span></div></div>')
    return f'<div style="display:flex;gap:36px;flex-wrap:wrap;margin:8px 0;">{"".join(cells)}</div>'


def info_label(t):
    """信息行行首的分类标签。"""
    return f'<span style="color:#78909c;font-weight:600;">{t}</span>'


def pfrac(num, den):
    """纯文本分式（计算书用）。"""
    return f"({num})/({den})"


def pct(x, dec=2):
    """百分数，固定小数位（保留尾零：0.20% 而非 0.2%，与教材写法一致）。"""
    return f"{x * 100:.{dec}f}%"
