"""题型编排层：单筋矩形截面受弯题（例3-1~3-4 同类）的公共求解流程单入口。

solve_design / solve_verify 接收纯数值 dict（UI 采集），返回：
  - HTML 版本的资料行/弯矩链条/公式过程/判定/KPI/配筋率标尺（界面直接渲染）
  - 纯文本计算书 report（分节：资料→弯矩→配筋/复核→选筋→结论，可一键复制）
  - 结构化 values/r（测试与内联回验用）
输入非法时抛 ValueError（界面统一捕获提示）。
"""

import math
import re

from . import doubly_rect, drawing, loading, section, singly_rect, spec_data
from .rebar import CLEAR_SPACING, SIDE_COVER, beam_bar_options, slab_bar_options
from .textmath import fmt, frac, sqrt_, html_block, kpi_row, info_label, pct

GAMMA_D = spec_data.gamma_d()


def _tag(line, no):
    """式号右挂（教材式淡色小字）。"""
    return (f'{line}<span style="float:right;color:#90a4ae;font-size:12px;'
            f'font-weight:400">{no}</span>')


def _head(text, tag=""):
    """分节小标题（一行加粗小字，无边框）。"""
    t = (f'<span style="float:right;color:#90a4ae;font-size:12px;font-weight:400">'
         f'{tag}</span>' if tag else "")
    return f'<div style="font-weight:700;color:#155e94;font-size:13px">{text}{t}</div>'


def _sec_counter():
    """编号小节计数器：sec('资料') → 「1. 资料」，编号与屏显顺序一致。

    返回 (sec, next_no)：sec(title, tag='') 产小节标题 html；next_no() 只取号
    （给非 html 渲染的选筋标题用）。
    """
    n = [0]

    def sec(title, tag=""):
        n[0] += 1
        return _head(f"{n[0]}. {title}", tag)

    def next_no():
        n[0] += 1
        return n[0]

    return sec, next_no


def _src_tags(source, k=2):
    """从 source 溯源串提取短表号：'附录B 表B-1 …' → '附录B 表B-1'，'表2-4 …' → '表2-4'。"""
    return " ".join(
        re.findall(r"附录[A-Z]|表[\dA-Za-z][\dA-Za-z.\-]*|规范\d+\.\d+", source)[:k])


# 表号 → 数据页表格锚点（附录B/C/D 与 表2-x 的取值表）；未列出的表号保持纯文本
_TBL_KEYS = {"B-1": "B1", "B-2": "B1", "B-3": "B3", "B-5": "B3", "3-1": "B3",
             "D-4": "D4", "D-1": "D1", "C-1": "C1", "C-2": "C2",
             "2-4": "G", "2-5": "G", "2-6": "G", "2-7": "G",
             "3.2": "G", "3.2.3": "G"}          # 规范条款（ψ）也指向分项系数表


def _ref(text, row=None):
    """把文本里的表号（表B-1 / 表D-1 / 表2-4 …）变成可点元素——点击跳到「数据」页并定位。

    row：要定位到的那一行（如"二类""C25""Φ20"）——点开表格后直接闪到该行，不只到整张表。
    只在 HTML 片段上调用（纯文本计算书里保持原样）；未列出的表号保持纯文本。
    """
    def sub(m):
        token = m.group(0)                      # "表B-1" / "规范3.2.3"（按原文显示）
        tbl = token[1:] if token.startswith("表") else token[2:]
        key = _TBL_KEYS.get(tbl)
        if not key:
            return token
        r = f' data-row="{row}"' if row else ""
        return ('<span class="nz-ref" data-tbl="{0}"{1} '
                'title="点击查看该表（数据页签）" '
                "onclick=\"emitEvent('nz_ref', '{0}', '{2}', nzFromTab(), window.scrollY)\">"
                '{3}</span>').format(key, r, row or "", token)
    return re.sub(r"表[\dA-Za-z][\dA-Za-z.\-]*|规范[\d.]+", sub, text)


def _src_tags_ref(source, k, row=None):
    """_src_tags 的可点版（HTML 用；row = 点开后要定位的行，如 C25/HRB400）。"""
    return _ref(_src_tags(source, k), row)


def _src_pair_ref(fc_src, fy_src, fc_row=None, fy_row=None):
    """fc/fy 出处并排的可点版：同 _src_pair 的去重，但两段各自带行定位。"""
    a, b_ = _src_tags(fc_src, 2), _src_tags(fy_src, 2)
    pa = a.split(" ")[0] if " " in a else ""
    if pa and b_.startswith(pa + " "):
        b_ = b_[len(pa) + 1:]
    return f"{_ref(a, fc_row)}、{_ref(b_, fy_row)}"


def _src_pair(fc_src, fy_src):
    """fc/fy 出处并排（教材式“由附录B表B-1及表B-3查得”），同前缀去重。"""
    a, b_ = _src_tags(fc_src, 2), _src_tags(fy_src, 2)
    pa = a.split(" ")[0] if " " in a else ""
    if pa and b_.startswith(pa + " "):
        b_ = b_[len(pa) + 1:]
    return f"{a}、{b_}"


def _f2(x):
    """荷载设计值显示：两位小数，整数值保留一位（2.20 / 5.78 / 48.0，同教材）。"""
    s = f"{x:.2f}"
    return s[:-1] if s.endswith("00") else s


def _f4(x):
    """4 位有效数字、保留尾零（教材 320.0×10⁶ N·mm 型写法，双筋链 M_u 显示用）。"""
    if x == 0:
        return "0"
    return f"{x:.{max(0, 3 - int(math.floor(math.log10(abs(x)))))}f}"


def _h_mod_up(h, member):
    """截面高按模数向上取整（梁50/板10，同 suggest_h 习惯）。"""
    mod = 50 if member == "梁" else 10
    return math.ceil(h / mod) * mod


# ---------------------------------------------------------------- 新增小节（教材解题骨架）

def _std_section(load, member, b, h):
    """「荷载标准值」小节：自重按 b·h·γc 推导（教材例3-2 写法）。

    题给 gk 与自重推导一致时单独一行写推导式（教材"板自重 gk = 0.10×1×25 = 2.5"）；
    不一致时与其余标准值并列按输入项名称逐项列出（教材例3-8"梁与铺板传来的
    自重 gk = 12.0"）——不使用"题给标准值（gk 见上）"这类应用内部措辞。
    返回 (html行, 纯文本行)。
    """
    gc = spec_data.conc_density()
    gk = float(load.get("gk", 0) or 0)
    qk = float(load.get("qk", 0) or 0)
    Gk = float(load.get("Gk", 0) or 0)
    Qk = float(load.get("Qk", 0) or 0)
    gk_auto = b * h / 1e6 * gc
    same = gk > 0 and abs(gk - gk_auto) < 5e-3
    name = "梁自重" if member == "梁" else "板自重"
    html, plain = [], []
    if same:
        html.append(f"{name}：g<sub>k</sub> = b·h·γ<sub>c</sub> = {b / 1000:g}×{h / 1000:g}×"
                    f"{fmt(gc, 3)} = {gk_auto:.1f} kN/m")
        plain.append(f"{name} gk = b·h·γc = {b / 1000:g}×{h / 1000:g}×{fmt(gc, 3)} = "
                     f"{gk_auto:.1f} kN/m")
    hg, pg = [], []
    if not same and gk > 0:
        hg.append(f"均布恒载 g<sub>k</sub> = {fmt(gk)} kN/m")
        pg.append(f"均布恒载 gk = {fmt(gk)} kN/m")
    if qk:
        hg.append(f"均布活载 q<sub>k</sub> = {fmt(qk)} kN/m")
        pg.append(f"均布活载 qk = {fmt(qk)} kN/m")
    if Gk:
        hg.append(f"跨中集中恒载 G<sub>k</sub> = {fmt(Gk)} kN")
        pg.append(f"跨中集中恒载 Gk = {fmt(Gk)} kN")
    if Qk:
        hg.append(f"跨中集中活载 Q<sub>k</sub> = {fmt(Qk)} kN")
        pg.append(f"跨中集中活载 Qk = {fmt(Qk)} kN")
    if hg:
        html.append("　｜　".join(hg))
        plain.append("　｜　".join(pg))
    return html, plain


def _gamma_section(load):
    """「分项系数」小节：逐条给值 + 表号出处（教材 3(1) 写法）。

    返回 (html行, 纯文本行)。
    """
    lvl = load.get("level", "III")
    sit = load.get("situation", "持久")
    kq = load.get("q_kind", "general")
    kQ = load.get("Q_kind", "general")
    lab = {"general": "一般可变", "controllable": "可控制"}
    # (html符号, 纯文本符号, 值, source, 小数位, 说明)
    items = [
        ("γ<sub>0</sub>", "γ0", spec_data.gamma0(lvl), spec_data.gamma0_source(lvl),
         1, f"{lvl}级"),
        ("ψ", "ψ", spec_data.psi(sit), spec_data.psi_source(sit), 1, sit),
        ("γ<sub>G</sub>", "γG", spec_data.gamma_G(), spec_data.gamma_G_source(),
         2, ""),
        ("γ<sub>Q</sub>(q<sub>k</sub>)", "γQ(qk)", spec_data.gamma_Q(kq),
         spec_data.gamma_Q_source(kq), 2, lab[kq]),
    ]
    if float(load.get("Qk", 0) or 0) > 0:
        items.append(("γ<sub>Q</sub>(Q<sub>k</sub>)", "γQ(Qk)", spec_data.gamma_Q(kQ),
                      spec_data.gamma_Q_source(kQ), 2, lab[kQ]))
    items.append(("γ<sub>d</sub>", "γd", GAMMA_D, spec_data.gamma_d_source(), 2, ""))

    _row_of = {"γQ(qk)": "γQ（一般可变）", "γQ(Qk)": "γQ（可控制可变）"}

    def cell(i, html_style):
        sym = i[0] if html_style else i[1]
        d = f"，{i[5]}" if i[5] else ""
        src = _src_tags(i[3], 1)
        if html_style:                      # 出处可点 + 行定位（查表口径的行名）
            src = _ref(src, _row_of.get(i[1], i[1]))
        return f"{sym} = {i[2]:.{i[4]}f}（{src}{d}）"

    split = 3   # 第一行：γ0、ψ、γG；第二行：γQ(qk)[、γQ(Qk)]、γd
    html = ["　".join(cell(i, True) for i in items[:split]),
            "　".join(cell(i, True) for i in items[split:])]
    plain = ["，".join(cell(i, False) for i in items[:split]),
             "，".join(cell(i, False) for i in items[split:])]
    return html, plain


def _moments_chain(load):
    """由标准值弯矩 M_G、M_Q 算弯矩设计值（教材例3-5/3-6/3-7「2. 内力计算」）：
    M = γ0·ψ(M_G + M_Q)。返回 (M_Nmm, html行, 纯文本行, meta)。
    """
    MG, MQ = float(load.get("MG", 0) or 0), float(load.get("MQ", 0) or 0)
    if MG <= 0 and MQ <= 0:
        raise ValueError("请输入标准值弯矩 M_G、M_Q（至少一个 >0）")
    y0 = spec_data.gamma0(load.get("level", "III"))
    psi = spec_data.psi(load.get("situation", "持久"))
    M = y0 * psi * (MG + MQ)                              # kN·m
    MG_s, MQ_s = _f2(MG), _f2(MQ)
    html = [f"M = γ<sub>0</sub>ψ(M<sub>G</sub> + M<sub>Q</sub>) = "
            f"{y0:.1f}×{psi:.1f}×({MG_s} + {MQ_s}) = {_f2(M)} kN·m"
            f"（= {_f2(M)}×10<sup>6</sup> N·mm）"]
    plain = [f"M = γ0·ψ(MG + MQ) = {y0:.1f}×{psi:.1f}×({MG_s} + {MQ_s}) = "
             f"{_f2(M)} kN·m"]
    meta = {"M": M, "y0": y0, "psi": psi, "MG": MG, "MQ": MQ}
    return M * 1e6, html, plain, meta


def _trial_block(sg, key, verb, M, b, as_, fc, fy, xi_b, rho_min, sec):
    """超筋/少筋时按反解 h 续演重算（教材例3-3“为此将截面高度……重算一遍”的写法）。

    返回 (html行, 纯文本行, trial | None)；trial = {h, h0, mod, verb, r}。
    反解值不可行时返回空（调用方退回只给建议的旧行为）。
    """
    if not sg or not sg.get(key):
        return [], [], None
    h2 = sg[key]
    h02 = h2 - as_
    if h02 <= 0:
        return [], [], None
    r2 = singly_rect.design(M, b, h02, fc, fy, xi_b, rho_min, GAMMA_D)
    if not r2["ok"]:
        return [], [], None
    a_max = singly_rect.alpha_s_max(xi_b)
    h2s = f"{h2:g}"
    a2, x2 = f"{r2['alpha_s']:.3f}", f"{r2['xi']:.3f}"
    a_eq = frac("γ<sub>d</sub>·M", "f<sub>c</sub>·b·h<sub>0</sub><sup>2</sup>")
    a_sub = frac(f"{GAMMA_D:.2f}×{_f2(M / 1e6)}×10<sup>6</sup>",
                 f"{fmt(fc)}×{fmt(b, 3)}×{h02:g}<sup>2</sup>")
    as_eq = frac("f<sub>c</sub>·b·ξ·h<sub>0</sub>", "f<sub>y</sub>")
    as_sub = frac(f"{fmt(fc)}×{fmt(b, 3)}×{x2}×{h02:g}", fmt(fy))
    rho_eq = frac("A<sub>s</sub>", "b·h<sub>0</sub>")
    rho_sub = frac(fmt(r2["As"], 3), f"{fmt(b, 3)}×{h02:g}")
    lines = [
        f"为此，将截面高度{verb}到 {h2s}mm（按 {sg['mod']}mm 模数取整），"
        f"h<sub>0</sub>′ = h − a<sub>s</sub> = {h2s} − {fmt(as_, 3)} = {h02:g}mm。",
        _tag(f"α<sub>s</sub> = {a_eq} = {a_sub} = {a2}"
             f" ≤ α<sub>s,max</sub> = {fmt(a_max, 3)}", "（3-17）"),
        _tag(f"ξ = 1 − {sqrt_('1−2α<sub>s</sub>')} = 1 − {sqrt_(f'1−2×{a2}')}"
             f" = {x2} ≤ ξ<sub>b</sub> = {fmt(xi_b, 3)}", "（3-18）"),
        "满足不发生超筋的要求。",
        _tag(f"A<sub>s</sub> = {as_eq} = {as_sub} = {fmt(r2['As'], 3)} mm²", "（3-19）"),
        f"ρ = {rho_eq} = {rho_sub} = {pct(r2['rho'])}"
        f" ≥ ρ<sub>min</sub> = {pct(rho_min)}",
        "满足纵向受拉钢筋最小配筋率要求。",
        f"→ 采用 h = {h2s}mm 后设计可行；点击下方「改 h 重算」按钮可一键套用。",
    ]
    plain = [
        f"  为此，截面高度{verb}到 {h2s}mm（{sg['mod']} 模数），"
        f"h0′ = {h2s} − {fmt(as_, 3)} = {h02:g} mm：",
        f"    αs = γd·M/(fc·b·h0²) = {a2} ≤ αs,max = {fmt(a_max, 3)} ✓",
        f"    ξ = 1-√(1-2×{a2}) = {x2} ≤ ξb = {xi_b} ✓（满足不发生超筋的要求）",
        f"    As = {fmt(r2['As'], 3)} mm²，ρ = {pct(r2['rho'])} ≥ ρmin = {pct(rho_min)} ✓"
        "（满足最小配筋率要求）",
    ]
    trial = {"h": h2, "h0": h02, "mod": sg["mod"], "verb": verb, "r": r2}
    return ([sec(f"截面{verb}至 h = {h2s}mm 试算")] + lines, plain, trial)


