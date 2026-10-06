"""水工混凝土单筋矩形截面受弯承载力计算 —— 交互界面（NB/T 11011-2022）。

运行：python main.py             （浏览器模式，开发调试）
      python main.py --native    （弹出桌面窗口）
数据源：kernel/data/spec_NB_T_11011-2022.json（教材附录B/C/D 及规范正文表，
均带 source 溯源字段；例3-1~3-4 可一键载入与教材对照）。
"""

import json
import logging
import math
import os
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

from nicegui import context as ng_context, ui

import problems_io
from kernel import drawing, pipeline, section, spec_data
from kernel.rebar import SLAB_SPACINGS
from kernel.textmath import HTML_KW, fmt

GAMMA_D = spec_data.gamma_d()          # 钢筋混凝土结构结构系数 γd

CONC_GRADES = spec_data.concrete_grades()
STEELS = spec_data.steel_types()
BAR_DIAS = spec_data.bar_diameters()
ENV_CLASSES = spec_data.environment_classes()

APP_BUILD = "2026-10-06"               # 发版时更新（exe 分发后用于确认同学手里是哪版）


def _num(w, default=0.0):
    """从 number 控件安全取值，空值按 default。"""
    v = w.value
    return default if v is None else v


# ---------------- 数学排版（下标/分式/根号，离线纯 HTML 实现） ----------------

def card_title(text, icon=None):
    """输入卡片的分区标题（可带语义图标）。"""
    with ui.row().classes("items-center gap-1 mb-1"):
        if icon:
            ui.icon(icon).classes("text-primary text-lg")
        ui.label(text).classes("text-sm font-bold text-primary")


def field_label(html):
    """输入控件上方的 HTML 小标签（支持下标）。"""
    ui.html(html, **HTML_KW).classes("text-xs text-gray-700").style("line-height:1.25")


def _plain_label(html):
    """HTML 标签转纯文本（供 aria-label 与自动化定位）。"""
    import re
    return re.sub(r"<[^>]+>", "", html).strip()


def num_f(html, suffix=None, **kw):
    """带 HTML 标签的数字输入（标签在上方；单位用框内后缀显示）。

    validation 透传 NiceGUI ValidationElement（红框 + 框下错误消息，值变化自动重校验）。
    空栏位显示"如 xx"示例占位（取该字段的结构默认值）——只教量级，输入即消失。
    """
    with ui.column().classes("gap-0"):
        field_label(html)
        props = "outlined"
        if suffix:
            props += f' suffix="{suffix}"'
        _v = kw.get("value")
        if isinstance(_v, (int, float)):
            props += f' placeholder="如 {_v:g}"'
        w = ui.number(**kw).props(props)
        return w.props(f'aria-label="{_plain_label(html)}"')


def _h0_design():
    """设计页按当前输入估算 h0（行内校验用，与 pipeline 同口径）。"""
    try:
        h = float(D["h"].value or 0)
        if h <= 0:
            return None
        c_min = spec_data.cover_min(D["env"].value, D["member"].value)
        c = math.ceil(1.4 * c_min) if D["y100"].value else c_min
        stirrup = float(D["stirrup"].value or 10)
        cs = (c + stirrup) if D["member"].value == "梁" else c
        layers = int(D["layers"].value or 1)
        dia = float(D["dia_est"].value or 20)
        _as, h0 = section.effective_depth(h, cs, bar_dia=dia, layers=layers)
        return h0
    except Exception:
        logging.getLogger(__name__).exception("h0 估算失败（行内校验暂停，不影响计算）")
        return None


def _h0_verify():
    """复核页 h0 = h − as（用户直接输入 as）。"""
    try:
        h, as_ = float(V["h"].value or 0), float(V["as"].value or 0)
        return (h - as_) if h > 0 and as_ > 0 else None
    except Exception:
        return None


def _pos_rule(msg="应大于 0"):
    def rule(v):
        if v is None:
            return None
        return None if v > 0 else msg
    return rule


def _asp_rule(h0_fn):
    """a′s 行内校验：应小于 h0（跨字段，h0 按当前输入估算）。"""
    def rule(v):
        if v is None:
            return None
        h0 = h0_fn()
        if h0 is None or h0 <= 0:
            return None                       # h0 无效时不叠加报错（此时 as 的错误已足够）
        return None if v < h0 else f"a′s 应小于 h0（当前约 {h0:g}mm）"
    return rule


def _as_lt_h_rule():
    def rule(v):
        if v is None:
            return None
        h = float(V["h"].value or 0)
        if h <= 0:
            return None
        return None if v < h else "as 应小于 h"
    return rule


def sel_f(html, options, cls="w-44", **kw):
    """带 HTML 标签的下拉选择。"""
    with ui.column().classes("gap-0"):
        field_label(html)
        w = ui.select(options, **kw).props("outlined").classes(cls)
        return w.props(f'aria-label="{_plain_label(html)}"')


CARD = "w-full rounded-xl border border-gray-200 shadow-sm"


def _dual_columns():
    """宽屏双栏容器：左输入列（sticky、打印隐藏），右结果列；窄屏回落单栏。

    样式在 .dual-row/.dual-side/.dual-main 自定义类里（媒体查询写死，
    不依赖 NiceGUI 预编译 Tailwind 的响应式变体）。卡片先在面板层创建，
    最后 .move 归位（免整段重缩进）。
    """
    row = ui.row().classes("dual-row")
    side = ui.column().classes("dual-side print-hide")
    main = ui.column().classes("dual-main")
    side.move(row)
    main.move(row)
    return row, side, main


def set_field_visible(w, visible):
    """显示/隐藏整个字段（含上方 HTML 标签）。"""
    w.parent_slot.parent.set_visibility(visible)


# ---------------------------------------------------------------- 弯矩链条

def _fill_gk(R):
    """按 b·h·γc 自动填入自重标准值（教材“荷载标准值计算”一步）并触发重算。"""
    gk = _num(R["b"], 0) * _num(R["h"], 0) / 1e6 * spec_data.conc_density()
    if gk <= 0:
        ui.notify("请先填写截面尺寸 b、h", type="warning", position="bottom-right",
                  timeout=2000)
        return
    R["gk"].value = round(gk, 2)
    R.get("_load_calc", lambda *_: None)(None)


def make_load_block(R, on_calc):
    """弯矩来源输入字段（设计/复核两页共用），在当前容器内创建。

    三种弯矩来源（Msrc 三态）：
      load    由荷载算 M：g<sub>k</sub>/q<sub>k</sub>/G<sub>k</sub>/Q<sub>k</sub>
              + 分项系数 + l₀ → 式(2-35)
      moments 由标准值弯矩算 M：M = γ₀·ψ(M_G + M_Q)（教材例3-5「2.内力计算」写法）
      direct  直接输入 M（题给设计值，已含 γ₀·ψ）
    level/situation 两模式共用（只建这一份控件）。
    """
    R["_load_calc"] = on_calc
    R["load_fields"] = ui.column().classes("w-full gap-0")      # 仅"由荷载算 M"
    with R["load_fields"]:
        with ui.row().classes("w-full items-end gap-4"):
            R["gk"] = num_f("均布恒载 g<sub>k</sub>", suffix="kN/m", value=2.0, min=0,
                            step=0.1, on_change=on_calc)
            R["gk_auto"] = ui.button("按自重填", on_click=lambda: _fill_gk(R)).props(
                "outline dense no-caps rounded")
            R["gk_auto"].tooltip("自重标准值 gk = b·h·γc（γc = 25.0 kN/m³，教材p79）"
                                 "——按当前截面自动填入并重算")
            R["qk"] = num_f("均布活载 q<sub>k</sub>", suffix="kN/m", value=1.2, min=0,
                            step=0.1, on_change=on_calc)
            R["Gk"] = num_f("跨中集中恒载 G<sub>k</sub>", suffix="kN", value=5.25, min=0,
                            step=0.05, on_change=on_calc)
            R["Qk"] = num_f("跨中集中活载 Q<sub>k</sub>", suffix="kN", value=40.0, min=0,
                            step=0.1, on_change=on_calc)
        with ui.row().classes("w-full items-end gap-4"):
            R["q_kind"] = sel_f("q<sub>k</sub> 的可变荷载类别（γ<sub>Q</sub> 取值）",
                                {"general": "一般可变（1.30）",
                                 "controllable": "可控制可变（1.20）"},
                                value="general", on_change=on_calc, cls="w-48")
            R["Q_kind"] = sel_f("Q<sub>k</sub> 的可变荷载类别（γ<sub>Q</sub> 取值）",
                                {"general": "一般可变（1.30）",
                                 "controllable": "可控制可变（1.20）"},
                                value="controllable", on_change=on_calc, cls="w-48")
    R["mom_fields"] = ui.column().classes("w-full gap-0")       # 仅"由标准值弯矩算 M"
    with R["mom_fields"]:
        with ui.row().classes("w-full items-end gap-4"):
            R["MG"] = num_f("恒载弯矩 M<sub>G</sub>（标准值）", suffix="kN·m", value=100.0,
                            min=0, step=0.5, on_change=on_calc)
            R["MQ"] = num_f("活载弯矩 M<sub>Q</sub>（标准值）", suffix="kN·m", value=135.0,
                            min=0, step=0.5, on_change=on_calc)
    R["coef_fields"] = ui.row().classes("w-full items-end gap-4")   # 两模式共用
    with R["coef_fields"]:
        R["level"] = sel_f("结构安全级别（γ<sub>0</sub> 取值）",
                           {"I": "I 级（1.1）", "II": "II 级（1.0）", "III": "III 级（0.9）"},
                           value="III", on_change=on_calc, cls="w-40")
        R["situation"] = sel_f("设计状况（ψ 取值）",
                               {"持久": "持久（1.0）", "短暂": "短暂（0.95）", "偶然": "偶然（0.85）"},
                               value="持久", on_change=on_calc, cls="w-40")
    R["l0_fields"] = ui.row().classes("w-full items-center gap-4")  # 仅"由荷载算 M"
    with R["l0_fields"]:
        R["l0src"] = ui.toggle({"calc": "由净跨计算", "direct": "直接输入 l₀"},
                               value="calc", on_change=on_calc).props("no-caps rounded")
        R["ln"] = num_f("净跨 l<sub>n</sub>", suffix="m", value=3.6, min=0,
                        step=0.05, on_change=on_calc)
        R["a"] = num_f("支承长度 a", suffix="m", value=0.40, min=0,
                       step=0.05, on_change=on_calc)
        R["l0"] = num_f("计算跨度 l<sub>0</sub>", suffix="m", value=3.78, min=0,
                        step=0.05, on_change=on_calc)
    return R


def sync_load_block(R, mode="load"):
    """按弯矩来源切块显示：load=荷载块+l₀；moments=M_G/M_Q；direct=都不显示。"""
    R["load_fields"].set_visibility(mode == "load")
    R["l0_fields"].set_visibility(mode == "load")
    R["mom_fields"].set_visibility(mode == "moments")
    R["coef_fields"].set_visibility(mode in ("load", "moments"))
    calc_mode = R["l0src"].value == "calc"
    set_field_visible(R["ln"], calc_mode)
    set_field_visible(R["a"], calc_mode)
    set_field_visible(R["l0"], not calc_mode)


# ---------------------------------------------------------------- 页面骨架

# ------- 按客户端隔离的状态（每个浏览器标签页独立，根治多开页串状态） -------
_CLIENTS = {}


def _state():
    try:
        cid = ng_context.client.id
    except Exception:
        cid = "__main__"
    st = _CLIENTS.get(cid)
    if st is None:
        st = {"D": {}, "V": {}, "P": {}, "TABS": {}, "cur": 0, "as": None}
        _CLIENTS[cid] = st
        try:                       # 标签页关闭/刷新后清理，防长期运行内存泄漏
            ng_context.client.on_disconnect(
                lambda _cid=cid: _CLIENTS.pop(_cid, None))
        except Exception:
            pass
    return st


class _CtxDict:
    """解析到“当前客户端”的字典代理：D/V/P/TABS 全部按标签页独立。"""

    def __init__(self, key):
        self._key = key

    def __getitem__(self, k):
        return _state()[self._key][k]

    def __setitem__(self, k, v):
        _state()[self._key][k] = v

    def get(self, k, default=None):
        return _state()[self._key].get(k, default)

    def items(self):
        return list(_state()[self._key].items())

    def __contains__(self, k):
        return k in _state()[self._key]


D = _CtxDict("D")        # 设计页控件（按客户端）
V = _CtxDict("V")        # 复核页控件（按客户端）
TABS = _CtxDict("TABS")  # 页签引用（跨页跳转用）


# ---------------------------------------------------------------- 配筋图

def pick_bar_row(e):
    """点击选筋表任意单元格：只记行 id（内容始终取自当前计算的行集）。

    reveal=True：先把配筋图滚进视野，到位后再播"画出"动画（否则动画在屏幕外就播完了）。
    """
    D["picked_id"] = e.args.get("id") if isinstance(e.args, dict) else None
    draw_design_fig(reveal=True)
    paint_recheck()
    save_problems()


def _fig_sig(ctx, layers, comp):
    """配筋图结构签名：布筋/受压筋/截面变化才播画出动画（改 M 不重播）。"""
    return (ctx.get("member"), ctx.get("b"), ctx.get("h"), ctx.get("cs"),
            tuple(layers), comp)


def draw_design_fig(reveal=False):
    """设计页配筋图。reveal=True（点选筋行）：先滚到图，到位后再播画出动画。"""
    ctx = D.get("fig_ctx")
    if not ctx:
        D["fig_cap"].set_content("")
        D["fig"].set_content("")
        return
    opts = ctx.get("opts") or []
    picked = None
    if opts:
        picked = next((r for r in opts if r["id"] == D.get("picked_id")), opts[0])
        D["picked_id"] = picked["id"]
        D["picked_row"] = picked
        # 行数据打标 → rows 同步驱动单选圈/高亮（通道可靠）
        for _r in opts:
            _r["pick"] = _r["id"] == picked["id"]
        D["bars"].rows = opts
    else:
        D["picked_id"] = None
    if ctx["member"] == "梁":
        if picked:
            dia = int(picked["dia"][1:])
            n = int(picked["cnt"].replace("根", ""))
            if "双层" in picked.get("fit", ""):
                # 双层方案行：按两层绘制（单层画会溢出截面——严重绘图错误）
                layers = drawing.split_layers(dia, n, ctx["b"], ctx["cs"])
                label = f"{n}Φ{dia}（双层）"
                cap = f"{picked['dia']}（{picked['cnt']}，双层）"
            else:
                layers, label = [(dia, n)], f"{n}Φ{dia}"
                cap = f"{picked['dia']}（{picked['cnt']}）"
        else:  # 单层排不下：按 As 推总根数均分两排
            dia = int(ctx["dia_est"])
            n = max(2, math.ceil(ctx["As"] / spec_data.bar_area(dia)))
            layers = drawing.split_layers(dia, n, ctx["b"], ctx["cs"])
            label = f"{n}Φ{dia}" + ("（双层示意）" if len(layers) > 1 else "")
            cap = label
        comp = ctx.get("comp")
        if comp:
            cap += f"　+　受压筋 {comp[1]}Φ{comp[0]}"
        anim = _fig_sig(ctx, layers, comp) != D.get("_fig_sig")
        D["_fig_sig"] = _fig_sig(ctx, layers, comp)
        svg = drawing.beam_svg(ctx["b"], ctx["h"], ctx["cs"], layers, label=label,
                               stirrup_c=ctx.get("c"), comp=comp,
                               comp_as=ctx.get("comp_as") if comp else None,
                               animate=anim)
    else:
        if picked:
            d, sp = picked["spec"][1:].split("@")
            anim = _fig_sig(ctx, [(int(d), 0)], (int(d), int(sp))) != D.get("_fig_sig")
            D["_fig_sig"] = _fig_sig(ctx, [(int(d), 0)], (int(d), int(sp)))
            svg = drawing.slab_svg(ctx["h"], ctx["as"], int(d), int(sp),
                                   label=picked["spec"],
                                   l0_mm=(ctx["l0"] * 1000 if ctx.get("l0") else None),
                                   b_mm=ctx["b"], animate=anim)
            cap = picked["spec"]
        else:
            svg = drawing.slab_svg(ctx["h"], ctx["as"], 12, 150, label="—",
                                   b_mm=ctx["b"])
            cap = "—"
    D["fig_cap"].set_content(
        f'<span style="color:#155e94;">当前：</span>{cap}'
        '<span style="color:#90a4ae;font-size:11px;font-weight:400;">'
        '　点击左表行或勾选圈切换</span>')
    D["fig"].set_content(f'<div class="nz-fig" style="text-align:center">{svg}</div>')
    fid = D["fig"].html_id
    ui.run_javascript(f"nzFigShow('{fid}')" if reveal else f"nzFigPlay('{fid}', 0)")


