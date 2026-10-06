"""双筋矩形截面复核内核测试：例3-8 锚点 + 式(3-28)/超筋封顶分支。

既可 pytest 运行，也可直接 python tests/test_doubly_rect.py。
锚点依据：教材例3-8（p92~93）、公式式(3-22)(3-25)(3-27)(3-28)（p87~88）。
"""

import math
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import doubly_rect

Failures = []


def check(name, actual, expected, tol=1e-3):
    ok = abs(actual - expected) <= tol
    print(f"  {'PASS' if ok else 'FAIL'}  {name}: 计算={actual:.6g}  教材={expected:g}")
    if not ok:
        Failures.append(f"{name}: 计算={actual!r} 教材={expected!r}")


def test_example_3_8():
    """例3-8 双筋梁复核（教材 p92~93 逐字对照）。"""
    print("例3-8 双筋梁复核")
    r = doubly_rect.verify(As=1884, Asp=763, b=250, h0=525, asp=49,
                           fc=14.3, fy=360, xi_b=0.518, gamma_d=1.20,
                           M=262.58e6, rho_min=0.002)
    check("ξ", r["xi"], 0.215)            # (360×1884−360×763)/(14.3×250×525)
    check("x (mm)", r["x"], 113)          # 0.215×525=112.875→113
    check("2a's (mm)", 2 * 49, 98)
    check("Mu (×10⁶ N·mm)", r["Mu"] / 1e6, 320.0, tol=0.05)
    check("M' (kN·m)", r["M_allowed"] / 1e6, 266.67, tol=0.01)
    check("ρ (%)", r["rho"] * 100, 1.44, tol=0.01)
    assert r["xi_ok"], "ξ≤ξb 应满足"
    assert r["two_asp_ok"], "x≥2a's 应满足"
    assert r["branch"] == "3-22"
    assert r["rho_ok"], "ρ≥ρmin 应满足"
    assert r["safe"], "M'=266.67 ≥ M=262.58 应判安全"


def test_branch_x_lt_2asp():
    """x < 2a's 分支：按式(3-28) Mu = fy·As·(h0−a's)。"""
    print("x < 2a's 分支（式3-28）")
    r = doubly_rect.verify(As=1200, Asp=1140, b=250, h0=420, asp=55,
                           fc=14.3, fy=360, xi_b=0.518, gamma_d=1.20)
    check("ξ", r["xi"], 0.014)
    check("x (mm)", r["x"], 6)
    assert not r["two_asp_ok"] and r["branch"] == "3-28"
    check("Mu (×10⁶ N·mm)", r["Mu"] / 1e6, 360 * 1200 * (420 - 55) / 1e6)


def test_branch_over_reinforced():
    """超筋分支：ξ>ξb 时取 x=ξb·h0 代入式(3-22)，xi_ok=False。"""
    print("超筋封顶分支")
    r = doubly_rect.verify(As=6000, Asp=763, b=250, h0=525, asp=49,
                           fc=14.3, fy=360, xi_b=0.518, gamma_d=1.20, M=1e6)
    check("ξ", r["xi"], 1.004)            # (360×6000−360×763)/(14.3×250×525)
    assert not r["xi_ok"]
    check("x=ξb·h0 (mm)", r["x"], round(0.518 * 525))   # 272
    check("Mu (×10⁶ N·mm)", r["Mu"] / 1e6,
          14.3 * 250 * 272 * (525 - 272 / 2) / 1e6 + 360 * 763 * (525 - 49) / 1e6,
          tol=0.05)
    assert not r.get("safe", False), "超筋不得判安全"


def test_display_chain_self_consistent():
    """显示与代入自洽：ξ 3位→x 整数→Mu 用显示值可复算。"""
    print("显示链自洽")
    r = doubly_rect.verify(As=1884, Asp=763, b=250, h0=525, asp=49,
                           fc=14.3, fy=360, xi_b=0.518, gamma_d=1.20)
    # 用显示值（ξ=0.215、x=113）手工复算 Mu，必须与返回值一致
    mu_shown = (14.3 * 250 * 113 * (525 - 113 / 2.0) + 360 * 763 * (525 - 49))
    check("Mu 复算 (×10⁶)", r["Mu"] / 1e6, mu_shown / 1e6)