# ---------------------------------------------------------------- 弯矩链条

def _m_chain(load, member, h_mm):
    """荷载标准值 → 弯矩设计值（式2-35）。返回 (M_Nmm, html行, 纯文本行, meta)。"""
    gk, qk = float(load.get("gk", 0)), float(load.get("qk", 0))
    Gk, Qk = float(load.get("Gk", 0)), float(load.get("Qk", 0))
    yG = spec_data.gamma_G()
    yQq = spec_data.gamma_Q(load.get("q_kind", "general"))
    yQQ = spec_data.gamma_Q(load.get("Q_kind", "general"))
    g, q = yG * gk, yQq * qk
    G, Q = yG * Gk, yQQ * Qk
    if load.get("l0src", "calc") == "calc":
        ln, a = float(load.get("ln", 0)), float(load.get("a", 0))
        if ln <= 0:
            raise ValueError("请输入净跨 ln（>0）")
        if member == "梁":
            l0 = loading.effective_span_beam(ln, a)
            rule = "min(l<sub>n</sub>+a, 1.05·l<sub>n</sub>)"
            rule_plain = "min(ln+a, 1.05ln)"
        else:
            l0 = loading.effective_span_slab(ln, a, h_mm / 1000.0)
            rule = "min(l<sub>n</sub>+a, l<sub>n</sub>+h)"
            rule_plain = "min(ln+a, ln+h)"
        if member == "梁":
            rule_sub = f"min({fmt(ln, 2)}+{fmt(a, 2)}, 1.05×{fmt(ln, 2)})"
        else:
            rule_sub = f"min({fmt(ln, 2)}+{fmt(a, 2)}, {fmt(ln, 2)}+{fmt(h_mm / 1000, 2)})"
    else:
        l0 = float(load.get("l0", 0))
        if l0 <= 0:
            raise ValueError("请输入计算跨度 l0（>0）")
        rule = "l<sub>0</sub>"
        rule_plain = rule_sub = None
    M_int = loading.midspan_M(g, q, l0, G, Q)          # kN·m
    y0 = spec_data.gamma0(load.get("level", "III"))
    psi = spec_data.psi(load.get("situation", "持久"))
    M = loading.M_design(y0, psi, M_int)               # kN·m
    has_conc = Gk > 0 or Qk > 0
    # 系数按表值小数位显示（γG/γQ 两位 1.10，γ0/ψ 一位 0.9/1.0）；设计值两位（2.20/48.0）
    cG, cQq, cQQ = f"{yG:.2f}", f"{yQq:.2f}", f"{yQQ:.2f}"
    c0, cP = f"{y0:.1f}", f"{psi:.1f}"
    gS, qS, GS, QS = _f2(g), _f2(q), _f2(G), _f2(Q)
    # HTML 行
    m_formula = frac("(g+q)·l<sub>0</sub><sup>2</sup>", 8) + (
        " + " + frac("(G+Q)·l<sub>0</sub>", 4) if has_conc else "")
    m_sub = frac(f"({gS}+{qS})×{_f2(l0)}<sup>2</sup>", 8) + (
        " + " + frac(f"({GS}+{QS})×{_f2(l0)}", 4) if has_conc else "")
    l0_line = (f"l<sub>0</sub> = {rule} = {rule_sub} = {_f2(l0)} m" if rule_sub
               else f"l<sub>0</sub> = {_f2(l0)} m（题给）")
    html = [
        f"g = γ<sub>G</sub>g<sub>k</sub> = {cG}×{fmt(gk)} = {gS} kN/m，"
        f"q = γ<sub>Q</sub>q<sub>k</sub> = {cQq}×{fmt(qk)} = {qS} kN/m",
    ]
    if has_conc:
        html.append(f"G = γ<sub>G</sub>G<sub>k</sub> = {cG}×{fmt(Gk)} = {GS} kN，"
                    f"Q = γ<sub>Q</sub>Q<sub>k</sub> = {cQQ}×{fmt(Qk)} = {QS} kN")
    html += [
        l0_line,
        f"M<sub>内</sub> = {m_formula} = {m_sub} = {_f2(M_int)} kN·m",
        f"M = γ<sub>0</sub>ψM<sub>内</sub> = {c0}×{cP}×{_f2(M_int)} = {_f2(M)} kN·m"
        f"（= {_f2(M)}×10<sup>6</sup> N·mm）",
    ]
    # 纯文本行
    plain = [f"g = γG·gk = {cG}×{fmt(gk)} = {gS} kN/m，"
             f"q = γQ·qk = {cQq}×{fmt(qk)} = {qS} kN/m"]
    if has_conc:
        plain.append(f"G = γG·Gk = {cG}×{fmt(Gk)} = {GS} kN，"
                     f"Q = γQ·Qk = {cQQ}×{fmt(Qk)} = {QS} kN")
    m_plain_expr = f"(g+q)l0²/8" + (f" + (G+Q)l0/4" if has_conc else "")
    m_plain_sub = f"({gS}+{qS})×{_f2(l0)}²/8" + (
        f" + ({GS}+{QS})×{_f2(l0)}/4" if has_conc else "")
    plain += [
        (f"l0 = {rule_plain} = {rule_sub} = {_f2(l0)} m" if rule_sub
         else f"l0 = {_f2(l0)} m（题给）"),
        f"M内 = {m_plain_expr} = {m_plain_sub} = {_f2(M_int)} kN·m",
        f"M = γ0·ψ·M内 = {c0}×{cP}×{_f2(M_int)} = {_f2(M)} kN·m",
    ]
    meta = {"y0": y0, "psi": psi, "M_int": M_int, "l0": l0,
            "g": g, "q": q, "G": G, "Q": Q, "has_conc": has_conc}
    return M * 1e6, html, plain, meta


# ---------------------------------------------------------------- 选筋（约束过滤）

def _doubly_inputs(inp, h0, member):
    """受压钢筋输入解析（设计/复核两页共用）。

    双筋截面仅适用于梁（教材3.5.2、图3-27，例3-5~3-7）：member≠"梁" 且带双筋输入时
    直接报错——不做静默替换（否则使用者会拿到与输入不符的单筋结果）。界面侧板不显示
    双筋控件、切构件时归位单筋，正常流程不会走到这里。板受压区不足的正确做法是加厚板
    或提高混凝土强度等级；连续板支座负筋属另一类问题（简支单跨正截面模型不覆盖）。

    返回 (mode, Asp, asp_, asp_desc, asp_plain)：
      mode ∈ {none, unknown, count, direct}；unknown（双筋设计·A′s 待求）时
      Asp=0、仅 a′s 有意义；count/direct 按表C-1 查表或直接输入取值。
    """
    mode = inp.get("dbl") or "none"
    if member != "梁":
        if mode != "none":
            # 不做静默替换：双筋输入 + 板 = 明确报错（否则使用者拿到与输入不符的单筋结果）
            raise ValueError("双筋截面仅适用于梁（教材3.5.2）：板不开放双筋，"
                             "受压区不足时应加厚板或提高混凝土强度等级")
        return "none", 0.0, 0.0, "", ""
    Asp, asp_, asp_desc, asp_plain = 0.0, 0.0, "", ""
    if mode == "direct":
        Asp = float(inp.get("Asp", 0) or 0)
        if Asp <= 0:
            raise ValueError("请输入受压钢筋面积 A′s（>0）")
        asp_desc = f"A′<sub>s</sub> = {fmt(Asp, 3)} mm²（直接输入）"
        asp_plain = f"A's = {fmt(Asp, 3)} mm²（直接输入）"
    elif mode == "count":
        d_p, n_p = int(inp.get("dia_p", 18)), int(inp.get("n_p", 0) or 0)
        if n_p <= 0:
            raise ValueError("请输入受压钢筋根数 n′（>0）")
        Asp = spec_data.bar_area_n(d_p, n_p)
        asp_desc = f"{n_p}Φ{d_p}：A′<sub>s</sub> = {fmt(Asp, 3)} mm²（查附录C {_ref('表C-1', f'Φ{d_p}')}）"
        asp_plain = f"{n_p}Φ{d_p}：A's = {fmt(Asp, 3)} mm²（查附录C 表C-1）"
    if mode in ("unknown", "count", "direct"):
        asp_ = float(inp.get("asp_", 0) or 0)
        if asp_ <= 0:
            raise ValueError("请输入受压钢筋合力点 a′s（>0）")
        if asp_ >= h0:
            raise ValueError("受压钢筋合力点 a′s 应小于 h0")
    return mode, Asp, asp_, asp_desc, asp_plain


def _bars_for(member, As, b, constraints, total_b=True):
    """按题目约束生成选筋建议（约束为空时保持原默认行为）。"""
    cons = constraints or {}
    if member == "梁":
        dias = cons.get("dias")
        opts = beam_bar_options(As, b, dias=dias,
                                allow_double=bool(cons.get("allow_double", False)))
        cols = [("dia", "直径"), ("cnt", "根数"), ("area", "实配面积 (mm²)"),
                ("margin", "富余"), ("fit", "排布宽度"), ("op", "操作")]
        title = ("梁布筋建议（排布宽度验算法同例3-1）" if opts
                 else "梁布筋建议（约束内无可行组合，见下方提示）")
        hint = ("" if opts else
                "约束内单层排不下：可放宽直径范围、加大梁宽 b、允许双层布置"
                "（a<sub>s</sub>=c<sub>s</sub>+35 后重算）或增大钢筋直径。")
        return {"member": member, "columns": cols, "rows": opts,
                "title": title, "hint": hint}
    dias = cons.get("dias")
    s_range = cons.get("s_range")
    opts = slab_bar_options(As, dias=dias, s_range=s_range,
                            total_b=(b if (cons.get("total", True) and total_b) else None))
    cols = [("spec", "配筋"), ("area", "实配面积 (mm²/m)"), ("margin", "富余")]
    if opts and "total" in opts[0]:
        cols.insert(2, ("total", f"b={b:g}mm 总根数"))
    cols.append(("op", "操作"))
    return {"member": member, "columns": cols, "rows": opts,
            "title": f"板选筋建议（每米板宽，间距取附录C {_ref('表C-2')}系列）", "hint": ""}


def _actual_as_h0(values, row):
    """按实配钢筋重算 as/h0：单层 cs+d/2、双层 cs+35、板 cs+d/2。

    返回 (as_actual, h0_actual)；截面信息不全时返回 (None, None)。
    """
    cs, h = values.get("cs"), values.get("h")
    if cs is None or h is None:
        return None, None
    try:
        if values["member"] == "梁":
            dia = int(row["dia"][1:])
            double = "双层" in row.get("fit", "")
            as_ = cs + (35.0 if double else dia / 2.0)
        else:
            d = int(row["spec"][1:].split("@")[0])
            as_ = cs + d / 2.0
    except (KeyError, ValueError, IndexError):
        return None, None
    return as_, h - as_


