"""规范数据加载层：查表数据与计算代码在这里隔离。

数据文件 kernel/data/spec_NB_T_11011-2022.json，每条数值带 source 溯源字段。
将来若改用 SQLite 或其它存储，只需改本文件，计算代码不动。
"""

import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):  # PyInstaller 打包后从解包目录读数据
    _DATA_FILE = Path(getattr(sys, "_MEIPASS", ".")) / "kernel" / "data" / "spec_NB_T_11011-2022.json"
else:
    _DATA_FILE = Path(__file__).parent / "data" / "spec_NB_T_11011-2022.json"
_cache = None


def _data():
    global _cache
    if _cache is None:
        with open(_DATA_FILE, encoding="utf-8") as f:
            _cache = json.load(f)
    return _cache


def _leaf(table, *keys):
    """取 {key: {value:..., source:...}} 形式的叶子，缺 key 时给出可读报错。"""
    node = table
    for k in keys:
        try:
            node = node[k]
        except KeyError:
            raise KeyError(f"规范数据缺项: {' → '.join((*keys, ))}，"
                           f"缺少 '{k}'（文件 {_DATA_FILE.name}，待数字化补充）") from None
    return node


def concrete_fc(grade):
    """混凝土轴心抗压强度设计值 fc (N/mm²)。grade 如 'C25'。"""
    return _leaf(_data()["concrete"], grade)["fc"]


def concrete_ft(grade):
    """混凝土轴心抗拉强度设计值 ft (N/mm²)。"""
    return _leaf(_data()["concrete"], grade)["ft"]


def concrete_Ec(grade):
    """混凝土弹性模量 Ec (×10⁴ N/mm²)。"""
    return _leaf(_data()["concrete_Ec"], grade)["value"]


def steel_fy(steel):
    """钢筋抗拉强度设计值 fy (N/mm²)。steel 如 'HRB400'。"""
    return _leaf(_data()["steel"], steel)["fy"]


def steel_Es(steel):
    """钢筋弹性模量 Es (N/mm²)。"""
    return _leaf(_data()["steel_Es"], steel)["value"]


def environment_classes():
    """环境类别→环境条件描述（规范表3.1.11）。"""
    return {k: v["value"] for k, v in _data()["environment_classes"].items()}


def economic_rho_percent(member):
    """常用（经济）配筋率范围 [%]，member '板'/'矩形梁'/'T形梁'。"""
    return _leaf(_data()["economic_rho_percent"], member)["value"]


def xi_b(steel):
    """相对界限受压区高度 ξb（适用于混凝土强度等级≤C50）。"""
    return _leaf(_data()["xi_b"], steel)["value"]


def rho_min(steel, member_type):
    """纵向受拉钢筋最小配筋率（小数，如 0.0020）。

    member_type '梁' / '板'（表10.5.1 项次1 按构件类型分档，不可省略）。
    """
    return _leaf(_data()["rho_min"], "受弯构件", member_type, steel)["value"]


def cover_min(env_class, member_type):
    """混凝土保护层最小厚度 c (mm)。env_class 如 '二类'，member_type '梁'/'板'。"""
    env = env_class[:-1] if env_class.endswith("类") else env_class
    return _leaf(_data()["cover_min"], env, member_type)["value"]


def gamma0(safety_level):
    """结构重要性系数 γ0。safety_level 'I'/'II'/'III'。"""
    return _leaf(_data()["gamma"], "gamma0", safety_level)["value"]


def psi(situation):
    """设计状况系数 ψ。situation '持久'/'短暂'。"""
    return _leaf(_data()["gamma"], "psi", situation)["value"]


def gamma_G():
    """永久荷载分项系数 γG。"""
    return _leaf(_data()["gamma"], "gamma_G")["value"]


def gamma_Q(kind="general"):
    """可变荷载分项系数 γQ。kind: 'general'（一般可变）/ 'controllable'（可控制的可变）。"""
    key = {"general": "gamma_Q_general",
           "controllable": "gamma_Q_controllable"}[kind]
    return _leaf(_data()["gamma"], key)["value"]


def gamma_d(structure="钢筋混凝土结构"):
    """结构系数 γd。"""
    return _leaf(_data()["gamma"], "gamma_d", structure)["value"]


def bar_area(dia):
    """单根钢筋公称截面面积 (mm²)。dia 为直径数值，如 16。"""
    return _leaf(_data()["bar_area_mm2"], str(dia))["value"]


def bar_area_n(dia, n):
    """n 根钢筋公称截面面积 (mm²)：1≤n≤9 查附录C 表C-1 多根列（教材手算习惯，
    如 6Φ20→1884、3Φ18→763；注意 ≠ n×单根四舍五入），n>9 按 n×单根。"""
    try:
        row = _leaf(_data()["bar_area_n_mm2"], str(dia))["value"]
    except KeyError:
        row = None
    if row and 1 <= n <= len(row):
        return row[n - 1]
    return bar_area(dia) * n


def construction(key):
    """构造规定数值（如 'beam_side_cover_mm'）。"""
    return _leaf(_data()["construction"], key)["value"]


def conc_density():
    """混凝土重力密度 γc (kN/m³)，自重 gk=b·h·γc 推导用（教材p79 例3-1）。"""
    return _leaf(_data()["construction"], "conc_density_kN_m3")["value"]


# ---------------- source 溯源（计算过程“查表出处”行用，与上面取值函数成对） ----------------

def concrete_fc_source(grade):
    return _leaf(_data()["concrete"], grade)["source"]


def steel_fy_source(steel):
    return _leaf(_data()["steel"], steel)["source"]


def xi_b_source(steel):
    return _leaf(_data()["xi_b"], steel)["source"]


def rho_min_source(steel, member_type):
    return _leaf(_data()["rho_min"], "受弯构件", member_type, steel)["source"]


def gamma0_source(safety_level):
    return _leaf(_data()["gamma"], "gamma0", safety_level)["source"]


def psi_source(situation):
    return _leaf(_data()["gamma"], "psi", situation)["source"]


def gamma_G_source():
    return _leaf(_data()["gamma"], "gamma_G")["source"]


def gamma_Q_source(kind="general"):
    key = {"general": "gamma_Q_general",
           "controllable": "gamma_Q_controllable"}[kind]
    return _leaf(_data()["gamma"], key)["source"]


def gamma_d_source(structure="钢筋混凝土结构"):
    return _leaf(_data()["gamma"], "gamma_d", structure)["source"]


def concrete_grades():
    """已数字化的混凝土强度等级列表，如 ['C20', ..., 'C60']。"""
    return list(_data()["concrete"])


def steel_types():
    """已数字化的普通钢筋种类列表。"""
    return list(_data()["steel"])


def bar_diameters():
    """已数字化的钢筋公称直径列表（mm，整数升序）。"""
    return sorted(int(d) for d in _data()["bar_area_mm2"])


def note(key):
    """数据文件 notes 中的提示文字（key 如 'cover'/'rho_min'）。"""
    return _leaf(_data()["notes"], key)
