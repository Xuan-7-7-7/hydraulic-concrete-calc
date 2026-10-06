"""用教材例3-1~3-4、例3-8（NB/T 11011-2022 部分）回归校验计算内核。

既可 pytest 运行，也可直接 python tests/test_examples.py 逐题打印对照。
所有期望值取自教材正文数值；容差按教材三位有效数字的舍入给出。
"""

import math
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import spec_data, section, singly_rect, doubly_rect, loading

Failures = []  # 收集不一致项，最后统一汇报


def _close(actual, expected, tol=1e-3, rel=False):
    if rel:
        return math.isclose(actual, expected, rel_tol=tol)
    return abs(actual - expected) <= tol


def check(name, actual, expected, tol=1e-3, rel=False):
    ok = _close(actual, expected, tol, rel)
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: 计算={actual:.6g}  教材={expected:g}")
    if not ok:
        Failures.append(f"{name}: 计算={actual!r} 教材={expected!r}")


def test_example_3_1():
    """例3-1 启闭机支承梁：荷载→内力→配筋（新规范）。"""
    print("例3-1 启闭机支承梁 (NB/T 11011-2022)")
    # 分项系数
    gamma0 = spec_data.gamma0("III")
    p = spec_data.psi("持久")
    gamma_G, gamma_Q1, gamma_Q2 = spec_data.gamma_G(), spec_data.gamma_Q("general"), spec_data.gamma_Q("controllable")
    gamma_d = spec_data.gamma_d()
    check("γ0", gamma0, 0.9); check("ψ", p, 1.0)
    check("γG", gamma_G, 1.10); check("γQ1", gamma_Q1, 1.30); check("γQ2", gamma_Q2, 1.20)
    check("γd", gamma_d, 1.20)
    # 荷载设计值（标准值由题给：gk=2.0, Gk=5.25, Qk=40.0, qk=1.20），kN/m、kN
    g, G = gamma_G * 2.0, gamma_G * 5.25
    q, Q = gamma_Q1 * 1.20, gamma_Q2 * 40.0
    check("g", g, 2.20); check("G", G, 5.78, tol=0.005)
    check("q", q, 1.56); check("Q", Q, 48.0)
    # 内力（kN/m 配 m → kN·m，再换算 N·mm 进内核）
    l0 = loading.effective_span_beam(ln=3.60, a=0.40)
    check("l0", l0, 3.78, tol=1e-9)
    M = loading.M_design(gamma0, p, loading.midspan_M(g, q, l0, G, Q)) * 1e6
    check("M (kN·m)", M / 1e6, 51.78, tol=0.01)
    # 截面有效高度：二类环境梁 c=35，cs=c+10，单层 d=20
    c = spec_data.cover_min("二类", "梁")
    cs = section.cs_beam(c)
    as_, h0 = section.effective_depth(400, cs, bar_dia=20, layers=1)
    check("c", c, 35); check("cs", cs, 45); check("as", as_, 55); check("h0", h0, 345)
    # 配筋计算
    fc, fy = spec_data.concrete_fc("C25"), spec_data.steel_fy("HRB400")
    xi_b, rho_min = spec_data.xi_b("HRB400"), spec_data.rho_min("HRB400", "梁")
    check("ξb", xi_b, 0.518); check("ρmin", rho_min, 0.0020)
    r = singly_rect.design(M, b=200, h0=h0, fc=fc, fy=fy, xi_b=xi_b, rho_min=rho_min, gamma_d=gamma_d)
    check("αs", r["alpha_s"], 0.219, tol=0.001)
    check("ξ", r["xi"], 0.250, tol=0.001)
    assert not r["over_reinforced"] and not r["under_reinforced"]
    check("As (mm²)", r["As"], 570, tol=0.01, rel=True)
    check("ρ (%)", r["rho"] * 100, 0.83, tol=0.01)