def picked_recheck(values, row, M=None):
    """选中行的实配回验（C）：返回 {'ok':bool, 'html':str}，不可解析返回 None。

    as/h0 按实配直径重算（单层 cs+d/2、双层 cs+35、板 cs+d/2），
    与预估直径不同时在结果中注明。
    """
    try:
        member = values["member"]
        b = values["b"]
        if member == "梁":
            dia = int(row["dia"][1:])
            n = int(row["cnt"].replace("根", ""))
            As = spec_data.bar_area_n(dia, n)     # 表C-1 查表（与选筋行实配面积一致）
            name = f"{n}Φ{dia}"
        else:
            d, s = row["spec"][1:].split("@")
            As = spec_data.bar_area(int(d)) * 1000.0 / s * b / 1000.0
            name = f"Φ{d}@{s}（b={b:g}mm 共 {round(b / int(s))} 根）"
    except Exception:
        return None
    as_act, h0_act = _actual_as_h0(values, row)
    h0 = h0_act if h0_act and h0_act > 0 else values["h0"]
    if values.get("doubly") and member == "梁":
        # 双筋设计：回验须计入已配/计算 A′s（式3-22 一侧），否则会误判超筋
        r = doubly_rect.verify(As, values.get("Asp") or 0, b=b, h0=h0,
                               asp=values.get("asp_", 0), fc=values["fc"],
                               fy=values["fy"], xi_b=values["xi_b"],
                               gamma_d=GAMMA_D, M=M, rho_min=values["rho_min"])
    else:
        r = singly_rect.verify(As, b=b, h0=h0, fc=values["fc"],
                               fy=values["fy"], xi_b=values["xi_b"],
                               gamma_d=GAMMA_D, M=M, rho_min=values["rho_min"])
    # 选筋叙述（教材选筋段：实配/富余 + 排布宽度算式“2×45+3×16+2×25=188≤200”）
    margin = fmt(As / values["As"], 3) if values.get("As") else "—"
    if member == "梁":
        if "双层" in row.get("fit", ""):
            lead = (f"选筋 {name}（实配 {fmt(As, 3)} mm²，富余 {margin}）"
                    f"——{row['fit'].replace('✓', '').strip()}，双层布置 ✓")
        else:
            w = 2 * SIDE_COVER + n * dia + (n - 1) * CLEAR_SPACING
            lead = (f"选筋 {name}（实配 {fmt(As, 3)} mm²，富余 {margin}）——"
                    f"排布宽度 = 2×{SIDE_COVER:g} + {n}×{dia} + {n - 1}×{CLEAR_SPACING:g}"
                    f" = {w:.0f} ≤ b = {b:g} mm，可单层布置 ✓")
    else:
        lead = (f"选筋 {row['spec']}（实配 {fmt(As, 3)} mm² ≥ 计算 "
                f"{fmt(values['As'], 3)} mm²，富余 {margin}）")
    xi_v, rho_v = f"{r['xi']:.3f}", pct(r["rho"])
    rho_cmp = "≥" if r["rho_ok"] else "&lt;"
    xi_cmp = "≤" if r["xi_ok"] else "&gt;"
    if values.get("doubly") and member == "梁":
        # 双筋实配略大于计算 As 时 ξ 名义略超 ξb——按教材3.5.3 步骤(1) 取
        # x=ξb·h0 封顶复核承载力（不再按单筋口径误判超筋）
        lines = [lead,
                 f"<b>实配回验</b>（双筋，A′<sub>s</sub> = "
                 f"{fmt(values.get('Asp') or 0, 3)} mm²）：A<sub>s</sub> = {fmt(As, 3)} mm²，"
                 f"ξ = {xi_v} {xi_cmp} ξ<sub>b</sub> = {fmt(values['xi_b'], 3)}"
                 + ("" if r["xi_ok"] else "（实配略超计算值，按 ξ<sub>b</sub> 封顶复核）")]
        ok = (r["rho_ok"] is not False)
    else:
        lines = [lead,
                 f"<b>实配回验</b> {name}：A<sub>s</sub> = {fmt(As, 3)} mm²，"
                 f"ρ = {rho_v} {rho_cmp} ρ<sub>min</sub> = {pct(values['rho_min'])} "
                 + ("✓" if r["rho_ok"] else "✘"),
                 f"ξ = {xi_v} {xi_cmp} ξ<sub>b</sub> = {fmt(values['xi_b'], 3)} "
                 + ("✓" if r["xi_ok"] else "✘ 超筋")]
        ok = r["xi_ok"] and (r["rho_ok"] is not False) and (r.get("safe", True))
    if as_act is not None and abs(as_act - values.get("as_", as_act)) > 0.05:
        lines.insert(1, f"a<sub>s</sub> 按实配重算：a<sub>s</sub> = {fmt(as_act, 3)}mm "
                        f"→ h<sub>0</sub> = {fmt(h0_act, 3)}mm"
                        f"（原估 a<sub>s</sub> = {fmt(values['as_'], 3)}mm）")
    if M is not None:
        lines.append(f"M′ = {_f2(r['M_allowed'] / 1e6)} kN·m "
                     + ("≥" if r["M_allowed"] >= M else "&lt;")
                     + f" M = {_f2(M / 1e6)} kN·m "
                     + ("✓" if r["M_allowed"] >= M else "✘"))
        ok = ok and r["M_allowed"] >= M
    html = html_block(lines)
    if ok:
        html = (f'<div style="background:#e8f5e9;border-radius:8px;padding:8px 12px;'
                f'color:#1b5e20;">{html}该实配方案可行。</div>')
    else:
        html = (f'<div style="background:#fdecea;border-radius:8px;padding:8px 12px;'
                f'color:#b71c1c;">{html}该实配方案不满足，见上表其余方案。</div>')
    return {"ok": ok, "html": html}


# ---------------------------------------------------------------- 设计题

class _Incomplete(Exception):
    """缺输入（区别于"输入非法"）：partial=True 时据此返回已算到的分段。

    missing: [(字段键, 显示名), ...]；stage: 算到哪一段（如 "1 资料"）。
    注意规则：**空 = 未填（分段）**，**填了但非法（b<0）= 仍然 ValueError**，
    绝不把错误伪装成"还没填"。
    """

    def __init__(self, missing, stage, done=(), msg=None):
        self.missing = list(missing)
        self.stage = stage
        self.done = list(done)
        self.msg = msg                       # 严格模式沿用原来的报错文案（测试与旧行为不变）
        super().__init__(msg or ("缺少输入：" + "、".join(lb for _, lb in self.missing)))


def _pending_sections(inp, done, stage=""):
    """未算到的段标题（编号与已算段共用同一骨架，让学生看到完整路线图）。

    停在"1 资料"且未完成时，资料已部分显示（材料/环境），不重复占位。
    """
    mode = inp.get("m_mode", "load")
    if mode == "load":
        order = ["资料", "荷载标准值", "分项系数", "荷载与内力", "配筋计算", "选筋与构造"]
    else:
        order = ["资料", "弯矩", "配筋计算", "选筋与构造"]
    start = len(done)
    if not done and stage == "1 资料":
        start = 1
    rest = order[start:]
    return [f"{i + start + 1}. {name}" for i, name in enumerate(rest)]


def solve_design(inp, partial=False):
    """截面设计（例3-1/3-2/3-3 同类）。非法输入抛 ValueError。

    partial=True：缺输入不再中断，返回已算到的分段（"填一段、出一段"）；
    同一代码路径（_solve_design_core），不复制简化逻辑——保证分段显示与整段一致。
    """
    acc = {"blocks": [], "done": [], "values": {}, "info": "", "m": ""}
    try:
        return _solve_design_core(inp, acc)
    except _Incomplete as e:
        if not partial:
            raise ValueError(e.msg or str(e)) from None
        return {"partial": True, "missing": e.missing, "stage": e.stage,
                "info_html": acc["info"], "m_html": acc["m"],
                "res_html": "", "pending_html": _pending_sections(inp, e.done, e.stage),
                "m_meta": {}, "kpi_html": "", "sweep_html": "",
                "verdict": None, "bars": None, "fig": None,
                "values": acc["values"], "report": ""}