def draw_verify_fig():
    """复核页配筋图：按用户输入的钢筋绘制。"""
    member = V["member"].value
    mode = V["Asrc"].value
    b, h, as_ = _num(V["b"]), _num(V["h"]), _num(V["as"])
    As = V["As_cache"] if mode == "direct" else _num(V["As"])
    if mode == "count":
        dia, n = V["dia_c"].value, max(1, int(_num(V["n"], 1)))
    elif mode == "spacing":
        dia = V["dia_s"].value
        n = max(1, math.ceil(_num(V["As"]) / spec_data.bar_area(dia))) if member == "梁" \
            else None
    else:
        dia, n = 20, (max(1, math.ceil((As or 0) / spec_data.bar_area(20)))
                      if As else None)
    if member == "梁":
        if n is None:
            return
        cs = max(as_ - dia / 2, 12)
        layers = drawing.split_layers(dia, n, b, cs)
        if len(layers) > 1:
            # 双层时形心在 cs+35（式3-20b）→ 反解 cs 重排（否则图上 as 与输入不符）
            cs = max(as_ - 35, 12)
            layers = drawing.split_layers(dia, n, b, cs)
        label = f"{n}Φ{dia}" + ("（双层）" if len(layers) > 1 else "")
        comp = None
        if V["dbl"].value == "count" and int(_num(V["n_p"], 0) or 0) > 0:
            comp = (V["dia_p"].value, int(_num(V["n_p"], 0)))
        anim = _fig_sig({"member": member, "b": b, "h": h, "cs": cs},
                        layers, comp) != V.get("_fig_sig")
        V["_fig_sig"] = _fig_sig({"member": member, "b": b, "h": h, "cs": cs},
                                 layers, comp)
        svg = drawing.beam_svg(b, h, cs, layers, label=label, comp=comp,
                               comp_as=_num(V["asp"]) if comp else None,
                               animate=anim)
    else:
        if mode == "spacing":
            sig = _fig_sig({"member": member, "b": b, "h": h, "cs": 0},
                           [(V["dia_s"].value, 0)], (V["dia_s"].value, V["spacing"].value))
            anim = sig != V.get("_fig_sig")
            V["_fig_sig"] = sig
            svg = drawing.slab_svg(h, as_, V["dia_s"].value, V["spacing"].value,
                                   label=f"Φ{V['dia_s'].value}@{V['spacing'].value}",
                                   l0_mm=(V.get("l0_cache") or 0) * 1000 or None,
                                   b_mm=b, animate=anim)
        else:
            n = n or 5
            n_draw = min(n, 6)
            sp = round((b - 180) / (n_draw - 1)) if n_draw > 1 else 100
            sig = _fig_sig({"member": member, "b": b, "h": h, "cs": 0},
                           [(dia, n)], (dia, sp))
            anim = sig != V.get("_fig_sig")
            V["_fig_sig"] = sig
            svg = drawing.slab_svg(h, as_, dia, sp, b_mm=b,
                                   label=f"{n}Φ{dia}" + ("（示意）" if n > n_draw else ""),
                                   animate=anim)
    V["fig"].set_content(f'<div class="nz-fig" style="text-align:center">{svg}</div>')
    ui.run_javascript(f"nzFigPlay('{V['fig'].html_id}', 0)")


def _env_select(refs, on_calc):
    refs["env"] = sel_f("环境类别", {k: f"{k}类" for k in ENV_CLASSES},
                        value="二", on_change=on_calc, cls="w-40")
    refs["env"].tooltip("\n".join(f"{k}类：{v}" for k, v in ENV_CLASSES.items()))


def _material_selects(refs, on_calc):
    refs["conc"] = sel_f("混凝土强度等级（f<sub>c</sub>）", {g: g for g in CONC_GRADES},
                         value="C25", on_change=on_calc, cls="w-44")
    refs["steel"] = sel_f("钢筋种类（f<sub>y</sub>）", {s: s for s in STEELS},
                          value="HRB400", on_change=on_calc, cls="w-40")


def clear_verdict(w):
    """清空判定横幅并复位样式——只清内容会残留底色，页面上留下空心胶囊。

    注意 NiceGUI 3.x 的 `el.style("...")` 是**追加**语义（Style.__call__(add=...)），
    传空串是静默 no-op；要清空必须用 `style(replace="")`。
    """
    w.set_content("")
    w.style(replace="")


def verdict_banner(w, ok, text, animate=False):
    if not (text or "").strip():
        clear_verdict(w)
        return
    bg = "#e8f5e9" if ok else "#fdecea"
    fg = "#1b5e20" if ok else "#b71c1c"
    w.set_content(text)
    w.style(f"white-space:pre-wrap;padding:10px 14px;border-radius:8px;"
            f"background:{bg};color:{fg};")
    if animate:
        _anim_play(w, "anim-banner", 500)


def _anim_play(el, cls="anim-chain", ms=900):
    """给元素播一次 CSS 动画（客户端一次性：加类 → 动画 → 自动摘除）。

    为什么不用"服务端判断哪次重绘是最后一次"：载入例题/换题时是程序化批量赋值，
    会连锁触发多次重绘，标志位会被中间那次消费掉。改为事件驱动 + 客户端一次性播放，
    每次播放都作用在当次已渲染好的 DOM 上。
    注：NiceGUI 3.x 的元素 DOM id 属性是 html_id（不是 id）。
    """
    eid = getattr(el, "html_id", None)
    if not eid:
        return
    ui.run_javascript(f"""
      const el = document.getElementById('{eid}');
      if (!el) return;
      el.classList.remove('{cls}');
      void el.offsetWidth;
      el.classList.add('{cls}');
      setTimeout(() => el.classList.remove('{cls}'), {ms});""")


_TOC_JS = """
(window.nzTOC = window.nzTOC || function(resId, tocId) {
  const res = document.getElementById(resId), toc = document.getElementById(tocId);
  if (!res || !toc) return;
  // 小节标题：pipeline _head() 产出的 13px 加粗 #155e94 div，文本形如 "1. 资料"
  const heads = Array.from(res.querySelectorAll('div')).filter(d => {
    if (d.children.length > 1) return false;
    const cs = getComputedStyle(d);
    return cs.fontWeight >= 600 && /^\\d\\. /.test((d.textContent || '').trim());
  });
  heads.forEach((h, i) => { h.classList.add('nz-sec'); h.dataset.sec = 's' + i; });
  // 每节的"整段"（标题行 + 到下一节标题前的所有兄弟行）——用于点击后的落点闪烁
  const segments = heads.map((h, i) => {
    const next = heads[i + 1];
    let start = h;                       // 起点：只含本标题的那个"行容器"
    while (start.parentElement && start.parentElement !== res &&
           !heads.some(x => x !== h && start.parentElement.contains(x))) start = start.parentElement;
    const els = [];
    let cur = start;
    while (cur && cur !== res && cur.parentElement) {
      if (next && (cur === next || cur.contains(next))) break;   // 到了下一节
      els.push(cur);
      cur = cur.nextElementSibling;
    }
    return els;
  });
  const stackPx = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nz-stack')) || 180;
  const labels = heads.map(h => (h.textContent || '').trim()
    .replace(/^([\\d])\\. /, '$1 ').replace(/（[^）]*）$/, '')
    .replace(/\\s*[—·].*$/, ''));
  const cur = heads.map((_, i) => 's' + i).filter(k => toc.dataset.on === k);
  toc.innerHTML = labels.map((t, i) =>
    `<span class="toc-chip" data-t="s${i}">${t}</span>`).join('');
  toc.querySelectorAll('.toc-chip').forEach(chip => {
    chip.onclick = () => {
      const off = document.body.classList.contains('motion-off');
      const i = parseInt(chip.dataset.t.slice(1), 10);
      const target = heads[i], seg = segments[i] || [];
      if (!target) return;
      // 目标整段闪一下（连点可重复触发；纯 class，不动布局——否则会打断平滑滚动）
      seg.forEach(el => {
        el.classList.remove('nz-hit');
        void el.offsetWidth;
        el.classList.add('nz-hit');
        clearTimeout(el._nzHitT);
        el._nzHitT = setTimeout(() => el.classList.remove('nz-hit'), 1500);
      });
      // 落点显式计算：吸顶层高 + 吸顶的 TOC 行高 + 8px 间隙。
      // 偏移从活 DOM 现算（页头 + 题号条/页签 + 小节导航）；注意必须把 TOC 行算进去，
      // 否则目标顶部会被吸顶的 TOC 条压住看不见。sticky 布局下 scrollIntoView 的
      // scroll-margin 落点还会固定偏一个页头高，所以不用它。
      const hdr = document.querySelector('header');
      const bar = document.querySelector('.nz-sticky-top');
      const tocRow = document.querySelector('.toc-row');
      const hdrH = hdr ? Math.round(hdr.getBoundingClientRect().height) : 76;
      const barH = bar ? Math.round(bar.getBoundingClientRect().height) : 0;
      const tocH = (tocRow && tocRow.offsetParent !== null && getComputedStyle(tocRow).position === 'sticky')
        ? Math.round(tocRow.getBoundingClientRect().height) + 4 : 0;
      const offY = hdrH + barH + tocH + 8;
      const y = target.getBoundingClientRect().top + window.scrollY - offY;
      window.scrollTo({ top: Math.max(0, y), behavior: off ? 'auto' : 'smooth' });
      // 点击即刻点亮所点芯片；跳转期间暂停 scroll-spy 标记
      //（spy 按"当时可见节"标，程序化滚动途中会先标到邻节——用户会看到高亮闪一下别的小节）
      mark(chip.dataset.t);
      window._nzJumping = true;
      clearTimeout(window._nzJumpT);
      window._nzJumpT = setTimeout(() => { window._nzJumping = false; mark(chip.dataset.t); }, 900);
    };
  });
  // scroll-spy：选中小节标题中最靠上可见者
  if (window.nzSpy) window.nzSpy.disconnect();
  if (!heads.length) { toc.style.display = 'none'; return; }
  toc.style.display = 'flex';
  const chips = Object.fromEntries(Array.from(toc.querySelectorAll('.toc-chip'))
    .map(c => [c.dataset.t, c]));
  const mark = (key) => Object.entries(chips).forEach(([k, c]) =>
    c.classList.toggle('on', k === key));
  // scroll 事件 + rAF 节流驱动，按活 DOM 现算：优先取观察带内最靠上的标题。
  // 不用 IntersectionObserver——页顶/页底两端都可能没有任何标题落在带内，瞬跳（End 键/
  // 拖滚动条）两端"零状态变化"IO 根本不回调，芯片会停在旧节（这正是要修的毛病）。
  // 带内没有时回退"带上方最近的小节"（标题纵向顺序排列，取最后一个越界者）；
  // 连越界者都没有（整块结果还在下方）就不动，保持现状。
  const markCurrent = (fallback) => {
    const bandTop = stackPx + 44, bandBot = window.innerHeight * 0.45;
    let inBand = null, above = null;
    heads.forEach(h => {
      const top = h.getBoundingClientRect().top;
      if (top >= bandTop && top < bandBot) { if (!inBand) inBand = h; }
      else if (top < bandTop) above = h;
    });
    // 带内外全空有两种空档：页顶空档（整块结果还在带下方）标第 1 节；
    // 页底空档（末节标题也爬不进带，如末节很短）标最后一节——都在看哪节一目了然。
    const atBottom = window.scrollY + window.innerHeight >=
      document.documentElement.scrollHeight - 4;
    const cur = inBand || above || (atBottom ? heads[heads.length - 1] : fallback || heads[0]);
    if (cur && chips[cur.dataset.sec]) mark(cur.dataset.sec);
  };
  markCurrent(heads[0]);                       // 即时点亮（重建后不滚动也有当前小节）
  let _raf = 0;
  const onScroll = () => {
    if (_raf) return;
    _raf = requestAnimationFrame(() => {
      _raf = 0;
      if (!window._nzJumping) markCurrent(null);  // 程序化跳转途中不标记（否则会闪到邻节）
    });
  };
  addEventListener('scroll', onScroll, { passive: true });
  addEventListener('resize', onScroll, { passive: true });
  window.nzSpy = { disconnect() {
    removeEventListener('scroll', onScroll);
    removeEventListener('resize', onScroll);
    if (_raf) cancelAnimationFrame(_raf);
  } };
  heads.forEach(h => window.nzSpy.observe(h));
});
"""


_TOPBAR_JS = """
(window.nzTopStack = window.nzTopStack || function() {
  const measure = () => {
    const hdr = document.querySelector('header');
    const hh = hdr ? Math.round(hdr.getBoundingClientRect().height) : 76;
    const el = document.querySelector('.nz-sticky-top');
    const h = el ? Math.round(el.getBoundingClientRect().height) : 0;
    document.documentElement.style.setProperty('--nz-header', hh + 'px');
    document.documentElement.style.setProperty('--nz-stack', (hh + h) + 'px');
  };
  measure();
  requestAnimationFrame(measure);   // DOM 补丁后再测一次（避免量到重建中的瞬时高度 0）
  setTimeout(measure, 300);
});
if (!window.nzStackBound) { window.nzStackBound = true; addEventListener('resize', window.nzTopStack); }
window.nzTopStack();
// 聚焦中的数字框遇滚轮先失焦——否则页面滚动会顺手改掉输入值（误触）
if (!window.nzWheelBound) {
  window.nzWheelBound = true;
  document.addEventListener('wheel', (e) => {
    const t = e.target;
    if (t && t.tagName === 'INPUT' && t.type === 'number' && document.activeElement === t) t.blur();
  }, { passive: true });
}
// 查表跳转：滚到数据页对应表格并闪一下（计算过程里的 .nz-ref 表号引用）
(window.nzRefGo = window.nzRefGo || function(id, row) {
  // 点引用 → 服务端才切到"数据"页签，面板渲染有延迟：轮询等目标出现（最多 2s）
  let tries = 0;
  const run = () => {
  const el = document.getElementById(id);
  if (!el) { if (++tries < 20) setTimeout(run, 100); return; }
  const card = el.closest('.q-card') || el;
  let target = card, flash = [card];
  if (row) {                                   // 行级定位：表内找含该文本的行
    const tr = [...card.querySelectorAll('tbody tr')].find(t => (t.innerText || '').includes(row));
    if (tr) {
      target = tr;
      const tds = [...tr.querySelectorAll('td')];
      flash = tds.length ? tds : [tr];
    }
  }
  const hdr = document.querySelector('header');
  const bar = document.querySelector('.nz-sticky-top');
  const off = (hdr ? Math.round(hdr.getBoundingClientRect().height) : 76)
            + (bar ? Math.round(bar.getBoundingClientRect().height) : 0) + 28;
  const y = target.getBoundingClientRect().top + window.scrollY - off;
  window.scrollTo({ top: Math.max(0, y), behavior: 'smooth' });
  // 到位后再闪（否则"闪完了才滚到"）；scrollend 与兜底共用单次闸，防重播
  let armed = false;
  const flashNow = () => {
    if (armed) return;
    armed = true;
    flash.forEach(e => {
      e.classList.remove('nz-hit');
      void e.offsetWidth;
      e.classList.add('nz-hit');
      clearTimeout(e._nzRefT);
      e._nzRefT = setTimeout(() => e.classList.remove('nz-hit'), 1800);
    });
  };
  if ('onscrollend' in window) addEventListener('scrollend', flashNow, { once: true });
  setTimeout(flashNow, 700);
  };
  run();
});
// 当前激活页签（中文名）——查表跳转时随事件上报，供"切回还原"记账
(window.nzFromTab = window.nzFromTab || function() {
  const t = [...document.querySelectorAll('.q-tab')].find(x => /q-tab--active/.test(x.className));
  return (((t && t.innerText) || '').replace(/[^一-龥]/g, '')) || '';
});
// 滚到指定位置：来源面板渲染有延迟，没到位就重试
(window.nzScrollTo = window.nzScrollTo || function(y) {
  let n = 0;
  const go = () => {
    window.scrollTo({ top: y, behavior: 'auto' });
    if (Math.abs(window.scrollY - y) > 8 && ++n < 15) setTimeout(go, 100);
  };
  go();
});
// 未填栏位统计 + 跳转：都按 DOM 真值（服务端读不到行级隐藏）
(window.nzEmptyInputs = window.nzEmptyInputs || function() {
  const panel = [...document.querySelectorAll('.q-tab-panel')].find(p => p.offsetParent !== null) || document;
  return [...panel.querySelectorAll('input[type=number]')]
    .filter(i => (i.value === '' || i.value == null) && i.offsetParent !== null
                 && !i.disabled && !i.readOnly);
});
(window.nzFocusNextEmpty = window.nzFocusNextEmpty || function() {
  const empties = window.nzEmptyInputs();
  if (!empties.length) return;
  // 点按钮时焦点在按钮上（indexOf 失效），故用"上次跳到的位置"接力；用户手动点进某框则以该框为准
  const cur = empties.indexOf(document.activeElement);
  const base = cur >= 0 ? cur : (typeof window._nzJumpIdx === 'number' ? window._nzJumpIdx : -1);
  const idx = (base + 1) % empties.length;
  window._nzJumpIdx = idx;
  const next = empties[idx];
  next.scrollIntoView({ block: 'center', behavior: 'smooth' });
  next.focus({ preventScroll: true });
  if (next.select) next.select();
});
(window.nzFigPlay = window.nzFigPlay || function(rootId, delayMs) {
  const root = document.getElementById(rootId);
  const fig = root && root.querySelector('.nz-fig');
  if (!fig) return;
  setTimeout(() => {                       // v-html 内部元素不受 Vue 绑定回滚
    fig.classList.remove('nz-play');
    void fig.offsetWidth;                  // 重排一次，连点也能重播
    fig.classList.add('nz-play');
  }, Math.max(0, delayMs | 0));
});
// 点选筋行：不在视野先滚到图，到位后再布防播动画（已在视野则几乎立刻播）
// 注意只布防一次——scrollend 与兜底定时器都要过 done 闸，否则动画会重播一遍
(window.nzFigShow = window.nzFigShow || function(rootId) {
  const root = document.getElementById(rootId);
  if (!root) return;
  const r = root.getBoundingClientRect();
  const needScroll = !(r.top >= 40 && r.bottom <= window.innerHeight - 40);
  if (!needScroll) { window.nzFigPlay(rootId, 60); return; }
  root.scrollIntoView({ block: 'center', behavior: 'smooth' });
  let done = false;
  const arm = (d) => { if (done) return; done = true; window.nzFigPlay(rootId, d); };
  if ('onscrollend' in window) addEventListener('scrollend', () => arm(80), { once: true });
  setTimeout(() => arm(80), 650);
});
// 数字框回车 → 跳到同页签下一个可见可用的数字框（连续录入；最后一格则失焦收键盘）
if (!window.nzEnterBound) {
  window.nzEnterBound = true;
  document.addEventListener('keydown', (e) => {
    const t = e.target;
    if (e.key !== 'Enter' || !t || t.tagName !== 'INPUT' || t.type !== 'number') return;
    const panel = [...document.querySelectorAll('.q-tab-panel')].find(p => p.offsetParent !== null) || document;
    const inputs = [...panel.querySelectorAll('input[type=number]')]
      .filter(i => i.offsetParent !== null && !i.disabled && !i.readOnly);
    const i = inputs.indexOf(t);
    if (i < 0) return;
    e.preventDefault();
    const nxt = inputs[i + 1];
    if (nxt) {
      nxt.scrollIntoView({ block: 'center', behavior: 'smooth' });
      nxt.focus({ preventScroll: true });
      if (nxt.select) nxt.select();
    } else {
      t.blur();
    }
  });
}
// KPI 释义气泡贴视口：气泡以格子左缘定位（max-width 290px），右半区的格子
// 在窄视口会把气泡伸出屏幕外；hover 时按格子位置算一个负左偏，钉回屏内
if (!window.nzTipBound) {
  window.nzTipBound = true;
  document.addEventListener('mouseover', (e) => {
    const tip = e.target && e.target.closest ? e.target.closest('.nz-tip') : null;
    if (!tip) return;
    const r = tip.getBoundingClientRect();
    const maxW = 290, margin = 8;
    const over = r.left + maxW + margin - window.innerWidth;
    tip.style.setProperty('--nz-tip-shift', over > 0 ? `-${Math.min(over, r.left - margin)}px` : '0px');
  }, { passive: true });
}
// 窄屏实时摘要条：结果卡进入视野上带 → 暂隐（那会儿结果本来就看得见，别压住 TOC），
// 滚回输入区 → 恢复；点击摘要条平滑滚到结果卡
if (!window.nzLiveBound) {
  window.nzLiveBound = true;
  let lvRaf = 0;
  const lvUpd = () => {
    const stack = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--nz-stack')) || 180;
    for (const panel of document.querySelectorAll('.q-tab-panel')) {
      const bar = panel.querySelector(':scope > .nz-live-bar');
      const anchor = panel.querySelector('.result-anchor');
      if (!bar) continue;
      if (!anchor) { bar.classList.add('nz-hide'); continue; }
      const r = anchor.getBoundingClientRect();
      bar.classList.toggle('nz-hide', r.top <= stack + 40 && r.bottom > stack);
    }
  };
  const lvOnScroll = () => { if (!lvRaf) lvRaf = requestAnimationFrame(() => { lvRaf = 0; lvUpd(); }); };
  addEventListener('scroll', lvOnScroll, { passive: true });
  addEventListener('resize', lvOnScroll, { passive: true });
  lvUpd();
}
if (!window.nzLiveClickBound) {
  window.nzLiveClickBound = true;
  document.addEventListener('click', (e) => {
    const bar = e.target && e.target.closest && e.target.closest('.nz-live-bar');
    if (!bar || bar.classList.contains('nz-hide')) return;
    const anchor = bar.closest('.q-tab-panel') && bar.closest('.q-tab-panel').querySelector('.result-anchor');
    if (anchor) anchor.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });
}
"""