def test_example_3_5_design_unknown():
    """例3-5 双筋设计·A′s 未知（教材 p90~91）：0.447>0.384 → A′s=303 → As=2463。"""
    print("例3-5 双筋设计（A′s 未知）")
    r = doubly_rect.design(M=235.0e6, b=250, h0=420, fc=14.3, fy=360,
                           xi_b=0.518, gamma_d=1.20, mode="unknown", asp=55,
                           rho_min=0.002)
    check("αs", r["alpha_s"], 0.447)
    check("αs,b", r["alpha_s_b"], 0.384)
    assert not r["single_ok"], "αs>αs,b 应转入双筋链"
    check("A′s (mm²)", r["Asp"], 303)
    check("As (mm²)", r["As"], 2463)
    check("总用量 (mm²)", r["total"], 2766)
    check("ρ (%)", r["rho"] * 100, 2.35, tol=0.01)
    assert r["branch"] == "3-29/3-30" and r["ok"] and r["rho_ok"]


def test_example_3_6_design_known():
    """例3-6 双筋设计·A′s=2Φ18=509 已知（教材 p91）：x=183≥110 走式(3-32)。"""
    print("例3-6 双筋设计（A′s 已知，x≥2a′s）")
    r = doubly_rect.design(M=235.0e6, b=250, h0=420, fc=14.3, fy=360,
                           xi_b=0.518, gamma_d=1.20, mode="known", Asp=509,
                           asp=55, rho_min=0.002)
    check("αs", r["alpha_s"], 0.341)
    check("ξ", r["xi"], 0.436)
    check("x (mm)", r["x"], 183)
    check("2a′s (mm)", 2 * 55, 110)
    assert r["branch"] == "3-32"
    check("As (mm²)", r["As"], 2326)
    check("总用量 (mm²)", r["total"], 2835)
    assert r["ok"]


def test_example_3_7_design_known_xlt2asp():
    """例3-7 双筋设计·A′s=3Φ22=1140 已知（教材 p92）：x=100<110 走式(3-33)。"""
    print("例3-7 双筋设计（A′s 已知，x<2a′s）")
    r = doubly_rect.design(M=235.0e6, b=250, h0=420, fc=14.3, fy=360,
                           xi_b=0.518, gamma_d=1.20, mode="known", Asp=1140,
                           asp=55, rho_min=0.002)
    check("αs", r["alpha_s"], 0.210)
    check("ξ", r["xi"], 0.238)
    check("x (mm)", r["x"], 100)
    assert r["branch"] == "3-33"
    check("As (mm²)", r["As"], 2146)
    check("总用量 (mm²)", r["total"], 3286)
    assert r["ok"]


def test_design_branches():
    """边界：未超筋→单筋即可；αs>αs,b（已知 A′s）→需增加 A′s 并给所需值。"""
    print("双筋设计边界分支")
    # 弯矩小 → αs ≤ αs,b：single_ok，不进入双筋链
    r = doubly_rect.design(M=150.0e6, b=250, h0=420, fc=14.3, fy=360,
                           xi_b=0.518, gamma_d=1.20, mode="unknown", asp=55)
    assert r["single_ok"] and r["alpha_s"] < r["alpha_s_b"], r
    # 已配 A′s 太小（弯矩 300）→ need_more，并给出按式(3-29) 所需的 Asp_min
    r2 = doubly_rect.design(M=300.0e6, b=250, h0=420, fc=14.3, fy=360,
                            xi_b=0.518, gamma_d=1.20, mode="known", Asp=200,
                            asp=55)
    assert r2["need_more"] and not r2["ok"] and r2["As"] is None
    check("所需 A′s (mm²)", r2["Asp_min"],
          round((1.20 * 300e6 - 0.384 * 14.3 * 250 * 420 ** 2) / (360 * 365)))


def test_design_display_chain():
    """显示链自洽：例3-5 用显示值（0.384、303）手工复算 As 与返回值一致。"""
    print("设计显示链自洽")
    r = doubly_rect.design(M=235.0e6, b=250, h0=420, fc=14.3, fy=360,
                           xi_b=0.518, gamma_d=1.20, mode="unknown", asp=55)
    as_shown = round((14.3 * 250 * 0.518 * 420 + 360 * 303) / 360)
    check("As 复算 (mm²)", r["As"], as_shown)
    check("A′s 复算 (mm²)", r["Asp"],
          round((1.20 * 235.0e6 - 0.384 * 14.3 * 250 * 420 ** 2) / (360 * 365)))


if __name__ == "__main__":
    test_example_3_8()
    test_branch_x_lt_2asp()
    test_branch_over_reinforced()
    test_display_chain_self_consistent()
    test_example_3_5_design_unknown()
    test_example_3_6_design_known()
    test_example_3_7_design_known_xlt2asp()
    test_design_branches()
    test_design_display_chain()
    if Failures:
        print(f"\n{len(Failures)} 处不一致：")
        for f in Failures:
            print("  -", f)
        sys.exit(1)
    print("\n全部通过")