def _solve_design_core(inp, acc):
    """设计主链（与原来一致；分段模式靠 acc 记录已算段落）。"""
    member = inp.get("member", "梁")
    _emp = set(inp.get("_empty") or ())          # 空栏位键（UI 侧采集）：空=未填（分段），非法=报错
    b, h = float(inp.get("b", 0) or 0), float(inp.get("h", 0) or 0)
    if b < 0 or h < 0:
        raise ValueError("请输入截面尺寸 b、h（>0）")
    conc, steel, env = inp["conc"], inp["steel"], inp["env"]
    fc, fy = spec_data.concrete_fc(conc), spec_data.steel_fy(steel)
    xi_b = spec_data.xi_b(steel)
    rho_min = spec_data.rho_min(steel, member)
    # 1. 资料：材料/出处两行不依赖环境类别与 h —— 供分段先出
    sec, next_no = _sec_counter()
    m_mode = inp.get("m_mode", "load")          # load / moments / direct
    load = inp.get("load", {})
    _info_head = [
        f"{info_label('材料')}　混凝土 {conc}：f<sub>c</sub> = {fmt(fc)} N/mm²　｜　"
        f"钢筋 {steel}：f<sub>y</sub> = {fmt(fy)} N/mm²，ξ<sub>b</sub> = {fmt(xi_b, 3)}，"
        f"ρ<sub>min</sub> = {pct(rho_min)}（{member}）",
        f"{info_label('出处')}　fc、fy "
        f"{_src_pair_ref(spec_data.concrete_fc_source(conc), spec_data.steel_fy_source(steel), conc, steel)}"
        f"　｜　"
        f"ξ<sub>b</sub> {_ref(_src_tags(spec_data.xi_b_source(steel), 1), steel)}　｜　"
        f"ρ<sub>min</sub> {_ref(_src_tags(spec_data.rho_min_source(steel, member), 2), member)}",
    ]
    # 环境类别（保护层查表）是"系数类陷阱"之一：空白题不预选 → 缺它先在资料段停住
    if not env or "env" in _emp:
        acc["info"] = html_block([sec("资料")] + _info_head)
        raise _Incomplete([("env", "环境类别")], "1 资料", acc["done"], "请选择环境类别")
    c_min = spec_data.cover_min(env, member)
    y100 = bool(inp.get("y100", False))
    c = math.ceil(1.4 * c_min) if y100 else c_min
    stirrup = float(inp.get("stirrup", 10) or 10)
    cs = section.cs_beam(c, stirrup) if member == "梁" else section.cs_slab(c)
    layers = int(inp.get("layers", 1) or 1)
    dia_est = float(inp.get("dia_est", 20) or 20)
    as_, h0 = section.effective_depth(h, cs, bar_dia=dia_est, layers=layers)
    # 受压钢筋（双筋设计，教材3.5.2；"none"=单筋链，行为与原来完全一致）
    dbl_mode, Asp, asp_, asp_desc, asp_plain = _doubly_inputs(inp, h0, member)
    doubly = dbl_mode in ("unknown", "count", "direct")
    # 构造校验
    warns_html, warns_plain = [], []
    if layers == 1 and cs < dia_est:
        w = (f"⚠ 构造校验（附录D D.1(1)）：纵向受力钢筋保护层不应小于其公称直径，"
             f"当前 c<sub>s</sub>={fmt(cs)}mm &lt; Φ{fmt(dia_est, 2)}，"
             "请加大保护层或改用较小直径重新估计。")
        warns_html.append(f'<span style="color:#e65100">{w}</span>')
        warns_plain.append(f"  ⚠ {w.replace('<sub>', '').replace('</sub>', '').replace('&lt;', '<')}")
    cs_formula = (f"c + 箍筋预估{fmt(stirrup, 0)}" if member == "梁"
                  else "c（板取最外层钢筋）")
    as_formula = (f"c<sub>s</sub> + Φ{fmt(dia_est, 0)}/2" if layers == 1
                  else "c<sub>s</sub> + 35")
    c_text = (f"{fmt(c_min)}×1.4 向上取整，使用年限100年" if y100
              else f"表D-1 {env}类{member}")
    # ---- 编号小节（教材解题骨架）：1 资料 → [2 荷载标准值 → 3 分项系数 → 4 荷载与内力]
    # 或 2 弯矩（直接输入 M）→ 5 配筋计算 → [试算] → 6 选筋与构造；编号与屏显顺序一致
    # 1. 资料（含查表出处；直接输入 M 时 γd 归入资料——教材例3-3 写法）
    info = list(_info_head)
    info.append(f"{info_label('环境')}　{env}类　｜　c = {fmt(c)}mm（{_ref(c_text, env + '类')}）　→　"
                f"c<sub>s</sub> = {cs_formula} = {fmt(cs)}mm")
    if m_mode == "moments":
        _miss3 = [(k, lb) for k, lb in (("level", "结构安全级别"), ("situation", "设计状况"))
                  if k in _emp or not load.get(k)]
        if _miss3:
            acc["info"] = html_block([sec("资料")] + info)
            raise _Incomplete(_miss3, "1 资料", acc["done"], "请选择结构安全级别与设计状况")
        _lvl, _sit = load.get("level", "III"), load.get("situation", "持久")
        info.insert(2, f"{info_label('系数')}　"
                       f"γ<sub>0</sub> = {spec_data.gamma0(_lvl):.1f}"
                       f"（{_ref(_src_tags(spec_data.gamma0_source(_lvl), 1), 'γ0')}，{_lvl}级）　"
                       f"ψ = {spec_data.psi(_sit):.1f}"
                       f"（{_ref(_src_tags(spec_data.psi_source(_sit), 1), 'ψ')}，{_sit}）　"
                       f"γ<sub>d</sub> = {GAMMA_D:.2f}"
                       f"（{_ref(_src_tags(spec_data.gamma_d_source(), 1), 'γd')}）")
    elif m_mode != "load":
        info.insert(2, f"{info_label('系数')}　γ<sub>d</sub> = {GAMMA_D:.2f}"
                       f"（{_ref(_src_tags(spec_data.gamma_d_source(), 1), 'γd')}）")
    if not h:
        # 缺 h：材料/出处/环境（含系数）已可算，先出这一段
        acc["info"] = html_block([sec("资料")] + info + warns_html)
        raise _Incomplete([("h", "截面高 h")], "1 资料", acc["done"],
                          "请输入截面尺寸 b、h（>0）")
    if h0 <= 0:
        raise ValueError(
            f"h0 = h - as 应大于 0（当前 h = {fmt(h, 3)}mm，"
            f"as = {fmt(as_, 3)}mm，请检查截面高度、保护层或布筋参数）")
    info.append(f"{info_label('截面')}　a<sub>s</sub> = {as_formula} = {fmt(as_, 3)}mm　→　"
                f"h<sub>0</sub> = h − a<sub>s</sub> = {fmt(h, 3)} − {fmt(as_, 3)} = {h0:g}mm")
    if doubly:
        info.append(f"{info_label('受压筋')}　a′<sub>s</sub> = {fmt(asp_, 3)}mm　｜　"
                    + (asp_desc if dbl_mode != "unknown"
                       else "A′<sub>s</sub> 待求（双筋设计·第一种情况）"))
    info_html = html_block([sec("资料")] + info + warns_html)
    acc["info"] = info_html
    acc["done"].append("资料")
    # 荷载链 / 标准值弯矩 / 直接输入的 M（逐段推进：缺哪段停哪段）
    m_sub_plain = []
    if m_mode == "load":
        _miss = []
        if not b:
            _miss.append(("b", "梁宽/板计算宽 b"))
        if "gk" in _emp:
            _miss.append(("gk", "均布恒载 gk"))
        if "qk" in _emp:
            _miss.append(("qk", "均布活载 qk"))
        if _miss:
            raise _Incomplete(_miss, "1 资料", acc["done"], "请输入均布荷载 gk、qk（>0）")
        std_html, std_plain = _std_section(load, member, b, h)
        acc["m"] += html_block([sec("荷载标准值")] + std_html)
        acc["done"].append("荷载标准值")
        _miss2 = [(k, lb) for k, lb in (("q_kind", "q<sub>k</sub> 的可变荷载类别"),
                                        ("Q_kind", "Q<sub>k</sub> 的可变荷载类别"),
                                        ("level", "结构安全级别"), ("situation", "设计状况"))
                  if k in _emp]
        if _miss2:
            raise _Incomplete(_miss2, "2 荷载标准值", acc["done"],
                              "请选择可变荷载类别、结构安全级别与设计状况")
        gam_html, gam_plain = _gamma_section(load)
        acc["m"] += html_block([sec("分项系数")] + gam_html)
        acc["done"].append("分项系数")
        _l0key, _l0name = (("l0", "计算跨度 l0") if load.get("l0src") == "direct"
                           else ("ln", "净跨 ln"))
        if _l0key in _emp or not load.get(_l0key):
            raise _Incomplete([(_l0key, _l0name)], "3 分项系数", acc["done"],
                              "请输入净跨 ln 或计算跨度 l0（>0）")
        M, m_html, m_plain, m_meta = _m_chain(load, member, h)
        acc["m"] += html_block([sec("荷载与内力", "（式2-35）")] + m_html)
        acc["done"].append("荷载与内力")
        m_html_out = acc["m"]
        m_title_plain = "二、荷载与内力"
        m_sub_plain = (["  （1）荷载标准值"] + [f"    {x}" for x in std_plain] +
                       ["  （2）分项系数"] + [f"    {x}" for x in gam_plain] +
                       ["  （3）荷载设计值与内力"])
    elif m_mode == "moments":
        if "MG" in _emp and "MQ" in _emp:
            raise _Incomplete([("MG", "恒载弯矩 MG"), ("MQ", "活载弯矩 MQ")], "1 资料",
                              acc["done"], "请输入标准值弯矩 M_G、M_Q（至少一个 >0）")
        M, m_html, m_plain, m_meta = _moments_chain(load)
        m_html_out = html_block([sec("内力计算")] + m_html)
        acc["m"] = m_html_out
        acc["done"].append("内力计算")
        m_title_plain = "二、内力计算"
    else:
        M_kNm = float(inp.get("M_kNm", 0) or 0)
        if "M_kNm" in _emp:
            raise _Incomplete([("M_kNm", "弯矩设计值 M")], "1 资料", acc["done"],
                              "请输入弯矩设计值 M（>0）")
        if M_kNm <= 0:
            raise ValueError("请输入弯矩设计值 M（>0）")
        M = M_kNm * 1e6
        m_meta = {"M": M_kNm, "y0": None, "psi": None}
        m_html = [f"已知 M = {_f2(M_kNm)} kN·m"]
        m_plain = [f"已知 M = {_f2(M_kNm)} kN·m"]
        m_html_out = html_block([sec("弯矩")] + m_html)
        acc["m"] = m_html_out
        acc["done"].append("弯矩")
        m_title_plain = "二、弯矩"
    # 配筋计算（公共显示量）——弯矩来源模式不经过荷载段，这里补 b 的分段检查
    if not b:
        raise _Incomplete([("b", "梁宽/板计算宽 b")],
                          acc["done"][-1] if acc["done"] else "1 资料",
                          acc["done"], "请输入截面尺寸 b、h（>0）")
    alpha_s_eq = frac("γ<sub>d</sub>·M", "f<sub>c</sub>·b·h<sub>0</sub><sup>2</sup>")
    alpha_s_sub = frac(f"{GAMMA_D:.2f}×{_f2(M / 1e6)}×10<sup>6</sup>",
                       f"{fmt(fc)}×{fmt(b, 3)}×{h0:g}<sup>2</sup>")
    alpha_plain = f"{GAMMA_D:.2f}×{_f2(M / 1e6)}×10⁶/({fmt(fc)}×{fmt(b, 3)}×{h0:g}²)"
    eco = spec_data.economic_rho_percent("板" if member == "板" else "矩形梁")
    eco_txt = f"常用配筋率 {eco[0]}%~{eco[1]}%"
    rho_max = singly_rect.rho_max(fc, fy, xi_b)
    sec_head = sec("配筋计算")
    # ---- 双筋设计（教材3.5.2、图3-27；例3-5/3-6/3-7）——整条链独立成稿
    dbl_single_note = None
    if doubly:
        dbl_known = dbl_mode in ("count", "direct")
        r = doubly_rect.design(M, b, h0, fc, fy, xi_b, GAMMA_D,
                               mode=("known" if dbl_known else "unknown"),
                               Asp=Asp, asp=asp_, rho_min=rho_min)
        if r.get("single_ok"):
            # 图3-27 左支"满足"：αs ≤ αs,b → 按单筋截面设计（回落单筋链，仅加提示）
            dbl_single_note = (
                f"α<sub>s</sub> = {alpha_plain} = {r['alpha_s']:.3f} ≤ "
                f"α<sub>s,max</sub> = {r['alpha_s_b']:.3f}，未超筋——按图3-27 转入"
                f"单筋截面设计，无需受压钢筋（以下按单筋链计算）。")
            doubly = False
        else:
            m_k = _f2(M / 1e6)
            asp_disp, two_asp = fmt(asp_, 3), fmt(2 * asp_, 3)
            a_b, alpha_val = f"{r['alpha_s_b']:.3f}", f"{r['alpha_s']:.3f}"
            values = {"member": member, "b": b, "h": h, "conc": conc, "steel": steel,
                      "env": env, "fc": fc, "fy": fy, "xi_b": xi_b, "rho_min": rho_min,
                      "c_min": c_min, "y100": y100, "c": c, "cs": cs, "layers": layers,
                      "as_": as_, "h0": h0, "stirrup": stirrup, "dia_est": dia_est,
                      "M": M, "a_max": r["alpha_s_b"], "rho_max": rho_max, "eco": eco,
                      "gamma_d": GAMMA_D, "doubly": True, "dbl_mode": dbl_mode,
                      "Asp": r.get("Asp") or 0.0, "asp_": asp_,
                      "asp_desc": asp_desc, "asp_plain": asp_plain,
                      "As": r.get("As"), "total": r.get("total"),
                      "Asp_min": r.get("Asp_min")}
            res = {"error": None, "values": values, "r": r, "m_meta": m_meta,
                   "m_html": m_html_out, "m_plain": m_plain,
                   "m_title_plain": m_title_plain, "m_sub_plain": m_sub_plain,
                   "info_html": info_html, "suggest": None, "report": None}
            if r.get("need_more"):
                # 已知 A′s 不足（图3-27 右支"不满足→需增加 A′s"）
                res_lines = [
                    _tag(f"α<sub>s</sub> = {frac('γ<sub>d</sub>·M − f′<sub>y</sub>·A′<sub>s</sub>(h<sub>0</sub> − a′<sub>s</sub>)', 'f<sub>c</sub>·b·h<sub>0</sub><sup>2</sup>')}"
                         + " = " + frac(f"{GAMMA_D:.2f}×{m_k}×10<sup>6</sup> − {fmt(fy)}×{fmt(round(Asp), 3)}×({h0:g} − {asp_disp})",
                                        f"{fmt(fc)}×{fmt(b, 3)}×{h0:g}<sup>2</sup>")
                         + f" = {alpha_val}", "（3-31）"),
                    f"α<sub>s,max</sub> = ξ<sub>b</sub>(1−0.5ξ<sub>b</sub>) = {a_b}（{_ref('表3-1', steel)}）",
                    f"α<sub>s</sub> &gt; α<sub>s,max</sub>，表明已配的 A′<sub>s</sub> = "
                    f"{fmt(round(Asp), 3)}mm² 不足，需增加 A′<sub>s</sub>。",
                    f"按式（3-29），所需 A′<sub>s</sub> ≥ {fmt(r['Asp_min'], 3)}mm²。",
                ]
                res["res_html"] = html_block([sec_head] + res_lines)
                res["verdict"] = {"ok": False,
                                  "html": f"✘ 已配受压钢筋不足：A′<sub>s</sub> = "
                                          f"{fmt(round(Asp), 3)}mm² 对应 α<sub>s</sub> = {alpha_val} "
                                          f"&gt; α<sub>s,max</sub> = {a_b}。"
                                          f"<br>建议：增加 A′<sub>s</sub> 至 ≥ "
                                          f"{fmt(r['Asp_min'], 3)}mm²（或改用「双筋·计算 A′s」"
                                          f"模式由本页求所需 A′<sub>s</sub>），也可加大截面。"}
                res["report"] = _report_design(inp, res, None)
                return res
            if dbl_known:
                # 第二种情况：式(3-31) → 式(3-18) → x≥2a′s 式(3-32) / x<2a′s 式(3-33)
                sign = "&gt;" if r["x"] > 2 * asp_ else ("=" if r["x"] == 2 * asp_ else "&lt;")
                res_lines = [
                    _tag(f"α<sub>s</sub> = {frac('γ<sub>d</sub>·M − f′<sub>y</sub>·A′<sub>s</sub>(h<sub>0</sub> − a′<sub>s</sub>)', 'f<sub>c</sub>·b·h<sub>0</sub><sup>2</sup>')}"
                         + " = " + frac(f"{GAMMA_D:.2f}×{m_k}×10<sup>6</sup> − {fmt(fy)}×{fmt(round(Asp), 3)}×({h0:g} − {asp_disp})",
                                        f"{fmt(fc)}×{fmt(b, 3)}×{h0:g}<sup>2</sup>")
                         + f" = {alpha_val}", "（3-31）"),
                    f"α<sub>s</sub> ≤ α<sub>s,max</sub> = {a_b}，满足适用条件，"
                    f"表明已配的 A′<sub>s</sub> 足够。",
                    _tag(f"ξ = 1 − {sqrt_('1−2α<sub>s</sub>')} = 1 − {sqrt_(f'1−2×{alpha_val}')}"
                         f" = {r['xi']:.3f} ≤ ξ<sub>b</sub> = {fmt(xi_b, 3)}", "（3-18）"),
                    f"x = ξ·h<sub>0</sub> = {r['xi']:.3f}×{h0:g} = {r['x']}mm"
                    f"　{sign} 2a′<sub>s</sub> = 2×{asp_disp} = {two_asp}mm",
                    ("满足 x≥2a′<sub>s</sub> 适用条件。" if r["branch"] == "3-32"
                     else "不满足 x≥2a′<sub>s</sub> 适用条件，按式（3-33）计算受拉钢筋。"),
                ]
                if r["branch"] == "3-32":
                    x_disp = str(r["x"])
                    res_lines.append(_tag(
                        f"A<sub>s</sub> = {frac('f<sub>c</sub>·b·x + f′<sub>y</sub>·A′<sub>s</sub>', 'f<sub>y</sub>')}"
                        f" = {frac(f'{fmt(fc)}×{fmt(b, 3)}×{x_disp} + {fmt(fy)}×{fmt(round(Asp), 3)}', fmt(fy))}"
                        f" = {fmt(r['As'], 3)} mm²", "（3-32）"))
                else:
                    res_lines.append(_tag(
                        f"A<sub>s</sub> = {frac('γ<sub>d</sub>·M', 'f<sub>y</sub>(h<sub>0</sub> − a′<sub>s</sub>)')}"
                        f" = {frac(f'{GAMMA_D:.2f}×{m_k}×10<sup>6</sup>', f'{fmt(fy)}×({h0:g} − {asp_disp})')}"
                        f" = {fmt(r['As'], 3)} mm²", "（3-33）"))
            else:
                # 第一种情况：式(3-29) A′s → 式(3-30) As（教材例3-5）
                res_lines = [
                    _tag(f"α<sub>s</sub> = {alpha_s_eq} = {alpha_s_sub} = {alpha_val}", "（3-17）"),
                    f"α<sub>s,max</sub> = ξ<sub>b</sub>(1−0.5ξ<sub>b</sub>) = {a_b}（{_ref('表3-1', steel)}）",
                    "α<sub>s</sub> &gt; α<sub>s,max</sub>（ξ &gt; ξ<sub>b</sub>），单筋截面"
                    "将出现超筋；不能加大截面尺寸、也不能提高混凝土强度等级时，"
                    "应设计成双筋截面。",
                    f"取 α<sub>s</sub> = α<sub>s,max</sub> = {a_b}，受压钢筋按单层布置："
                    f"a′<sub>s</sub> = {asp_disp}mm。",
                    _tag(f"A′<sub>s</sub> = {frac('γ<sub>d</sub>·M − α<sub>s,max</sub>·f<sub>c</sub>·b·h<sub>0</sub><sup>2</sup>', 'f′<sub>y</sub>(h<sub>0</sub> − a′<sub>s</sub>)')}"
                         + " = " + frac(f"{GAMMA_D:.2f}×{m_k}×10<sup>6</sup> − {a_b}×{fmt(fc)}×{fmt(b, 3)}×{h0:g}<sup>2</sup>",
                                        f"{fmt(fy)}×({h0:g} − {asp_disp})")
                         + f" = {fmt(r['Asp'], 3)} mm²", "（3-29）"),
                    _tag(f"A<sub>s</sub> = {frac('f<sub>c</sub>·b·ξ<sub>b</sub>·h<sub>0</sub> + f′<sub>y</sub>·A′<sub>s</sub>', 'f<sub>y</sub>')}"
                         + " = " + frac(f"{fmt(fc)}×{fmt(b, 3)}×{fmt(xi_b, 3)}×{h0:g} + {fmt(fy)}×{fmt(r['Asp'], 3)}", fmt(fy))
                         + f" = {fmt(r['As'], 3)} mm²", "（3-30）"),
                ]
            rho = r["rho"]
            res_lines += [
                f"A<sub>s</sub> + A′<sub>s</sub> = {fmt(r['As'], 3)} + {fmt(r['Asp'], 3)}"
                f" = {fmt(r['total'], 3)} mm²",
                f"ρ = {frac('A<sub>s</sub>', 'b·h<sub>0</sub>')} = "
                f"{frac(fmt(r['As'], 3), f'{fmt(b, 3)}×{h0:g}')} = {pct(rho)}　"
                + (f"≥ ρ<sub>min</sub> = {pct(rho_min)}" if r["rho_ok"]
                   else f"&lt; ρ<sub>min</sub> = {pct(rho_min)}"),
                ("满足纵向受拉钢筋最小配筋率要求。" if r["rho_ok"]
                 else f"不满足纵向受拉钢筋最小配筋率要求，受拉钢筋应按 "
                      f"A<sub>s</sub> = ρ<sub>min</sub>·b·h<sub>0</sub> = "
                      f"{fmt(r['As_min'], 3)}mm² 配置。"),
            ]
            res["res_html"] = html_block([sec_head] + res_lines)
            res["kpi_html"] = kpi_row([
                ("受拉钢筋 A<sub>s</sub>", fmt(r["As"], 3), "mm²",
                 "双筋截面受拉钢筋计算值（式3-29/3-32 分支）；尚未含选筋富余，实配见下方选筋段。"),
                ("受压钢筋 A′<sub>s</sub>" if dbl_known else "所需受压筋 A′<sub>s</sub>",
                 fmt(r["Asp"], 3), "mm²",
                 "已配受压钢筋面积（查附录C 表C-1）。" if dbl_known
                 else "由 αs > αs,max 反算所需的受压钢筋面积（式3-29）；选配建议见下方选筋段。"),
                ("总用量 A<sub>s</sub>+A′<sub>s</sub>", fmt(r["total"], 3), "mm²",
                 "受拉与受压钢筋计算面积之和，便于估算钢筋总量。"),
            ])
            res["rho_ui"] = {
                "value": (min(rho / rho_max, 1.0) if rho_max > 0 else 0),
                "color": ("negative" if rho > 0.9 * rho_max else
                          ("positive" if eco[0] <= rho * 100 <= eco[1] else "warning")),
                "scale_html": (f"0 ── ρ<sub>min</sub> = {pct(rho_min)} ── "
                               f"常用 {eco[0]}~{eco[1]}% ── ρ<sub>max</sub> = "
                               f"{pct(rho_max, 3)}（式3-10b）　｜　当前 ρ = {pct(rho)}"),
            }
            if not r["rho_ok"]:
                res["verdict"] = {"ok": False,
                                  "html": f"✘ 少筋：ρ = {pct(rho)} &lt; ρ<sub>min</sub> = "
                                          f"{pct(rho_min)}。<br>建议：减小截面尺寸（h 或 b）"
                                          f"或按构造 A<sub>s</sub> = ρ<sub>min</sub>·b·h<sub>0</sub> = "
                                          f"{fmt(r['As_min'], 3)}mm² 配置。"}
                res["report"] = _report_design(inp, res, None)
                return res
            if dbl_known:
                res["verdict"] = {"ok": True,
                                  "html": f"✔ 设计可行（双筋·A′<sub>s</sub> 已知）："
                                          f"A<sub>s</sub> = {fmt(r['As'], 3)}mm²，总用量 "
                                          f"{fmt(r['total'], 3)}mm²（A′<sub>s</sub> = "
                                          f"{fmt(r['Asp'], 3)}mm² 已配足够）。"}
            else:
                res["verdict"] = {"ok": True,
                                  "html": f"✔ 设计可行（双筋）：受拉筋 A<sub>s</sub> = "
                                          f"{fmt(r['As'], 3)}mm²，受压筋 A′<sub>s</sub> = "
                                          f"{fmt(r['Asp'], 3)}mm²，总用量 "
                                          f"{fmt(r['total'], 3)}mm²（取 ξ = ξ<sub>b</sub>，"
                                          f"充分利用受压区混凝土）。"}
            bars = _bars_for(member, r["As"], b, inp.get("constraints"))
            bars["title"] = f"{next_no()}. 选筋与构造 — {bars['title']}"
            fig_comp = None
            if dbl_known and dbl_mode == "count":
                fig_comp = (int(inp.get("dia_p", 18)), int(inp.get("n_p", 0) or 0))
            elif not dbl_known:
                cons = inp.get("constraints") or {}
                comp_rows = beam_bar_options(r["Asp"], b, dias=cons.get("dias"),
                                             allow_double=False, max_show=3)
                if comp_rows:
                    c0 = comp_rows[0]
                    comp_name = f"{c0['cnt'].replace('根', '')}{c0['dia']}"
                    extra = (f"受压钢筋：按计算值 A′<sub>s</sub> = {fmt(r['Asp'], 3)}mm²，"
                             f"建议 {comp_name}"
                             f"（实配 {c0['area']}，富余 {c0['margin']}）")
                    bars["hint"] = (extra + ("<br>" + bars["hint"] if bars["hint"] else ""))
                    fig_comp = (int(c0["dia"][1:]), int(c0["cnt"].replace("根", "")))
            res["bars"] = bars
            res["fig"] = {"member": member, "b": b, "h": h, "cs": cs, "as": as_,
                          "dia_est": dia_est, "As": r["As"], "opts": bars["rows"],
                          "c": c, "l0": m_meta.get("l0"),
                          "comp": fig_comp, "comp_as": asp_}
            res["report"] = _report_design(inp, res, inp.get("picked_id"))
            return res

    # ---- 单筋设计（原路径）
    r = singly_rect.design(M, b=b, h0=h0, fc=fc, fy=fy, xi_b=xi_b,
                           rho_min=rho_min, gamma_d=GAMMA_D)
    a_max = r["alpha_s_max"]
    values = {"member": member, "b": b, "h": h, "conc": conc, "steel": steel,
              "env": env, "fc": fc, "fy": fy, "xi_b": xi_b, "rho_min": rho_min,
              "c_min": c_min, "y100": y100, "c": c, "cs": cs, "layers": layers,
              "as_": as_, "h0": h0, "stirrup": stirrup, "dia_est": dia_est,
              "M": M, "a_max": a_max, "rho_max": rho_max, "eco": eco,
              "gamma_d": GAMMA_D, "doubly": False}
    res = {"error": None, "values": values, "r": r, "m_meta": m_meta,
           "m_html": m_html_out, "m_plain": m_plain, "m_title_plain": m_title_plain,
           "m_sub_plain": m_sub_plain, "info_html": info_html,
           "suggest": None, "report": None}
    # 破坏形态扫描图（少筋/适筋/超筋三区 + 当前点；超筋无解时不画当前点）
    res["sweep_html"] = drawing.rho_sweep_svg(
        r["rho"], b, h0, fc, fy, xi_b, rho_min, rho_max, GAMMA_D)

    if r["over_reinforced"]:
        xi_part = (f"ξ = {r['xi']:.3f} &gt; ξ<sub>b</sub> = {fmt(xi_b, 3)}"
                   if r["xi"] is not None else "ξ 无实根（α<sub>s</sub> &gt; 0.5）")
        fail_lines = [
            _tag(f"α<sub>s</sub> = {alpha_s_eq} = {alpha_s_sub} = {r['alpha_s']:.3f}",
                 "（3-17）"),
            f"α<sub>s,max</sub> = ξ<sub>b</sub>(1−0.5ξ<sub>b</sub>) = {fmt(a_max, 3)}",
            xi_part,
            "不满足不发生超筋的要求。",
        ]
        sg = singly_rect.suggest_h(M, b, fc, fy, xi_b, rho_min, GAMMA_D,
                                   as_fn=lambda _h: as_, member=member)
        res["suggest"] = sg
        trial_html, _trial_plain, trial = _trial_block(
            sg, "h_min", "提高", M, b, as_, fc, fy, xi_b, rho_min, sec)
        if trial:
            res["suggest"]["trial"] = trial
        res["res_html"] = html_block([sec_head] + fail_lines + trial_html)
        hint = (f"<br>→ 反解建议：h ≥ {sg['h_min']}mm（按 {sg['mod']} 模数取整）"
                if sg.get("h_min") else "")
        if trial:
            hint += (f"<br>→ 已按 h = {trial['h']:g}mm 试算：设计可行"
                     f"（见「截面提高至 h = {trial['h']:g}mm 试算」）。")
        res["verdict"] = {"ok": False,
                          "html": "✘ 超筋破坏，单筋截面无解。建议：① 加大截面高度 h；"
                                  "② 提高混凝土强度等级；③ 改用双筋截面。" + hint}
        res["report"] = _report_design(inp, res, None)
        return res

    rho = r["rho"]
    under = r["under_reinforced"]
    xi_val, alpha_val = f"{r['xi']:.3f}", f"{r['alpha_s']:.3f}"
    as_eq = frac("f<sub>c</sub>·b·ξ·h<sub>0</sub>", "f<sub>y</sub>")
    as_sub = frac(f"{fmt(fc)}×{fmt(b, 3)}×{xi_val}×{h0:g}", fmt(fy))
    rho_eq = frac("A<sub>s</sub>", "b·h<sub>0</sub>")
    rho_sub = frac(fmt(r["As"], 3), f"{fmt(b, 3)}×{h0:g}")
    res_lines = [
        _tag(f"α<sub>s</sub> = {alpha_s_eq} = {alpha_s_sub} = {alpha_val}"
             f" ≤ α<sub>s,max</sub> = {fmt(a_max, 3)}", "（3-17）"),
        _tag(f"ξ = 1 − {sqrt_('1−2α<sub>s</sub>')} = 1 − {sqrt_(f'1−2×{alpha_val}')}"
             f" = {xi_val} ≤ ξ<sub>b</sub> = {fmt(xi_b, 3)}", "（3-18）"),
        "满足不发生超筋的要求。",
        _tag(f"A<sub>s</sub> = {as_eq} = {as_sub} = {fmt(r['As'], 3)} mm²", "（3-19）"),
        f"ρ = {rho_eq} = {rho_sub} = {pct(rho)}"
        f" {'≥' if not under else '&lt;'} ρ<sub>min</sub> = {pct(rho_min)}",
        ("满足纵向受拉钢筋最小配筋率要求。" if not under
         else "不满足纵向受拉钢筋最小配筋率要求。"),
    ]
    if dbl_single_note:
        res_lines.insert(0, dbl_single_note)
    values.update({"alpha_s": r["alpha_s"], "xi": r["xi"], "As": r["As"], "rho": rho})

    if under:
        sg = singly_rect.suggest_h(M, b, fc, fy, xi_b, rho_min, GAMMA_D,
                                   as_fn=lambda _h: as_, member=member)
        res["suggest"] = sg
        trial_html, _trial_plain, trial = _trial_block(
            sg, "h_max", "减小", M, b, as_, fc, fy, xi_b, rho_min, sec)
        if trial:
            res["suggest"]["trial"] = trial
        res["res_html"] = html_block([sec_head] + res_lines + trial_html)
        hint = (f"（反解：h ≤ {sg['h_max']}mm，按 {sg['mod']} 模数）"
                if sg.get("h_max") else "")
        if trial:
            hint += (f"<br>→ 已按 h = {trial['h']:g}mm 试算：满足最小配筋率"
                     f"（见「截面减小至 h = {trial['h']:g}mm 试算」）。")
        res["verdict"] = {"ok": False,
                          "html": f"✘ 少筋破坏：ρ = {pct(rho)} &lt; "
                                  f"ρ<sub>min</sub> = {pct(rho_min)}。<br>"
                                  "建议：减小截面尺寸（h 或 b）或加大配筋。" + hint}
        res["bars_hint_extra"] = f"{eco_txt}：当前截面偏大或荷载偏小。"
        res["report"] = _report_design(inp, res, None)
        return res

    # 设计可行
    res["verdict"] = {"ok": True, "html": "✔ 设计可行（适筋、且不低于最小配筋率要求）。"}
    res["kpi_html"] = kpi_row([
        ("计算配筋 A<sub>s</sub>", fmt(r["As"], 3), "mm²",
         "按承载力计算所需的纵向受拉钢筋面积（式3-19）；尚未含选筋富余——实配面积见下方「6 选筋与构造」。"),
        ("配筋率 ρ", pct(rho), "",
         "ρ = As/(b·h0)；与 ρmin、ρmax 比较判断少筋/适筋/超筋（ρmax 见式3-10b）。"),
        ("有效高度 h<sub>0</sub>", f"{h0:g}", "mm",
         "h0 = h − as；as 为受拉钢筋合力点至受拉边缘距离（按预估直径 as = cs + d/2）。"),
    ])
    if not (eco[0] <= rho * 100 <= eco[1]):
        res_lines.append(f"提示：ρ 不在{eco_txt}内，可考虑调整截面尺寸。")
    res["res_html"] = html_block([sec_head] + res_lines)
    res["rho_ui"] = {
        "value": (min(rho / rho_max, 1.0) if rho_max > 0 else 0),
        "color": ("negative" if rho > 0.9 * rho_max else
                  ("positive" if eco[0] <= rho * 100 <= eco[1] else "warning")),
        "scale_html": (f"0 ── ρ<sub>min</sub> = {pct(rho_min)} ── "
                       f"常用 {eco[0]}~{eco[1]}% ── ρ<sub>max</sub> = "
                       f"{pct(rho_max, 3)}（式3-10b）　｜　当前 ρ = {pct(rho)}"),
    }
    # 选筋建议（含题目约束）
    bars = _bars_for(member, r["As"], b, inp.get("constraints"))
    bars["title"] = f"{next_no()}. 选筋与构造 — {bars['title']}"
    res["bars"] = bars
    res["fig"] = {"member": member, "b": b, "h": h, "cs": cs, "as": as_,
                  "dia_est": dia_est, "As": r["As"], "opts": bars["rows"],
                  "c": c, "l0": m_meta.get("l0")}
    res["report"] = _report_design(inp, res, inp.get("picked_id"))
    return res