def _refresh_toc(res_el, toc_el):
    """重绘后重建小节导航（客户端扫描小节标题 + scroll-spy）。"""
    if res_el is None or toc_el is None:
        return
    ui.run_javascript(f'nzTOC("{res_el.html_id}", "{toc_el.html_id}")')


def _chain_sig(html):
    """过程块结构签名：小节标题序列 + 行数。

    纯数值编辑（改 b、改 M）不改签名 → 不播逐行动画；
    试算块出现、警告行增减等结构变化才播（避免逐键闪烁）。
    """
    heads = tuple(re.findall(r">(\d\. [^<]{1,12})", html or ""))
    return heads, (html or "").count("<div")


def _anim_then(pool, key, *fns):
    """模式/档位切换处理器：先依次执行同步与重算，再给结果块播一次逐行动画。"""
    def handler(_e=None):
        for f in fns:
            f()
        _anim_play(pool[key])
    return handler


# 页头「动效」开关：js_handler 纯客户端处理——点击零往返立即生效 + localStorage 记忆。
# 走服务端 on_click 再 run_javascript 要隔一次消息往返，慢连接下按钮手感发"涩"。
_MOTION_TOGGLE_JS = """
() => {
  const off = document.body.classList.toggle('motion-off');
  localStorage.setItem('nz_motion', off ? 'off' : 'on');
  document.querySelectorAll('.anim-toggle').forEach(
    b => b.style.opacity = off ? '.45' : '1');
}"""


def notify_error_once(msg):
    """输入错误提示：同一客户端同一条消息只弹一次，避免逐键输入时刷屏。"""
    st = _state()
    if st.get("_err") != msg:
        ui.notify(msg, type="warning", position="bottom-right", timeout=3000)
        st["_err"] = msg


def toast(msg):
    ui.notify(msg, type="positive", position="bottom-right", timeout=2600)


def scroll_to_result():
    """平滑滚动到当前可见页的“结果”卡（设计/复核两页各有锚点，取可见者）。"""
    ui.run_javascript("""
        for (const el of document.querySelectorAll('.result-anchor')) {
            if (el.offsetParent !== null) {
                el.scrollIntoView({behavior: 'smooth', block: 'start'});
                break;
            }
        }""")


def adopt_suggested_h():
    """超筋/少筋续演的一键采用：把反解的 h 写入输入框并整页重算（教材例3-3 流程）。"""
    tr = ((D.get("_res") or {}).get("suggest") or {}).get("trial")
    if not tr:
        return
    D["h"].value = tr["h"]
    sync_design()
    calc_design()
    _anim_play(D["res"])
    toast(f"已将 h 改为 {tr['h']:g}mm 并重算")
    scroll_to_result()


def adopt_suggested_h_verify():
    """复核不安全时的一键采用：把反解最小 h 写入输入框重算（与设计页 adopt 对称）。

    仅单筋不安全才有 h_hint（双筋的缺额定性好归到"加高受压筋/提等级"，不反解 h）。
    """
    hh = (V.get("_res") or {}).get("h_hint")
    if not hh or not hh.get("h"):
        return
    V["h"].value = hh["h"]
    sync_verify()
    calc_verify()
    _anim_play(V["res"])
    toast(f"已将 h 改为 {hh['h']:g}mm 并重算")
    scroll_to_result()


# ---------------------------------------------------------------- 设计页

# ---------------------------------------------------------------- 例题按钮条（选中态）

# (状态键, 按钮文字, 点击动作)——设计/复核两页各一条
_DESIGN_PRESETS = (
    ("3-1", "例3-1 启闭机梁", lambda: preset_design("3-1")),
    ("3-2", "例3-2 人行道板", lambda: preset_design("3-2")),
    ("3-3", "例3-3 泵房梁(超筋)", lambda: preset_design("3-3")),
    ("3-5", "例3-5 双筋·算A′s", lambda: preset_design("3-5")),
    ("3-6", "例3-6 双筋·已配A′s", lambda: preset_design("3-6")),
    ("3-7", "例3-7 双筋·x<2a′s 分支", lambda: preset_design("3-7")),
    ("reset", "↺ 重置为默认", lambda: reset_design()),
)
_VERIFY_PRESETS = (
    ("3-4", "例3-4 已建板复核", lambda: preset_verify()),
    ("3-8", "例3-8 双筋梁复核", lambda: preset_verify_38()),
    ("reset", "↺ 重置为默认", lambda: reset_verify()),
)


def _sync_preset_row(pool, items):
    """按 pool['_preset'] 重建例题按钮条（选中=实心主色，未选=描边）。

    状态未变不重建（否则逐键输入会反复销毁/新建按钮）；与题号条
    refresh_problem_bar 同款做法——Quasar 按钮的 outline 属性无法原地增删，
    只能重建才能真正切换实心/描边。
    """
    row = pool.get("preset_row")
    if row is None or pool.get("_preset_shown") == pool.get("_preset"):
        return
    pool["_preset_shown"] = pool.get("_preset")
    row.clear()
    with row:
        for key, label, fn in items:
            b = ui.button(label, on_click=fn)
            if key == pool.get("_preset"):
                b.props("color=primary no-caps rounded dense")
            else:
                b.props("outline no-caps rounded dense")


def _set_preset(pool, key, items):
    """更新当前页的例题选中态（None=已手动改动，不再是原例题）。"""
    pool["_preset"] = key
    _sync_preset_row(pool, items)


def build_design_tab():
    with ui.tab_panel("设计"):
        # 窄屏（<1024px 单栏）实时摘要条：输入区滚动时判定/关键数钉在吸顶层下，
        # 结果卡进入视野后由客户端 JS 暂隐（宽屏双栏下整条由 CSS 隐藏）
        D["live"] = ui.html("", **HTML_KW).classes("nz-live-bar print-hide")
        D["exrow"] = ui.row().classes("w-full items-center gap-2 mb-1 print-hide")
        with D["exrow"]:
            ui.html("《水工钢筋混凝土结构学》例题一键载入：", **HTML_KW).classes("text-sm text-gray-500")
            D["preset_row"] = ui.row().classes("gap-1")
            with D["preset_row"]:      # 初始全描边；点击例题/重置后 _sync_preset_row 重建高亮
                for _key, _label, _fn in _DESIGN_PRESETS:
                    ui.button(_label, on_click=_fn).props("outline dense no-caps rounded")
        _cols = _dual_columns()
        card_m = ui.card().classes(CARD)
        with card_m:
            card_title("③ 弯矩设计值 M 的来源", "calculate")
            with ui.row().classes("w-full items-end gap-6"):
                D["member"] = ui.toggle({"梁": "梁", "板": "板"}, value="梁",
                                        on_change=_anim_then(D, 'res', sync_design, calc_design)).props("no-caps rounded")
                D["Msrc"] = ui.toggle({"load": "由荷载算 M", "moments": "由弯矩标准值算 M",
                                       "direct": "直接输入 M"},
                                      value="load",
                                      on_change=_anim_then(D, 'res', sync_design, calc_design)).props("no-caps rounded")
            make_load_block(D, lambda e: (sync_design(), calc_design()))
            with ui.row().classes("w-full items-end gap-4") as D["M_row"]:
                D["M"] = num_f("弯矩设计值 M（含 γ<sub>0</sub>·ψ）", suffix="kN·m", value=212.60,
                               min=0, step=0.01, on_change=calc_design)
        card_s = ui.card().classes(CARD)
        with card_s:
            card_title("② 截面尺寸与受拉钢筋布置", "straighten")
            with ui.row().classes("w-full items-end gap-4"):
                D["b"] = num_f("梁宽/板计算宽 b", suffix="mm", value=200, min=1, step=10,
                               on_change=calc_design, validation=_pos_rule())
                D["h"] = num_f("截面高 h", suffix="mm", value=400, min=1, step=10,
                               on_change=calc_design, validation=_pos_rule())
                D["layers"] = ui.toggle({"1": "单层受拉筋", "2": "双层受拉筋"}, value="1",
                                        on_change=_anim_then(D, 'res', sync_design, calc_design)).props("no-caps rounded")
                D["dia_est"] = sel_f("预估受拉筋直径（单层布筋，估 a<sub>s</sub> 用）",
                                     {d: f"Φ{d}" for d in BAR_DIAS},
                                     value=20, on_change=calc_design, cls="w-44")
                D["stirrup"] = num_f("箍筋直径预估", suffix="mm", value=10, min=0, step=1,
                                     on_change=calc_design)
            # 受压钢筋（双筋设计，教材3.5.2 图3-27；双筋仅梁适用——板时整行隐藏+提示）
            with ui.row().classes("w-full items-end gap-4") as D["dbl_row"]:
                D["dbl"] = ui.toggle({"none": "单筋（无受压筋）", "unknown": "双筋·计算 A′s",
                                      "known": "双筋·已知 A′s"}, value="none",
                                     on_change=_anim_then(D, 'res', sync_design, calc_design)
                                     ).props("no-caps rounded")
                D["asp"] = num_f("受压钢筋 a′<sub>s</sub>", suffix="mm", value=55, min=1,
                                 step=1, on_change=calc_design,
                                 validation=_asp_rule(_h0_design))
                D["asp"].tooltip("受压钢筋合力点至受压边缘距离：单层布置时 a′s = cs + d′/2 "
                                 "（教材例3-5~3-7 取 cs+10 = 55mm）")
            with ui.row().classes("w-full items-end gap-4") as D["asp_row"]:
                D["Asp_src"] = ui.toggle({"count": "直径×根数", "direct": "直接输入 A′s"},
                                         value="count",
                                         on_change=_anim_then(D, 'res', sync_design, calc_design)
                                         ).props("no-caps rounded")
                D["dia_p"] = sel_f("受压筋直径", {d: f"Φ{d}" for d in BAR_DIAS},
                                   value=18, on_change=calc_design, cls="w-32")
                D["n_p"] = num_f("受压筋根数 n′", value=2, min=1, step=1,
                                 on_change=calc_design)
                D["Asp"] = num_f("受压钢筋面积 A′<sub>s</sub>", suffix="mm²", value=509,
                                 min=0, step=1, on_change=calc_design)
            D["dbl_hint"] = ui.html(
                '<span style="color:#78909c;font-size:12px;line-height:1.6;">'
                '双筋截面仅适用于梁（教材3.5.2）：板受压区不足时应加厚板或提高混凝土强度等级；'
                '连续板支座负筋属另一类问题（本工具按简支单跨正截面计算）。</span>', **HTML_KW)
        card_e = ui.card().classes(CARD)
        with card_e:
            card_title("① 材料强度与环境类别", "layers")
            with ui.row().classes("w-full items-end gap-4"):
                _material_selects(D, calc_design)
                _env_select(D, calc_design)
                D["y100"] = ui.switch("设计使用年限 100 年",
                                      value=False, on_change=calc_design).props("dense")
                D["y100"].tooltip("附录D D.1(2)：使用年限100年时，保护层厚度不应小于表D-1数值的1.4倍")
        card_r = ui.card().classes(CARD + " result-anchor")
        D["card_r"] = card_r
        with card_r:
            card_title("计算过程与结果", "insights")
            with ui.row().classes("w-full justify-end"):
                ui.button("📋 复制计算书", on_click=copy_report_design).props(
                    "outline dense no-caps rounded")
                ui.button("⬇ 下载计算书", on_click=download_report_design).props(
                    "outline dense no-caps rounded")
            D["toc"] = ui.html("", **HTML_KW).classes("toc-row print-hide")
            D["kpi"] = ui.html("", **HTML_KW)
            # 教材解题骨架：1 资料（原在③卡的信息行并入计算过程）
            D["info"] = ui.html("", **HTML_KW).style("color:#37474f")
            D["mchain"] = ui.html("", **HTML_KW).style("color:#455a64")
            ui.separator()
            D["res"] = ui.html("", **HTML_KW).style("font-size:15px")
            ui.separator()
            D["verdict"] = ui.html("", **HTML_KW).classes("text-base font-bold")
            # 超筋/少筋续演后的一键采用（文案由 _paint_design 按反解值设置）
            D["adopt"] = ui.button("", on_click=adopt_suggested_h).props(
                "outline dense no-caps rounded color=warning")
            D["adopt"].set_visibility(False)
            D["rho_wrap"] = ui.column().classes("w-full gap-1")
            with D["rho_wrap"]:
                D["rho_bar"] = ui.linear_progress(value=0, show_value=False).props("rounded")
                D["rho_scale"] = ui.html("", **HTML_KW).classes("text-xs text-gray-500")
            # 破坏形态扫描图（少筋/适筋/超筋 + 当前点，由 sweep_html 填充）
            D["sweep_wrap"] = ui.html("", **HTML_KW).classes("mt-1")
            D["bars_title"] = ui.label("").classes("font-bold mt-2")
            with ui.row().classes("w-full items-start gap-4 flex-wrap"):
                # min(380px,100%)：窄屏钳到容器宽，别把整页撑出横向滚动（表格自身可横滚）
                with ui.column().classes("flex-grow gap-1").style("min-width:min(380px,100%)"):
                    D["bars"] = ui.table(
                        columns=[], rows=[], row_key="id").props(
                        "flat bordered hide-pagination rows-per-page=0").classes("w-full")
                    # 整行可点切配筋图；选中态由行数据 pick 驱动（单选圈+高亮+左强调条）
                    _TINT = (":class=\"{'bg-blue-1': props.row.pick}\" "
                             ":style=\"props.row.pick ? 'border-left:3px solid #155e94' : ''\"")
                    _ALIGN = {"dia": "center", "cnt": "center", "area": "right",
                              "margin": "right", "fit": "center", "spec": "center"}
                    for _k in ("dia", "cnt", "area", "margin", "fit", "spec"):
                        _al = _ALIGN.get(_k, "center")
                        _tpl = ('<q-td key="' + _k + '" :props="props" '
                                'style="cursor:pointer;text-align:' + _al + '" '
                                "@click=\"$parent.$emit('pick', props.row)\" "
                                + _TINT + '>')
                        if _k in ("dia", "spec"):
                            _tpl += ('<q-icon v-if="props.row.pick" '
                                     'name="radio_button_checked" color="primary" '
                                     'size="18px" class="q-mr-xs"/>'
                                     '<q-icon v-else name="radio_button_unchecked" '
                                     'color="grey-4" size="18px" class="q-mr-xs"/>')
                        _tpl += '{{ props.value }}</q-td>'
                        D["bars"].add_slot(f"body-cell-{_k}", _tpl)
                    D["bars"].add_slot("body-cell-op", '''
                        <q-td key="op" :props="props" style="text-align:center"
                              :class="{'bg-blue-1': props.row.pick}">
                            <q-btn dense unelevated no-caps rounded color="primary"
                                   icon="fact_check" label="去复核"
                                   @click.stop="$parent.$emit('review', props.row)" />
                        </q-td>
                    ''')
                    D["bars"].on("pick", pick_bar_row)
                    D["bars"].on("review", review_from_design)
                    D["bars_hint"] = ui.html("", **HTML_KW).style("color:#e65100")
                    D["recheck"] = ui.html("", **HTML_KW).classes("mt-1")
                    D["recheck"].set_visibility(False)
                    D["err"] = ui.label("").style("color:#b71c1c;white-space:pre-wrap")
                    D["jump"] = ui.button(
                        "", on_click=lambda: ui.run_javascript("nzFocusNextEmpty()")
                        ).props("outline dense no-caps rounded")
                    D["jump"].set_visibility(False)
                with ui.card().classes("rounded-xl border border-gray-200 shadow-sm q-pa-md").style("min-width:min(340px,100%)"):
                    ui.html("截面配筋图", **HTML_KW).classes("text-sm font-bold text-gray-600")
                    D["fig_cap"] = ui.html("", **HTML_KW).classes("text-base font-bold")
                    D["fig"] = ui.html("", **HTML_KW)
        card_c = ui.card().classes(CARD)
        with card_c:
            card_title("④ 选筋与构造约束", "tune")
            D["cons_row"] = ui.row().classes("w-full items-end gap-4 mt-1 flex-wrap")
            with D["cons_row"]:
                D["c_dia_min"] = ui.select({d: f"Φ{d}" for d in BAR_DIAS},
                                           value=12, label="最小直径",
                                           on_change=calc_design
                                           ).props("outlined").classes("w-32")
                D["c_dia_max"] = ui.select({d: f"Φ{d}" for d in BAR_DIAS},
                                           value=25, label="最大直径",
                                           on_change=calc_design
                                           ).props("outlined").classes("w-32")
                D["c_sp_min"] = ui.select({s: str(s) for s in SLAB_SPACINGS},
                                          value=70, label="最小间距",
                                          on_change=calc_design
                                          ).props("outlined").classes("w-32")
                D["c_sp_max"] = ui.select({s: str(s) for s in SLAB_SPACINGS},
                                          value=330, label="最大间距",
                                          on_change=calc_design
                                          ).props("outlined").classes("w-32")
                D["c_total"] = ui.switch("按板宽给总根数", value=True,
                                         on_change=calc_design).props("dense")
                D["c_double"] = ui.switch("排不下允许双层", value=True,
                                          on_change=calc_design).props("dense")
        # 状态/提示/"还需填写"上移到结果区顶部（原来沉在卡片底部，看不到）
        _kids = list(card_r.default_slot.children)
        _at = _kids.index(D["info"])            # 插在"资料"之前
        D["verdict"].move(card_r, _at)
        D["err"].move(card_r, _at + 1)
        D["jump"].move(card_r, _at + 2)
        # 宽屏双栏归位：输入四卡→左列（sticky、打印隐藏），结果卡→右列
        # 顺序 = 计算过程顺序（资料→截面→荷载/M 来源→选筋约束），自上而下填 = 结果自上而下长出来
        for _c in (card_e, card_s, card_m, card_c):
            _c.move(_cols[1])
        card_r.move(_cols[2])


