"""题目卡导入导出（problems_io）回归。

锚点说明：D_FIELDS/V_FIELDS 的键位集合是硬编码锚点——界面上新增/删除输入字段时
必须同步 problems_io 的字段表，否则导出会漏字段/导入认不出，这里负责兜底提醒。
"""

from problems_io import D_FIELDS, V_FIELDS, dump_cards, parse_cards

# 界面 D/V 控件的全部可存值键位（= problems.json 的 D/V 键，去 rho_bar 进度条）
_D_WIDGET_KEYS = {
    "member", "conc", "steel", "env", "y100", "b", "h", "layers", "dia_est",
    "stirrup", "dbl", "asp", "Asp_src", "dia_p", "n_p", "Asp", "Msrc", "M",
    "MG", "MQ", "gk", "qk", "Gk", "Qk", "q_kind", "Q_kind", "level",
    "situation", "l0src", "ln", "a", "l0", "c_dia_min", "c_dia_max",
    "c_sp_min", "c_sp_max", "c_total", "c_double",
}
_V_WIDGET_KEYS = {
    "member", "Asrc", "As", "dia_s", "spacing", "dia_c", "n", "b", "h", "as",
    "dbl", "asp", "dia_p", "n_p", "Asp", "conc", "steel", "Msrc", "M",
    "MG", "MQ", "gk", "qk", "Gk", "Qk", "q_kind", "Q_kind", "level",
    "situation", "l0src", "ln", "a", "l0",
}


def test_spec_covers_widget_keys():
    """字段表键位必须与界面控件键位一一对应（多/少都算漂移）。"""
    assert {k for k, *_ in D_FIELDS} == _D_WIDGET_KEYS
    assert {k for k, *_ in V_FIELDS} == _V_WIDGET_KEYS


def test_dump_parse_round_trip():
    """导出→导入应无损还原（含 None/bool/int/float/下拉码；名称含分隔符被消毒）。"""
    card = {"kind": "复核", "name": "例3-8｜双筋:梁",
            "D": {"member": "梁", "conc": "C30", "steel": "HRB400", "env": "二",
                  "y100": False, "b": 250, "h": 600.0, "layers": "2", "dia_est": 20,
                  "stirrup": 10, "dbl": "known", "asp": 55, "Asp_src": "count",
                  "dia_p": 18, "n_p": 3, "Asp": 763, "Msrc": "load",
                  "M": None, "MG": None, "MQ": None,
                  "gk": 2.5, "qk": 0.0, "Gk": 0.0, "Qk": 80, "q_kind": "general",
                  "Q_kind": "general", "level": "I", "situation": "持久",
                  "l0src": "direct", "ln": None, "a": None, "l0": 6.5,
                  "c_dia_min": 12, "c_dia_max": 25, "c_sp_min": 70,
                  "c_sp_max": 330, "c_total": True, "c_double": True},
            "V": {"member": "梁", "Asrc": "count", "As": 2199, "dia_s": 20,
                  "spacing": 120, "dia_c": 18, "n": 6, "b": 250, "h": 600,
                  "as": 65, "dbl": "count", "asp": 49, "dia_p": 18, "n_p": 3,
                  "Asp": 763, "conc": "C30", "steel": "HRB400", "Msrc": "direct",
                  "M": 235.0, "MG": None, "MQ": None, "gk": None, "qk": None,
                  "Gk": None, "Qk": None, "q_kind": "general", "Q_kind": "general",
                  "level": "II", "situation": "持久", "l0src": "direct",
                  "ln": None, "a": None, "l0": 6.5}}
    text = dump_cards([card])
    got = parse_cards(text)
    assert len(got) == 1
    g = got[0]
    assert g["kind"] == "复核" and g["name"] == "例3-8_双筋_梁"
    assert g["D"] == card["D"]
    assert g["V"] == card["V"]
    assert g["bad"] == []
    # 类型锚点：整数落 int、非整数落 float、开关落 bool（整值 float 坍缩 int 是预期）
    assert isinstance(g["D"]["b"], int) and isinstance(g["D"]["h"], int)
    assert g["V"]["M"] == 235 and isinstance(g["D"]["gk"], float) and g["D"]["gk"] == 2.5
    assert g["D"]["y100"] is False and g["D"]["c_total"] is True


def test_parse_rejects_non_card():
    """非题目卡文本必须明确报错（提示去导出，而不是吞进解析器）。"""
    for text in ("随便一段话", "", "题目数：3\nb=250"):
        try:
            parse_cards(text)
        except ValueError:
            pass
        else:
            raise AssertionError(f"应拒绝文本：{text!r}")


def test_parse_tolerates_bad_lines():
    """坏行只记入 bad，不中断同卡与后续卡。"""
    text = dump_cards([
        {"kind": "设计", "name": "好题", "D": {"b": 250, "h": 500}, "V": {}}])
    text = text.replace("梁宽/板计算宽 b（mm）：250", "梁宽/板计算宽 b（mm）：二百五\n不认识的行：x")
    text += "\n【2】类型：复核｜名称：第二题\n── 复核输入 ──\n截面高 h（mm）：300\n"
    cards = parse_cards(text)
    assert len(cards) == 2
    assert cards[0]["D"]["b"] is None            # 坏值 → 空
    assert any("二百五" in b for b in cards[0]["bad"])
    assert any("不认识的行" in b for b in cards[0]["bad"])
    assert cards[0]["D"]["h"] == 500             # 同卡好行不受牵连
    assert cards[1]["V"]["h"] == 300             # 后续卡正常


def test_parse_accepts_raw_codes_and_fullwidth():
    """手改文件场景：下拉直写内部码、半角冒号/等号、布尔 0/1 都应认。"""
    text = dump_cards([{"kind": "设计", "name": "t",
                        "D": {"member": "梁", "conc": "C25", "dia_p": 18, "y100": False},
                        "V": {}}])
    text = text.replace("构件类型：梁", "构件类型 = 板").replace(
        "混凝土强度等级（fc）：C25", "混凝土强度等级（fc）:C40").replace(
        "受压筋直径：Φ18", "受压筋直径：20").replace(
        "设计使用年限 100 年：否", "设计使用年限 100 年：1")
    card = parse_cards(text)[0]
    assert card["D"]["member"] == "板"
    assert card["D"]["conc"] == "C40"
    assert card["D"]["dia_p"] == 20
    assert card["D"]["y100"] is True