# ---------------------------------------------------------------- 复核题

def solve_verify(inp):
    """承载力复核（例3-4 同类）。非法输入抛 ValueError。

    编号骨架同设计页：1 资料 → [2 荷载标准值 → 3 分项系数 → 4 荷载与内力] 或
    2 弯矩 → 5 承载力复核；判定写成教材整句（满足不发生超筋的要求……）。
    """
    member = inp.get("member", "板")
    b, h, as_ = float(inp.get("b", 0) or 0), float(inp.get("h", 0) or 0), \
        float(inp.get("as_", 0) or 0)
    if b <= 0 or h <= 0 or as_ <= 0:
        raise ValueError("请输入截面尺寸 b、h 与 as（>0）")
    h0 = h - as_
    if h0 <= 0:
        raise ValueError("h0 = h - as 应大于 0")
    mode = inp.get("Asrc", "direct")
    if mode == "direct":
        As = float(inp.get("As", 0) or 0)
        as_desc = f"A<sub>s</sub> = {fmt(As, 3)} mm²（直接输入）"
        as_plain = f"As = {fmt(As, 3)} mm²（直接输入）"
    elif mode == "spacing":
        d, s = int(inp.get("dia_s", 8)), int(inp.get("spacing", 120))
        As = spec_data.bar_area(d) * 1000.0 / s
        as_desc = (f"Φ{d}@{s}：A<sub>s</sub> = {frac('A<sub>d</sub>·1000', 's')}"
                   f" = {frac(f'{fmt(spec_data.bar_area(d))}×1000', fmt(s))}"
                   f" = {fmt(As, 3)} mm²/m（附录C {_ref('表C-2')} 算法）")
        as_plain = f"Φ{d}@{s}：As = {fmt(spec_data.bar_area(d))}×1000/{s} = {fmt(As, 3)} mm²/m"
    else:
        d, n = int(inp.get("dia_c", 16)), int(inp.get("n", 0) or 0)
        if n <= 0:
            raise ValueError("请输入钢筋根数 n（>0）")
        As = spec_data.bar_area_n(d, n)      # 表C-1 多根列（教材手算查表习惯）
        as_desc = (f"{n}Φ{d}：A<sub>s</sub> = {fmt(As, 3)} mm²（查附录C {_ref('表C-1', f'Φ{d}')}）")
        as_plain = f"{n}Φ{d}：As = {fmt(As, 3)} mm²（查附录C 表C-1）"
    if As <= 0:
        raise ValueError("请输入钢筋面积 As（>0）")
    # 受压钢筋（双筋复核，可选；"none" = 单筋，行为与原单筋链完全一致）
    dbl_mode, Asp, asp_, asp_desc, asp_plain = _doubly_inputs(inp, h0, member)
    doubly = dbl_mode in ("count", "direct")
    conc, steel = inp["conc"], inp["steel"]
    fc, fy = spec_data.concrete_fc(conc), spec_data.steel_fy(steel)
    xi_b = spec_data.xi_b(steel)
    rho_min = spec_data.rho_min(steel, member)
    # ---- 编号小节
    sec, _next_no = _sec_counter()
    m_mode = inp.get("m_mode", "direct")        # load / moments / direct
    load = inp.get("load", {})
    # 1. 资料
    info = [
        f"{info_label('材料')}　混凝土 {conc}：f<sub>c</sub> = {fmt(fc)} N/mm²　｜　"
        f"钢筋 {steel}：f<sub>y</sub> = {fmt(fy)} N/mm²，ξ<sub>b</sub> = {fmt(xi_b, 3)}，"
        f"ρ<sub>min</sub> = {pct(rho_min)}（{member}）",
        f"{info_label('出处')}　fc、fy "
        f"{_src_pair_ref(spec_data.concrete_fc_source(conc), spec_data.steel_fy_source(steel), conc, steel)}"
        f"　｜　"
        f"ξ<sub>b</sub> {_ref(_src_tags(spec_data.xi_b_source(steel), 1), steel)}　｜　"
        f"ρ<sub>min</sub> {_ref(_src_tags(spec_data.rho_min_source(steel, member), 2), member)}",
        f"{info_label('截面')}　b×h = {fmt(b, 3)}×{fmt(h, 3)}mm，"
        f"a<sub>s</sub> = {fmt(as_, 3)}mm　→　h<sub>0</sub> = {h0:g}mm　｜　{as_desc}",
    ]
    if m_mode == "moments":
        _lvl, _sit = load.get("level", "III"), load.get("situation", "持久")
        info.insert(2, f"{info_label('系数')}　"
                       f"γ<sub>0</sub> = {spec_data.gamma0(_lvl):.1f}"
                       f"（{_ref(_src_tags(spec_data.gamma0_source(_lvl), 1), 'γ0')}，{_lvl}级）　"
                       f"ψ = {spec_data.psi(_sit):.1f}"
                       f"（{_ref(_src_tags(spec_data.psi_source(_sit), 1), 'ψ')}，{_sit}）　"
                       f"γ<sub>d</sub> = {GAMMA_D:.2f}"
                       f"（{_ref(_src_tags(spec_data.gamma_d_source(), 1), 'γd')}）")
    elif m_mode != "load":
        info.insert(2, f"{info_label('系数')}　γ<sub>d</sub> = {GAMMA_D:.2f}"
                       f"（{_ref(_src_tags(spec_data.gamma_d_source(), 1), 'γd')}）")
    if doubly:
        info.append(f"{info_label('受压筋')}　a′<sub>s</sub> = {fmt(asp_, 3)}mm"
                    f"　｜　{asp_desc}")
    info_html = html_block([sec("资料")] + info)
    # 荷载链 / 标准值弯矩 / 题给弯矩
    m_sub_plain = []
    if m_mode == "load":
        M, m_html, m_plain, m_meta = _m_chain(load, member, h)
        std_html, std_plain = _std_section(load, member, b, h)
        gam_html, gam_plain = _gamma_section(load)
        m_html_out = html_block(
            [sec("荷载标准值")] + std_html +
            [sec("分项系数")] + gam_html +
            [sec("荷载与内力", "（式2-35）")] + m_html)
        m_title_plain = "二、荷载与内力"
        m_sub_plain = (["  （1）荷载标准值"] + [f"    {x}" for x in std_plain] +
                       ["  （2）分项系数"] + [f"    {x}" for x in gam_plain] +
                       ["  （3）荷载设计值与内力"])
    elif m_mode == "moments":
        M, m_html, m_plain, m_meta = _moments_chain(load)
        m_html_out = html_block([sec("内力计算")] + m_html)
        m_title_plain = "二、内力计算"
    else:
        M_kNm = float(inp.get("M_kNm", 0) or 0)
        M = M_kNm * 1e6 if M_kNm > 0 else None
        m_meta = {"M": M_kNm}
        m_html = ([f"已知 M = {_f2(M_kNm)} kN·m"]
                  if M is not None else ["M = —（未输入，仅计算 M<sub>u</sub>）"])
        m_plain = ([f"已知 M = {_f2(M_kNm)} kN·m"] if M is not None
                   else ["M = —（未输入，仅计算 Mu）"])
        m_html_out = html_block([sec("弯矩")] + m_html)
        m_title_plain = "二、弯矩"
    if doubly:
        r = doubly_rect.verify(As, Asp, b=b, h0=h0, asp=asp_, fc=fc, fy=fy,
                               xi_b=xi_b, gamma_d=GAMMA_D, M=M, rho_min=rho_min)
    else:
        r = singly_rect.verify(As, b=b, h0=h0, fc=fc, fy=fy, xi_b=xi_b,
                               gamma_d=GAMMA_D, M=M, rho_min=rho_min)
    values = {"member": member, "b": b, "h": h, "as_": as_, "h0": h0,
              "As": As, "as_desc": as_desc, "as_plain": as_plain,
              "doubly": doubly, "Asp": Asp, "asp_": asp_,
              "asp_desc": asp_desc, "asp_plain": asp_plain,
              "conc": conc, "steel": steel, "fc": fc, "fy": fy,
              "xi_b": xi_b, "rho_min": rho_min, "M": M, "gamma_d": GAMMA_D}
    res = {"error": None, "values": values, "r": r, "m_meta": m_meta,
           "m_html": m_html_out, "m_plain": m_plain, "m_title_plain": m_title_plain,
           "m_sub_plain": m_sub_plain, "info_html": info_html}
    xi_val = f"{r['xi']:.3f}"
    if doubly:
        # 教材例3-8 手算习惯：M_u 4 位有效保留尾零（320.0），M′ 按显示值代入
        mu_k = _f4(r["Mu"] / 1e6)
        mal_k = _f2(float(mu_k) / GAMMA_D)
    else:
        mu_k, mal_k = fmt(r["Mu"] / 1e6, 3), fmt(r["M_allowed"] / 1e6, 3)
    res["kpi_html"] = kpi_row([
        ("相对受压区高度 ξ", xi_val, "",
         "ξ = x/h0；需 ≤ ξb（表3-1）才不发生超筋破坏。"),
        ("抗弯承载力 M<sub>u</sub>", mu_k, "kN·m",
         "按实配钢筋（查附录C 表C-1）算出的受弯承载力（式3-22/3-25）。"),
        ("M′ = M<sub>u</sub>/γ<sub>d</sub>", mal_k, "kN·m",
         "承载力设计值：Mu 除以结构系数 γd（表2-7），与弯矩设计值 M 比较。"),
    ])
    rho_line = (f"ρ = {frac('A<sub>s</sub>', 'b·h<sub>0</sub>')} = "
                f"{frac(fmt(round(As), 3), f'{fmt(b, 3)}×{h0:g}')} = "
                f"{pct(r['rho'])}　"
                + (f"≥ ρ<sub>min</sub> = {pct(rho_min)}" if r["rho_ok"]
                   else f"&lt; ρ<sub>min</sub> = {pct(rho_min)}"))
    if doubly:
        # 5. 承载力复核（教材3.5.3：式3-25 定 x → 适用条件 → 式3-22/3-28 求 M_u）
        x_disp = f"{r['x']}"
        asp_disp, two_asp = fmt(asp_, 3), fmt(2 * asp_, 3)
        xi_line = (f"ξ = {frac('f<sub>y</sub>·A<sub>s</sub> − f′<sub>y</sub>·A′<sub>s</sub>', 'f<sub>c</sub>·b·h<sub>0</sub>')}"
                   f" = {frac(f'{fmt(fy)}×{fmt(round(As), 3)}−{fmt(fy)}×{fmt(round(Asp), 3)}', f'{fmt(fc)}×{fmt(b, 3)}×{h0:g}')}"
                   f" = {xi_val}　"
                   + ("≤ ξ<sub>b</sub> = " + fmt(xi_b, 3) if r["xi_ok"]
                      else f"&gt; ξ<sub>b</sub> = {fmt(xi_b, 3)}"))
        formula_lines = [_tag(xi_line, "（3-25）")]
        if r["xi_ok"]:
            formula_lines.append("满足不发生超筋的要求。")
            sign = ("&gt;" if r["x"] > 2 * asp_ else
                    ("=" if r["x"] == 2 * asp_ else "&lt;"))
            formula_lines.append(
                f"x = ξ·h<sub>0</sub> = {xi_val}×{h0:g} = {x_disp}mm"
                f"　{sign} 2a′<sub>s</sub> = 2×{asp_disp} = {two_asp}mm")
            formula_lines.append(
                "满足 x≥2a′<sub>s</sub> 适用条件。" if r["two_asp_ok"]
                else "不满足 x≥2a′<sub>s</sub> 适用条件，按式（3-28）计算。")
        else:
            formula_lines.append(
                f"ξ &gt; ξ<sub>b</sub>（超筋），按教材复核步骤（1）取 "
                f"x = ξ<sub>b</sub>·h<sub>0</sub> = {fmt(xi_b, 3)}×{h0:g}"
                f" = {x_disp}mm 代入式（3-22）计算。")
        if r["branch"] == "3-22":
            mu_line = (f"M<sub>u</sub> = f<sub>c</sub>·b·x(h<sub>0</sub> − x/2)"
                       f" + f′<sub>y</sub>·A′<sub>s</sub>(h<sub>0</sub> − a′<sub>s</sub>)"
                       f" = {fmt(fc)}×{fmt(b, 3)}×{x_disp}×({h0:g} − {x_disp}/2)"
                       f" + {fmt(fy)}×{fmt(round(Asp), 3)}"
                       f"×({h0:g} − {asp_disp})"
                       f" = {mu_k}×10<sup>6</sup> N·mm = {mu_k} kN·m")
            formula_lines.append(_tag(mu_line, "（3-22）"))
        else:
            mu_line = (f"M<sub>u</sub> = f<sub>y</sub>·A<sub>s</sub>"
                       f"(h<sub>0</sub> − a′<sub>s</sub>)"
                       f" = {fmt(fy)}×{fmt(round(As), 3)}"
                       f"×({h0:g} − {asp_disp})"
                       f" = {mu_k}×10<sup>6</sup> N·mm = {mu_k} kN·m")
            formula_lines.append(_tag(mu_line, "（3-28）"))
    else:
        a_val = f"{r['alpha_s']:.3f}"
        formula_lines = [
            _tag((f"ξ = {frac('f<sub>y</sub>·A<sub>s</sub>', 'f<sub>c</sub>·b·h<sub>0</sub>')}"
                  f" = {frac(f'{fmt(fy)}×{fmt(round(As), 3)}', f'{fmt(fc)}×{fmt(b, 3)}×{h0:g}')}"
                  f" = {xi_val}　"
                  + ("≤ ξ<sub>b</sub> = " + fmt(xi_b, 3) if r["xi_ok"]
                     else f"&gt; ξ<sub>b</sub> = {fmt(xi_b, 3)}")), "（3-14）"),
            ("满足不发生超筋的要求。" if r["xi_ok"]
             else f"ξ &gt; ξ<sub>b</sub> = {fmt(xi_b, 3)}，不满足不发生超筋的要求（超筋）。"),
            _tag(f"α<sub>s</sub> = ξ(1−0.5ξ) = {xi_val}×(1−0.5×{xi_val}) = {a_val}",
                 "（3-12）"),
            _tag(f"M<sub>u</sub> = α<sub>s</sub>·f<sub>c</sub>·b·h<sub>0</sub><sup>2</sup> "
                 f"= {a_val}×{fmt(fc)}×{fmt(b, 3)}×{h0:g}<sup>2</sup> "
                 f"= {mu_k} kN·m", "（3-13）"),
        ]
    formula_lines += [
        f"M′ = {frac('M<sub>u</sub>', 'γ<sub>d</sub>')}"
        f" = {frac(mu_k, f'{GAMMA_D:.2f}')} = {mal_k} kN·m",
        rho_line,
        ("满足纵向受拉钢筋最小配筋率要求。" if r["rho_ok"]
         else "不满足纵向受拉钢筋最小配筋率要求（少筋）。"),
    ]
    if M is not None:
        m_k = _f2(M / 1e6)
        formula_lines.append(
            f"M = {m_k} kN·m，M′ 与 M 比较：{mal_k} "
            f"{'≥' if r['M_allowed'] >= M else '&lt;'} {m_k}")
        if doubly:
            formula_lines.append(
                "正截面受弯承载力满足当前荷载的要求。" if r["M_allowed"] >= M
                else "正截面受弯承载力不能满足当前荷载的要求，不安全。")
        else:
            formula_lines.append(
                "正截面受弯承载力满足要求。" if r["M_allowed"] >= M
                else "正截面受弯承载力不能满足要求，不安全。")
    # 复核页无独立弯矩卡：弯矩块 + 复核小节并入结果块
    res["res_html"] = m_html_out + html_block(
        [sec("承载力复核")] + formula_lines)
    # ρ 标尺（与设计页一致）
    eco = spec_data.economic_rho_percent("板" if member == "板" else "矩形梁")
    rho_max = singly_rect.rho_max(fc, fy, xi_b)
    res["rho_ui"] = {
        "value": (min(r["rho"] / rho_max, 1.0) if rho_max > 0 else 0),
        "color": ("negative" if r["rho"] > 0.9 * rho_max else
                  ("positive" if eco[0] <= r["rho"] * 100 <= eco[1] else "warning")),
        "scale_html": (f"0 ── ρ<sub>min</sub> = {pct(rho_min)} ── "
                       f"常用 {eco[0]}~{eco[1]}% ── ρ<sub>max</sub> = "
                       f"{pct(rho_max, 3)}（式3-10b）　｜　当前 ρ = {pct(r['rho'])}"),
    }
    # 判定（不安全时给反解最小截面高提示——闭式解，同设计页续演思路；双筋不适用）
    h_hint = None
    if M is not None and not r["safe"] and r["rho_ok"] and not doubly:
        if not r["xi_ok"]:
            h0_min = singly_rect.min_h0_for_xi(round(As), b, fc, fy, xi_b)
            h_hint = {"why": "超筋", "h0_min": h0_min}
        elif r["M_allowed"] < M:
            h0_min = singly_rect.min_h0_for_M(round(As), M, b, fc, fy, GAMMA_D)
            h_hint = {"why": "受弯承载力不足", "h0_min": h0_min}
        if h_hint:
            h_hint["h"] = _h_mod_up(h0_min + as_, member)
            h_hint["mod"] = 50 if member == "梁" else 10
    res["h_hint"] = h_hint
    if M is None:
        res["verdict"] = {"ok": r["xi_ok"] and r["rho_ok"],
                          "html": ("✔ 未输入 M：抗弯承载力 M<sub>u</sub> = "
                                   + mu_k + " kN·m"
                                   if r["xi_ok"] and r["rho_ok"] else
                                   "✘ 截面超筋或严重少筋，请检查输入（结果见上）。")}
    elif r["safe"]:
        res["verdict"] = {"ok": True,
                          "html": f"✔ 承载力满足：M′ = M<sub>u</sub>/γ<sub>d</sub> = "
                                  f"{mal_k} kN·m ≥ M = {_f2(M / 1e6)} kN·m。"}
    else:
        why = []
        if not r["xi_ok"]:
            why.append("ξ &gt; ξ<sub>b</sub>（超筋）")
        if not r["rho_ok"]:
            why.append("ρ &lt; ρ<sub>min</sub>（少筋）")
        if r["M_allowed"] < M:
            why.append(f"M′ = {mal_k} &lt; M = {_f2(M / 1e6)}（受弯承载力不足）")
        tip = ""
        if h_hint:
            tip = (f"<br>→ 反解（{h_hint['why']}）：需 h<sub>0</sub> ≥ "
                   f"{fmt(h_hint['h0_min'], 3)}mm，取 h ≥ {h_hint['h']:g}mm"
                   f"（按 {h_hint['mod']}mm 模数）")
        res["verdict"] = {"ok": False, "html": "✘ 不安全：" + "；".join(why) + "。" + tip}
    res["report"] = _report_verify(inp, res)
    return res