def sync_design():
    msrc = D["Msrc"].value
    D["M_row"].set_visibility(msrc == "direct")
    sync_load_block(D, msrc)
    is_beam = D["member"].value == "梁"
    if not is_beam and D["dbl"].value != "none":
        D["dbl"].set_value("none")            # 双筋仅梁：板归位单筋（连锁一次 calc，不再递归）
        if not (D.get("_loading") or _state().get("_mid_load")):
            toast("板不适用双筋截面（教材3.5.2），已切换为单筋")
    set_field_visible(D["stirrup"], is_beam)
    set_field_visible(D["dia_est"], D["layers"].value == "1")
    for _k in ("c_sp_min", "c_sp_max", "c_total"):
        D[_k].set_visibility(not is_beam)
    D["c_double"].set_visibility(is_beam)
    D["dbl_row"].set_visibility(is_beam)
    D["asp_row"].set_visibility(is_beam)
    D["dbl_hint"].set_visibility(not is_beam)
    dmode = D["dbl"].value
    known = dmode == "known"
    cnt = D["Asp_src"].value == "count"
    set_field_visible(D["asp"], dmode != "none")
    set_field_visible(D["Asp_src"], known)
    set_field_visible(D["dia_p"], known and cnt)
    set_field_visible(D["n_p"], known and cnt)
    set_field_visible(D["Asp"], known and not cnt)


def _collect_load(R):
    """从荷载块控件收集纯数值 dict（pipeline 输入）。"""
    return {"gk": _num(R["gk"]), "qk": _num(R["qk"]),
            "Gk": _num(R["Gk"]), "Qk": _num(R["Qk"]),
            "MG": _num(R["MG"]), "MQ": _num(R["MQ"]),
            "q_kind": R["q_kind"].value, "Q_kind": R["Q_kind"].value,
            "level": R["level"].value, "situation": R["situation"].value,
            "l0src": R["l0src"].value, "ln": _num(R["ln"]),
            "a": _num(R["a"]), "l0": _num(R["l0"])}


def _collect_design():
    lo = int(_num(D["c_dia_min"], min(BAR_DIAS)))
    hi = int(_num(D["c_dia_max"], max(BAR_DIAS)))
    return {
        "_empty": sorted(k for k in (D_NUMKEYS | set(_COEF_KEYS))
                         if getattr(D.get(k), "value", None) is None),
        "member": D["member"].value, "b": _num(D["b"]), "h": _num(D["h"]),
        "conc": D["conc"].value, "steel": D["steel"].value, "env": D["env"].value,
        "y100": bool(D["y100"].value),
        "layers": int(D["layers"].value), "dia_est": _num(D["dia_est"]),
        "stirrup": _num(D["stirrup"], 10),
        "m_mode": D["Msrc"].value, "M_kNm": _num(D["M"]),
        "dbl": (D["dbl"].value if D["dbl"].value != "known"
                else D["Asp_src"].value),
        "Asp": _num(D["Asp"]), "dia_p": D["dia_p"].value,
        "n_p": _num(D["n_p"], 0), "asp_": _num(D["asp"]),
        "load": _collect_load(D),
        "constraints": {
            "dias": [d for d in BAR_DIAS if lo <= d <= hi],
            "s_range": (int(_num(D["c_sp_min"], min(SLAB_SPACINGS))),
                        int(_num(D["c_sp_max"], max(SLAB_SPACINGS)))),
            "allow_double": bool(D["c_double"].value),
            "total": bool(D["c_total"].value)},
        "picked_id": D.get("picked_id"),
    }


def verdict_partial(w, text):
    """分段（未算完）提示：中性灰，与"已完成"的绿/红判定横幅明确区分。"""
    w.set_content(text)
    w.style("white-space:pre-wrap;padding:10px 14px;border-radius:8px;"
            "background:#eef2f7;color:#546e7a;")


def _paint_partial_design(res):
    """分段结果：已算到的段照常显示，未算到的段出灰标题占位 + 列出还差什么。"""
    D["info"].set_content(res.get("info_html") or "")
    D["mchain"].set_content(res.get("m_html") or "")
    miss = res.get("missing") or []
    miss_txt = "、".join(lb for _, lb in miss)
    D["_missing_txt"] = miss_txt
    pend = res.get("pending_html") or []
    parts = []
    for i, name in enumerate(pend):
        parts.append(f'<div style="color:#90a4ae;font-size:13px;font-weight:700;'
                     f'margin:16px 0 4px;">{name}</div>')
        if i == 0:
            parts.append(f'<div style="color:#b0bec5;font-size:12px;">'
                         f'待填写：{miss_txt}（填好后自动继续）</div>')
    D["res"].set_content("".join(parts))
    verdict_partial(D["verdict"], f"◌ 进行中 · 已算到「{res.get('stage', '')}」，还差 {miss_txt}")


def _clear_design_result(hint=""):
    D["res"].set_content("")
    clear_verdict(D["verdict"])
    D["live"].set_content("")
    D["info"].set_content("")
    D["mchain"].set_content("")
    D["sweep_wrap"].set_content("")
    D["kpi"].set_visibility(False)
    D["rho_wrap"].set_visibility(False)
    D["adopt"].set_visibility(False)
    D["bars_title"].set_text("")
    D["bars"].set_visibility(False)
    D["fig"].set_content("")
    D["fig_cap"].set_content("")
    D["recheck"].set_content("")
    D["recheck"].set_visibility(False)
    D["bars_hint"].set_content(hint)
    _refresh_toc(D.get("card_r"), D.get("toc"))


def calc_design(*_):
    if _state().get("_mid_load"):
        return                                # 载入批量赋值期间的连锁 calc 全跳过（尾部有显式总算）
    if not D.get("_loading") and D.get("_preset"):
        _set_preset(D, None, _DESIGN_PRESETS)   # 手动改了输入 → 已不是原例题
    D["asp"].validate()                       # 跨字段规则刷新（h/布筋变化影响 a′s<h0）
    _sync_jump(D, D_NUMKEYS)                  # "还需填写 N 项"计数随显隐/填值更新
    try:
        D["err"].set_text("")
        res = pipeline.solve_design(_collect_design(), partial=True)
    except (ValueError, KeyError) as e:
        _clear_design_result()
        D["_vred"] = False
        if not _num(D["b"]) and not _num(D["h"]):
            # 空白模板进场：中性"待填写"提示，不算错误
            D["err"].set_text("· 请在左侧填写截面与荷载参数，输入后自动计算")
            D["err"].style("color:#78909c")
        else:
            D["err"].set_text(f"⚠ {e}")
            D["err"].style("color:#b71c1c")
            # 程序化赋值（载入/预设/联动）途中不弹 toast，只留行内提示
            if not (D.get("_loading") or V.get("_loading")
                    or V.get("_prog") or _state().get("_mid_load")):
                notify_error_once(str(e))
        save_problems()
        return
    if res.get("partial"):
        # 分段（填一段出一段）：已算到的段照常显示，未算段出灰标题占位
        _clear_design_result()
        D["_res"] = None
        D["_vred"] = False
        D["fig_ctx"] = None
        D["live"].set_content("")         # 分段态无最终判定，摘要条不出
        D["err"].set_text("")                 # "进行中·还差…"由判定区显示，避免重复提示
        _paint_partial_design(res)
        _state()["_err"] = None
        _refresh_toc(D.get("card_r"), D.get("toc"))
        save_problems()
        return
    _state()["_err"] = None
    _paint_design(res)
    # 复核上下文若派生自设计页：设计参数变化 → 标记复核结果过期
    if V.get("_derived"):
        V["_stale"] = (_design_fp() != V.get("_src_fp"))
    save_problems()


def _live_bar_html(ok, label, kpis):
    """窄屏（<1024px 单栏）粘性实时摘要条内容：判定胶囊 + 关键数。

    宽屏双栏下结果常驻右列，此条由 CSS 隐藏；内容在每次重绘时整条刷新。
    """
    flag = ("✔ " if ok else "✘ ") + label
    fg, bg = ("#1b5e20", "#e8f5e9") if ok else ("#b71c1c", "#fdecea")
    kpi = "　｜　".join(kpis)
    return (f'<span class="nz-lv-flag" style="color:{fg};background:{bg};">{flag}</span>'
            f'<span class="nz-lv-kpi">{kpi}</span>')


def _paint_design(res):
    ok = res["verdict"]["ok"]
    D["_res"] = res
    D["info"].set_content(res["info_html"])
    D["mchain"].set_content(res["m_html"])
    _sig = _chain_sig(res["res_html"])
    _chain_new = _sig != D.get("_chain_sig")
    D["_chain_sig"] = _sig
    D["res"].set_content(res["res_html"])
    if _chain_new:
        _anim_play(D["res"])
    D["sweep_wrap"].set_content(res.get("sweep_html") or "")
    _vtxt = res["verdict"]["html"]
    vad = _vtxt != D.get("_verdict_html")
    D["_verdict_html"] = _vtxt
    verdict_banner(D["verdict"], ok, _vtxt, animate=vad)
    # 窄屏实时摘要条（宽屏由 CSS 隐藏，内容照刷不显示）
    _lv = res["values"]
    _lv_kpis = [f"As = {fmt(_lv.get('As') or _lv.get('as_'), 0)} mm²"]
    if _lv.get("Asp"):
        _lv_kpis.append(f"A′s = {fmt(_lv['Asp'], 0)} mm²")
    _lv_kpis += [f"ρ = {res['r']['rho'] * 100:.2f}%",
                 f"M = {fmt(_lv['M'] / 1e6, 1)} kN·m"]
    D["live"].set_content(_live_bar_html(ok, "设计可行" if ok else "暂不可行", _lv_kpis))
    # 超筋/少筋续演时提供“改 h 一键重算”
    tr = ((res.get("suggest") or {}).get("trial"))
    if tr:
        D["adopt"].set_text(f"↩ 将 h 改为 {tr['h']:g}mm 并重算")
        D["adopt"].set_visibility(True)
    else:
        D["adopt"].set_visibility(False)
    if not ok:
        if not D.get("_vred"):
            scroll_to_result()
        D["_vred"] = True
        D["kpi"].set_visibility(False)
        D["rho_wrap"].set_visibility(False)
        D["fig"].set_content("")
        D["fig_cap"].set_content("")
        D["bars_title"].set_text("")
        D["bars"].set_visibility(False)
        D["recheck"].set_content("")
        D["recheck"].set_visibility(False)
        D["bars_hint"].set_content(res.get("bars_hint_extra", ""))
        return
    D["_vred"] = False
    _state()["as"] = res["values"]["as_"]      # 去复核时带入 a_s
    _kpi = res["kpi_html"]
    _flash = _kpi != D.get("_kpi_html")
    D["_kpi_html"] = _kpi
    D["kpi"].set_content(_kpi)
    D["kpi"].set_visibility(True)
    if _flash:
        _anim_play(D["kpi"], "anim-flash", 600)
    ru = res["rho_ui"]
    D["rho_bar"].set_value(ru["value"])
    D["rho_bar"].props(f"color={ru['color']} rounded")
    D["rho_scale"].set_content(ru["scale_html"])
    D["rho_wrap"].set_visibility(True)
    bars = res["bars"]
    D["bars_title"].set_text(bars["title"])
    D["bars"].columns = [{"name": k, "label": lab, "field": k}
                         for k, lab in bars["columns"]]
    D["bars"].rows = bars["rows"]
    D["bars"].set_visibility(True)
    D["bars_hint"].set_content(bars["hint"])
    D["fig_ctx"] = res["fig"]
    draw_design_fig()
    paint_recheck(res)
    _refresh_toc(D.get("card_r"), D.get("toc"))


def paint_recheck(res=None):
    """选中行的内联实配回验（C）。"""
    res = res or D.get("_res")
    row = D.get("picked_row")
    if not res or not row or not res["verdict"]["ok"]:
        D["recheck"].set_content("")
        D["recheck"].set_visibility(False)
        return
    chk = pipeline.picked_recheck(res["values"], row, res["values"].get("M"))
    if chk:
        D["recheck"].set_content(chk["html"])
        D["recheck"].set_visibility(True)
    else:
        D["recheck"].set_content("")
        D["recheck"].set_visibility(False)


def _tbl_jump(*args):
    """计算过程里点表号 → 切「数据」页签并滚到该表（行级定位）。

    同时记住"从哪个页签、什么位置"来的——切回时由 _tab_changed 还原
    （服务端记账，不嗅探 DOM；客户端只上报当前页签与 scrollY）。
    """
    key = args[0] if args else None
    rest = list(args[1:]) if not isinstance(key, (list, tuple)) else list(key)
    if isinstance(key, (list, tuple)):
        key = rest[0] if rest else None
        rest = rest[1:]
    row = rest[0] if rest else None
    from_tab = rest[1] if len(rest) > 1 else None
    from_y = rest[2] if len(rest) > 2 else None
    if not key:
        return
    if from_tab and from_tab != "数据" and isinstance(from_y, (int, float)):
        _state()["_back"] = (from_tab, int(from_y))          # 记账：切回时还原
    TABS["tabs"].set_value("数据")
    ui.run_javascript(f"nzRefGo('nz-tbl-{key}', {json.dumps(row or '')})")


def _not_done_toast(pool):
    """分段（未算完）时点复制/下载：明确说还差什么，别给出半截计算书。"""
    miss = pool.get("_missing_txt")
    toast(f"尚未算完：还差 {miss}（填好后自动继续）" if miss
          else "尚未算完：先补齐左侧栏位再复制计算书")


def copy_report_design():
    if D.get("_res") is None:                 # 分段/出错态：没有完整结果
        _not_done_toast(D)
        return
    try:
        res = pipeline.solve_design(_collect_design())
        ui.clipboard.write(res["report"])
        toast("计算书已复制，可直接粘贴到 Word/记事本")
    except (ValueError, KeyError) as e:
        notify_error_once(str(e))


def _design_fp():
    """设计侧关键参数指纹（供"复核结果是否过期"比对）。"""
    d = _collect_design()
    key = {"member": d["member"], "b": d["b"], "h": d["h"], "conc": d["conc"],
           "steel": d["steel"], "m_mode": d["m_mode"], "M_kNm": d["M_kNm"],
           "load": d["load"]}
    return json.dumps(key, sort_keys=True, ensure_ascii=False)


def _transfer_to_verify(row=None):
    """把设计页参数带入复核页（row=选筋行时同时带入钢筋），并记录来源指纹。

    row=None 时只带参数、不动 As 输入（用于"设计变更后重新带入"）。
    """
    V["_prog"] = True            # 程序赋值期间的 calc 视为非手动编辑
    try:
        member = D["member"].value
        cs = (D.get("_res") or {}).get("values", {}).get("cs")
        if member == "梁":
            V["member"].value = "梁"
            if row:
                V["Asrc"].value = "count"
                V["dia_c"].value = int(row["dia"][1:])
                V["n"].value = int(row["cnt"].replace("根", ""))
                desc = f"复核 {row['dia']}（{row['cnt']}）"
                if cs is not None:
                    V["as"].value = cs + (35 if "双层" in row.get("fit", "")
                                          else int(row["dia"][1:]) / 2)
            else:
                desc = "复核（按当前设计参数重新带入）"
        else:
            V["member"].value = "板"
            if row:
                V["Asrc"].value = "spacing"
                d, s = row["spec"][1:].split("@")
                V["dia_s"].value = int(d)
                V["spacing"].value = int(s)
                desc = f"复核 {row['spec']}"
                if cs is not None:
                    V["as"].value = cs + int(d) / 2
            else:
                desc = "复核（按当前设计参数重新带入）"
        if cs is None and _state().get("as"):
            V["as"].value = _state()["as"]
        V["b"].value, V["h"].value = _num(D["b"]), _num(D["h"])
        V["conc"].value, V["steel"].value = D["conc"].value, D["steel"].value
        # 受压筋：双筋设计结果一并带入（未知模式按计算值直接输入），单筋回"无"
        _dv = (D.get("_res") or {}).get("values") or {}
        if _dv.get("doubly") and _dv.get("dbl_mode") == "count":
            V["dbl"].value = "count"
            V["dia_p"].value = int(D["dia_p"].value)
            V["n_p"].value = int(_num(D["n_p"], 2) or 2)
            V["asp"].value = _num(D["asp"], 55)
        elif _dv.get("doubly"):
            V["dbl"].value = "direct"
            V["Asp"].value = _dv.get("Asp")
            V["asp"].value = _dv.get("asp_") or 55
        else:
            V["dbl"].value = "none"
        _m_src = D["Msrc"].value          # 弯矩来源三态原样带入
        V["Msrc"].value = _m_src
        if _m_src == "direct":
            V["M"].value = _num(D["M"])
        elif _m_src == "moments":
            for k in ("MG", "MQ", "level", "situation"):
                V[k].value = D[k].value
        else:
            for k in ("gk", "qk", "Gk", "Qk", "ln", "a", "l0"):
                V[k].value = D[k].value
            for k in ("q_kind", "Q_kind", "level", "situation", "l0src"):
                V[k].value = D[k].value
        sync_verify()
        V["_src_fp"] = _design_fp()   # 记录带入时的设计参数指纹
        V["_derived"] = True          # 本复核上下文派生自设计页
        V["_stale"] = False
        calc_verify()
        TABS["tabs"].set_value("复核")
        _anim_play(V["res"])
        toast(f"已带入复核页：{desc}")
    finally:
        V["_prog"] = False