def test_example_3_2():
    """例3-2 坝顶人行道板：板式配筋（新规范）。"""
    print("例3-2 坝顶人行道板 (NB/T 11011-2022)")
    gamma0, p, gamma_d = spec_data.gamma0("III"), spec_data.psi("持久"), spec_data.gamma_d()
    g = spec_data.gamma_G() * (0.10 * 1.0 * 25.0)   # 板自重 gk=2.50 kN/m
    q = spec_data.gamma_Q("general") * 3.0          # 人群 qk=3.0 kN/m
    l0 = loading.effective_span_slab(ln=2.70, a=0.15, h=0.10)
    check("l0", l0, 2.80, tol=1e-9)
    M = loading.M_design(gamma0, p, loading.midspan_M(g, q, l0)) * 1e6
    check("M (kN·m)", M / 1e6, 5.87, tol=0.01)
    c = spec_data.cover_min("二类", "板")
    cs = section.cs_slab(c)
    as_, h0 = section.effective_depth(100, cs, bar_dia=10, layers=1)
    check("cs", cs, 25); check("as", as_, 30); check("h0", h0, 70)
    fc, fy = spec_data.concrete_fc("C25"), spec_data.steel_fy("HPB300")
    xi_b, rho_min = spec_data.xi_b("HPB300"), spec_data.rho_min("HPB300", "板")
    check("ξb", xi_b, 0.576)
    r = singly_rect.design(M, b=1000, h0=h0, fc=fc, fy=fy, xi_b=xi_b, rho_min=rho_min, gamma_d=gamma_d)
    check("αs", r["alpha_s"], 0.121, tol=0.001)
    check("ξ", r["xi"], 0.129, tol=0.001)
    assert not r["over_reinforced"] and not r["under_reinforced"]
    check("As (mm²/m)", r["As"], 398, tol=0.01, rel=True)
    check("ρ (%)", r["rho"] * 100, 0.57, tol=0.01)


def test_example_3_3():
    """例3-3 泵房简支梁：M 直接给定，先超筋、加大截面后重算。"""
    print("例3-3 泵房简支梁 (NB/T 11011-2022)")
    M = 212.60e6
    fc, fy = spec_data.concrete_fc("C30"), spec_data.steel_fy("HRB400")
    xi_b, rho_min, gamma_d = spec_data.xi_b("HRB400"), spec_data.rho_min("HRB400", "梁"), spec_data.gamma_d()
    check("fc", fc, 14.3); check("ξb", xi_b, 0.518)
    # 第一次：h=500，双层筋 as=cs+35=80
    cs = section.cs_beam(spec_data.cover_min("二类", "梁"))
    as_, h0 = section.effective_depth(500, cs, layers=2)
    check("as", as_, 80); check("h0", h0, 420)
    r1 = singly_rect.design(M, b=250, h0=h0, fc=fc, fy=fy, xi_b=xi_b, rho_min=rho_min, gamma_d=gamma_d)
    check("αs(1)", r1["alpha_s"], 0.405, tol=0.001)
    check("ξ(1)", r1["xi"], 0.564, tol=0.001)
    assert r1["over_reinforced"], "第一次计算应判超筋"
    # 第二次：h 提高到 550（50mm 模数）
    as_, h0 = section.effective_depth(550, cs, layers=2)
    check("h0(2)", h0, 470)
    r2 = singly_rect.design(M, b=250, h0=h0, fc=fc, fy=fy, xi_b=xi_b, rho_min=rho_min, gamma_d=gamma_d)
    check("αs(2)", r2["alpha_s"], 0.323, tol=0.001)
    check("ξ(2)", r2["xi"], 0.405, tol=0.001)
    assert not r2["over_reinforced"]
    check("As (mm²)", r2["As"], 1890, tol=0.01, rel=True)
    check("ρ (%)", r2["rho"] * 100, 1.61, tol=0.01)
    assert not r2["under_reinforced"]