# ---------------------------------------------------------------- 计算书（纯文本）

def _design_report_doubly_calc(L, v, r):
    """计算书「三、配筋计算」双筋段（教材3.5.2，图3-27）。"""
    h0 = v["h0"]
    m_k = _f2(v["M"] / 1e6)
    asp_d = fmt(v["asp_"], 3)
    L.append("三、配筋计算")
    if r.get("need_more"):
        L.append(f"  αs = (γd·M − f′y·A′s(h0−a′s))/(fc·b·h0²) = "
                 f"({v['gamma_d']:.2f}×{m_k}×10⁶ − {fmt(v['fy'])}×"
                 f"{fmt(round(v['Asp']), 3)}×({h0:g}−{asp_d})/"
                 f"({fmt(v['fc'])}×{v['b']:g}×{h0:g}²) = {r['alpha_s']:.3f}")
        L.append(f"  αs > αs,max = {fmt(r['alpha_s_b'], 3)}（表3-1），"
                 f"表明已配的 A′s = {fmt(round(v['Asp']), 3)} mm² 不足，需增加 A′s")
        L.append(f"  按式(3-29)，所需 A′s ≥ {fmt(r['Asp_min'], 3)} mm²")
        return True
    if r.get("mode") == "unknown":
        L.append(f"  αs = γd·M/(fc·b·h0²) = {v['gamma_d']:.2f}×{m_k}×10⁶/"
                 f"({fmt(v['fc'])}×{v['b']:g}×{h0:g}²) = {r['alpha_s']:.3f} > "
                 f"αs,max = {fmt(r['alpha_s_b'], 3)}（表3-1）")
        L.append("  αs > αs,max，单筋截面将出现超筋；不能加大截面尺寸、也不能提高"
                 "混凝土强度等级时，应设计成双筋截面")
        L.append(f"  取 αs = αs,max = {fmt(r['alpha_s_b'], 3)}，受压钢筋按单层布置："
                 f"a′s = {asp_d} mm")
        L.append(f"  A′s = (γd·M − αs,max·fc·b·h0²)/(f′y(h0−a′s)) = "
                 f"({v['gamma_d']:.2f}×{m_k}×10⁶ − {fmt(r['alpha_s_b'], 3)}×"
                 f"{fmt(v['fc'])}×{v['b']:g}×{h0:g}²)/({fmt(v['fy'])}×"
                 f"({h0:g}−{asp_d})) = {fmt(r['Asp'], 3)} mm²")
        L.append(f"  As = (fc·b·ξb·h0 + f′y·A′s)/fy = {fmt(v['fc'])}×{v['b']:g}×"
                 f"{v['xi_b']}×{h0:g} + {fmt(v['fy'])}×{fmt(r['Asp'], 3)})/"
                 f"{fmt(v['fy'])} = {fmt(r['As'], 3)} mm²")
    else:
        L.append(f"  αs = (γd·M − f′y·A′s(h0−a′s))/(fc·b·h0²) = "
                 f"({v['gamma_d']:.2f}×{m_k}×10⁶ − {fmt(v['fy'])}×"
                 f"{fmt(round(v['Asp']), 3)}×({h0:g}−{asp_d}))/"
                 f"({fmt(v['fc'])}×{v['b']:g}×{h0:g}²) = {r['alpha_s']:.3f} ≤ "
                 f"αs,max = {fmt(r['alpha_s_b'], 3)}（表3-1）")
        L.append(f"  满足适用条件，表明已配的 A′s = {fmt(round(v['Asp']), 3)} mm² 足够")
        L.append(f"  ξ = 1-√(1-2αs) = 1-√(1-2×{r['alpha_s']:.3f}) = {r['xi']:.3f} "
                 f"≤ ξb = {v['xi_b']}")
        L.append(f"  x = ξ·h0 = {r['xi']:.3f}×{h0:g} = {r['x']} mm "
                 + (">" if r["x"] > 2 * v["asp_"] else "=")
                 + f" 2a′s = {fmt(2 * v['asp_'], 3)} mm")
        if r["branch"] == "3-32":
            L.append("  满足 x≥2a′s 适用条件")
            L.append(f"  As = (fc·b·x + f′y·A′s)/fy = {fmt(v['fc'])}×{v['b']:g}×"
                     f"{r['x']} + {fmt(v['fy'])}×{fmt(round(v['Asp']), 3)})/"
                     f"{fmt(v['fy'])} = {fmt(r['As'], 3)} mm²")
        else:
            L.append("  不满足 x≥2a′s 适用条件，按式(3-33)计算受拉钢筋")
            L.append(f"  As = γd·M/(fy(h0−a′s)) = {v['gamma_d']:.2f}×{m_k}×10⁶/"
                     f"({fmt(v['fy'])}×({h0:g}−{asp_d})) = {fmt(r['As'], 3)} mm²")
    L.append(f"  As + A′s = {fmt(r['As'], 3)} + {fmt(r['Asp'], 3)} = "
             f"{fmt(r['total'], 3)} mm²")
    L.append(f"  ρ = As/(b·h0) = {fmt(r['As'], 3)}/({v['b']:g}×{h0:g}) = "
             f"{pct(r['rho'])} {'≥' if r['rho_ok'] else '<'} ρmin = "
             f"{pct(v['rho_min'])} {'✓' if r['rho_ok'] else '✘'}")
    L.append("  满足纵向受拉钢筋最小配筋率要求。" if r["rho_ok"]
             else f"  不满足最小配筋率要求，应按 As = ρmin·b·h0 = "
                  f"{fmt(r['As_min'], 3)} mm² 配置。")
    return not r["rho_ok"]


