"""扩充数字化后的规范数据锚点校验（教材附录B/C/D 与规范正文表）。"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel import spec_data


def test_concrete_full_series():
    """附录B 表B-1/B-2：混凝土全系列强度设计值与弹性模量。"""
    expect = {  # grade: (fc, ft, Ec×10⁴)
        "C20": (9.6, 1.10, 2.55), "C25": (11.9, 1.27, 2.80),
        "C30": (14.3, 1.43, 3.00), "C35": (16.7, 1.57, 3.15),
        "C40": (19.1, 1.71, 3.25), "C45": (21.1, 1.80, 3.35),
        "C50": (23.1, 1.89, 3.45), "C55": (25.3, 1.96, 3.55),
        "C60": (27.5, 2.04, 3.60),
    }
    for grade, (fc, ft, Ec) in expect.items():
        assert spec_data.concrete_fc(grade) == fc, grade
        assert spec_data.concrete_ft(grade) == ft, grade
        assert spec_data.concrete_Ec(grade) == Ec, grade


def test_steel_full_series():
    """附录B 表B-3/B-5：钢筋全系列强度设计值与弹性模量。"""
    expect = {"HPB300": (270, 210000), "HRB400": (360, 200000),
              "RRB400": (360, 200000), "HRB500": (435, 200000)}
    for steel, (fy, Es) in expect.items():
        assert spec_data.steel_fy(steel) == fy, steel
        assert spec_data.steel_Es(steel) == Es, steel


def test_xi_b_formula_consistency():
    """ξb 与式(3-4)（规范式7.1.3）ξb=0.8/(1+fy/(0.0033·Es)) 一致。"""
    for steel in spec_data.steel_types():
        fy, Es = spec_data.steel_fy(steel), spec_data.steel_Es(steel)
        xi = 0.8 / (1.0 + fy / (0.0033 * Es))
        assert math.isclose(spec_data.xi_b(steel), xi, abs_tol=5e-4), steel


def test_rho_min_by_member():
    """表10.5.1（附录D 表D-4）：受弯构件最小配筋率分梁/板。"""
    assert spec_data.rho_min("HPB300", "梁") == 0.0025
    assert spec_data.rho_min("HRB400", "梁") == 0.0020
    assert spec_data.rho_min("HRB500", "梁") == 0.0020
    assert spec_data.rho_min("HPB300", "板") == 0.0020
    assert spec_data.rho_min("HRB400", "板") == 0.0015
    assert spec_data.rho_min("HRB500", "板") == 0.0015


def test_cover_all_env_classes():
    """附录D 表D-1：保护层最小厚度，NB/T 值（无括号）。"""
    expect = {  # env: (板, 梁)
        "一": (20, 25), "二": (25, 35), "三": (30, 45),
        "四": (45, 55), "五": (50, 60),
    }
    for env, (slab, beam) in expect.items():
        assert spec_data.cover_min(env + "类", "板") == slab, env
        assert spec_data.cover_min(env + "类", "梁") == beam, env
        # 兼容不带"类"后缀的写法
        assert spec_data.cover_min(env, "梁") == beam, env


def test_bar_area_full_series():
    """附录C 表C-1：单根钢筋公称截面面积。"""
    expect = {6: 28.3, 8: 50.3, 10: 78.5, 12: 113.1, 14: 153.9, 16: 201.1,
              18: 254.5, 20: 314.2, 22: 380.1, 25: 490.9, 28: 615.8,
              32: 804.2, 36: 1017.9, 40: 1256.6, 50: 1964.0}
    assert spec_data.bar_diameters() == sorted(expect)
    for dia, area in expect.items():
        assert spec_data.bar_area(dia) == area, dia


def test_gamma_series():
    """表2-4~2-7（规范3.2.3）：系数系列。"""
    assert spec_data.gamma0("I") == 1.1
    assert spec_data.gamma0("II") == 1.0
    assert spec_data.gamma0("III") == 0.9
    assert spec_data.psi("持久") == 1.0
    assert spec_data.psi("短暂") == 0.95
    assert spec_data.psi("偶然") == 0.85
    assert spec_data.gamma_G() == 1.10
    assert spec_data.gamma_Q("general") == 1.30
    assert spec_data.gamma_Q("controllable") == 1.20
    assert spec_data.gamma_d() == 1.20


def test_environment_classes():
    """规范表3.1.11：环境类别描述齐全。"""
    envs = spec_data.environment_classes()
    assert set(envs) == {"一", "二", "三", "四", "五"}
    assert "露天" in envs["二"]


def test_economic_rho():
    """教材3.4节：常用配筋率范围。"""
    assert spec_data.economic_rho_percent("板") == [0.4, 0.8]
    assert spec_data.economic_rho_percent("矩形梁") == [0.6, 1.5]
