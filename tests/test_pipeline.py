"""编排层 solve_design / solve_verify 回归（教材例3-1/3-3/3-4 锚点 + 计算书）。"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import pipeline, spec_data


def _load_38():
    """例3-8：已建简支矩形梁双筋复核（教材p92~93）。"""
    return {
        "member": "梁", "b": 250, "h": 600, "as_": 75,
        "Asrc": "count", "dia_c": 20, "n": 6,
        "dbl": "count", "dia_p": 18, "n_p": 3, "asp_": 49,
        "conc": "C30", "steel": "HRB400",
        "m_mode": "load", "M_kNm": 0,
        "load": {"gk": 12.0, "qk": 0.0, "Gk": 0.0, "Qk": 80.0,
                 "q_kind": "general", "Q_kind": "general",
                 "level": "I", "situation": "持久",
                 "l0src": "direct", "l0": 6.5},
    }


def _load_35():
    """例3-5/3-6/3-7：双筋设计（教材 p90~92），截面/材料同例3-3（250×500 双层 C30 HRB400 二类）。"""
    return {
        "member": "梁", "b": 250, "h": 500, "layers": 2, "dia_est": 20,
        "stirrup": 10, "conc": "C30", "steel": "HRB400", "env": "二",
        "y100": False, "m_mode": "direct", "M_kNm": 235.0,
        "dbl": "unknown", "asp_": 55,
    }


def test_design_example_3_5_doubly_unknown():
    """例3-5 双筋设计·A′s 未知：0.447>0.384 → A′s=303 → As=2463，总 2766。"""
    res = pipeline.solve_design(_load_35())
    v, r = res["values"], res["r"]
    assert math.isclose(v["as_"], 80) and math.isclose(v["h0"], 420)
    assert math.isclose(r["alpha_s"], 0.447) and math.isclose(r["alpha_s_b"], 0.384)
    assert r["Asp"] == 303 and r["As"] == 2463 and r["total"] == 2766
    assert res["verdict"]["ok"] and r["branch"] == "3-29/3-30"
    html = res["res_html"]
    for t in ("0.447", "0.384", "303", "2463", "2766",
              "（3-17）", "（3-29）", "（3-30）", "应设计成双筋截面"):
        assert t in html, f"缺 {t}"
    kpi = res["kpi_html"]
    assert "2463" in kpi and "303" in kpi and "2766" in kpi
    rep = res["report"]
    assert "双筋矩形截面" in rep and "2463" in rep and "2766" in rep
    assert "2Φ14" in rep, "受压筋建议应取教材例3-5 的 2Φ14"
    assert "结论：设计可行（双筋" in rep


def test_design_example_3_6_known():
    """例3-6 双筋设计·A′s=2Φ18=509：x=183≥110 走式(3-32)，As=2326，总 2835。"""
    inp = _load_35()
    inp.update({"dbl": "count", "dia_p": 18, "n_p": 2})
    res = pipeline.solve_design(inp)
    v, r = res["values"], res["r"]
    assert v["Asp"] == 509, "表C-1：2Φ18=509"
    assert math.isclose(r["alpha_s"], 0.341) and math.isclose(r["xi"], 0.436)
    assert r["x"] == 183 and r["branch"] == "3-32"
    assert r["As"] == 2326 and r["total"] == 2835
    assert res["verdict"]["ok"]
    html = res["res_html"]
    for t in ("0.341", "0.436", "183", "110", "2326", "2835",
              "（3-31）", "（3-18）", "（3-32）",
              "满足适用条件，表明已配的 A′<sub>s</sub> 足够。"):
        assert t in html, f"缺 {t}"
    assert "双筋·A′<sub>s</sub> 已知" in res["verdict"]["html"]


def test_design_example_3_7_known_xlt2asp():
    """例3-7 双筋设计·A′s=3Φ22=1140：x=100<110 走式(3-33)，As=2146，总 3286。"""
    inp = _load_35()
    inp.update({"dbl": "count", "dia_p": 22, "n_p": 3})
    res = pipeline.solve_design(inp)
    v, r = res["values"], res["r"]
    assert v["Asp"] == 1140, "表C-1：3Φ22=1140"
    assert math.isclose(r["alpha_s"], 0.210) and math.isclose(r["xi"], 0.238)
    assert r["x"] == 100 and r["branch"] == "3-33"
    assert r["As"] == 2146 and r["total"] == 3286
    html = res["res_html"]
    for t in ("0.210", "0.238", "100", "2146", "3286",
              "（3-33）", "不满足 x≥2a′<sub>s</sub> 适用条件，按式（3-33）计算受拉钢筋。"):
        assert t in html, f"缺 {t}"
    rep = res["report"]
    assert "2146" in rep and "3286" in rep and "3-33" in rep


def test_design_doubly_branches():
    """双筋设计边界：已配 A′s 不足 → 判不安全并给所需值；未超筋 → 回落单筋链。"""
    # 已配 2Φ14=308，M 加大到 300 → αs > αs,max，需增加 A′s
    inp = _load_35()
    inp.update({"dbl": "count", "dia_p": 14, "n_p": 2, "M_kNm": 300.0})
    res = pipeline.solve_design(inp)
    r = res["r"]
    assert r["need_more"] and res["verdict"]["ok"] is False
    assert "不足" in res["verdict"]["html"] and "所需 A′<sub>s</sub>" in res["res_html"]
    assert res["r"]["Asp_min"] > 308
    # M 减到 150 → αs ≤ αs,b：转入单筋链（结果与纯单筋一致）
    inp2 = _load_35()
    inp2.update({"M_kNm": 150.0})
    res2 = pipeline.solve_design(inp2)
    assert res2["values"]["doubly"] is False
    assert "转入单筋截面设计，无需受压钢筋" in res2["res_html"]
    inp3 = _load_35()
    inp3.update({"M_kNm": 150.0, "dbl": "none"})
    res3 = pipeline.solve_design(inp3)
    assert res3["r"]["As"] == res2["r"]["As"], "未超筋回落后应与单筋链完全一致"
    assert "双筋" not in res3["report"].split("\n")[0]


def test_moments_chain_example_3_5():
    """弯矩公式链（教材例3-5「2.内力计算」）：M = γ0ψ(MG+MQ) = 1.0×1.0×(100.0+135.0) = 235.0。"""
    inp = _load_35()
    inp.pop("M_kNm")
    inp.update({"m_mode": "moments", "dbl": "unknown", "asp_": 55,
                "load": {"MG": 100.0, "MQ": 135.0, "level": "II",
                         "situation": "持久"}})
    res = pipeline.solve_design(inp)
    assert math.isclose(res["values"]["M"] / 1e6, 235.0)
    h = res["m_html"]
    for t in ("内力计算", "γ<sub>0</sub>ψ(M<sub>G</sub> + M<sub>Q</sub>)",
              "(100.0 + 135.0)", "235.0"):
        assert t in h, f"缺 {t}"
    info = res["info_html"]
    assert "γ<sub>0</sub> = 1.0" in info and "ψ = 1.0" in info, "资料应给 γ0/ψ 出处"
    # 链后仍走双筋设计（M=235 同例3-5）
    assert res["r"]["Asp"] == 303 and res["r"]["As"] == 2463
    rep = res["report"]
    assert "二、内力计算" in rep
    assert "M = γ0·ψ(MG + MQ) = 1.0×1.0×(100.0 + 135.0) = 235.0 kN·m" in rep


def test_moments_chain_verify_page():
    """复核页同样支持"由标准值弯矩算 M"（两页通用模板）。"""
    inp = _load_38()
    inp.update({"m_mode": "moments",
                "load": {"MG": 100.0, "MQ": 135.0, "level": "III",
                         "situation": "持久"}})
    res = pipeline.solve_verify(inp)
    assert math.isclose(res["values"]["M"] / 1e6, 0.9 * 235.0, rel_tol=1e-9)
    assert "内力计算" in res["res_html"] and "(100.0 + 135.0)" in res["res_html"]
    assert "二、内力计算" in res["report"]
    # MG/MQ 全空 → 明确报错（模板场景下不应静默算 0）
    bad = _load_38()
    bad.update({"m_mode": "moments", "load": {"MG": 0, "MQ": 0,
                                              "level": "III", "situation": "持久"}})
    try:
        pipeline.solve_verify(bad)
        raise AssertionError("MG/MQ 全空应报错")
    except ValueError as e:
        assert "M_G" in str(e) or "弯矩" in str(e)


def test_verify_example_3_8_doubly():
    """例3-8 全链：M=262.58 → ξ=0.215 → x=113 > 2a′s=98 → Mu=320.0 → M′=266.67 ≥ M。"""
    res = pipeline.solve_verify(_load_38())
    v, r = res["values"], res["r"]
    # 表C-1 查表（≠ n×单根四舍五入）：6Φ20→1884，3Φ18→763
    assert v["As"] == 1884 and v["Asp"] == 763
    assert math.isclose(v["M"] / 1e6, 262.58, rel_tol=1e-3)
    assert math.isclose(v["h0"], 525)
    assert math.isclose(r["xi"], 0.215) and r["x"] == 113
    assert math.isclose(r["Mu"] / 1e6, 320.0, rel_tol=1e-3)
    assert math.isclose(r["M_allowed"] / 1e6, 266.67, rel_tol=1e-3)
    assert r["safe"] and res["verdict"]["ok"]
    html = res["res_html"]
    for t in ("0.215", "113", "98", "320.0", "266.67", "262.58",
              "满足不发生超筋的要求。", "满足 x≥2a′<sub>s</sub> 适用条件。",
              "（3-25）", "（3-22）", "正截面受弯承载力满足当前荷载的要求。",
              "1884", "763"):
        assert t in html, f"缺 {t}"
    rep = res["report"]
    assert "双筋矩形截面" in rep and "1884" in rep and "763" in rep
    assert "320.0" in rep and "266.67" in rep and "262.58" in rep
    assert "正截面受弯承载力满足当前荷载的要求。" in rep
    assert "a's = 49 mm" in rep


def test_verify_38_x_reverse_and_over():
    """双筋边界：x<2a′s 走式(3-28)；ξ>ξb 封顶且判不安全（与单筋页一致）。"""
    inp = _load_38()
    inp.update({"dia_c": 12, "n": 2, "dbl": "direct", "Asp": 200, "asp_": 60})
    res = pipeline.solve_verify(inp)
    r = res["r"]
    assert r["branch"] == "3-28" and not r["two_asp_ok"]
    assert "（3-28）" in res["res_html"]
    assert "不满足 x≥2a′<sub>s</sub> 适用条件，按式（3-28）计算。" in res["res_html"]
    # 超筋：As 极大 → ξ>ξb 封顶 x=ξb·h0，判定不安全（与单筋页口径一致）
    inp2 = _load_38()
    inp2.update({"Asrc": "direct", "As": 9000, "dbl": "count", "dia_p": 18, "n_p": 3,
                 "asp_": 49})
    res2 = pipeline.solve_verify(inp2)
    r2 = res2["r"]
    assert not r2["xi_ok"] and r2["x"] == round(spec_data.xi_b("HRB400") * 525)
    assert "取 x = ξ<sub>b</sub>·h<sub>0</sub>" in res2["res_html"]
    assert res2["verdict"]["ok"] is False and "超筋" in res2["verdict"]["html"]
    assert res2["report"].count("超筋") >= 1


def _load_31():
    return {
        "member": "梁", "b": 200, "h": 400,
        "conc": "C25", "steel": "HRB400", "env": "二", "y100": False,
        "layers": 1, "dia_est": 20, "stirrup": 10,
        "m_mode": "load", "M_kNm": 0,
        "load": {"gk": 2.0, "qk": 1.2, "Gk": 5.25, "Qk": 40.0,
                 "q_kind": "general", "Q_kind": "controllable",
                 "level": "III", "situation": "持久",
                 "l0src": "calc", "ln": 3.60, "a": 0.40, "l0": 3.78},
    }


def test_design_example_3_1():
    res = pipeline.solve_design(_load_31())
    v = res["values"]
    assert math.isclose(v["M"] / 1e6, 51.78, rel_tol=1e-3)
    assert math.isclose(v["h0"], 345)
    assert math.isclose(v["as_"], 55)
    # 舍入代入链（教材手算）：0.219 → 0.250 → As=570（全精度为 572）
    assert math.isclose(res["r"]["As"], 570, rel_tol=1e-3)
    assert res["verdict"]["ok"] and not res["r"]["over_reinforced"]
    # 计算书：分节 + 关键数 + 首选选筋
    rep = res["report"]
    assert "一、资料" in rep and "二、荷载与内力" in rep
    assert "三、配筋计算" in rep and "四、选筋与构造" in rep
    assert "（1）荷载标准值" in rep and "（2）分项系数" in rep
    assert "51.78" in rep and "3Φ16" in rep and "设计可行" in rep
    assert "570" in rep and "0.250" in rep
    assert "2×45+3×16+2×25 = 188" in rep, "排布宽度算式应入计算书"


def test_design_example_3_3_over():
    inp = _load_31()
    inp.update({"conc": "C30", "b": 250, "h": 500, "layers": 2,
                "m_mode": "direct", "M_kNm": 212.60})
    res = pipeline.solve_design(inp)
    assert res["r"]["over_reinforced"]
    assert res["suggest"] and res["suggest"]["h_min"] == 550
    assert "超筋" in res["report"] and "550" in res["report"]
    assert res["verdict"]["ok"] is False


def test_design_under_suggest():
    inp = _load_31()
    inp.update({"b": 800, "h": 800})          # 截面过大 → 少筋
    res = pipeline.solve_design(inp)
    assert res["r"]["under_reinforced"]
    assert res["suggest"] and res["suggest"].get("h_max")
    assert res["suggest"]["h_max"] < 800
    assert "少筋" in res["report"]


def test_verify_example_3_4():
    inp = {
        "member": "板", "b": 1000, "h": 120, "as_": 29,
        "Asrc": "spacing", "dia_s": 8, "spacing": 120,
        "conc": "C25", "steel": "HPB300",
        "m_mode": "direct", "M_kNm": 8.22,
    }
    res = pipeline.solve_verify(inp)
    v, r = res["values"], res["r"]
    assert math.isclose(v["As"], 419.167, rel_tol=1e-3)
    assert math.isclose(v["h0"], 91)
    # 教材手算链：As=419 → ξ=0.104 → αs=0.099 → Mu=9.76 → M′=8.13
    assert math.isclose(r["Mu"] / 1e6, 9.76, rel_tol=1e-3)
    assert math.isclose(r["M_allowed"] / 1e6, 8.13, rel_tol=1e-3)
    assert res["verdict"]["ok"] is False and not r["safe"]
    rep = res["report"]
    assert "承载力复核" in rep and "不安全" in rep and "8.13" in rep
    assert "正截面受弯承载力不能满足要求，不安全。" in rep
    # 编号小节 + 判定整句
    v2 = res["res_html"]
    assert "2. 弯矩" in v2 and "3. 承载力复核" in v2
    assert "满足不发生超筋的要求。" in v2
    assert "正截面受弯承载力不能满足要求，不安全。" in v2


def test_beam_constraints_and_double():
    inp = _load_31()
    inp["constraints"] = {"dias": [16, 18, 20], "allow_double": False}
    res = pipeline.solve_design(inp)
    rows = res["bars"]["rows"]
    assert rows and all(int(x["dia"][1:]) in (16, 18, 20) for x in rows)
    # 单层排不下 + 允许双层 → 给出满足侧保护层的双层行（b=250,h=500,M=180 → As≈1780）
    inp2 = _load_31()
    inp2.update({"b": 250, "h": 500, "layers": 1, "dia_est": 20,
                 "m_mode": "direct", "M_kNm": 180,
                 "constraints": {"allow_double": True}})
    res2 = pipeline.solve_design(inp2)
    assert res2["bars"]["rows"], "双层应给方案"
    assert "双层" in res2["bars"]["rows"][0]["fit"]
    # 物理校验：每个方案每排宽度 ≤ b−2×45（侧保护层），14Φ14 这类废案不再出现
    for x in res2["bars"]["rows"]:
        n_ = int(x["cnt"].replace("根", ""))
        d_ = int(x["dia"][1:])
        halves = [n_ - n_ // 2, n_ // 2] if "双层" in x["fit"] else [n_]
        for nn in halves:
            assert 2 * 45 + nn * d_ + (nn - 1) * 25 <= 250 + 1e-6


def test_slab_total_columns():
    inp = {
        "member": "板", "b": 3400, "h": 100,
        "conc": "C25", "steel": "HPB300", "env": "二", "y100": False,
        "layers": 1, "dia_est": 10, "stirrup": 10,
        "m_mode": "direct", "M_kNm": 19.94,   # 例3-2 的 M 按板宽 3.4m 等比例放大
        "constraints": {"s_range": (100, 200)},
    }
    res = pipeline.solve_design(inp)
    rows = res["bars"]["rows"]
    assert rows, "板应给建议"
    assert "total" in rows[0] and rows[0]["total"].endswith("根")
    assert all(any(c[0] == "total" for c in res["bars"]["columns"]) for _ in [0])
    # 间距约束生效
    sps = [int(x["spec"].split("@")[1]) for x in rows]
    assert all(100 <= s <= 200 for s in sps), sps


def test_picked_recheck():
    inp = _load_31()
    res = pipeline.solve_design(inp)
    row = res["bars"]["rows"][0]           # 3Φ16
    chk = pipeline.picked_recheck(res["values"], row, res["values"]["M"])
    assert chk and chk["ok"], "3Φ16 应复核可行"
    # 换一个过小的构造行（不可行方案难造，用富余大的都可行；只验证接口稳定）
    assert "实配回验" in chk["html"]


def test_picked_recheck_uses_actual_as():
    """实配回验应按实配直径重算 as/h0（例3-1：估Φ20 as=55 → 实配3Φ16 as=53）。"""
    inp = _load_31()
    res = pipeline.solve_design(inp)
    v = res["values"]
    assert abs(v["as_"] - 55) < 1e-9 and abs(v["h0"] - 345) < 1e-9
    row = res["bars"]["rows"][0]                        # 3Φ16（cs=45 → as=53）
    chk = pipeline.picked_recheck(v, row, v["M"])
    assert chk and chk["ok"]
    assert "53" in chk["html"] and "347" in chk["html"], \
        "应按 as=cs+Φ16/2=53 重算 h0=347 并注明"
    # 计算书同口径
    assert "as 按实配重算" in res["report"] and "347" in res["report"]


def test_picked_recheck_double_layer_as():
    """双层方案行回验：as = cs+35；设计按单层预估（as=55）时应重算注明 h0=420。"""
    inp = _load_31()
    inp.update({"b": 250, "h": 500, "layers": 1, "dia_est": 20,
                "m_mode": "direct", "M_kNm": 180,
                "constraints": {"allow_double": True}})
    res = pipeline.solve_design(inp)
    dbl = next(r for r in res["bars"]["rows"] if "双层" in r["fit"])
    chk = pipeline.picked_recheck(res["values"], dbl, res["values"]["M"])
    assert chk, "双层行应可回验"
    assert "按实配重算" in chk["html"] and "420" in chk["html"], \
        "双层 as=cs+35=80 → h0=500−80=420 应重算并注明"


def test_textbook_section_skeleton():
    """教材解题骨架：编号小节 + 分项系数带表号 + 自重推导 + 判定整句。"""
    res = pipeline.solve_design(_load_31())
    all_html = res["info_html"] + res["m_html"] + res["res_html"]
    for head in ("1. 资料", "2. 荷载标准值", "3. 分项系数",
                 "4. 荷载与内力", "5. 配筋计算"):
        assert head in all_html, f"缺小节 {head}"
    assert res["bars"]["title"].startswith("6. 选筋与构造")
    # 分项系数带表号出处（教材 3(1) 写法）
    assert "表2-4" in res["m_html"] and "表2-5" in res["m_html"]
    assert "表2-6" in res["m_html"] and "表2-7" in res["m_html"]
    # 自重按 b·h·γc 推导（例3-1：0.20×0.40×25.0 = 2.0）；过程中不再出现内部比对叙述
    assert "b·h·γ" in res["m_html"] and "2.0 kN/m" in res["m_html"]
    assert "与题给一致" not in res["m_html"] and "以题给为准" not in res["m_html"]
    # 题给 gk 与自重不一致时与其余标准值并列列出（例3-8：gk=12 ≠ 0.25×0.6×25）
    res38 = pipeline.solve_verify(_load_38())
    assert "均布恒载 g<sub>k</sub> = 12 kN/m" in res38["m_html"], "不一致时应直书题给值"
    assert "题给标准值" not in res38["m_html"] and "见上" not in res38["m_html"]
    assert "b·h·γ" not in res38["m_html"]
    # 判定改为教材整句（行尾不再挂 ✓）
    assert "满足不发生超筋的要求。" in res["res_html"]
    assert "满足纵向受拉钢筋最小配筋率要求。" in res["res_html"]
    # 舍入显示链：ξ 三位小数 0.250、As=570、ρ 两位 0.83%
    assert "0.250" in res["res_html"] and "570" in res["res_html"]
    assert "0.83%" in res["res_html"] and "0.20%" in res["res_html"]
    # 资料带查表出处
    assert "附录B" in res["info_html"] and "表D-4" in res["info_html"]


def test_over_reinforced_trial():
    """例3-3：超筋后按反解 h≥550 续演重算（教材“为此将截面高度……”写法）。"""
    inp = _load_31()
    inp.update({"conc": "C30", "b": 250, "h": 500, "layers": 2,
                "m_mode": "direct", "M_kNm": 212.60})
    res = pipeline.solve_design(inp)
    assert res["r"]["over_reinforced"]
    tr = res["suggest"].get("trial")
    assert tr and tr["h"] == 550, "应自动试算 h=550"
    html = res["res_html"]
    assert "截面提高至 h = 550mm 试算" in html
    assert "0.323" in html and "0.405" in html and "1890" in html
    assert "满足不发生超筋的要求。" in html and "1.61%" in html
    assert "h = 550mm" in res["verdict"]["html"], "判定应提示已试算"
    rep = res["report"]
    assert "截面高度提高到 550 mm" in rep and "1890" in rep


def test_under_reinforced_trial_and_rho_line():
    """少筋：ρ 行按实际方向显示（修旧硬编码 ≥ bug）+ 截面减小续演。"""
    inp = _load_31()
    inp.update({"b": 800, "h": 800})          # 截面过大 → 少筋
    res = pipeline.solve_design(inp)
    assert res["r"]["under_reinforced"]
    html = res["res_html"]
    assert "不满足纵向受拉钢筋最小配筋率要求。" in html
    assert "&lt; ρ<sub>min</sub>" in html, "少筋时 ρ 行应显示 < 而非 ≥"
    tr = res["suggest"].get("trial")
    assert tr and tr["h"] < 800, "应反解出更小的可行 h 并试算"
    assert "截面减小至" in html
    assert "满足纵向受拉钢筋最小配筋率要求。" in html.split("截面减小至")[-1]


def test_recheck_width_formula():
    """选筋叙述含排布宽度算式（教材例3-1：2×45+3×16+2×25=188≤200）。"""
    res = pipeline.solve_design(_load_31())
    row = res["bars"]["rows"][0]               # 3Φ16
    chk = pipeline.picked_recheck(res["values"], row, res["values"]["M"])
    assert "排布宽度 = 2×45 + 3×16 + 2×25 = 188 ≤ b = 200" in chk["html"]
    assert "选筋 3Φ16" in chk["html"]


def test_l0_sub_and_step_labels():
    """板 l0 代入串修复 + 分节小标题/式号（轻量清晰化）。"""
    inp = {
        "member": "板", "b": 1000, "h": 100,
        "conc": "C25", "steel": "HPB300", "env": "二", "y100": False,
        "layers": 1, "dia_est": 10, "stirrup": 10,
        "m_mode": "load", "M_kNm": 0,
        "load": {"gk": 2.5, "qk": 3.0, "Gk": 0, "Qk": 0,
                 "q_kind": "general", "Q_kind": "general",
                 "level": "III", "situation": "持久",
                 "l0src": "calc", "ln": 2.7, "a": 0.15, "l0": 2.8},
    }
    res = pipeline.solve_design(inp)
    m = res["m_html"]
    assert "min(2.7+0.15, 2.7+0.1)" in m, "l0 代入应为 min(ln+a, ln+h)"
    assert "min(2.7+0.15, 2.7, " not in m, "不应多出 ln,"
    assert "荷载与内力" in m and "（式2-35）" in m
    r = res["res_html"]
    assert "配筋计算" in r and "（3-17）" in r and "（3-18）" in r and "（3-19）" in r
    rv = pipeline.solve_verify({
        "member": "板", "b": 1000, "h": 120, "as_": 29,
        "Asrc": "spacing", "dia_s": 8, "spacing": 120,
        "conc": "C25", "steel": "HPB300",
        "m_mode": "direct", "M_kNm": 8.22,
    })
    v = rv["res_html"]
    assert "承载力复核" in v and "（3-14）" in v and "（3-12）" in v and "（3-13）" in v


def test_verify_inverse_h_and_rho_scale():
    """例3-4 不安全 → 反解需 h≥130mm（板10模数）+ ρ 标尺与设计页一致。"""
    res = pipeline.solve_verify({
        "member": "板", "b": 1000, "h": 120, "as_": 29,
        "Asrc": "spacing", "dia_s": 8, "spacing": 120,
        "conc": "C25", "steel": "HPB300",
        "m_mode": "direct", "M_kNm": 8.22,
    })
    hh = res["h_hint"]
    assert hh and hh["why"] == "受弯承载力不足"
    assert math.isclose(hh["h0_min"], 91.945, rel_tol=2e-3), hh["h0_min"]
    assert hh["h"] == 130 and hh["mod"] == 10
    assert "反解" in res["verdict"]["html"] and "130" in res["verdict"]["html"]
    assert "反解" in res["report"] and "130" in res["report"]
    assert res["rho_ui"]["scale_html"] and "0.20%" in res["rho_ui"]["scale_html"]
    # 超筋复核的反解（ξ 控制下的最小 h0）
    assert math.isclose(pipeline.singly_rect.min_h0_for_xi(2000, 250, 14.3, 360, 0.518),
                        388.8, rel_tol=2e-3)


def test_design_rho_sweep_chart():
    """破坏形态扫描图：三区着色 + 当前点；超筋路径无当前点；Mu_of_rho 恒等式。"""
    res = pipeline.solve_design(_load_31())
    svg = res["sweep_html"]
    assert "少筋" in svg and "适筋" in svg and "超筋" in svg
    assert "当前 ρ=0.83%" in svg and "<polyline" in svg
    assert "ρmin=0.20%" in svg and "ρmax=1.46%" in svg
    # 超筋（例3-3）：r["rho"]=None → 不画当前点，但图仍在
    inp = _load_31()
    inp.update({"conc": "C30", "b": 250, "h": 500, "layers": 2,
                "m_mode": "direct", "M_kNm": 212.60})
    over = pipeline.solve_design(inp)
    assert "少筋" in over["sweep_html"] and "当前" not in over["sweep_html"]
    # 恒等式：ρ=ξb·fc/fy 时 Mu_of_rho == αs,max·fc·b·h0²
    rho = 0.518 * 11.9 / 360
    m1 = pipeline.singly_rect.Mu_of_rho(rho, 200, 345, 11.9, 360)
    m2 = pipeline.singly_rect.alpha_s_max(0.518) * 11.9 * 200 * 345 ** 2
    assert math.isclose(m1, m2, rel_tol=1e-9)


def test_doubly_only_for_beam():
    """双筋仅适用于梁：板带双筋输入时内核直接拒绝（不做静默替换）；梁双筋不受影响。"""
    base = {"member": "板", "b": 1000, "h": 120, "layers": 1, "dia_est": 10,
            "stirrup": 10, "conc": "C25", "steel": "HRB400", "env": "二",
            "y100": False, "m_mode": "direct", "M_kNm": 30.0}
    single = pipeline.solve_design({**base, "dbl": "none"})   # 板按单筋照常
    assert single["r"]["As"] > 0
    try:
        pipeline.solve_design({**base, "dbl": "unknown", "asp_": 30.0})
        raise AssertionError("板 + 双筋设计应报错，而不是静默按单筋计算")
    except ValueError as e:
        assert "仅适用于梁" in str(e), str(e)
    vbase = {"member": "板", "b": 1000, "h": 120, "as_": 25,
             "Asrc": "count", "dia_c": 10, "n": 5, "conc": "C25", "steel": "HRB400",
             "m_mode": "direct", "M_kNm": 30.0}
    vs = pipeline.solve_verify({**vbase, "dbl": "none"})      # 板复核按单筋照常
    assert vs["verdict"] is not None
    try:
        pipeline.solve_verify({**vbase, "dbl": "count", "dia_p": 18, "n_p": 2,
                               "asp_": 30.0})
        raise AssertionError("板 + 双筋复核应报错")
    except ValueError as e:
        assert "仅适用于梁" in str(e), str(e)
    # 梁仍然可用双筋（回归保护）
    beam = pipeline.solve_design(_load_35())
    assert beam["values"].get("doubly") and beam["r"]["Asp"] == 303


def test_design_rejects_zero_h0():
    """h0=0 必须在进入承载力计算前报输入错误，不能触发除零。"""
    inp = {"member": "板", "b": 1000, "h": 30, "conc": "C25",
           "steel": "HRB400", "env": "二", "layers": 1, "dia_est": 10,
           "stirrup": 10, "m_mode": "direct", "M_kNm": 20.0, "dbl": "none",
           "load": {}}
    try:
        pipeline.solve_design(inp)
        raise AssertionError("h0=0 应报输入错误，不能继续计算")
    except ValueError as e:
        assert "h0 = h - as 应大于 0" in str(e), str(e)


def test_design_rejects_negative_h0():
    """h0<0 必须报输入错误，不能继续算成“超筋”。"""
    inp = {"member": "板", "b": 1000, "h": 25, "conc": "C25",
           "steel": "HRB400", "env": "二", "layers": 1, "dia_est": 10,
           "stirrup": 10, "m_mode": "direct", "M_kNm": 20.0, "dbl": "none",
           "load": {}}
    try:
        pipeline.solve_design(inp)
        raise AssertionError("h0<0 应报输入错误，不能按超筋处理")
    except ValueError as e:
        assert "h0 = h - as 应大于 0" in str(e), str(e)


def test_design_partial_stages():
    """分段模式：缺输入返回已算段（不中断）；分段行按序包含于整段结果；非法输入仍报错。"""
    import re

    def _lines(h):
        return [t.strip() for t in re.findall(r'>([^<]+)<', h) if t.strip()]

    def _in_order(sub, full):
        it = iter(full)
        return all(any(x == y for x in it) for y in sub)

    base = {"member": "梁", "b": 200, "h": 400, "conc": "C25", "steel": "HRB400", "env": "二",
            "layers": 1, "dia_est": 20, "stirrup": 10, "m_mode": "load",
            "load": {"gk": 10.0, "qk": 8.0, "Gk": 0, "Qk": 0, "q_kind": "general",
                     "Q_kind": "general", "level": "III", "situation": "持久",
                     "l0src": "calc", "ln": 3.6, "a": 0.4}}
    # 1) 缺 h：严格模式仍报错（旧行为）；分段模式只出材料/环境
    inp = {**base, "h": 0, "_empty": ["h"]}
    try:
        pipeline.solve_design(inp)
        raise AssertionError("严格模式应报错")
    except ValueError as e:
        assert "截面" in str(e) or "h" in str(e), str(e)
    r = pipeline.solve_design(inp, partial=True)
    assert r["partial"] and "材料" in r["info_html"] and "截面" not in r["info_html"]
    assert [k for k, _ in r["missing"]] == ["h"]
    assert r["pending_html"], "应给出未算段占位"
    # 2) 荷载齐、缺净跨 ln：停在"分项系数"之后
    inp2 = {**base, "_empty": ["ln"], "load": {**base["load"], "ln": 0}}
    r2 = pipeline.solve_design(inp2, partial=True)
    assert r2["partial"] and "荷载标准值" in r2["m_html"] and "分项系数" in r2["m_html"]
    assert "荷载与内力" not in r2["m_html"] and [k for k, _ in r2["missing"]] == ["ln"]
    # 3) 全齐：完整结果；分段已出的行按序包含其中（同一代码路径，不分叉）
    full = pipeline.solve_design(base)
    assert not full.get("partial") and full["verdict"]["ok"]
    assert _in_order(_lines(r["info_html"]), _lines(full["info_html"]))
    # 4) 非法输入（b<0）仍报错，不伪装成"还没填"
    bad = {**base, "b": -5}
    try:
        pipeline.solve_design(bad, partial=True)
        raise AssertionError("非法输入应报错")
    except ValueError as e:
        assert "截面" in str(e) or "b" in str(e), str(e)
