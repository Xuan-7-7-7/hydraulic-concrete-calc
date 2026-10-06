"""单筋矩形截面正截面受弯承载力计算内核（NB/T 11011-2022）。

设计方向（例3-1/3-2/3-3）：
    式(3-17)  αs = γd·M / (fc·b·h0²)      —— M 为已含 γ0·ψ 的弯矩设计值
    式(3-18)  ξ  = 1 - √(1-2αs)
    式(3-19)  As = fc·b·ξ·h0 / fy
复核方向（例3-4）——上面三步的逆运算：
    式(3-14)  ξ  = fy·As / (fc·b·h0)
    式(3-12)  αs = ξ(1-0.5ξ)
    式(3-13)  Mu = αs·fc·b·h0²，与 M 比较（M允许 = Mu/γd）

γd 始终作用在"效应"一侧：设计时乘进 M，复核时除在 Mu 上。

单位约定：弯矩 N·mm，应力 N/mm²，长度 mm，面积 mm²。
"""

import math


def alpha_s_from_M(M, b, h0, fc, gamma_d):
    """式(3-17)。"""
    return gamma_d * M / (fc * b * h0 ** 2)


def xi_from_alpha_s(alpha_s):
    """式(3-18)。αs > 0.5 时判别式无实根，返回 None（必然超筋）。"""
    disc = 1.0 - 2.0 * alpha_s
    if disc < 0.0:
        return None
    return 1.0 - math.sqrt(disc)


def alpha_s_from_xi(xi):
    """式(3-12)。"""
    return xi * (1.0 - 0.5 * xi)


def alpha_s_max(xi_b):
    """与 ξb 对应的 αs 上限，即超筋判据：αs > αs,max 则超筋。"""
    return alpha_s_from_xi(xi_b)


def rho_max(fc, fy, xi_b):
    """式(3-10b) 适筋最大配筋率：ρmax = 0.85·ξb·fc/fy。"""
    return 0.85 * xi_b * fc / fy


def As_from_xi(xi, b, h0, fc, fy):
    """式(3-19)。"""
    return fc * b * xi * h0 / fy


def design(M, b, h0, fc, fy, xi_b, rho_min, gamma_d):
    """截面设计：已知弯矩设计值 M（N·mm，已含 γ0·ψ），求受拉钢筋面积 As。

    按教材手算习惯逐步舍入代入——显示用的三位小数值进入下一步：
      αs 取3位 → ξ = 1-√(1-2αs) 取3位 → As = fc·b·ξ·h0/fy
      教材例3-1：0.219 → 0.250 → As=570mm²（全精度为 572，判据与显示自洽）。
    超筋判据与教材一致取 ξ > ξb（例3-3：“ξ=0.564>ξb=0.518，不满足”）。

    返回 dict：
      alpha_s / xi / As / rho          中间量与结果（超筋时 As、rho 为 None）
      over_reinforced                  ξ > ξb（或 αs>0.5 无实根），需加大截面、提高混凝土等级或改双筋
      under_reinforced                 ρ < ρmin，属少筋，需减小截面或加筋
      ok                               设计可行（不超筋且不少筋）
      alpha_s_max                      超筋判据阈值，供调用方提示
    """
    alpha_s = round(alpha_s_from_M(M, b, h0, fc, gamma_d), 3)
    a_max = alpha_s_max(xi_b)
    xi_raw = xi_from_alpha_s(alpha_s)
    xi = round(xi_raw, 3) if xi_raw is not None else None
    if xi is None or xi > xi_b:
        # 超筋：ξ>ξb（或 αs>0.5 无实根），单筋截面无解
        return {"alpha_s": alpha_s, "alpha_s_max": a_max, "xi": xi,
                "As": None, "rho": None,
                "over_reinforced": True, "under_reinforced": False, "ok": False}
    As = round(As_from_xi(xi, b, h0, fc, fy))   # 教材 As 按整数 mm² 写（570/398/1890）
    rho = As / (b * h0)
    under = rho < rho_min
    return {"alpha_s": alpha_s, "alpha_s_max": a_max, "xi": xi, "As": As,
            "rho": rho, "over_reinforced": False,
            "under_reinforced": under, "ok": not under}


