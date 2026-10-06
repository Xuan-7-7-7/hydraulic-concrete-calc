"""荷载与内力（式 2-35 及计算跨度），例3-1/3-2/3-4 的上游步骤。

M 的完整链条：
  设计值：g = γG·gk，q = γQ·qk，G = γG·Gk，Q = γQ·Qk
  内力：  M内 = (g+q)·l0²/8 + (G+Q)·l0/4     （简支梁/板跨中：均布 + 跨中集中）
  组合：  M = γ0·ψ·M内
计算跨度：
  梁：l0 = min{ln+a, 1.05·ln}
  板：l0 = min{ln+a, ln+h}
"""

def effective_span_beam(ln, a):
    """简支梁计算跨度 l0。ln 净跨、a 支承长度（单位一致）。"""
    return min(ln + a, 1.05 * ln)


def effective_span_slab(ln, a, h):
    """简支板计算跨度 l0。"""
    return min(ln + a, ln + h)


def midspan_M(g, q, l0, G=0.0, Q=0.0):
    """简支梁/板跨中弯矩（未乘 γ0·ψ）。

    g、q：均布荷载设计值（永久/可变），G、Q：跨中集中荷载设计值，无集中荷载时省略。
    """
    return (g + q) * l0 ** 2 / 8.0 + (G + Q) * l0 / 4.0


def M_design(gamma0, psi, M_internal):
    """式(2-35)：M = γ0·ψ·M内。"""
    return gamma0 * psi * M_internal
