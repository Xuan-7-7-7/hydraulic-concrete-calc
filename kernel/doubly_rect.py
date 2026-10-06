"""双筋矩形截面构件正截面受弯承载力计算（教材 3.5，例3-5~3-8 同类）。

配筋计算（3.5.2，图3-27 流程）：
  第一种情况（A′s 未知，例3-5）：式(3-17) αs；超筋（αs>αs,b）时取 αs=αs,b，
    式(3-29) A′s、式(3-30) As；未超筋则单筋即可（single_ok）。
  第二种情况（A′s 已知，例3-6/3-7）：式(3-31) 扣除已配 A′s 承担的弯矩；
    式(3-18) ξ；x≥2a′s 时式(3-32)、x<2a′s 时式(3-33)。

承载力复核（3.5.3，例3-8）：
  As、A's 按显示整数代入 → ξ = (fy·As − fy'·A's)/(fc·b·h0) 取3位
  → x = ξ·h0 取整数 mm
  → ξ ≤ ξb：
      x ≥ 2a's：Mu = fc·b·x·(h0 − x/2) + fy'·A's·(h0 − a's)   （式3-22）
      x <  2a's：Mu = fy·As·(h0 − a's)                        （式3-28，假定 x/2 = a's）
  → ξ > ξb（超筋）：教材 3.5.3 步骤(1) 取 x = ξb·h0，再代入式(3-22)
  → M' = Mu/γd（教材 3.5.3 步骤(3)：应满足 M ≤ Mu/γd）

例3-8（教材 p92~93）：As=1884（6Φ20 查表C-1）、A's=763（3Φ18 查表C-1）、
  b=250、h0=525、a's=49、fc=14.3、fy=fy'=360 → ξ=0.215、x=113>98、
  Mu=320.0×10⁶ N·mm、M'=320.0/1.20=266.67 kN·m > M=262.58 kN·m。
"""

import math


def alpha_s_b_of(xi_b):
    """表3-1：与 ξb 对应的 αs,b（按显示 3 位，教材例3-5 代入 0.384）。"""
    return round(xi_b * (1.0 - 0.5 * xi_b), 3)


def design(M, b, h0, fc, fy, xi_b, gamma_d, mode="unknown", Asp=None, asp=None,
           fyp=None, rho_min=None):
    """双筋矩形截面配筋计算（教材 3.5.2、图3-27）。M 为已含 γ0·ψ 的弯矩设计值。

    手算舍入代入链（显示位数进入下一步，与 singly_rect.design 同约定）：
      αs 取3位（αs,b 按显示 0.384 代入）→ ξ 取3位 → x=ξ·h0 取整数mm → As/A′s 取整数mm²。
    mode="unknown"（A′s 未知，例3-5）：αs ≤ αs,b 时返回 single_ok=True（按单筋设计）；
      否则式(3-29) A′s=303、式(3-30) As=2463（代入显示值 0.384、303）。
    mode="known"（A′s 已知，例3-6/3-7）：式(3-31) αs；αs > αs,b → need_more=True
      （返回按式(3-29) 所需的 Asp_min）；否则 ξ（式3-18）→ x=ξ·h0
      （例3-6：0.436→183≥110 走式3-32；例3-7：0.238→100<110 走式3-33）。

    返回 dict：alpha_s / alpha_s_b / branch；
      unknown：single_ok（单筋即可）/ Asp（计算值）/ As / total；
      known：Asp（已配，显示整数）/ As / total / xi / x；need_more=True 时 As=None、Asp_min。
    通用尾部：rho、rho_ok（传 rho_min 时）、As_min（按图3-27 的 ρmin·b·h0，仅少筋时）。
    """
    if fyp is None:
        fyp = fy
    a_s_b = alpha_s_b_of(xi_b)
    base = {"alpha_s_b": a_s_b, "mode": mode}
    if mode == "unknown":
        alpha_s = round(gamma_d * M / (fc * b * h0 ** 2), 3)      # 式(3-17)
        if alpha_s <= a_s_b:
            return {**base, "alpha_s": alpha_s, "single_ok": True, "ok": True}
        Asp_c = round((gamma_d * M - a_s_b * fc * b * h0 ** 2)
                      / (fyp * (h0 - asp)))                        # 式(3-29)
        As = round((fc * b * xi_b * h0 + fyp * Asp_c) / fy)        # 式(3-30)
        res = {**base, "alpha_s": alpha_s, "single_ok": False,
               "branch": "3-29/3-30", "Asp": Asp_c, "As": As,
               "total": As + Asp_c, "ok": True}
    else:
        Asp_in = float(round(Asp))                                 # 显示整数代入
        alpha_s = round((gamma_d * M - fyp * Asp_in * (h0 - asp))
                        / (fc * b * h0 ** 2), 3)                   # 式(3-31)
        if alpha_s > a_s_b:
            Asp_min = round((gamma_d * M - a_s_b * fc * b * h0 ** 2)
                            / (fyp * (h0 - asp)))                  # 式(3-29)
            return {**base, "alpha_s": alpha_s, "single_ok": False,
                    "need_more": True, "Asp": Asp_in, "As": None,
                    "Asp_min": Asp_min, "ok": False}
        xi = round(1.0 - math.sqrt(1.0 - 2.0 * alpha_s), 3)        # 式(3-18)
        x = round(xi * h0)
        if x >= 2 * asp:
            branch = "3-32"                                        # 例3-6
            As = round((fc * b * x + fyp * Asp_in) / fy)
        else:
            branch = "3-33"                                        # 例3-7：As = γd·M/(fy(h0−a′s))
            As = round(gamma_d * M / (fy * (h0 - asp)))
        res = {**base, "alpha_s": alpha_s, "single_ok": False, "xi": xi, "x": x,
               "branch": branch, "Asp": Asp_in, "As": As,
               "total": As + Asp_in, "ok": True}
    rho = res["As"] / (b * h0)
    res["rho"] = rho
    if rho_min is not None:
        res["rho_ok"] = rho >= rho_min
        if not res["rho_ok"]:
            res["As_min"] = math.ceil(rho_min * b * h0)            # 图3-27：按 ρmin·b·h0 配置
    else:
        res["rho_ok"] = None
    return res