def review_from_design(e):
    """选筋表“去复核”：带入钢筋、截面、材料与弯矩，跳到复核页完成验算。

    a_s 按实配直径重算（单层 cs+d/2、双层 cs+35、板 cs+d/2），与实配回验一致。
    """
    _transfer_to_verify(e.args)


D_DEFAULTS, V_DEFAULTS = {}, {}
D_NUMKEYS, V_NUMKEYS = set(), set()   # 数字输入键——题型模板要求全部置空（真空白）
# 系数类下拉（查表陷阱）：空白模板不预选，逼使用者按题核对（γQ 类别 / γ0 / ψ / 保护层环境）
_COEF_KEYS = ("q_kind", "Q_kind", "level", "situation", "env")

# ---------------- 题目工作区（A）：多题切换 + problems.json 持久化 --------------

P = _CtxDict("P")                       # 题号条状态（按客户端）
STORE = {"problems": [], "current": 0, "seq": 0}   # 题库（文件持久化）
_STORE_STATE = {"blocked": False}       # 存档读不到且无法隔离时暂停写，避免覆盖原档


def _cur():
    return _state()["cur"]


def _set_cur(i):
    _state()["cur"] = i


def _scroll_top():
    ui.run_javascript("window.scrollTo({top: 0, behavior: 'smooth'})")


def _problems_path():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "problems.json"
    return Path(__file__).parent / "problems.json"


def _notify_store_problem(msg):
    """题库读写异常提示：同一客户端同一条消息只弹一次。"""
    st = _state()
    if st.get("_store_warned") == msg:
        return
    st["_store_warned"] = msg
    try:
        ui.notify(msg, type="negative", position="bottom-right", timeout=6000)
    except Exception:
        logging.getLogger(__name__).exception("题库异常提示发送失败")


_STORE_LOCK = threading.Lock()          # 序列化落盘（写线程与处理器线程并发护住 json.dumps）
_STORE_TIMER = {"t": None}              # 计算类落盘的合并定时器