def test_example_3_4():
    """例3-4 已建简支板承载力复核：As→Mu→与 M 比较，判不安全。"""
    print("例3-4 已建简支板复核 (NB/T 11011-2022)")
    gamma0, p, gamma_d = spec_data.gamma0("II"), spec_data.psi("短暂"), spec_data.gamma_d()
    check("γ0", gamma0, 1.0); check("ψ(短暂)", p, 0.95)
    g = spec_data.gamma_G() * 3.0          # 板自重 gk=0.12×1×25=3.0 kN/m
    q = spec_data.gamma_Q("general") * 3.0  # 施工荷载 qk=3.0 kN/m
    M = loading.M_design(gamma0, p, loading.midspan_M(g, q, l0=3.10)) * 1e6
    check("M (kN·m)", M / 1e6, 8.22, tol=0.01)
    fc, fy = spec_data.concrete_fc("C25"), spec_data.steel_fy("HPB300")
    xi_b = spec_data.xi_b("HPB300")
    as_, h0 = section.effective_depth(120, cs=25, bar_dia=8, layers=1)
    check("as", as_, 29); check("h0", h0, 91)
    As = spec_data.bar_area(8) * 1000 / 120   # Φ8@120 每米 419 mm²
    check("As (mm²/m)", As, 419, tol=0.01, rel=True)
    r = singly_rect.verify(As, b=1000, h0=h0, fc=fc, fy=fy, xi_b=xi_b,
                           gamma_d=gamma_d, M=M, rho_min=spec_data.rho_min("HPB300", "板"))
    check("ξ", r["xi"], 0.104, tol=0.001)
    check("αs", r["alpha_s"], 0.099, tol=0.001)
    check("Mu (kN·m)", r["Mu"] / 1e6, 9.76, tol=0.01)
    check("M'=Mu/γd (kN·m)", r["M_allowed"] / 1e6, 8.13, tol=0.01)
    assert not r["safe"], "教材结论：M'<M，正截面受弯承载力不满足，不安全"


def test_example_3_8():
    """例3-8 已建简支矩形梁（双筋）复核：M=262.58 → ξ=0.215 → x=113 → Mu=320.0 → M′=266.67。"""
    print("例3-8 已建简支矩形梁（双筋）复核 (NB/T 11011-2022)")
    gamma0, p = spec_data.gamma0("I"), spec_data.psi("持久")
    gamma_d = spec_data.gamma_d()
    check("γ0", gamma0, 1.1); check("ψ", p, 1.0)
    check("γG", spec_data.gamma_G(), 1.10)
    check("γQ1(一般可变)", spec_data.gamma_Q("general"), 1.30)
    g = spec_data.gamma_G() * 12.0
    Q = spec_data.gamma_Q("general") * 80.0
    M = loading.M_design(gamma0, p, loading.midspan_M(g, 0.0, l0=6.5, G=0.0, Q=Q)) * 1e6
    check("M (kN·m)", M / 1e6, 262.58, tol=0.01)
    fc, fy = spec_data.concrete_fc("C30"), spec_data.steel_fy("HRB400")
    xi_b = spec_data.xi_b("HRB400")
    check("as", 75.0, 75); check("h0", 600 - 75.0, 525)
    As = spec_data.bar_area_n(20, 6)       # 查附录C 表C-1：1884（≠ 6×314.2）
    Asp = spec_data.bar_area_n(18, 3)      # 查附录C 表C-1：763（≠ 3×254.5）
    check("As (mm²) 表C-1", As, 1884)
    check("A's (mm²) 表C-1", Asp, 763)
    a_s = 40 + 18 / 2
    check("a's = cs+d/2", a_s, 49)
    r = doubly_rect.verify(As, Asp, b=250, h0=525, asp=a_s, fc=fc, fy=fy,
                           xi_b=xi_b, gamma_d=gamma_d, M=M,
                           rho_min=spec_data.rho_min("HRB400", "梁"))
    check("ξ", r["xi"], 0.215, tol=0.001)
    check("x (mm)", r["x"], 113, tol=0.5)
    check("2a's (mm)", 2 * a_s, 98)
    check("Mu (kN·m)", r["Mu"] / 1e6, 320.0, tol=0.05)
    check("M'=Mu/γd (kN·m)", r["M_allowed"] / 1e6, 266.67, tol=0.01)
    assert r["branch"] == "3-22" and r["safe"], \
        "教材结论：M'=266.67 > M=262.58，正截面受弯承载力满足当前荷载的要求"


def test_rho_max():
    """式(3-10b)：ρmax = 0.85·ξb·fc/fy（C25+HRB400 ≈ 1.46%）。"""
    r = singly_rect.rho_max(spec_data.concrete_fc("C25"),
                            spec_data.steel_fy("HRB400"), spec_data.xi_b("HRB400"))
    check("ρmax (%)", r * 100, 1.455, tol=0.001)


def main():
    for t in (test_example_3_1, test_example_3_2, test_example_3_3,
              test_example_3_4, test_example_3_8, test_rho_max):
        t()
    print()
    if Failures:
        print(f"共 {len(Failures)} 项不一致：")
        for f in Failures:
            print(" -", f)
        sys.exit(1)
    print("五道例题（例3-1~3-4、例3-8）全部复核通过，内核与教材数值一致。")


if __name__ == "__main__":
    main()