def verify(As, Asp, b, h0, asp, fc, fy, xi_b, gamma_d, M=None,
           rho_min=None, fyp=None):
    """双筋承载力复核：已知实配 As、A's，求 Mu 并判断能否承担 M。

    手算舍入链：As、Asp 按显示整数代入 → ξ 取3位 → x=ξ·h0 取整数mm
    （例3-8：0.215→113）。fyp 缺省取 fy（fy' 按附录B 表B-3，与 fy 同表）。
    M 为作用在截面上的弯矩设计值（N·mm，已含 γ0·ψ），可省略（只算 Mu）。
    rho_min 传入时同时校核 ρ = As/(b·h0) ≥ ρmin（教材 p88：弯矩较大的
    双筋截面可不验算，其他情况需验算——故保留入口与单筋一致）。
    返回 dict：xi / xi_ok / x / two_asp_ok / branch / Mu / M_allowed /
    rho / rho_ok / safe。
    """
    As, Asp = round(As), round(Asp)          # 代入用显示整数（教材：1884、763）
    if fyp is None:
        fyp = fy
    xi = round((fy * As - fyp * Asp) / (fc * b * h0), 3)
    xi_ok = xi <= xi_b
    if xi_ok:
        x = round(xi * h0)
        two_asp_ok = x >= 2 * asp
        if two_asp_ok:
            branch = "3-22"
            Mu = fc * b * x * (h0 - x / 2.0) + fyp * Asp * (h0 - asp)
        else:
            branch = "3-28"                   # 假定 x/2 = a's，对受压筋合力点取矩
            Mu = fy * As * (h0 - asp)
    else:
        # 教材 3.5.3 步骤(1)：如不满足 x ≤ ξb·h0，则取 x = ξb·h0 再代入式(3-22)
        x = round(xi_b * h0)
        two_asp_ok = None
        branch = "3-22"
        Mu = fc * b * x * (h0 - x / 2.0) + fyp * Asp * (h0 - asp)
    rho = As / (b * h0)
    res = {"xi": xi, "xi_ok": xi_ok, "x": x, "two_asp_ok": two_asp_ok,
           "branch": branch, "Mu": Mu, "M_allowed": Mu / gamma_d, "rho": rho}
    if rho_min is not None:
        res["rho_ok"] = rho >= rho_min
    else:
        res["rho_ok"] = None
    if M is not None:
        res["M"] = M
        safe = xi_ok and res["M_allowed"] >= M   # 超筋一律不安全（与单筋页一致）
        if res["rho_ok"] is not None:
            safe = safe and res["rho_ok"]
        res["safe"] = safe
    return res