def _write_store():
    """原子写题库：先写同目录临时文件，再 os.replace 替换正式档。"""
    if _STORE_STATE["blocked"]:
        _notify_store_problem("题库文件当前不可写，已暂停自动保存；"
                              "请检查 problems.json 是否被占用或目录是否可写")
        return False
    p = _problems_path()
    tmp = p.with_name(p.name + ".tmp")
    try:
        with _STORE_LOCK:
            tmp.write_text(json.dumps(STORE, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(tmp, p)
    except OSError:
        logging.getLogger(__name__).exception("题库保存失败：%s", p)
        try:
            tmp.unlink()
        except OSError:
            pass
        _notify_store_problem("题库保存失败：无法写入 problems.json，"
                              "请检查文件是否被占用或目录是否可写")
        return False
    _state()["_store_warned"] = None
    return True


def _schedule_store(delay=0.6):
    """计算类落盘合并：最后一次改动后 delay 秒才真正写盘。

    逐键输入/批量套值期间连锁 calc 每次都同步落盘纯属空转；
    尾沿合并后，载入/连击序列天然只写一次，也进一步避开了 _mid_load 竞态面。
    结构性操作（新建/删除/改名/导入/预设）仍走同步 _write_store，确保即落。
    """
    t = _STORE_TIMER["t"]
    if t is not None:
        t.cancel()
    t = threading.Timer(delay, _write_store)
    t.daemon = True
    _STORE_TIMER["t"] = t
    t.start()


def _new_default_store():
    """建立可用的内存题库（首次运行，或启动重置/坏档隔离后的新档）。

    出厂首题即"课本例题"（locked 不可删）：启动重置删档后走 missing 分支到这里，
    与老档改名迁移的结果保持一致——顶部永远有且只有这一道公共参照题。
    """
    STORE["problems"] = [{"name": "课本例题", "locked": True, "kind": "设计",
                          "D": dict(D_DEFAULTS), "V": dict(V_DEFAULTS)}]
    STORE["current"], STORE["seq"] = 0, 1
    _set_cur(0)


def _load_store():
    """读取题库。返回 ok / missing / bad / blocked。

    bad：原文件存在但无法解析，已改名为 *.corrupt-<时间>.json 保留；
    blocked：原文件存在但读不到或无法隔离，调用方不得覆盖它。
    """
    p = _problems_path()
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing"
    except OSError:
        logging.getLogger(__name__).exception("题库文件无法读取：%s", p)
        _STORE_STATE["blocked"] = True
        _notify_store_problem("题库文件无法读取，已暂停自动保存；"
                              "请检查 problems.json 的权限或占用情况")
        return "blocked"
    try:
        data = json.loads(raw)
        valid = (isinstance(data, dict)
                 and isinstance(data.get("problems"), list)
                 and data["problems"]
                 and all(isinstance(x, dict) for x in data["problems"]))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        dest = p.with_name(
            f"{p.stem}.corrupt-{time.strftime('%Y%m%d-%H%M%S')}{p.suffix}")
        try:
            os.replace(p, dest)
        except OSError:
            logging.getLogger(__name__).exception("题库文件无法解析且无法隔离：%s", p)
            _STORE_STATE["blocked"] = True
            _notify_store_problem("题库文件无法解析且无法隔离，已暂停自动保存；"
                                  "请手工备份并检查 problems.json")
            return "blocked"
        logging.getLogger(__name__).error("题库文件无法解析，已保留为 %s", dest)
        _notify_store_problem(f"题库文件无法解析，原文件已保留为 {dest.name}，将新建题库")
        return "bad"
    STORE["problems"] = data["problems"]
    for _p in STORE["problems"]:
        # 题型功能前创建的旧题默认归“设计”（可在重命名里改）
        _p.setdefault("kind", "设计")
    if STORE["problems"]:
        first = STORE["problems"][0]
        if first.get("name") == "启闭机梁练习":
            first["name"] = "课本例题"     # 首题定位为课本例题（公共参照题）
        first.setdefault("locked", True)   # 公共参照题不可删除
    try:
        ci = int(data.get("current", 0)) % len(STORE["problems"])
    except (TypeError, ValueError):
        ci = 0
    try:
        STORE["seq"] = int(data.get("seq", 0))
    except (TypeError, ValueError):
        STORE["seq"] = 0
    STORE["current"] = ci
    _set_cur(ci)
    return "ok"


def _vals(pool):
    """控件值快照（仅 JSON 可序列化的 value 控件）。"""
    return {k: w.value for k, w in pool.items() if hasattr(w, "value")}


def save_problems():
    """把当前 D/V 状态写入当前题目并落盘（每次计算后调用）。

    载入题目期间（_mid_load）跳过——否则 D 面板套值触发的连锁 calc 会把
    还没套值的旧 V 面板写进新题（载入竞态）；载入收尾由 load 统一存一次。
    """
    if _state().get("_mid_load"):
        return
    if not STORE["problems"]:
        return
    cur = STORE["problems"][_cur()]
    cur["D"] = _vals(D)
    cur["V"] = _vals(V)
    cur["preset"], cur["vpreset"] = D.get("_preset"), V.get("_preset")   # 例题选中态也存
    cur["vsrc"], cur["vderived"] = V.get("_src_fp"), V.get("_derived")   # 复核来源指纹/派生标记
    STORE["current"] = _cur()
    _schedule_store()


def _tree_visible(w):
    """元素是否真的可见——沿祖先链检查（行/包裹层的 set_visibility 藏在上层，
    只看 w.visible 会把被藏起来的字段也算进来）。"""
    e = w
    while e is not None:
        if not getattr(e, "visible", True):
            return False
        slot = getattr(e, "parent_slot", None)
        e = getattr(slot, "parent", None) if slot is not None else None
    return True


def _sync_jump(pool, numkeys):
    """更新"还需填写 N 项 ▸ 跳到下一个"按钮：N = 真的可见且未填的数字栏位。"""
    btn = pool.get("jump")
    if btn is None:
        return
    n = sum(1 for k, w in pool.items()
            if k in numkeys and getattr(w, "value", None) is None and _tree_visible(w))
    if n:
        btn.set_text(f"还需填写 {n} 项 ▸ 跳到下一个")
        btn.set_visibility(True)
    else:
        btn.set_visibility(False)


def _apply_values(values, refs):
    for k, v in (values or {}).items():
        w = refs.get(k)
        if w is not None and hasattr(w, "value"):
            try:
                w.value = v
            except (ValueError, TypeError):
                pass


def refresh_problem_bar():
    """重绘画题号条（当前题高亮；chip 带题型标签——设计/复核）。"""
    if not P["bar"]:
        return
    P["bar"].clear()
    with P["bar"]:
        for i, prob in enumerate(STORE["problems"]):
            active = (i == _cur())
            label = prob.get("name", f"题目{i + 1}")
            kind = prob.get("kind")
            if kind and not label.startswith(kind):
                label = f"{label}（{kind}）"   # 题名已含题型（如"设计1"）时不重复标注
            b = ui.button(label,
                          on_click=lambda e, idx=i: switch_problem(idx))
            if active:
                b.props("color=primary no-caps rounded dense")
            else:
                b.props("outline no-caps rounded dense")
    # chip 数量变化 → 顶栏高度可能变化 → 重测吸顶偏移
    ui.run_javascript("window.nzTopStack && window.nzTopStack()")


def switch_problem(idx):
    if idx == _cur() or not (0 <= idx < len(STORE["problems"])):
        return
    save_problems()
    _set_cur(idx)
    load_current_problem()
    refresh_problem_bar()
    _scroll_top()
    toast(f"已切换到 {STORE['problems'][idx].get('name')}")


def load_current_problem():
    prob = STORE["problems"][_cur()]
    st = _state()
    st["_mid_load"] = True                    # 载入期间禁落盘（防旧面板值写入新题）
    try:
        V["_prog"] = True                     # 载入赋值视为非手动编辑
        D["_loading"] = V["_loading"] = True  # 载入期间的 calc 不清除例题选中态
        D["_preset"] = prob.get("preset")
        V["_preset"] = prob.get("vpreset")
        V["_src_fp"] = prob.get("vsrc")       # 复核来源指纹/派生标记随题目恢复
        V["_derived"] = bool(prob.get("vderived"))
        _apply_values(D_DEFAULTS, D)          # 先回出厂默认：题目存档缺的键（后加的字段）
        _apply_values(V_DEFAULTS, V)          # 不再从上一题"串值"，随后落盘也不会把它固化
        _apply_values(prob.get("D"), D)
        _apply_values(prob.get("V"), V)
        if prob.get("tpl"):                   # 空白模板：存档缺失的数字键同样置空（真空，而非出厂默认）
            for _pool, _keys, _stored in ((D, list(D_NUMKEYS) + list(_COEF_KEYS), prob.get("D") or {}),
                                          (V, list(V_NUMKEYS) + list(_COEF_KEYS), prob.get("V") or {})):
                for _k in _keys:
                    _w = _pool.get(_k)
                    if _w is not None and hasattr(_w, "value") and _k not in _stored:
                        _w.value = None
        D["picked_id"] = None
        st["_mid_load"] = False               # 赋值结束：放行收尾显式总算（期间连锁 calc 已跳过）
        sync_design()
        calc_design()
        sync_verify()
        calc_verify()
    finally:
        D["_loading"] = V["_loading"] = False
        V["_prog"] = False
        st["_mid_load"] = False
        save_problems()                       # 收尾：以套好的面板值统一落盘一次
    _anim_play(D["res"])
    _anim_play(V["res"])
    tpl = bool(prob.get("tpl"))               # 空白模板题：隐藏例题一键载入条
    D["exrow"].set_visibility(not tpl)
    V["exrow"].set_visibility(not tpl)
    update_stale_bar()
    _sync_preset_row(D, _DESIGN_PRESETS)
    _sync_preset_row(V, _VERIFY_PRESETS)


def _name_taken(nm, exclude=None):
    """题库内是否已有同名题（exclude=正在编辑的下标，改名时排除自身）。"""
    return any(i != exclude and (p.get("name") or "").strip() == nm
               for i, p in enumerate(STORE["problems"]))


def _next_default_name(kind):
    """默认题名"设计N"/"复核N"：N = 该题型已用最大编号 + 1（按题型分组，互不干扰）。

    不用全局计数器（曾出现题库只剩 1 道题、新建却叫"题目32"的跳号）；
    删题后编号会被复用——名字只是标签，重号不会同时在库。
    """
    mx = 0
    pat = re.compile(rf"^{re.escape(kind)}(\d+)$")
    for p in STORE["problems"]:
        m = pat.match((p.get("name") or "").strip())
        if m:
            mx = max(mx, int(m.group(1)))
    return f"{kind}{mx + 1}"


# ---------------- 分享 / 备份：题目卡（人读 .txt）导入导出 ----------------

def _export_card_text(probs):
    """题库条目 → 题目卡文本（problems_io 负责格式；这里只供数）。"""
    return problems_io.dump_cards([
        {"kind": p.get("kind") or "设计", "name": p.get("name") or "",
         "D": p.get("D") or {}, "V": p.get("V") or {}}
        for p in probs])


def _safe_fname(s):
    return (s or "题目").replace('"', "").replace("/", "_").replace(
        "\\", "_").replace("｜", "_").replace("：", "_")


def export_current_problem():
    if not STORE["problems"]:
        return
    p = STORE["problems"][_cur()]
    ui.download(_export_card_text([p]).encode("utf-8-sig"),
                f"题目卡_{_safe_fname(p.get('name'))}.txt", "text/plain")
    toast("已导出当前题目卡（.txt，记事本/手机可直接打开）")


def export_all_problems():
    n = len(STORE["problems"])
    if not n:
        return
    ui.download(_export_card_text(STORE["problems"]).encode("utf-8-sig"),
                f"题目卡_全部{n}题.txt", "text/plain")
    toast(f"已导出全部 {n} 道题目卡（建议定期备份一份）")


def _import_upload(e):
    """上传的题目卡 .txt → 解析导入（BOM 兼容记事本导出）。"""
    try:
        text = e.content.read().decode("utf-8-sig", errors="replace")
    except Exception:
        logging.getLogger(__name__).exception("题目卡文件读取失败")
        ui.notify("文件读取失败，请重新选择", type="negative",
                  position="bottom-right", timeout=4000)
        return
    _import_cards_text(text, getattr(e, "name", ""))


def _import_cards_text(text, source=""):
    """题目卡文本 → 追加为新题（同名自动加 (2)；绝不覆盖已有题）。"""
    try:
        cards = problems_io.parse_cards(text)
    except ValueError as e:
        ui.notify(str(e), type="negative", position="bottom-right", timeout=6000)
        return
    if not cards:
        ui.notify("题目卡里没有题目", type="warning", position="bottom-right",
                  timeout=4000)
        return
    for c in cards:
        nm = c["name"] or _next_default_name(c["kind"])
        if _name_taken(nm):
            i = 2
            while _name_taken(f"{nm}({i})"):
                i += 1
            nm = f"{nm}({i})"
        # 只收界面认识的键位（旧版卡/新版程序防串键）；locked/tpl 等标记不随卡走
        STORE["problems"].append({
            "name": nm, "kind": c["kind"],
            "D": {k: v for k, v in c["D"].items() if k in D},
            "V": {k: v for k, v in c["V"].items() if k in V}})
    _set_cur(len(STORE["problems"]) - len(cards))
    STORE["current"] = _cur()
    _write_store()
    load_current_problem()
    refresh_problem_bar()
    _scroll_top()
    nbad = sum(len(c["bad"]) for c in cards)
    if nbad:
        logging.getLogger(__name__).info(
            "题目卡导入（%s）：%d 行无法识别跳过", source or "粘贴", nbad)
    toast(f"已导入 {len(cards)} 道题" + (f"，{nbad} 行无法识别已跳过" if nbad else ""))


def share_dialog():
    """分享/备份对话框：导出题目卡 .txt；导入走选文件或直接粘贴文本。"""
    with ui.dialog() as dlg, ui.card().classes("w-[560px] max-w-[94vw] q-pa-lg"):
        ui.label("分享 / 备份题目").classes("font-bold text-lg")
        ui.label("导出为「题目卡」.txt——记事本、手机都能直接打开看；同学收到后在"
                 "这个对话框里「导入」即可还原成可计算题目，不需要懂任何格式。"
                 ).classes("text-sm text-gray-600")
        with ui.row().classes("w-full gap-2 mt-1"):
            ui.button("⬇ 导出当前题", on_click=export_current_problem).props(
                "outline dense no-caps rounded")
            ui.button("⬇ 导出全部题目", on_click=export_all_problems).props(
                "outline dense no-caps rounded")
        ui.separator().classes("my-2")
        ui.label("导入题目卡").classes("font-bold")
        ui.upload(on_upload=lambda e: (_import_upload(e), dlg.close())).props(
            'accept=".txt,text/plain" auto-upload flat outlined dense '
            'label="选择题目卡 .txt 文件"').classes("w-full")
        paste = ui.textarea("…或把题目卡文本直接粘贴到这里（微信里长按复制也行）",
                            ).props("outlined dense").classes("w-full")
        with ui.row().classes("w-full justify-end gap-2 mt-1"):
            ui.button("关闭", on_click=dlg.close).props("flat")
            ui.button("导入粘贴内容",
                      on_click=lambda: (_import_cards_text(paste.value or ""),
                                        dlg.close())).props("color=primary")
    dlg.open()


def new_problem_dialog(kind=None, copy=False):
    """新建题目的命名对话框：确认才创建（取消 = 不创建）。题型由菜单项决定。"""
    if copy and STORE["problems"]:
        src = STORE["problems"][_cur()]
        kind_eff = src.get("kind") or ("复核" if TABS["tabs"].value == "复核" else "设计")
    else:
        kind_eff = kind or "设计"
    default = _next_default_name(kind_eff)
    with ui.dialog() as dlg, ui.card().classes("w-96 q-pa-lg"):
        ui.label("新建题目").classes("font-bold")
        ui.label("复制当前题目（含全部输入）" if copy
                 else f"{kind_eff} · 空白模板（数值留空，进场即填）"
                 ).classes("text-xs text-gray-500")
        name_in = ui.input("题目名称", value=default).props("maxlength=16")
        err_l = ui.label("").style("color:#b71c1c;font-size:12px;min-height:16px")

        def _create():
            nm = (name_in.value or "").strip()
            if not nm:
                err_l.set_text("题目名称不能为空")
                return
            if _name_taken(nm):
                err_l.set_text(f"已有同名题目「{nm}」")
                return
            new_problem(kind=kind, copy=copy, name=nm)
            dlg.close()

        name_in.on("keydown.enter", lambda: _create())
        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("取消", on_click=dlg.close).props("flat")
            ui.button("创建", on_click=_create).props("color=primary")
    dlg.open()


def new_problem(kind=None, copy=False, name=None):
    """新建题目（题型模板制——沉淀“这一类题”的框架，而不是复制上一题实例）。

    kind='设计'/'复核'：题型模板——出厂默认输入（干净骨架）+ 自动切到对应页签；
    copy=True：复制当前题全部输入（菜单末项，同题改参数变体场景）。
    name：题名（由 new_problem_dialog 传入）；缺省用"题目N"（库内最大编号+1）。
    题型随 problems.json 持久化，显示在题号 chip 上。
    """
    save_problems()
    STORE["seq"] = STORE.get("seq", 0) + 1    # 旧存档字段，仅兼容保留
    if copy:
        src = STORE["problems"][_cur()]
        kind_eff = src.get("kind") or ("复核" if TABS["tabs"].value == "复核" else "设计")
    else:
        kind_eff = kind or "设计"
    name = (name or "").strip() or _next_default_name(kind_eff)
    if copy:
        prob = {"name": name, "D": dict(src.get("D") or {}),
                "V": dict(src.get("V") or {}),
                "kind": kind_eff,
                "preset": src.get("preset"), "vpreset": src.get("vpreset"),
                "tpl": False}
    else:
        # 空白模板：数值输入全空（进场直接填本题的数），下拉/开关保留结构默认
        prob = {"name": name,
                "D": {**D_DEFAULTS, **{k: None for k in D_NUMKEYS},
                      **{k: None for k in _COEF_KEYS}},      # 系数类不预选（必须按题核对）
                "V": {**V_DEFAULTS, **{k: None for k in V_NUMKEYS},
                      **{k: None for k in _COEF_KEYS}},
                "kind": kind_eff, "tpl": True}   # tpl=空白模板题：隐藏例题条
    STORE["problems"].append(prob)
    _set_cur(len(STORE["problems"]) - 1)
    STORE["current"] = _cur()
    saved = _write_store()
    if not copy and kind:
        TABS["tabs"].set_value("设计" if kind == "设计" else "复核")
    load_current_problem()
    refresh_problem_bar()
    _scroll_top()
    if saved:
        if copy:
            toast(f"已新建「{name}」（复制当前输入为起点）")
        else:
            toast(f"已新建「{name}」（空白模板，改数即算）")


def delete_problem():
    cur = STORE["problems"][_cur()]
    if cur.get("locked"):
        ui.notify(f"「{cur.get('name', '课本例题')}」是公共参照题，不可删除", type="warning",
                  position="bottom-right", timeout=2400)
        return
    if len(STORE["problems"]) <= 1:
        ui.notify("至少保留一道题目", type="warning", position="bottom-right",
                  timeout=2000)
        return
    idx = _cur()
    name = STORE["problems"][idx].get("name", f"题目{idx + 1}")
    with ui.dialog() as dlg, ui.card().classes("w-96 q-pa-lg"):
        ui.label("删除题目").classes("font-bold text-negative")
        ui.label(f"将删除「{name}」及其全部输入，删除后不可恢复。").classes("text-sm")
        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("取消", on_click=dlg.close).props("flat")
            ui.button("确认删除",
                      on_click=lambda: (_do_delete(), dlg.close())
                      ).props("color=negative")
    dlg.open()


def _do_delete():
    idx = _cur()
    STORE["problems"].pop(idx)
    _set_cur(min(idx, len(STORE["problems"]) - 1))
    STORE["current"] = _cur()
    saved = _write_store()
    load_current_problem()
    refresh_problem_bar()
    _scroll_top()
    if saved:
        toast("已删除当前题目")


def rename_problem():
    idx = _cur()
    with ui.dialog() as dlg, ui.card().classes("w-96 q-pa-lg"):
        ui.label("编辑题目").classes("font-bold")
        name_in = ui.input("题目名称",
                           value=STORE["problems"][idx].get("name", "")
                           ).props("maxlength=16")
        kind_t = ui.toggle({"设计": "设计题", "复核": "复核题"},
                           value=STORE["problems"][idx].get("kind") or "设计"
                           ).props("no-caps rounded")
        err_l = ui.label("").style("color:#b71c1c;font-size:12px;min-height:16px")

        def _do_rename():
            nm = (name_in.value or "").strip()
            if not nm:
                err_l.set_text("题目名称不能为空")
                return
            if _name_taken(nm, exclude=idx):
                err_l.set_text(f"已有同名题目「{nm}」")
                return
            STORE["problems"][idx]["name"] = nm
            STORE["problems"][idx]["kind"] = kind_t.value   # 题型可在此修正
            saved = _write_store()
            refresh_problem_bar()
            if saved:
                toast("已保存")
            dlg.close()

        name_in.on("keydown.enter", lambda: _do_rename())

        with ui.row().classes("w-full justify-end gap-2 mt-3"):
            ui.button("取消", on_click=dlg.close).props("flat")
            ui.button("保存", on_click=_do_rename).props("color=primary")
    dlg.open()


def _snapshot_defaults():
    """记录各页输入控件的初始值，供一键重置（只取有 value 属性的控件）。

    同时记录哪些键是数字输入——“空白模板”要把数值全部置空，
    下拉/开关/页签类保留结构默认（必须有值，谈不上空）。
    """
    for pool, numkeys, src in ((D_DEFAULTS, D_NUMKEYS, D),
                               (V_DEFAULTS, V_NUMKEYS, V)):
        pool.update({k: w.value for k, w in src.items() if hasattr(w, "value")})
        numkeys.clear()
        numkeys.update(k for k, w in src.items() if isinstance(w, ui.number))


def _apply_defaults(pool, refs, sync, calc):
    for k, v in pool.items():
        w = refs.get(k)
        if w is not None and hasattr(w, "value"):
            try:
                w.value = v
            except Exception:
                pass
    sync()
    calc()


def reset_design():
    D["_loading"] = True             # 载入过程中的 calc 不清除选中态
    D["_preset"] = "reset"           # 先记选中态（calc 内的持久化即写入该值）
    _apply_defaults(D_DEFAULTS, D, sync_design, calc_design)
    D["_loading"] = False
    D["picked_id"] = None
    _sync_preset_row(D, _DESIGN_PRESETS)
    _anim_play(D["res"])
    toast("已重置为默认值")


def reset_verify():
    V["_loading"] = True             # 同设计页：载入过程中的 calc 不清除选中态
    V["_preset"] = "reset"
    _apply_defaults(V_DEFAULTS, V, sync_verify, calc_verify)
    V["_loading"] = False
    _sync_preset_row(V, _VERIFY_PRESETS)
    _anim_play(V["res"])
    toast("已重置为默认值")


def preset_design(key):
    D["_loading"] = True             # 载入过程中的 calc 不清除选中态
    D["_preset"] = key               # 先记选中态（calc 内的持久化即写入该值）
    _apply_values(D_DEFAULTS, D)      # 先回出厂默认（约束/100年开关等不残留），再叠加例题参数
    if key == "3-1":
        D["member"].value = "梁"
        D["Msrc"].value = "load"
        D["ln"].value, D["a"].value = 3.60, 0.40
        D["l0src"].value = "calc"
        D["gk"].value, D["qk"].value = 2.0, 1.20
        D["Gk"].value, D["Qk"].value = 5.25, 40.0
        D["q_kind"].value, D["Q_kind"].value = "general", "controllable"
        D["level"].value, D["situation"].value = "III", "持久"
        D["b"].value, D["h"].value = 200, 400
        D["layers"].value = "1"
        D["dia_est"].value = 20
        D["stirrup"].value = 10
        D["conc"].value, D["steel"].value, D["env"].value = "C25", "HRB400", "二"
    elif key == "3-2":
        D["member"].value = "板"
        D["Msrc"].value = "load"
        D["ln"].value, D["a"].value = 2.70, 0.15
        D["l0src"].value = "calc"
        D["gk"].value, D["qk"].value = 2.50, 3.0
        D["Gk"].value, D["Qk"].value = 0, 0
        D["q_kind"].value = "general"
        D["level"].value, D["situation"].value = "III", "持久"
        D["b"].value, D["h"].value = 1000, 100
        D["layers"].value = "1"
        D["dia_est"].value = 10
        D["conc"].value, D["steel"].value, D["env"].value = "C25", "HPB300", "二"
    elif key == "3-3":
        D["member"].value = "梁"
        D["Msrc"].value = "direct"
        D["M"].value = 212.60
        D["b"].value, D["h"].value = 250, 500
        D["layers"].value = "2"
        D["stirrup"].value = 10
        D["conc"].value, D["steel"].value, D["env"].value = "C30", "HRB400", "二"
    elif key in ("3-5", "3-6", "3-7"):
        # 双筋设计三连（教材 p90~92）：截面/材料/弯矩同题，差别在受压筋
        D["member"].value = "梁"
        D["Msrc"].value = "moments"          # M = γ0·ψ(MG+MQ) = 1.0×1.0×(100.0+135.0)
        D["MG"].value, D["MQ"].value = 100.0, 135.0
        D["level"].value = "II"              # γ0 = 1.0
        D["situation"].value = "持久"        # ψ = 1.0
        D["b"].value, D["h"].value = 250, 500
        D["layers"].value = "2"
        D["stirrup"].value = 10
        D["conc"].value, D["steel"].value, D["env"].value = "C30", "HRB400", "二"
        D["asp"].value = 55
        if key == "3-5":
            D["dbl"].value = "unknown"          # A′s 未知 → 式(3-29)(3-30)
        else:
            D["dbl"].value = "known"            # A′s 已知 → 式(3-31) 起
            D["Asp_src"].value = "count"
            if key == "3-6":
                D["dia_p"].value, D["n_p"].value = 18, 2   # 2Φ18 = 509
            else:
                D["dia_p"].value, D["n_p"].value = 22, 3   # 3Φ22 = 1140
    sync_design()
    calc_design()
    D["_loading"] = False
    _sync_preset_row(D, _DESIGN_PRESETS)
    _anim_play(D["res"])
    toast({"3-1": "已载入例3-1 启闭机支承梁", "3-2": "已载入例3-2 坝顶人行道板",
           "3-3": "已载入例3-3 泵房简支梁（当前 h=500，超筋演示）",
           "3-5": "已载入例3-5 双筋梁（A′s 待求）",
           "3-6": "已载入例3-6 双筋梁（已配 2Φ18，x≥2a′s）",
           "3-7": "已载入例3-7 双筋梁（已配 3Φ22，x<2a′s）"}[key])
    scroll_to_result()


# ---------------------------------------------------------------- 复核页

def on_verify_member_change(e):
    """复核页切换构件类型时，As 输入方式自动切到匹配模式（板→间距，梁→根数）。"""
    if e.value == "板" and V["Asrc"].value == "count":
        V["Asrc"].value = "spacing"
    elif e.value == "梁" and V["Asrc"].value == "spacing":
        V["Asrc"].value = "count"
    sync_verify()
    calc_verify()
    _anim_play(V["res"])


def build_verify_tab():
    with ui.tab_panel("复核"):
        V["live"] = ui.html("", **HTML_KW).classes("nz-live-bar print-hide")
        V["exrow"] = ui.row().classes("w-full items-center gap-2 mb-1 print-hide")
        with V["exrow"]:
            ui.html("《水工钢筋混凝土结构学》例题一键载入：", **HTML_KW).classes("text-sm text-gray-500")
            V["preset_row"] = ui.row().classes("gap-1")
            with V["preset_row"]:      # 选中态同设计页：点击后重建为实心主色
                for _key, _label, _fn in _VERIFY_PRESETS:
                    ui.button(_label, on_click=_fn).props("outline dense no-caps rounded")
        _vcols = _dual_columns()
        card_1 = ui.card().classes(CARD)
        with card_1:
            card_title("① 已知钢筋、截面与材料", "fact_check")
            with ui.row().classes("w-full items-end gap-6"):
                V["member"] = ui.toggle({"梁": "梁", "板": "板"}, value="板",
                                        on_change=on_verify_member_change).props("no-caps rounded")
                V["Asrc"] = ui.toggle({"direct": "直接输入 As", "spacing": "直径@间距(板)",
                                       "count": "直径×根数(梁)"}, value="spacing",
                                      on_change=_anim_then(V, 'res', sync_verify, calc_verify)).props("no-caps rounded")
            with ui.row().classes("w-full items-end gap-4"):
                V["As"] = num_f("受拉钢筋面积 A<sub>s</sub>", suffix="mm²", value=419, min=0, step=1,
                                on_change=calc_verify)
                V["dia_s"] = sel_f("钢筋直径", {d: f"Φ{d}" for d in BAR_DIAS},
                                   value=8, on_change=calc_verify, cls="w-32")
                V["spacing"] = sel_f("间距", {s: f"@{s}" for s in SLAB_SPACINGS},
                                     value=120, on_change=calc_verify, cls="w-32")
                V["dia_c"] = sel_f("钢筋直径", {d: f"Φ{d}" for d in BAR_DIAS},
                                   value=16, on_change=calc_verify, cls="w-32")
                V["n"] = num_f("根数 n", value=3, min=1, step=1, on_change=calc_verify)
            with ui.row().classes("w-full items-end gap-4"):
                V["b"] = num_f("梁宽/板计算宽 b", suffix="mm", value=1000, min=1, step=10,
                               on_change=calc_verify, validation=_pos_rule())
                V["h"] = num_f("截面高 h", suffix="mm", value=120, min=1, step=10,
                               on_change=calc_verify, validation=_pos_rule())
                V["as"] = num_f("受拉钢筋 a<sub>s</sub>", suffix="mm", value=29, min=1,
                                step=1, on_change=calc_verify,
                                validation=_as_lt_h_rule())
            # 受压钢筋（双筋复核，可选；双筋仅梁适用——板时整行隐藏+提示）
            with ui.row().classes("w-full items-end gap-4") as V["dbl_row"]:
                V["dbl"] = ui.toggle({"none": "单筋（无受压筋）", "count": "双筋·直径×根数",
                                      "direct": "双筋·直接输入 A′s"}, value="none",
                                     on_change=_anim_then(V, 'res', sync_verify, calc_verify)
                                     ).props("no-caps rounded")
                V["asp"] = num_f("受压钢筋 a′<sub>s</sub>", suffix="mm", value=49, min=1,
                                 step=1, on_change=calc_verify,
                                 validation=_asp_rule(_h0_verify))
            with ui.row().classes("w-full items-end gap-4") as V["asp_row"]:
                V["dia_p"] = sel_f("受压筋直径", {d: f"Φ{d}" for d in BAR_DIAS},
                                   value=18, on_change=calc_verify, cls="w-32")
                V["n_p"] = num_f("受压筋根数 n′", value=3, min=1, step=1,
                                 on_change=calc_verify)
                V["Asp"] = num_f("受压钢筋面积 A′<sub>s</sub>", suffix="mm²", value=763,
                                 min=0, step=1, on_change=calc_verify)
            V["dbl_hint"] = ui.html(
                '<span style="color:#78909c;font-size:12px;line-height:1.6;">'
                '双筋截面仅适用于梁（教材3.5.2）：板受压区不足时应加厚板或提高混凝土强度等级；'
                '连续板支座负筋属另一类问题（本工具按简支单跨正截面计算）。</span>', **HTML_KW)
            ui.separator().classes("my-1")
            ui.separator().classes("my-1")
            with ui.row().classes("w-full items-end gap-4"):
                _material_selects(V, calc_verify)
            with ui.row().classes("w-full items-center gap-4"):
                with ui.column().classes("gap-0 items-center"):
                    ui.html("已知钢筋截面图", **HTML_KW).classes("text-sm font-bold")
                    V["fig"] = ui.html("", **HTML_KW)
        card_2 = ui.card().classes(CARD)
        with card_2:
            card_title("② 弯矩设计值 M", "calculate")
            V["Msrc"] = ui.toggle({"direct": "直接输入 M", "moments": "由弯矩标准值算 M",
                                   "load": "由荷载算 M"},
                                  value="direct",
                                  on_change=_anim_then(V, 'res', sync_verify, calc_verify)).props("no-caps rounded")
            make_load_block(V, lambda e: (sync_verify(), calc_verify()))
            with ui.row().classes("w-full items-end gap-4") as V["M_row"]:
                V["M"] = num_f("弯矩设计值 M（含 γ<sub>0</sub>·ψ）", suffix="kN·m", value=8.22,
                               min=0, step=0.01, on_change=calc_verify)
        card_r = ui.card().classes(CARD + " result-anchor")
        V["card_r"] = card_r
        with card_r:
            card_title("复核过程与结果", "verified")
            with ui.row().classes("w-full justify-end"):
                ui.button("📋 复制计算书", on_click=copy_report_verify).props(
                    "outline dense no-caps rounded")
                ui.button("⬇ 下载计算书", on_click=download_report_verify).props(
                    "outline dense no-caps rounded")
            V["toc"] = ui.html("", **HTML_KW).classes("toc-row print-hide")
            # 设计参数变更 → 复核结果过期提示（带"重新带入"动作）
            V["stale_bar"] = ui.row().classes("w-full items-center gap-2").style(
                "background:#fff8e1;border:1px solid #ffe082;border-radius:8px;padding:6px 10px")
            with V["stale_bar"]:
                ui.html('<span style="color:#795548;font-size:13.5px">'
                        '⚠ 设计参数在带入复核后已变更，本页结果基于旧参数。</span>', **HTML_KW)
                ui.button("按当前设计重新带入",
                          on_click=lambda: _transfer_to_verify(D.get("picked_row"))).props(
                    "dense unelevated no-caps rounded color=warning")
            V["stale_bar"].set_visibility(False)
            V["kpi"] = ui.html("", **HTML_KW)
            V["info"] = ui.html("", **HTML_KW).style("color:#37474f")
            ui.separator()
            V["res"] = ui.html("", **HTML_KW).style("font-size:15px")
            ui.separator()
            V["verdict"] = ui.html("", **HTML_KW).classes("text-base font-bold")
            # 复核不安全的一键采用（文案由 _paint_verify 按反解值设置；与设计页 adopt 对称）
            V["adopt"] = ui.button("", on_click=adopt_suggested_h_verify).props(
                "outline dense no-caps rounded color=warning")
            V["adopt"].set_visibility(False)
            V["rho_wrap"] = ui.column().classes("w-full gap-1")
            with V["rho_wrap"]:
                V["rho_bar"] = ui.linear_progress(value=0, show_value=False).props("rounded")
                V["rho_scale"] = ui.html("", **HTML_KW).classes("text-xs text-gray-500")
            V["err"] = ui.label("").style("color:#b71c1c;white-space:pre-wrap")
            V["jump"] = ui.button(
                "", on_click=lambda: ui.run_javascript("nzFocusNextEmpty()")
                ).props("outline dense no-caps rounded")
            V["jump"].set_visibility(False)
        # 状态/提示/"还需填写"上移到结果区顶部（同设计页）
        _vkids = list(card_r.default_slot.children)
        _vat = _vkids.index(V["info"])
        V["verdict"].move(card_r, _vat)
        V["adopt"].move(card_r, _vat + 1)
        V["err"].move(card_r, _vat + 2)
        V["jump"].move(card_r, _vat + 3)
        # 宽屏双栏归位（同设计页）
        for _c in (card_1, card_2):
            _c.move(_vcols[1])
        card_r.move(_vcols[2])


def sync_verify():
    mode = V["Asrc"].value
    is_beam = V["member"].value == "梁"
    if not is_beam and V["dbl"].value != "none":
        V["dbl"].set_value("none")            # 双筋仅梁：板归位单筋（连锁一次 calc，不再递归）
        if not (V.get("_loading") or _state().get("_mid_load")):
            toast("板不适用双筋截面（教材3.5.2），已切换为单筋")
    V["dbl_row"].set_visibility(is_beam)
    V["asp_row"].set_visibility(is_beam)
    V["dbl_hint"].set_visibility(not is_beam)
    set_field_visible(V["As"], mode == "direct")
    set_field_visible(V["dia_s"], mode == "spacing")
    set_field_visible(V["spacing"], mode == "spacing")
    set_field_visible(V["dia_c"], mode == "count")
    set_field_visible(V["n"], mode == "count")
    dmode = V["dbl"].value
    set_field_visible(V["dia_p"], dmode == "count")
    set_field_visible(V["n_p"], dmode == "count")
    set_field_visible(V["Asp"], dmode == "direct")
    set_field_visible(V["asp"], dmode != "none")
    V["M_row"].set_visibility(V["Msrc"].value == "direct")
    sync_load_block(V, V["Msrc"].value)


def _collect_verify():
    return {
        "_empty": sorted(k for k in (V_NUMKEYS | set(_COEF_KEYS))
                         if getattr(V.get(k), "value", None) is None),
        "member": V["member"].value, "b": _num(V["b"]), "h": _num(V["h"]),
        "as_": _num(V["as"]),
        "Asrc": V["Asrc"].value, "As": _num(V["As"]),
        "dia_s": V["dia_s"].value, "spacing": V["spacing"].value,
        "dia_c": V["dia_c"].value, "n": _num(V["n"], 0),
        "dbl": V["dbl"].value, "Asp": _num(V["Asp"]),
        "dia_p": V["dia_p"].value, "n_p": _num(V["n_p"], 0), "asp_": _num(V["asp"]),
        "conc": V["conc"].value, "steel": V["steel"].value,
        "m_mode": V["Msrc"].value, "M_kNm": _num(V["M"]),
        "load": _collect_load(V),
    }


def calc_verify(*_):
    if _state().get("_mid_load"):
        return                                # 载入批量赋值期间的连锁 calc 全跳过（尾部有显式总算）
    if not V.get("_loading") and V.get("_preset"):
        _set_preset(V, None, _VERIFY_PRESETS)   # 手动改了输入 → 已不是原例题
    if not V.get("_prog") and not V.get("_loading"):
        V["_derived"] = False                   # 手动编辑复核输入 → 用户接管，不再标过期
    V["as"].validate()                        # 跨字段规则刷新（h 变化影响 as<h）
    V["asp"].validate()                       # （h/as 变化影响 a′s<h0）
    _sync_jump(V, V_NUMKEYS)                  # "还需填写 N 项"计数随显隐/填值更新
    try:
        V["err"].set_text("")
        res = pipeline.solve_verify(_collect_verify())
    except (ValueError, KeyError) as e:
        V["res"].set_content("")
        clear_verdict(V["verdict"])
        V["adopt"].set_visibility(False)
        V["_res"] = None
        V["live"].set_content("")
        V["info"].set_content("")
        V["kpi"].set_visibility(False)
        V["rho_wrap"].set_visibility(False)
        V["fig"].set_content("")
        V["_vred"] = False
        _refresh_toc(V.get("card_r"), V.get("toc"))
        if not _num(V["b"]) and not _num(V["h"]) and not _num(V["as"]):
            # 空白模板进场：中性"待填写"提示，不算错误
            V["err"].set_text("· 请在左侧填写钢筋、截面与弯矩参数，输入后自动计算")
            V["err"].style("color:#78909c")
        else:
            V["err"].set_text(f"⚠ {e}")
            V["err"].style("color:#b71c1c")
            if not (D.get("_loading") or V.get("_loading")
                    or V.get("_prog") or _state().get("_mid_load")):
                notify_error_once(str(e))
        save_problems()
        return
    _state()["_err"] = None
    _paint_verify(res)
    save_problems()


def _paint_verify(res):
    v = res["values"]
    V["_res"] = res                           # 供一键改 h（h_hint）等后续动作读取
    V["info"].set_content(res["info_html"])
    _kpi = res["kpi_html"]
    _flash = _kpi != V.get("_kpi_html")
    V["_kpi_html"] = _kpi
    V["kpi"].set_content(_kpi)
    V["kpi"].set_visibility(True)
    if _flash:
        _anim_play(V["kpi"], "anim-flash", 600)
    V["As_cache"] = v["As"]
    draw_verify_fig()
    V["l0_cache"] = res["m_meta"].get("l0")
    _sig = _chain_sig(res["res_html"])
    _chain_new = _sig != V.get("_chain_sig")
    V["_chain_sig"] = _sig
    V["res"].set_content(res["res_html"])
    if _chain_new:
        _anim_play(V["res"])
    _vtxt = res["verdict"]["html"]
    vad = _vtxt != V.get("_verdict_html")
    V["_verdict_html"] = _vtxt
    verdict_banner(V["verdict"], res["verdict"]["ok"], _vtxt, animate=vad)
    # 一键改 h：仅单筋不安全且有反解值时出现（双筋不适用——设计页同规则）
    _hh = res.get("h_hint")
    if _hh and _hh.get("h"):
        V["adopt"].set_text(f"↩ 将 h 改为 {_hh['h']:g}mm 并重算")
        V["adopt"].set_visibility(True)
    else:
        V["adopt"].set_visibility(False)
    # 窄屏实时摘要条
    _lv_kpis = [f"As = {fmt(v['As'], 0)} mm²"]
    if v["M"] is not None:
        _lv_kpis.append(f"M′ = {fmt(res['r']['M_allowed'] / 1e6, 1)} ≥ M = "
                        f"{fmt(v['M'] / 1e6, 1)} kN·m")
    _lv_kpis.append(f"ρ = {res['r']['rho'] * 100:.2f}%")
    V["live"].set_content(_live_bar_html(res["verdict"]["ok"],
                                         "承载力满足" if res["verdict"]["ok"] else "承载力不足",
                                         _lv_kpis))
    update_stale_bar()
    ru = res.get("rho_ui")
    if ru:
        V["rho_bar"].set_value(ru["value"])
        V["rho_bar"].props(f"color={ru['color']} rounded")
        V["rho_scale"].set_content(ru["scale_html"])
        V["rho_wrap"].set_visibility(True)
    else:
        V["rho_wrap"].set_visibility(False)
    _vred = (v["M"] is not None and not res["verdict"]["ok"])
    if _vred and not V.get("_vred"):
        scroll_to_result()
    V["_vred"] = _vred
    _refresh_toc(V.get("card_r"), V.get("toc"))


def copy_report_verify():
    try:
        res = pipeline.solve_verify(_collect_verify())
        ui.clipboard.write(res["report"])
        toast("计算书已复制，可直接粘贴到 Word/记事本")
    except (ValueError, KeyError) as e:
        notify_error_once(str(e))


def _download_report(res):
    """计算书下载为 .txt（data URL 方式，浏览器/桌面模式/打包 exe 均可用）。"""
    name = STORE["problems"][_cur()].get("name", "题目") if STORE["problems"] else "题目"
    name = name.replace('"', "").replace("/", "_").replace("\\", "_")
    data = urllib.parse.quote(res["report"])
    ui.run_javascript(
        'const a=document.createElement("a");'
        f'a.href="data:text/plain;charset=utf-8,{data}";'
        f'a.download="{name}-计算书.txt";'
        'document.body.appendChild(a);a.click();a.remove();')


def download_report_design():
    if D.get("_res") is None:                 # 分段/出错态：别下载半截计算书
        _not_done_toast(D)
        return
    try:
        _download_report(pipeline.solve_design(_collect_design()))
    except (ValueError, KeyError) as e:
        notify_error_once(str(e))


def download_report_verify():
    if V.get("_res") is None:
        _not_done_toast(V)
        return
    try:
        _download_report(pipeline.solve_verify(_collect_verify()))
    except (ValueError, KeyError) as e:
        notify_error_once(str(e))


def preset_verify_38():
    """例3-8：已建简支矩形梁（双筋）复核，教材p92~93 参数与结果一体带入。"""
    V["_loading"] = True
    V["_preset"] = "3-8"
    _apply_values(V_DEFAULTS, V)      # 先回默认再叠加例3-8 参数（同设计页做法）
    V["member"].value = "梁"
    V["Asrc"].value = "count"
    V["dia_c"].value, V["n"].value = 20, 6
    V["b"].value, V["h"].value, V["as"].value = 250, 600, 75
    V["dbl"].value = "count"
    V["dia_p"].value, V["n_p"].value, V["asp"].value = 18, 3, 49
    V["conc"].value, V["steel"].value = "C30", "HRB400"
    V["Msrc"].value = "load"
    V["gk"].value, V["qk"].value = 12.0, 0.0
    V["Gk"].value, V["Qk"].value = 0.0, 80.0
    V["q_kind"].value, V["Q_kind"].value = "general", "general"   # γQ = 1.30
    V["level"].value, V["situation"].value = "I", "持久"           # γ0 = 1.1，ψ = 1.0
    V["l0src"].value, V["l0"].value = "direct", 6.5
    sync_verify()
    calc_verify()
    V["_loading"] = False
    _sync_preset_row(V, _VERIFY_PRESETS)
    _anim_play(V["res"])
    toast("已载入例3-8 已建简支矩形梁（双筋）复核")
    scroll_to_result()


def preset_verify():
    V["_loading"] = True
    V["_preset"] = "3-4"
    _apply_values(V_DEFAULTS, V)      # 同设计页：先回默认再叠加例3-4 参数
    V["member"].value = "板"
    V["Asrc"].value = "spacing"
    V["dia_s"].value, V["spacing"].value = 8, 120
    V["b"].value, V["h"].value, V["as"].value = 1000, 120, 29
    V["conc"].value, V["steel"].value = "C25", "HPB300"
    V["Msrc"].value = "direct"
    V["M"].value = 8.22
    sync_verify()
    calc_verify()
    V["_loading"] = False
    _sync_preset_row(V, _VERIFY_PRESETS)
    _anim_play(V["res"])
    toast("已载入例3-4 已建简支板复核")
    scroll_to_result()


# ---------------------------------------------------------------- 数据查询页

def build_data_tab():
    with ui.tab_panel("数据"):
        ui.label("以下数据取自《水工钢筋混凝土结构学》附录B/C/D（NB/T 11011-2022），"
                 "每条均可溯源（见数据文件 source 字段）。").classes("text-gray-500")
        conc_rows = [{"等级": g, "fc (N/mm²)": fmt(spec_data.concrete_fc(g)),
                      "ft (N/mm²)": fmt(spec_data.concrete_ft(g)),
                      "Ec (×10⁴)": fmt(spec_data.concrete_Ec(g))}
                     for g in CONC_GRADES]
        _card_table("混凝土强度设计值与弹性模量（附录B 表B-1/B-2）",
                    ["等级", "fc (N/mm²)", "ft (N/mm²)", "Ec (×10⁴)"], conc_rows, icon="layers",
                    right=("fc (N/mm²)", "ft (N/mm²)", "Ec (×10⁴)"), key="B1")
        steel_rows = [{"钢筋": s, "fy (N/mm²)": fmt(spec_data.steel_fy(s)),
                       "Es (N/mm²)": f"{spec_data.steel_Es(s) / 1e5:g}×10⁵",
                       "ξb": fmt(spec_data.xi_b(s))}
                      for s in STEELS]
        _card_table("普通钢筋强度设计值、弹性模量与 ξb（表B-3/B-5、表3-1）",
                    ["钢筋", "fy (N/mm²)", "Es (N/mm²)", "ξb"], steel_rows, icon="linear_scale",
                    right=("fy (N/mm²)", "Es (N/mm²)", "ξb"), key="B3")
        members = ("梁", "板")
        rho_rows = [{"构件": m, **{s: fmt(spec_data.rho_min(s, m) * 100) + "%" for s in STEELS}}
                    for m in members]
        _card_table("受弯构件最小配筋率 ρ<sub>min</sub>（附录D 表D-4 = 规范表10.5.1）",
                    ["构件", *STEELS], rho_rows, icon="fact_check", right=tuple(STEELS), key="D4")
        cover_rows = [{"环境": f"{k}类", "板 (mm)": spec_data.cover_min(k, "板"),
                       "梁 (mm)": spec_data.cover_min(k, "梁"), "环境条件": v}
                      for k, v in ENV_CLASSES.items()]
        bar_rows = [{"直径": f"Φ{d}", "单根 (mm²)": fmt(spec_data.bar_area(d)),
                     "2根": fmt(spec_data.bar_area_n(d, 2)),
                     "3根": fmt(spec_data.bar_area_n(d, 3)),
                     "6根": fmt(spec_data.bar_area_n(d, 6))} for d in BAR_DIAS]
        _card_table("钢筋公称截面面积 A<sub>s</sub>（附录C 表C-1；多根列＝教材手算查表口径）",
                    ["直径", "单根 (mm²)", "2根", "3根", "6根"], bar_rows, icon="straighten",
                    right=("单根 (mm²)", "2根", "3根", "6根"), key="C1")
        # 表C-2 只有单列 26 个数：套 q-table 会拉满全宽、中间大片空白（1384px 高），
        # 改为芯片阵列紧凑呈现；nz-tbl-C2 锚点保留（计算过程里的"表C-2"引用仍可跳转）
        with ui.card().classes(CARD):
            ui.html('<div id="nz-tbl-C2" style="position:relative;top:-8px"></div>')
            with ui.row().classes("items-center gap-1"):
                ui.icon("format_line_spacing").classes("text-primary text-lg")
                ui.html("板受力钢筋间距系列（附录C 表C-2）", **HTML_KW).classes("font-bold")
            _sp_chips = "".join(
                f'<span style="border:1px solid #dce5ec;border-radius:6px;padding:4px 12px;'
                f'font-size:13.5px;color:#37474f;background:#f8fafc;">{sp}</span>'
                for sp in SLAB_SPACINGS)
            ui.html(f'<div style="display:flex;flex-wrap:wrap;gap:8px;">{_sp_chips}</div>',
                    **HTML_KW)
        _card_table("保护层最小厚度 c 与环境类别（附录D 表D-1、规范表3.1.11）",
                    ["环境", "板 (mm)", "梁 (mm)", "环境条件"], cover_rows, icon="security",
                    right=("板 (mm)", "梁 (mm)"), key="D1")
        gamma_rows = [
            {"系数": "γ0（结构重要性）", "取值": "I级1.1 / II级1.0 / III级0.9", "出处": "表2-4"},
            {"系数": "ψ（设计状况）", "取值": "持久1.0 / 短暂0.95 / 偶然0.85", "出处": "规范3.2.3"},
            {"系数": "γG（永久荷载）", "取值": "1.10", "出处": "表2-5"},
            {"系数": "γQ（一般可变）", "取值": "1.30", "出处": "表2-6"},
            {"系数": "γQ（可控制可变）", "取值": "1.20", "出处": "表2-6"},
            {"系数": "γd（结构系数）", "取值": "1.20（永久作用为主时+0.05）", "出处": "表2-7"},
        ]
        _card_table("分项系数与结构系数（第2章）", ["系数", "取值", "出处"], gamma_rows, icon="tune", key="G")
        with ui.card().classes("w-full"):
            ui.label("构造与计算提示").classes("font-bold")
            for key in ("cover", "rho_min", "gamma_d", "xi_b", "steel_fyv"):
                txts = spec_data.note(key)
                if isinstance(txts, str):
                    txts = [txts]
                for t in txts:
                    ui.label("· " + t).style("color:#455a64")
        # 版本标识：exe 发给同学后，从这里一眼确认手里是哪一版
        ui.label(f"程序构建：{APP_BUILD} ｜ 规范：NB/T 11011-2022 ｜ "
                 f"数据文件 kernel/data/spec_NB_T_11011-2022.json"
                 ).classes("text-xs text-gray-400 mt-1")


def _card_table(title, columns, rows, icon=None, right=(), key=None):
    with ui.card().classes(CARD):
        if key:                               # 供"查表跳转"定位（计算过程里的表号可点）
            ui.html(f'<div id="nz-tbl-{key}" style="position:relative;top:-8px"></div>')
        with ui.row().classes("items-center gap-1"):
            if icon:
                ui.icon(icon).classes("text-primary text-lg")
            ui.html(title, **HTML_KW).classes("font-bold")
        cols = [{"name": c, "label": c, "field": c,
                 **({"align": "right"} if c in right else {})} for c in columns]
        ui.table(columns=cols, rows=rows, row_key=columns[0]).props(
            "flat bordered hide-pagination rows-per-page=0").classes("w-full")


# ---------------------------------------------------------------- 组装

def update_stale_bar():
    """复核页过期提示条：仅当复核上下文派生自设计且设计参数已变更时显示。"""
    bar = V.get("stale_bar")
    if bar:
        bar.set_visibility(bool(V.get("_derived") and V.get("_stale")))


def _tab_changed(e):
    if e.value == "复核":
        update_stale_bar()
    back = _state().get("_back")
    if back and back[0] == e.value:            # 从"数据"页切回来源页签 → 还原跳转前位置
        _state()["_back"] = None
        ui.run_javascript(f"nzScrollTo({back[1]})")


def build_ui():
    ui.dark_mode(False)
    ui.query("body").style("background:#eef2f7")
    ui.add_head_html("""<style>
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:#b3c2ce;border-radius:5px}
::-webkit-scrollbar-thumb:hover{background:#90a4ae}
/* 数字输入框：隐藏原生上下步进箭头（外观），滚轮误改值由下面的 wheel 守卫根治 */
input[type=number]::-webkit-outer-spin-button,
input[type=number]::-webkit-inner-spin-button{-webkit-appearance:none;margin:0}
input[type=number]{appearance:textfield;-moz-appearance:textfield}
/* Quasar 页面板容器自带 overflow（hidden/auto）——会让页面内所有 position:sticky
   （左输入栏 / 结果 TOC / 顶栏）静默失效；放开为 visible（NiceGUI 同一时刻只挂一个面板，不会串面板） */
/* 面板容器放开 overflow 是为了面板内 sticky（顶栏/TOC）不被静默废掉；但 visible 会让
   快速连点页签时卡在 ±100% 过渡半路的旧面板直接摊在页面上（实测整页被撑到 sw 685/2444）。
   overflow-x:clip 同样裁掉横向溢出，却不产生滚动容器——sticky 依旧认 viewport（clip 与
   hidden 的本质区别），纵向吸顶不受影响 */
.q-tab-panels,.q-tab-panels .q-panel.scroll{overflow-x:clip;overflow-y:visible}
/* 顶栏吸顶（题号条 + 页签）；--nz-header/--nz-stack 由客户端 nzTopStack() 实测写入 */
.nz-sticky-top{position:sticky;top:var(--nz-header,76px);z-index:8;background:#eef2f7;
padding-top:2px;border-bottom:1px solid #dbe3ea;margin-bottom:6px}
/* 题号条/操作按钮不压缩：题目多时条内横向滚动，按钮保持原宽 */
.nz-sticky-top .q-btn{flex:0 0 auto;white-space:nowrap}
/* 宽屏双栏：左输入（sticky）右结果；窄屏单栏（NiceGUI 预编译 Tailwind 不含响应式变体，用自定义类） */
.dual-row{display:flex;flex-direction:column;gap:16px;width:100%}
.dual-side{width:100%}
.dual-main{width:100%}
@media (min-width:1024px){
.dual-row{flex-direction:row;align-items:flex-start;flex-wrap:nowrap}
.dual-side{flex:0 0 400px;width:auto;min-width:0;overflow-x:hidden;position:sticky;top:var(--nz-stack,180px);max-height:calc(100vh - var(--nz-stack,180px) - 20px);overflow-y:auto;padding-right:4px}
.dual-side::after{content:'';position:sticky;bottom:0;flex:0 0 18px;height:18px;margin-top:-18px;
background:linear-gradient(180deg,rgba(238,242,247,0),#eef2f7);pointer-events:none}
.dual-main{flex:1 1 auto;width:auto;min-width:0}}
/* 打印：隐藏交互件，结果卡排成报告（浏览器 Ctrl+P 直出计算书 PDF） */
@media print{
header,.nicegui-tabs,.q-btn,.print-hide{display:none!important}
*{animation:none!important;transition:none!important}
body{background:#fff!important;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.result-anchor{border:none!important;box-shadow:none!important}
.dual-row{display:block!important}
.q-tab-panel{padding:0!important}}
@page{margin:12mm}

/* ---- 动效（mac 风格弹簧语言）：全部 ≤400ms；页头右侧「动效」按钮可整体关闭 ---- */
:root{--spring:cubic-bezier(0.16,1,0.3,1);--spring-snap:cubic-bezier(0.23,1,0.32,1)}
@supports (animation-timing-function: linear(0,1)){
:root{--spring:linear(0,.5 18%,.86 42%,1.01 62%,1);--spring-snap:linear(0,.62 22%,1.02 55%,1)}}
@keyframes nzLine{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
@keyframes nzFlash{from{background:#fff3cd}to{background:transparent}}
@keyframes nzBanner{from{opacity:0;transform:translateY(8px) scale(.985)}to{opacity:1;transform:none}}
/* 计算链逐行淡入：结构变化时播放；前 8 行错落，其余同步跟上（总时长封顶） */
.anim-chain > *{animation:nzLine .32s var(--spring) both}
.anim-chain > *:nth-child(1){animation-delay:0ms}
.anim-chain > *:nth-child(2){animation-delay:40ms}
.anim-chain > *:nth-child(3){animation-delay:80ms}
.anim-chain > *:nth-child(4){animation-delay:120ms}
.anim-chain > *:nth-child(5){animation-delay:160ms}
.anim-chain > *:nth-child(6){animation-delay:200ms}
.anim-chain > *:nth-child(7){animation-delay:240ms}
.anim-chain > *:nth-child(8){animation-delay:280ms}
.anim-chain > *:nth-child(n+9){animation-delay:320ms}
/* KPI 数值变化闪变（仅值变化时挂类） */
.anim-flash > *{animation:nzFlash .5s ease-out both}
/* 判定横幅入场 */
.anim-banner{animation:nzBanner .28s var(--spring) both}
/* 配筋图画出：轮廓/箍筋描边（pathLength=1）+ 钢筋点弹入 stagger */
@keyframes nzDraw{to{stroke-dashoffset:0}}
@keyframes nzPop{from{opacity:0;transform:scale(0)}to{opacity:1;transform:scale(1)}}
/* 配筋图"画出"动画：默认不播，需容器拿到 nz-play 才播（布防机制）——
   这样"点选筋行 → 先滚到图 → 到位后再布防"才能让动画在眼前播放，而不是在屏幕外播完 */
.nz-fig.nz-play svg .nz-draw{stroke-dasharray:1;stroke-dashoffset:1;animation:nzDraw .4s var(--spring) forwards}
.nz-fig.nz-play svg .nz-stirrup{animation-delay:.15s}
.nz-fig.nz-play svg .nz-dot{transform-box:fill-box;transform-origin:center;
animation:nzPop .2s var(--spring) both;
animation-delay:calc(min(var(--i, 0) * 40ms + .18s, .55s))}
/* 按钮按压反馈（mac 触感）＋ ρ 标尺 0.35s 弹簧（Quasar 默认 2.1s 偏慢） */
.q-btn{transition:transform .16s var(--spring-snap)}
.q-btn:active{transform:scale(.97)}
.q-linear-progress__model--with-transition{transition:transform .35s var(--spring-snap)!important}
/* 系统「减弱动效」→ 降级为 80ms 交叉淡入（Apple 口径） */
@media (prefers-reduced-motion: reduce){
*{animation-duration:.08s!important;animation-delay:0ms!important;transition-duration:.08s!important}}
/* 页头「动效」按钮关闭后全部停用（本地记忆） */
body.motion-off *{animation:none!important;transition:none!important}

/* ---- 结果区小节导航（TOC）：粘性横排 chip，scroll-spy 高亮当前节 ---- */
.toc-row{position:sticky;top:calc(var(--nz-stack,180px) + 4px);z-index:5;display:flex;flex-wrap:wrap;gap:4px;
padding:6px 8px;margin:4px 0 8px;background:rgba(255,255,255,.92);
border:1px solid #e3e8ee;border-radius:8px;backdrop-filter:blur(8px)}
.toc-chip{font-size:12px;line-height:1;padding:5px 9px;border-radius:999px;cursor:pointer;
color:#54707f;background:#f1f5f8;border:1px solid transparent;user-select:none;
transition:background .18s var(--spring-snap),color .18s var(--spring-snap)}
.toc-chip:hover{background:#e3edf4;color:#155e94}
.toc-chip.on{background:#155e94;color:#fff}
.toc-chip.err{color:#b71c1c;background:#fdecea}
.toc-chip.err.on{background:#b71c1c;color:#fff}
/* 窄屏（<1024px 单栏）实时摘要条：输入区滚动时判定/关键数钉在吸顶层下，
   点一下滚到结果卡；结果卡进入视野后由 JS 暂隐（nz-hide，避免压住 TOC）。
   宽屏双栏下结果常驻右列，整条由 CSS 隐藏；:empty 兜底未算出判定时不占位 */
.nz-live-bar{display:none}
@media (max-width:1023.9px){
.nz-live-bar{position:sticky;top:calc(var(--nz-stack,180px) - 2px);z-index:7;display:flex;
align-items:center;gap:8px;padding:7px 10px;margin:0 0 8px;background:rgba(255,255,255,.94);
backdrop-filter:blur(8px);border:1px solid #e3e8ee;border-radius:8px;cursor:pointer;
box-shadow:0 2px 10px rgba(21,94,148,.08)}
.nz-live-bar.nz-hide{display:none}}
.nz-live-bar:empty{display:none}
.nz-lv-flag{font-weight:700;font-size:12.5px;white-space:nowrap;padding:2px 9px;border-radius:999px}
.nz-lv-kpi{font-size:12.5px;color:#37474f;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* 计算过程里的表号引用：可点 → 跳到"数据"页对应表格 */
.nz-ref{cursor:pointer;color:#155e94;border-bottom:1px dotted rgba(21,94,148,.5)}
.nz-ref:hover{background:#e3edf4;border-bottom-style:solid}
/* 点 TOC 跳转：目标小节整段闪一下（识别性反馈，可重复触发；1.2s > 400ms 微交互上限，属"落点识别"）
   注意不要加 padding/margin —— 任何布局位移都会打断正在起跑的平滑滚动 */
@keyframes nzHit{0%{background:#fff3cd;box-shadow:inset 3px 0 0 #155e94}
60%{background:#fff8e1;box-shadow:inset 3px 0 0 #155e94}
100%{background:transparent;box-shadow:inset 3px 0 0 transparent}}
.nz-hit{animation:nzHit 1.2s var(--spring) both}
body.motion-off .nz-hit{animation:none;background:#fff3cd;box-shadow:inset 3px 0 0 #155e94}
/* KPI 指标悬停释义气泡：鼠标移上去才出现，零占位、不改动任何排版。
   默认必须 display:none——visibility:hidden 的绝对定位盒虽不显示，仍会扩进
   滚动溢出区（气泡 max-width 290px），窄屏下把整页撑出横向滚动（实测 +36~100px）。
   淡入因此改走 keyframes：display 翻转首次渲染时 animation 照常播，transition 不行 */
.nz-tip{position:relative;cursor:help}
.nz-tip>div:first-child{border-bottom:1px dotted rgba(120,144,156,.6)}
.nz-tip::after{content:attr(data-tip);position:absolute;left:var(--nz-tip-shift,0px);top:calc(100% + 6px);
width:max-content;max-width:290px;background:#37474f;color:#fff;font-size:12px;
font-weight:400;line-height:1.6;padding:7px 10px;border-radius:8px;text-align:left;
display:none;pointer-events:none;z-index:30;
box-shadow:0 6px 18px rgba(21,94,148,.18)}
@keyframes nzTipIn{from{opacity:0}to{opacity:1}}
.nz-tip:hover::after{display:block;animation:nzTipIn .15s ease both}
@media print{.nz-tip::after{display:none}}
/* 小节标题：点击定位时给页头留出空间 */
.nz-sec{scroll-margin-top:calc(var(--nz-stack,180px) + 52px)}
</style>""")
    ui.colors(primary="#155e94")
    with ui.header().classes("items-center justify-between bg-gradient-to-r from-[#0d4d79] to-[#1d7fb8]"):
        with ui.row().classes("items-center gap-3"):
            ui.icon("calculate").classes("text-4xl opacity-90")
            with ui.column().classes("gap-0"):
                ui.label("水工混凝土受弯构件正截面承载力计算").classes("text-xl font-bold")
                ui.label("单筋矩形截面 · NB/T 11011-2022 · 《水工钢筋混凝土结构学》第3章例题配套").classes("text-xs opacity-80")
        ui.button(icon="animation").props(
            "flat dense round color=white").classes("anim-toggle").tooltip(
            "动效：标准 ⇄ 关闭（本地记忆；关闭后不播任何动画）"
            ).on("click", js_handler=_MOTION_TOGGLE_JS)
    with ui.element("div").classes("nz-sticky-top print-hide w-full"):
        with ui.row().classes("w-full max-w-6xl mx-auto items-center gap-1 mt-1 flex-nowrap"):
            P["bar"] = ui.row().classes("gap-1 flex-grow").style(
                "min-width:0; flex:1 1 auto; flex-wrap:nowrap; overflow-x:auto; padding-bottom:2px")
            # 新建 = 弹菜单选题型模板（设计/复核空白骨架），“复制当前”降为末项
            with ui.button("＋ 新建").props("outline dense no-caps rounded"):
                with ui.menu():
                    ui.menu_item("设计（空白模板）",
                                 on_click=lambda: new_problem_dialog(kind="设计"))
                    ui.menu_item("复核（空白模板）",
                                 on_click=lambda: new_problem_dialog(kind="复核"))
                    ui.menu_item("复制当前（含全部输入）",
                                 on_click=lambda: new_problem_dialog(copy=True))
            ui.button("✎ 重命名", on_click=rename_problem).props(
                "outline dense no-caps rounded")
            ui.button("删除当前", on_click=delete_problem).props(
                "outline dense no-caps rounded")
            ui.button("⇅ 分享", on_click=share_dialog).props(
                "outline dense no-caps rounded").tooltip(
                "导出/导入题目卡（.txt 人读格式，可直接发微信/网盘）")
        with ui.tabs(on_change=_tab_changed).classes("w-full max-w-6xl mx-auto bg-white text-primary") as tabs:
            ui.tab("设计", icon="edit_note")
            ui.tab("复核", icon="fact_check")
            ui.tab("数据", icon="table_chart")
    TABS["tabs"] = tabs
    # 计算过程里的可点表号（.nz-ref → emitEvent）→ 跳数据页对应表格
    ui.on("nz_ref", lambda e: _tbl_jump(*(e.args if isinstance(e.args, (list, tuple))
                                          else (e.args,))))
    with ui.tab_panels(tabs, value="设计").classes("w-full max-w-6xl mx-auto"):
        build_design_tab()
        build_verify_tab()
        build_data_tab()
    _snapshot_defaults()
    status = _load_store()
    if status != "ok":                         # 首次运行/坏档隔离：以默认值建“题目1”
        _new_default_store()
        if status != "blocked":                # blocked 时不落盘，避免覆盖原档
            _write_store()
    load_current_problem()                     # 载入当前题目参数
    refresh_problem_bar()
    # 小节导航脚本（TOC + scroll-spy，_refresh_toc 在每次重绘后调用）
    ui.add_head_html(f"<script>{_TOC_JS}{_TOPBAR_JS}</script>")
    # 客户端连接后恢复「动效」本地偏好（纯前端，无服务端状态）
    ui.timer(0.8, lambda: ui.run_javascript("""
      if (localStorage.getItem('nz_motion') === 'off') {
        document.body.classList.add('motion-off');
        document.querySelectorAll('.anim-toggle').forEach(b => b.style.opacity = '.45');
      }
      window.nzTopStack && window.nzTopStack();"""), once=True)
    # 底部不设页脚；规范与数据来源见“数据”页签


def main():
    build_ui()


def _reset_store_at_boot():
    """启动即重置题库：删掉 problems.json，让本次会话从出厂状态（仅课本例题）开始。

    产品策略：题目不跨会话保留，实现为**进程启动时删除存档**而非退出时清理——
    崩溃/强杀后下次启动同样干净，且不用处理"优雅退出"信号。删除走的是
    _load_store 的 missing 分支 → _new_default_store 出厂重建，零新逻辑。
    必须放在 __main__（ui.run 之前）：root 函数每个客户端连接都会执行，
    重置放那里会把同会话第二个标签页打开时的用户题一并清掉。
    会话内一切照旧：多标签共享、计算即存、题目卡导入导出。
    """
    try:
        Path(_problems_path()).unlink(missing_ok=True)
    except OSError:
        # 删不掉（只读目录/被占用）就沿用现有档：功能照常，只是不重置
        logging.getLogger(__name__).exception("启动重置题库失败（保留现有 problems.json）")


if __name__ in {"__main__", "__mp_main__"}:
    # 打包成 exe 后（sys.frozen）双击启动默认弹桌面窗口；开发时用 --native 指定
    # 用 root 函数模式（脚本模式会重新执行入口文件，exe 下不可行）
    _reset_store_at_boot()
    native = getattr(sys, "frozen", False) or "--native" in sys.argv
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    icon = base / "app_icon.ico"
    ui.run(root=main, title="水工混凝土受弯承载力计算", native=native, reload=False,
           # 桌面窗口模式自动选空闲端口（避免与开发服务 8321 冲突导致 exe 起不来）
           port=None if native else 8380,
           show=False, favicon=str(icon) if icon.exists() else "🧮",
           # window_size 会隐式激活 native（NiceGUI ui_run 文档）——开发模式不传，
           # 否则每次启动额外开一个隐藏 pywebview 窗口连回 8321，进程强杀后残留的
           # 孤儿 WebView2 洪水式重连可把下一个服务器淹没
           window_size=(1200, 860) if native else None)