def _report_design(inp, res, picked_id):
    v = res["values"]
    r = res["r"]
    member, b, h = v["member"], v["b"], v["h"]
    h0 = v["h0"]
    L = ["双筋矩形截面正截面受弯承载力计算书 —— 截面设计"
         if v.get("doubly") else
         "单筋矩形截面正截面受弯承载力计算书 —— 截面设计",
         "依据：NB/T 11011-2022《水工混凝土结构设计规范》；",
         "　　　《水工钢筋混凝土结构学》第3章", ""]
    L.append("一、资料")
    L.append(f"  混凝土 {v['conc']}：fc = {v['fc']} N/mm²；"
             f"钢筋 {v['steel']}：fy = {v['fy']} N/mm²，ξb = {v['xi_b']}")
    env_note = (f"（{fmt(v['c_min'])}×1.4 向上取整，使用年限100年）" if v["y100"]
                else f"（{_ref('表D-1', v['env'] + '类')} {v['env']}类{member}）")
    cs_plain = ("c+箍筋预估%0.0f" % v["stirrup"]) if member == "梁" else "c（板）"
    as_plain = (f"cs+Φ{v['dia_est']:g}/2" if v["layers"] == 1 else "cs+35")
    L.append(f"  环境类别{v['env']}：c = {v['c']:g} mm {env_note} → "
             f"cs = {cs_plain} = {v['cs']:g} mm")
    L.append(f"  截面 b×h = {b:g}×{h:g} mm，{v['layers']}层布筋 "
             f"as = {as_plain} = {v['as_']:g} mm → h0 = {v['h0']:g} mm")
    if v.get("doubly"):
        asp_note = (v["asp_plain"] if v.get("dbl_mode") != "unknown"
                    else "A′s 待求（双筋设计·第一种情况）")
        L.append(f"  受压筋 a's = {v['asp_']:g} mm　｜　{asp_note}")
    L.append(f"  系数 γd = {v['gamma_d']}")
    L.append(f"  查表：fc、fy "
             f"{_src_pair(spec_data.concrete_fc_source(v['conc']), spec_data.steel_fy_source(v['steel']))}"
             f"；ξb {_src_tags(spec_data.xi_b_source(v['steel']), 1)}"
             f"；ρmin {_src_tags(spec_data.rho_min_source(v['steel'], member), 2)}")
    L += [f"  {x}" for x in res["m_plain"]]
    pos = len(L) - len(res["m_plain"])
    L.insert(pos, res["m_title_plain"])
    for i, x in enumerate(res.get("m_sub_plain") or []):
        L.insert(pos + 1 + i, x)
    L.append("")
    doubly = bool(v.get("doubly"))
    if doubly:
        under = _design_report_doubly_calc(L, v, r)
        if r.get("need_more"):
            L.append("")
            L.append("结论：不安全（已配受压钢筋 A′s 不足，需增加 A′s）。")
            return "\n".join(L)
    elif r["over_reinforced"]:
        L.append("三、配筋计算")
        L.append(f"  αs = γd·M/(fc·b·h0²) = {fmt(r['alpha_s'], 3)}，"
                 f"αs,max = {fmt(v['a_max'], 3)}")
        if r["xi"] is not None:
            L.append(f"  ξ = {r['xi']:.3f} > ξb = {v['xi_b']}，"
                     "不满足不发生超筋的要求，超筋，单筋截面无解")
        else:
            L.append("  ξ 无实根（αs > 0.5），不满足不发生超筋的要求，超筋")
        if res.get("suggest") and res["suggest"].get("h_min"):
            L.append(f"  反解建议：h ≥ {res['suggest']['h_min']} mm"
                     f"（按 {res['suggest']['mod']} 模数取整）")
        tr = (res.get("suggest") or {}).get("trial")
        if tr:
            t = tr["r"]
            L.append(f"  为此，截面高度提高到 {tr['h']:g} mm（{tr['mod']} 模数），"
                     f"h0′ = {fmt(tr['h0'], 3)} mm：")
            L.append(f"    αs = {t['alpha_s']:.3f} ≤ αs,max = {fmt(v['a_max'], 3)}；"
                     f"ξ = {t['xi']:.3f} ≤ ξb = {v['xi_b']} ✓（满足不发生超筋的要求）")
            L.append(f"    As = {fmt(t['As'], 3)} mm²，ρ = {pct(t['rho'])} "
                     f"≥ ρmin = {pct(v['rho_min'])} ✓（满足最小配筋率要求）→ 可行")
        L.append("  另可：提高混凝土强度等级，或改用双筋截面。")
        L.append("")
        L.append("结论：超筋，当前截面不可行。")
        return "\n".join(L)
    else:
        rho = r["rho"]
        under = r["under_reinforced"]
        L.append("三、配筋计算")
        L.append(f"  αs = γd·M/(fc·b·h0²) = {v['gamma_d']:.2f}×{_f2(v['M'] / 1e6)}×10⁶"
                 f"/({fmt(v['fc'])}×{b:g}×{h0:g}²) = {r['alpha_s']:.3f} "
                 f"≤ αs,max = {fmt(v['a_max'], 3)}")
        xi_v = f"{r['xi']:.3f}"
        L.append(f"  ξ = 1-√(1-2αs) = 1-√(1-2×{r['alpha_s']:.3f}) = {xi_v} "
                 f"≤ ξb = {v['xi_b']}")
        L.append("  满足不发生超筋的要求。")
        L.append(f"  As = fc·b·ξ·h0/fy = {fmt(v['fc'])}×{b:g}×{xi_v}×{h0:g}/{fmt(v['fy'])}"
                 f" = {fmt(r['As'], 3)} mm²")
        L.append(f"  ρ = As/(b·h0) = {fmt(r['As'], 3)}/({b:g}×{h0:g}) = {pct(rho)}"
                 f" {'≥' if not under else '<'} ρmin = {pct(v['rho_min'])} "
                 f"{'✓' if not under else '✘'}")
        L.append("  满足纵向受拉钢筋最小配筋率要求。" if not under
                 else "  不满足纵向受拉钢筋最小配筋率要求。")
    L.append("")
    L.append("四、选筋与构造")
    bars = res.get("bars")
    picked = None
    if bars and bars["rows"]:
        picked = next((x for x in bars["rows"] if x.get("id") == picked_id),
                      bars["rows"][0])
    if picked is None:
        L.append("  （约束内无可行选筋方案）" if not under else
                 "  （少筋不可行，选筋从略）")
    else:
        if member == "梁":
            name = f"{picked['cnt'].replace('根', '')}Φ{picked['dia'][1:]}"
            n = int(picked["cnt"].replace("根", ""))
            d_ = int(picked["dia"][1:])
            L.append(f"  计算 As = {fmt(r['As'], 3)} mm²，建议 {name}"
                     f"（实配 {picked['area']}，富余 {picked['margin']}）")
            if "双层" in picked.get("fit", ""):
                L.append(f"  排布：{picked['fit'].replace('✓', '').strip()}，双层布置 ✓")
            else:
                w = 2 * SIDE_COVER + n * d_ + (n - 1) * CLEAR_SPACING
                L.append(f"  单层排布宽度 = 2×{SIDE_COVER:g}+{n}×{d_}"
                         f"+{n - 1}×{CLEAR_SPACING:g} = {w:g} ≤ b = {b:g} mm，可单层布置 ✓")
            Asr = spec_data.bar_area_n(d_, n)
        else:
            name = picked["spec"]
            L.append(f"  计算 As = {fmt(r['As'], 3)} mm²，建议 {name}"
                     f"（每米实配 {picked['area'].replace('/m', '')}"
                     + (f"，{b:g}mm 板宽共 {picked['total']}" if picked.get("total") else "")
                     + f"，富余 {picked['margin']}）")
            d, s = name[1:].split("@")
            Asr = spec_data.bar_area(int(d)) * 1000.0 / int(s) * b / 1000.0
        as_act, h0_act = _actual_as_h0(v, picked)
        as_note = ""
        if as_act is not None and h0_act and h0_act > 0:
            h0 = h0_act
            if abs(as_act - v["as_"]) > 0.05:
                as_note = f"，as 按实配重算 = {fmt(as_act, 3)}mm → h0 = {h0:g}mm"
        if doubly:
            rv = doubly_rect.verify(Asr, v["Asp"], b=b, h0=h0, asp=v["asp_"],
                                    fc=v["fc"], fy=v["fy"], xi_b=v["xi_b"],
                                    gamma_d=v["gamma_d"], M=v["M"],
                                    rho_min=v["rho_min"])
            L.append(f"  实配回验（双筋）：As = {fmt(Asr, 3)} mm²{as_note}，"
                     f"ξ = {rv['xi']:.3f} {'≤' if rv['xi_ok'] else '>'} ξb"
                     + ("" if rv["xi_ok"] else "（实配略超计算值，按 ξb 封顶复核）")
                     + f"，M′ = {_f2(rv['M_allowed'] / 1e6)} kN·m "
                     f"{'≥' if rv['M_allowed'] >= v['M'] else '<'} "
                     f"M = {_f2(v['M'] / 1e6)} kN·m")
        else:
            rv = singly_rect.verify(Asr, b=b, h0=h0, fc=v["fc"], fy=v["fy"],
                                    xi_b=v["xi_b"], gamma_d=v["gamma_d"],
                                    M=v["M"], rho_min=v["rho_min"])
            L.append(f"  实配回验：As = {fmt(Asr, 3)} mm²{as_note}，ρ = {pct(rv['rho'])} "
                     f"{'≥' if rv['rho_ok'] else '<'} ρmin ✓，ξ = {rv['xi']:.3f} "
                     f"{'≤' if rv['xi_ok'] else '>'} ξb，"
                     f"M′ = {_f2(rv['M_allowed'] / 1e6)} kN·m "
                     f"{'≥' if rv['M_allowed'] >= v['M'] else '<'} M = {_f2(v['M'] / 1e6)} kN·m")
    if doubly and v.get("dbl_mode") == "unknown":
        _rows = beam_bar_options(r["Asp"], b,
                                 dias=(inp.get("constraints") or {}).get("dias"),
                                 allow_double=False, max_show=1)
        if _rows:
            _c = _rows[0]
            L.append(f"  受压钢筋：按计算 A′s = {fmt(r['Asp'], 3)} mm²，建议 "
                     f"{_c['cnt'].replace('根', '')}Φ{_c['dia'][1:]}"
                     f"（实配 {_c['area']}，富余 {_c['margin']}）")
    L.append("")
    eco = v["eco"]
    if under:
        if doubly:
            L.append(f"结论：少筋（ρ &lt; ρmin），应按 As = ρmin·b·h0 = "
                     f"{fmt(r['As_min'], 3)} mm² 构造配置或减小截面。")
            return "\n".join(L)
        concl = "结论：少筋，当前截面不可行"
        if res.get("suggest") and res["suggest"].get("h_max"):
            concl += f"（反解 h ≤ {res['suggest']['h_max']} mm）"
        tr = (res.get("suggest") or {}).get("trial")
        if tr:
            concl += (f"；截面减小至 {tr['h']:g} mm 试算满足最小配筋率"
                      f"（ρ = {pct(tr['r']['rho'])}）")
        L.append(concl + "。")
    elif doubly:
        L.append(f"结论：设计可行（双筋：As = {fmt(r['As'], 3)} mm²、"
                 f"A′s = {fmt(r['Asp'], 3)} mm²，总用量 {fmt(r['total'], 3)} mm²）。")
    else:
        eco_note = ("" if eco[0] <= rho * 100 <= eco[1]
                    else f"，ρ 不在常用范围 {eco[0]}~{eco[1]}%")
        L.append(f"结论：设计可行（适筋，ρ ≥ ρmin{eco_note}）。")
    return "\n".join(L)


