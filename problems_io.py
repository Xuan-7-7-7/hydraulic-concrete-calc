"""题目卡导入导出——给人看的纯文本题目交换格式（.txt）。

设计背景：exe 的使用者（同学）不懂编程，JSON 档既看不懂也不敢改；
题目卡让"分享题目"走微信/网盘发文本文件的路子——记事本、手机都能直接打开看，
收到的人在软件里「分享/备份 → 导入」即可还原成可计算题目。

格式约定（v1，宽松解析、行式键值）：
    水工受弯构件题目卡 v1 —— 由「水工混凝土受弯承载力计算」导出   ← 首行含「题目卡」即识别
    题目数：2
    ════…
    【1】类型：设计｜名称：课本例题                                  ← 卡片头
    ════…
    ── 设计输入 ────…                                               ← 分节行
    构件类型：梁                                                     ← 字段行（标签：值）
    梁宽/板计算宽 b（mm）：250
    ── 复核输入 ────…
    …
- 值存界面显示文字（下拉/开关），数字直接写数值；空值＝留空（导入后与界面空白等价）
- 空行、═/─ 分隔线、无法识别的行解析时忽略并记入 bad（不中断整卡）
- _D_FIELDS/_V_FIELDS 是标签↔键位↔选项的唯一事实源：键位与 problems.json 的
  D/V 字典一致（rho_bar 进度条等非输入控件不在列）；改界面下拉/开关文案时
  必须同步这里，否则新值导出会以内部码落盘（导入仍兼容，tests/test_problems_io
  的键位集合锚点测试会兜底提醒）
"""

import re

from kernel import spec_data
from kernel.rebar import SLAB_SPACINGS

HEADER = "水工受弯构件题目卡"

_BAR = {d: f"Φ{d}" for d in spec_data.bar_diameters()}
_ENV = {k: f"{k}类" for k in spec_data.environment_classes()}
_GAMMA_Q = {"general": "一般可变（1.30）", "controllable": "可控制可变（1.20）"}
_LEVEL = {"I": "I 级（1.1）", "II": "II 级（1.0）", "III": "III 级（0.9）"}
_SITUATION = {"持久": "持久（1.0）", "短暂": "短暂（0.95）", "偶然": "偶然（0.85）"}

# （键位, 卡片标签, 种类 num/sel/sw, 选项 {内部值: 显示文字}）——顺序即卡片行序
D_FIELDS = [
    ("member", "构件类型", "sel", {"梁": "梁", "板": "板"}),
    ("conc", "混凝土强度等级（fc）", "sel", {g: g for g in spec_data.concrete_grades()}),
    ("steel", "钢筋种类（fy）", "sel", {s: s for s in spec_data.steel_types()}),
    ("env", "环境类别", "sel", _ENV),
    ("y100", "设计使用年限 100 年", "sw", None),
    ("b", "梁宽/板计算宽 b（mm）", "num", None),
    ("h", "截面高 h（mm）", "num", None),
    ("layers", "受拉筋布置", "sel", {"1": "单层受拉筋", "2": "双层受拉筋"}),
    ("dia_est", "预估受拉筋直径（估 as 用）", "sel", _BAR),
    ("stirrup", "箍筋直径预估（mm）", "num", None),
    ("dbl", "受压筋模式", "sel",
     {"none": "单筋（无受压筋）", "unknown": "双筋·计算 A′s", "known": "双筋·已知 A′s"}),
    ("asp", "受压钢筋 a′s（mm）", "num", None),
    ("Asp_src", "受压筋输入方式", "sel", {"count": "直径×根数", "direct": "直接输入 A′s"}),
    ("dia_p", "受压筋直径", "sel", _BAR),
    ("n_p", "受压筋根数 n′", "num", None),
    ("Asp", "受压钢筋面积 A′s（mm²）", "num", None),
    ("Msrc", "弯矩来源", "sel",
     {"load": "由荷载算 M", "moments": "由弯矩标准值算 M", "direct": "直接输入 M"}),
    ("M", "弯矩设计值 M（含 γ0·ψ）（kN·m）", "num", None),
    ("MG", "恒载弯矩 MG（标准值）（kN·m）", "num", None),
    ("MQ", "活载弯矩 MQ（标准值）（kN·m）", "num", None),
    ("gk", "均布恒载 gk（kN/m）", "num", None),
    ("qk", "均布活载 qk（kN/m）", "num", None),
    ("Gk", "跨中集中恒载 Gk（kN）", "num", None),
    ("Qk", "跨中集中活载 Qk（kN）", "num", None),
    ("q_kind", "qk 的可变荷载类别", "sel", _GAMMA_Q),
    ("Q_kind", "Qk 的可变荷载类别", "sel", _GAMMA_Q),
    ("level", "结构安全级别", "sel", _LEVEL),
    ("situation", "设计状况", "sel", _SITUATION),
    ("l0src", "计算跨度来源", "sel", {"calc": "由净跨计算", "direct": "直接输入 l0"}),
    ("ln", "净跨 ln（m）", "num", None),
    ("a", "支承长度 a（m）", "num", None),
    ("l0", "计算跨度 l0（m）", "num", None),
    ("c_dia_min", "选筋最小直径", "sel", _BAR),
    ("c_dia_max", "选筋最大直径", "sel", _BAR),
    ("c_sp_min", "板筋最小间距", "sel", {s: str(s) for s in SLAB_SPACINGS}),
    ("c_sp_max", "板筋最大间距", "sel", {s: str(s) for s in SLAB_SPACINGS}),
    ("c_total", "按板宽给总根数", "sw", None),
    ("c_double", "排不下允许双层", "sw", None),
]