def verify(As, b, h0, fc, fy, xi_b, gamma_d, M=None, rho_min=None):
    """承载力复核：已知实配受拉钢筋面积 As，求 Mu 并判断能否承担 M。

    同为手算舍入链：As 按显示整数代入 → ξ 取3位 → αs = ξ(1-0.5ξ) 取3位
    → Mu = αs·fc·b·h0²
    （教材例3-4：419 → 0.104 → 0.099 → Mu=9.76×10⁶ N·mm，M′=8.13kN·m）。
    M 为作用在截面上的弯矩设计值（N·mm，已含 γ0·ψ），可省略（只算 Mu）。
    rho_min 传入时同时校核实际配筋率不少于最小配筋率。
    返回 dict：xi / xi_ok / alpha_s / Mu / M_allowed(=Mu/γd) / rho / rho_ok /
    safe（xi_ok 且 rho_ok 且 M_allowed≥M）。
    """
    As = round(As)                       # 代入用显示整数（教材：As=419mm²）
    xi = round(fy * As / (fc * b * h0), 3)
    alpha_s = round(alpha_s_from_xi(xi), 3)
    Mu = alpha_s * fc * b * h0 ** 2
    rho = As / (b * h0)
    res = {"xi": xi, "xi_ok": xi <= xi_b, "alpha_s": alpha_s, "Mu": Mu,
           "M_allowed": Mu / gamma_d, "rho": rho}
    if rho_min is not None:
        res["rho_ok"] = rho >= rho_min
    else:
        res["rho_ok"] = None
    if M is not None:
        res["M"] = M
        safe = res["xi_ok"] and res["M_allowed"] >= M
        if res["rho_ok"] is not None:
            safe = safe and res["rho_ok"]
        res["safe"] = safe
    return res


def suggest_h(M, b, fc, fy, xi_b, rho_min, gamma_d, as_fn, member="梁",
              mod=None, h_range=(200, 2000)):
    """超筋/少筋时反解可行截面高 h（例3-3 教材人工试算的自动化）。

    as_fn(h) -> as：按当前布筋方式给出高度扣减（单层 cs+d/2、双层 cs+35，与 h 无关）。
    mod：h 取整模数——梁 50、板 10（与教材试算习惯一致）。
    返回 {"h_min": 可行区间最小h或None, "h_max": 可行区间最大h或None, "mod": 模数}：
      超筋 → 取 h_min；少筋 → 取 h_max；区间不存在时两者均为 None。
    """
    mod = mod or (50 if member == "梁" else 10)
    lo, hi = h_range
    ok_hs = []
    h = int(math.ceil(lo / mod) * mod)
    while h <= hi:
        as_ = as_fn(h)
        if 0 < as_ < h:
            r = design(M, b, h - as_, fc, fy, xi_b, rho_min, gamma_d)
            if not r["over_reinforced"] and not r["under_reinforced"]:
                ok_hs.append(h)
        h += mod
    if not ok_hs:
        return {"h_min": None, "h_max": None, "mod": mod}
    # 超筋调用时取可行区间最小 h；少筋时取最大 h——由调用方按判定方向选用
    return {"h_min": ok_hs[0], "h_max": ok_hs[-1], "mod": mod}


def min_h0_for_M(As, M, b, fc, fy, gamma_d):
    """复核受弯承载力不足时反解最小有效高度 h0（闭式解）。

    ξ = fy·As/(fc·b·h0) 代入 Mu = αs·fc·b·h0² 化简得
      Mu(h0) = fy·As·h0 − (fy·As)²/(2·fc·b)   （h0 的线性函数）
    令 Mu ≥ γd·M 解出 h0。
    """
    a = fy * As
    return (gamma_d * M + a * a / (2.0 * fc * b)) / a


def min_h0_for_xi(As, b, fc, fy, xi_b):
    """复核超筋时反解最小有效高度 h0：ξ = fy·As/(fc·b·h0) ≤ ξb。"""
    return fy * As / (xi_b * fc * b)


def Mu_of_rho(rho, b, h0, fc, fy):
    """给定配筋率 ρ=As/(b·h0) 的极限受弯承载力（闭式，供破坏形态扫描图用）。

    由 ξ = fy·ρ/fc 代入 Mu = ξ(1-0.5ξ)·fc·b·h0² 化简：
      Mu = b·h0²·(fy·ρ − fy²·ρ²/(2·fc))
    顶点在 ρ = fc/fy（混凝土受压控制），过顶点后承载力下降——超筋特征。
    """
    return b * h0 * h0 * (fy * rho - fy * fy * rho * rho / (2.0 * fc))
