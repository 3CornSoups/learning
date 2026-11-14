"""
toy_grpo.py —— 用纯 numpy 做的最小对照实验
================================================
目的：只验证一件事 —— GRPO 的「组内归一化」到底有没有用。

场景：上下文老虎机（contextual bandit）
  · 有 P 道题（prompt），每道题有 K 个候选答案
  · 每个 (题, 答案) 组合有一个隐藏的真实质量 Q，模型看不见
  · 模型只能：出一道题 → 按自己的概率分布抽 G 个答案 → 拿到带噪声的分数

对比两种算法：
  none  = 最朴素的策略梯度：直接用分数当优势（A = r），没有基线
  grpo  = GRPO：同一道题抽 G 个答案，用组内均值和标准差归一化
                 A_i = (r_i - mean(r)) / (std(r) + eps)

运行：
  python3 code/toy_grpo.py
"""

import numpy as np

P = 256          # 题目数
K = 12           # 每题的候选答案数
G = 8            # 每题采样几个（GRPO 的 group size）
STEPS = 400      # 训练步数
BATCH = 64       # 每步用多少道题
LR = 2.0
NOISE = 0.10     # 奖励噪声（模拟奖励模型打分抖动）
SEEDS = [0, 1, 2, 3, 4]


def softmax(z):
    z = z - z.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def sample_from(p, n_samples, rng):
    """按概率 p 向量化地从每行采样 n_samples 个下标（逆 CDF 法）"""
    cdf = np.cumsum(p, axis=-1)
    u = rng.random((p.shape[0], n_samples))
    idx = (u[..., None] > cdf[:, None, :]).sum(axis=-1)
    return np.clip(idx, 0, p.shape[1] - 1)      # 浮点误差兜底


def run(mode="grpo", seed=0):
    rng = np.random.default_rng(seed)

    # 隐藏真相：每个 (题, 答案) 的真实质量，[0,1] 之间，答案之间有差距
    Q = rng.random((P, K))

    Z = np.zeros((P, K))          # 策略参数 = logits，初始均匀
    curve = []

    for step in range(STEPS):
        idx = rng.integers(0, P, BATCH)          # 本步抽到的题
        p = softmax(Z[idx])                      # (B,K) 当前策略
        act = sample_from(p, G, rng)             # (B,G) 每题 G 个答案
        r = Q[idx[:, None], act] + NOISE * rng.standard_normal((BATCH, G))

        if mode == "grpo":
            adv = (r - r.mean(axis=1, keepdims=True)) / (r.std(axis=1, keepdims=True) + 1e-6)
        else:
            adv = r                              # 没有基线，直接用分数

        # 策略梯度：∇log π(a) = onehot(a) - p
        onehot = np.zeros((BATCH, G, K))
        np.put_along_axis(onehot, act[..., None], 1.0, axis=-1)
        grad = (adv[..., None] * (onehot - p[:, None, :])).mean(axis=1)
        Z[idx] += LR * grad

        curve.append(r.mean())

    # 评估：① 最优答案命中率  ② 期望奖励（用最终策略算 softmax 加权）
    best_hit = (Z.argmax(axis=1) == Q.argmax(axis=1)).mean()
    final_r = (softmax(Z) * Q).sum(axis=1).mean()

    early = float(np.mean(curve[:20]))
    late = float(np.mean(curve[-20:]))
    gain100 = float(np.mean(curve[80:100]) - np.mean(curve[:20]))
    return dict(early=early, late=late, gain100=gain100,
                best_hit=best_hit, final_r=final_r, curve=curve)


def sparkline(xs, width=56):
    chars = "▁▂▃▄▅▆▇█"
    n = len(xs)
    step = max(1, n // width)
    ys = [np.mean(xs[i:i + step]) for i in range(0, n, step)][:width]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or 1.0
    return "".join(chars[min(len(chars) - 1, int((y - lo) / span * (len(chars) - 1)))] for y in ys)


if __name__ == "__main__":
    print(f"设置：{P} 题 × {K} 个答案，每题采样 G={G}，{STEPS} 步，batch={BATCH}，奖励噪声 {NOISE}")
    print(f"随机种子：{SEEDS}\n")

    res = {}
    for mode in ("none", "grpo"):
        rows = [run(mode, s) for s in SEEDS]
        res[mode] = rows

    print(f"{'算法':<14}{'前20步均分':>11}{'末20步均分':>11}{'前100步涨幅':>13}{'最优解命中':>12}{'策略期望分':>12}")
    print("-" * 76)
    for mode, name in (("none", "无基线"), ("grpo", "GRPO")):
        rows = res[mode]
        f = lambda k: np.mean([r[k] for r in rows])
        print(f"{name:<14}{f('early'):>9.3f}{f('late'):>9.3f}"
              f"{f('gain100'):>14.3f}{f('best_hit'):>11.1%}{f('final_r'):>12.3f}")

    print("\n训练曲线（每行 5 个种子，左→右 = 步数 0 → 400）")
    for mode, name in (("none", "无基线"), ("grpo", "GRPO")):
        print(f"\n  {name}")
        for i, r in enumerate(res[mode]):
            print(f"    seed{i}  {sparkline(r['curve'])}")

    n, g = res["none"], res["grpo"]
    d_hit = np.mean([x["best_hit"] for x in g]) - np.mean([x["best_hit"] for x in n])
    d_gain = np.mean([x["gain100"] for x in g]) - np.mean([x["gain100"] for x in n])
    print("\n结论")
    print(f"  · 前 100 步涨幅：GRPO 高 {d_gain:+.3f}")
    print(f"  · 最终命中最优答案：GRPO 高 {d_hit:+.1%}")
    print("  · 两者用的样本量、学习率、网络结构完全一样，唯一区别就是「优势怎么算」。")
    print("  · 这就是 GRPO 的全部：把分数换成「在你这一组里排第几」，梯度噪声自然变小。")