V_FIELDS = [
    ("member", "构件类型", "sel", {"梁": "梁", "板": "板"}),
    ("Asrc", "受拉筋输入方式", "sel",
     {"direct": "直接输入 As", "spacing": "直径@间距（板）", "count": "直径×根数（梁）"}),
    ("As", "受拉钢筋面积 As（mm²）", "num", None),
    ("dia_s", "受拉筋直径", "sel", _BAR),
    ("spacing", "板筋间距", "sel", {s: f"@{s}" for s in SLAB_SPACINGS}),
    ("dia_c", "受拉筋直径（梁·根数式）", "sel", _BAR),
    ("n", "根数 n", "num", None),
    ("b", "梁宽/板计算宽 b（mm）", "num", None),
    ("h", "截面高 h（mm）", "num", None),
    ("as", "受拉钢筋 as（mm）", "num", None),
    ("dbl", "受压筋模式", "sel",
     {"none": "单筋（无受压筋）", "count": "双筋·直径×根数", "direct": "双筋·直接输入 A′s"}),
    ("asp", "受压钢筋 a′s（mm）", "num", None),
    ("dia_p", "受压筋直径", "sel", _BAR),
    ("n_p", "受压筋根数 n′", "num", None),
    ("Asp", "受压钢筋面积 A′s（mm²）", "num", None),
    ("conc", "混凝土强度等级（fc）", "sel", {g: g for g in spec_data.concrete_grades()}),
    ("steel", "钢筋种类（fy）", "sel", {s: s for s in spec_data.steel_types()}),
    ("Msrc", "弯矩来源", "sel",
     {"direct": "直接输入 M", "moments": "由弯矩标准值算 M", "load": "由荷载算 M"}),
    ("M", "弯矩设计值 M（含 γ0·ψ）（kN·m）", "num", None),
    ("MG", "恒载弯矩 MG（标准值）（kN·m）", "num", None),
    ("MQ", "活载弯矩 MQ（标准值）（kN·m）", "num", None),
    ("gk", "均布恒载 gk（kN/m）", "num", None),
    ("qk", "均布活载 qk（kN/m）", "num", None),
    ("Gk", "跨中集中恒载 Gk（kN）", "num", None),
    ("Qk", "跨中集中活载 Qk（kN）", "num", None),
    ("q_kind", "qk 的可变荷载类别", "sel", _GAMMA_Q),
    ("Q_kind", "Qk 的可变荷载类别", "sel", _GAMMA_Q),
    ("level", "结构安全级别", "sel", _LEVEL),
    ("situation", "设计状况", "sel", _SITUATION),
    ("l0src", "计算跨度来源", "sel", {"calc": "由净跨计算", "direct": "直接输入 l0"}),
    ("ln", "净跨 ln（m）", "num", None),
    ("a", "支承长度 a（m）", "num", None),
    ("l0", "计算跨度 l0（m）", "num", None),
]

_SECTIONS = (("D", "设计输入", D_FIELDS), ("V", "复核输入", V_FIELDS))

_CARD_RE = re.compile(r"^【[^】]*】\s*类型\s*[：:]\s*(设计|复核)\s*[｜|]\s*名称\s*[：:]\s*(.+)$")
_FIELD_RE = re.compile(r"^([^：:=【】]+?)\s*[：:=]\s*(.*)$")


class _Bad(Exception):
    """单字段值无法解析（行级容错，不中断整卡）。"""