def _report_verify(inp, res):
    v = res["values"]
    r = res["r"]
    member = v["member"]
    doubly = v.get("doubly")
    L = ["双筋矩形截面正截面受弯承载力计算书 —— 承载力复核" if doubly
         else "单筋矩形截面正截面受弯承载力计算书 —— 承载力复核",
         "依据：NB/T 11011-2022《水工混凝土结构设计规范》；",
         "　　　《水工钢筋混凝土结构学》第3章", ""]
    L.append("一、资料")
    L.append(f"  混凝土 {v['conc']}：fc = {v['fc']} N/mm²；"
             f"钢筋 {v['steel']}：fy = {v['fy']} N/mm²，ξb = {v['xi_b']}")
    L.append(f"  截面 b×h = {v['b']:g}×{v['h']:g} mm，as = {v['as_']:g} mm → "
             f"h0 = {v['h0']:g} mm")
    L.append(f"  配筋 {v['as_plain']}")
    if doubly:
        L.append(f"  受压筋 {v['asp_plain']}，a's = {v['asp_']:g} mm")
    L.append(f"  系数 γd = {v['gamma_d']:.2f}，ρmin = {pct(v['rho_min'])}")
    L.append(f"  查表：fc、fy "
             f"{_src_pair(spec_data.concrete_fc_source(v['conc']), spec_data.steel_fy_source(v['steel']))}"
             f"；ξb {_src_tags(spec_data.xi_b_source(v['steel']), 1)}"
             f"；ρmin {_src_tags(spec_data.rho_min_source(v['steel'], member), 2)}")
    L += [f"  {x}" for x in res["m_plain"]]
    pos = len(L) - len(res["m_plain"])
    L.insert(pos, res["m_title_plain"])
    for i, x in enumerate(res.get("m_sub_plain") or []):
        L.insert(pos + 1 + i, x)
    L.append("")
    L.append("三、复核计算")
    xi_v = f"{r['xi']:.3f}"
    if doubly:
        mu_k = _f4(r["Mu"] / 1e6)
        mal_k = _f2(float(mu_k) / v["gamma_d"])
        L.append(f"  ξ = (fy·As − fy·A's)/(fc·b·h0) = "
                 f"({fmt(v['fy'])}×{fmt(round(v['As']), 3)} − "
                 f"{fmt(v['fy'])}×{fmt(round(v['Asp']), 3)})/"
                 f"({fmt(v['fc'])}×{v['b']:g}×{v['h0']:g}) = {xi_v} "
                 + ("≤ ξb ✓" if r["xi_ok"] else f"> ξb = {v['xi_b']} ✘ 超筋"))
        L.append("  满足不发生超筋的要求。" if r["xi_ok"]
                 else f"  ξ > ξb（超筋），按复核步骤（1）取 x = ξb·h0 代入式(3-22)计算。")
        if r["xi_ok"]:
            sign = ">" if r["x"] > 2 * v["asp_"] else "="
            L.append(f"  x = ξ·h0 = {xi_v}×{v['h0']:g} = {r['x']} mm {sign} "
                     f"2a's = 2×{v['asp_']:g} = {2 * v['asp_']:g} mm")
            L.append("  满足 x≥2a's 适用条件。" if r["two_asp_ok"]
                     else "  不满足 x≥2a's 适用条件，按式(3-28)计算。")
        if r["branch"] == "3-22":
            L.append(f"  Mu = fc·b·x(h0−x/2) + fy·A's(h0−a's) = "
                     f"{fmt(v['fc'])}×{v['b']:g}×{r['x']}×({v['h0']:g}−{r['x']}/2) + "
                     f"{fmt(v['fy'])}×{fmt(round(v['Asp']), 3)}×"
                     f"({v['h0']:g}−{v['asp_']:g}) = {mu_k} kN·m")
        else:
            L.append(f"  Mu = fy·As(h0−a's) = {fmt(v['fy'])}×"
                     f"{fmt(round(v['As']), 3)}×({v['h0']:g}−{v['asp_']:g}) = "
                     f"{mu_k} kN·m")
        L.append(f"  M′ = Mu/γd = {mu_k}/{v['gamma_d']:.2f} = {mal_k} kN·m")
    else:
        a_v = f"{r['alpha_s']:.3f}"
        mu_k, mal_k = fmt(r["Mu"] / 1e6, 3), fmt(r["M_allowed"] / 1e6, 3)
        L.append(f"  ξ = fy·As/(fc·b·h0) = {fmt(v['fy'])}×{fmt(round(v['As']), 3)}/"
                 f"({fmt(v['fc'])}×{v['b']:g}×{v['h0']:g}) = {xi_v} "
                 + ("≤ ξb ✓" if r["xi_ok"] else f"> ξb = {v['xi_b']} ✘ 超筋"))
        L.append("  满足不发生超筋的要求。" if r["xi_ok"]
                 else "  不满足不发生超筋的要求（超筋）。")
        L.append(f"  αs = ξ(1-0.5ξ) = {xi_v}×(1-0.5×{xi_v}) = {a_v}")
        L.append(f"  Mu = αs·fc·b·h0² = {a_v}×{fmt(v['fc'])}×"
                 f"{v['b']:g}×{v['h0']:g}² = {mu_k} kN·m")
        L.append(f"  M′ = Mu/γd = {mu_k}/{v['gamma_d']:.2f} = {mal_k} kN·m")
    L.append(f"  ρ = As/(b·h0) = {pct(r['rho'])} "
             + (f"≥ ρmin = {pct(v['rho_min'])} ✓" if r["rho_ok"]
                else f"< ρmin = {pct(v['rho_min'])} ✘ 少筋"))
    L.append("  满足纵向受拉钢筋最小配筋率要求。" if r["rho_ok"]
             else "  不满足纵向受拉钢筋最小配筋率要求。")
    if v["M"] is not None:
        L.append(f"  比较：M′ = {mal_k} kN·m "
                 + ("≥" if r["M_allowed"] >= v["M"] else "<")
                 + f" M = {_f2(v['M'] / 1e6)} kN·m")
        if doubly:
            L.append("  正截面受弯承载力满足当前荷载的要求。" if r["M_allowed"] >= v["M"]
                     else "  正截面受弯承载力不能满足当前荷载的要求，不安全。")
        else:
            L.append("  正截面受弯承载力满足要求。" if r["M_allowed"] >= v["M"]
                     else "  正截面受弯承载力不能满足要求，不安全。")
        hh = res.get("h_hint")
        if hh:
            L.append(f"  反解（{hh['why']}）：需 h0 ≥ {fmt(hh['h0_min'], 3)} mm，"
                     f"取 h ≥ {hh['h']:g} mm（按 {hh['mod']}mm 模数）")
    L.append("")
    if v["M"] is None:
        L.append("结论：未给弯矩，仅计算 Mu。" if r["xi_ok"] and r["rho_ok"]
                 else "结论：截面超筋或少筋，不可行。")
    elif r["safe"]:
        L.append(f"结论：承载力满足（M′ = {mal_k} ≥ "
                 f"M = {_f2(v['M'] / 1e6)} kN·m）。")
    else:
        why = []
        if not r["xi_ok"]:
            why.append("超筋")
        if not r["rho_ok"]:
            why.append("少筋")
        if r["M_allowed"] < v["M"]:
            why.append("受弯承载力不足")
        L.append("结论：不安全（" + "、".join(why) + "）。")
    return "\n".join(L)
