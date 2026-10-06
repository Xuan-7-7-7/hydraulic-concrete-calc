"""选筋建议逻辑校验（对照教材例3-1/3-2 实配结果）。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from kernel.rebar import beam_bar_options, slab_bar_options


def test_example_3_1_bar_choice():
    """例3-1：As=570mm²、b=200 → 教材选 3Φ16（603mm²，排布宽度188≤200）。"""
    opts = beam_bar_options(572.0, 200)
    assert opts, "应给出至少一组建议"
    top = opts[0]
    assert top["dia"] == "Φ16" and top["cnt"] == "3根"
    assert top["area"] == "603 mm²"
    assert "188" in top["fit"]


def test_slab_spacing_table_algorithm():
    """表C-2算法：Φ8@120 = 419 mm²/m（例3-4 锚点）。"""
    assert any(o["spec"] == "Φ8@120" and o["area"].startswith("419")
               for o in slab_bar_options(398.08, max_show=50))


def test_beam_no_fit_returns_empty():
    """窄梁单层排不下时返回空表（提示用户改双层或加宽）。"""
    assert beam_bar_options(4000.0, 150) == []


def test_beam_double_respects_side_cover():
    """双层方案也必须满足两侧保护层：14Φ14@b=250（每排7根宽248>160）不再出现。"""
    assert beam_bar_options(2100, 250, dias=[14], allow_double=True) == []
    rows = beam_bar_options(1780, 250, dias=[25], allow_double=True)
    assert rows and "双层" in rows[0]["fit"], "物理可行的 4Φ25 双层（2+2）应保留"