def _enc_field(kind, opts, v):
    """值 → 卡片文字。选项外的内部码原样落盘（版本容错，导入端认得）。"""
    if v is None:
        return ""
    if kind == "sw":
        return "是" if v else "否"
    if kind == "sel":
        return (opts or {}).get(v, str(v))
    if isinstance(v, int):
        return str(v)
    return f"{float(v):g}"


def _dec_field(kind, opts, text):
    """卡片文字 → 值。认显示文字，也兼容直接写内部码（手改文件的场景）。"""
    t = (text or "").strip()
    if t == "":
        return None
    if kind == "sw":
        if t in ("是", "开", "勾选", "true", "True", "1"):
            return True
        if t in ("否", "关", "false", "False", "0"):
            return False
        raise _Bad(t)
    if kind == "sel":
        opts = opts or {}
        inv = {lab: val for val, lab in opts.items()}
        if t in inv:
            return inv[t]
        for val in opts:                    # 内部码直写（如 "20"、"count"）
            if str(val) == t:
                return val
        raise _Bad(t)
    try:
        f = float(t.replace("，", "").replace(",", ""))
    except ValueError:
        raise _Bad(t) from None
    if not f.is_integer():
        return f
    return int(f)


def _safe_name(name):
    """卡片头里的名称不能含分隔符（｜/：），替换为下划线。"""
    return re.sub(r"[｜|：:]", "_", str(name or "")).strip() or "未命名"


def dump_cards(cards):
    """题目卡列表 → 文本。card = {"kind","name","D","V"}（值与存档同构，可含 None）。"""
    out = [f"{HEADER} v1 —— 由「水工混凝土受弯承载力计算」导出",
           "（本文件是给人看的题目卡：记事本/手机可直接打开；",
           "  收到的人在软件里用「分享/备份 → 导入」即可还原为可计算题目）",
           f"题目数：{len(cards)}"]
    for i, c in enumerate(cards, 1):
        bar = "═" * 34
        out += ["", bar, f"【{i}】类型：{c.get('kind') or '设计'}｜名称：{_safe_name(c.get('name'))}", bar]
        for _sec, sec_label, fields in _SECTIONS:
            vals = c.get(_sec) or {}
            out.append(f"── {sec_label} " + "─" * 24)
            for key, label, kind, opts in fields:
                out.append(f"{label}：{_enc_field(kind, opts, vals.get(key))}")
    return "\n".join(out) + "\n"


def parse_cards(text):
    """文本 → 题目卡列表。非题目卡文本抛 ValueError；坏行记入卡片的 bad 不中断。

    返回 [{"kind","name","D","V","bad":[...]}]，值已按字段类型解析（num→int/float、
    sw→bool、sel→内部值、空→None）。
    """
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first = next((l for l in lines if l.strip()), "")
    if HEADER not in first:
        raise ValueError("这不是题目卡文件：首行应含「题目卡」字样"
                         "（请用软件「分享/备份 → 导出」生成的 .txt 文件）")
    cards, cur, sec_key, sec_fields = [], None, None, None
    for ln, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or set(s) <= set("═—─-_= "):
            continue
        if HEADER in s or s.startswith(("题目数", "版本")) or "还原为可计算题目" in s:
            continue
        if s.replace("─", "").replace("—", "").replace(" ", "") in ("设计输入", "复核输入"):
            sec_key = "D" if "设计" in s else "V"
            sec_fields = dict((f[1], f) for f in (D_FIELDS if sec_key == "D" else V_FIELDS))
            continue
        m = _CARD_RE.match(s)
        if m:
            cur = {"kind": m.group(1), "name": m.group(2).strip(), "D": {}, "V": {}, "bad": []}
            cards.append(cur)
            sec_key = sec_fields = None
            continue
        fm = _FIELD_RE.match(s)
        if not (cur and sec_fields and fm):
            if cur is not None:
                cur["bad"].append(f"第{ln}行无法识别：{s[:40]}")
            continue
        label, val_text = fm.group(1).strip(), fm.group(2)
        spec = sec_fields.get(label)
        if spec is None:
            cur["bad"].append(f"第{ln}行无法识别：{label}")
            continue
        _key, _label, kind, opts = spec
        try:
            cur[sec_key][spec[0]] = _dec_field(kind, opts, val_text)
        except _Bad:
            cur[sec_key][spec[0]] = None       # 坏值显式置空（导入后=界面留空），不中断
            cur["bad"].append(f"第{ln}行「{label}」的值“{val_text.strip()[:30]}”无法识别")
    return cards
