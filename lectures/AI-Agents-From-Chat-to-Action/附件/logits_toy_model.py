# -*- coding: utf-8 -*-
"""
教学用微型 Transformer：把 logits 是怎么算出来的，逐层打印出来。

规模（故意缩到可以手算）：
    |V| = 6 个 token，d_model = 4，n = 3 个位置，1 层，1 个注意力头，d_ff = 4
    权重是手工构造的（不是训练出来的），只为了让每一步的数字干净、能看懂；
    真实模型里这套权重由梯度下降学出来。

任务：法国的首都是 → 巴黎      英国的首都是 → 伦敦
只看纯标准库，python logits_toy_model.py 直接跑。
"""
import math

VOCAB = ["法国", "首都", "是", "巴黎", "英国", "伦敦"]

# ── 词表向量（嵌入矩阵 E，同时兼任反嵌入矩阵 W_U：weight tying）────────────────
# 关键设计：巴黎 = 法国 + 首都，伦敦 = 英国 + 首都。
# 于是"把两个概念的向量加起来"就自动指向正确答案——这正是点积读出的威力。
E = [
    [1, 0, 0, 0],   # 0 法国
    [0, 1, 0, 0],   # 1 首都
    [0, 0, 1, 0],   # 2 是
    [1, 1, 0, 0],   # 3 巴黎 = 法国 + 首都
    [0, 0, 0, 1],   # 4 英国
    [0, 1, 0, 1],   # 5 伦敦 = 首都 + 英国
]
W_U = E                      # 反嵌入 = 嵌入（共享权重）

# ── 位置编码：此处取全 0，避免干扰数字；真实模型用 RoPE ─────────────────────
POS = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]

# ── RMSNorm 增益（全 1，等于不做额外缩放）─────────────────────────────────
GAIN = [1, 1, 1, 1]
EPS = 1e-6

# ── 注意力参数（行 = 输入维度，列 = 输出维度；即 out = x @ W）──────────────
# W_q 只在第 3 行非零：把"是"这个方向翻译成"同时匹配 法国 与 首都"的查询。
W_Q = [
    [0, 0, 0, 0],
    [0, 0, 0, 0],
    [1, 1, 0, 0],
    [0, 0, 0, 0],
]
W_K = [                      # 单位矩阵：Key 就是归一化后的隐状态本身
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
]
W_V = [                      # 把 法国 / 首都 两个方向都搬成 [1,1,0,0]
    [0.5, 0.5, 0, 0],
    [0.5, 0.5, 0, 0],
    [0, 0, 0, 0],
    [0, 0, 0, 0],
]
W_O = [                      # 输出投影 = 单位矩阵（不额外变换）
    [1, 0, 0, 0],
    [0, 1, 0, 0],
    [0, 0, 1, 0],
    [0, 0, 0, 1],
]

# ── 前馈参数（ReLU）─────────────────────────────────────────────────────
# W1 的四列分别是四个"检测器"：① 法国且首都 ② 法国且非"是" ③ 首都 ④ 是
W1 = [                       # 行 = 输入维度
    [1, 1, 0, 0],
    [1, 0, 1, 0],
    [0, -1, 0, 1],
    [0, 0, 0, 0],
]
W2 = [                       # 行 = 隐藏维度
    [0.5, 0.5, 0, 0],
    [0, 0, 0, 0],
    [0.25, 0.25, 0, 0],
    [0, 0, 0, 0],
]


def mv(x, W):
    """行向量 × 矩阵：out[j] = Σ_i x[i] * W[i][j]"""
    return [sum(x[i] * W[i][j] for i in range(len(x))) for j in range(len(W[0]))]


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def rmsnorm(x):
    rms = math.sqrt(sum(v * v for v in x) / len(x) + EPS)
    return [(v / rms) * g for v, g in zip(x, GAIN)], rms


def softmax(z):
    m = max(z)
    e = [math.exp(v - m) for v in z]
    s = sum(e)
    return [v / s for v in e]


def show(name, x, fmt="{:+.4f}"):
    print(f"  {name:<14}" + "[" + ", ".join(fmt.format(v) for v in x) + "]")


# ══════════════════════════════════════════════════════════════════════
ids = [0, 1, 2]                       # 法国的首都是
print("句子：", "".join(VOCAB[i] for i in ids), "→ 下一个 token 应该是 巴黎（id 3）")
print("token ids：", ids, "   n =", len(ids), "  d_model =", len(E[0]), "  |V| =", len(VOCAB))

print("\n【0】嵌入查表 + 位置")
h0 = [add(E[i], POS[t]) for t, i in enumerate(ids)]
for t, v in enumerate(h0):
    show(f"h0[{t}] ({VOCAB[ids[t]]})", v, "{:+.2f}")

print("\n【1】RMSNorm（pre-norm：先归一化再进子层）")
A, rms_vals = [], []
for t, v in enumerate(h0):
    a, r = rmsnorm(v)
    A.append(a)
    rms_vals.append(r)
    show(f"a[{t}]  rms={r:.4f}", a)

print("\n【2】Q / K / V")
Q = [mv(a, W_Q) for a in A]
K = [mv(a, W_K) for a in A]
V = [mv(a, W_V) for a in A]
for t in range(len(ids)):
    show(f"q[{t}]", Q[t])
for t in range(len(ids)):
    show(f"k[{t}]", K[t])
for t in range(len(ids)):
    show(f"v[{t}]", V[t])

print("\n【3】注意力分数 s = q·kᵀ / √d_head，√4 = 2，上三角加因果掩码 −∞")
d_head = len(E[0])
S = [[None] * len(ids) for _ in ids]
for i in range(len(ids)):
    for j in range(len(ids)):
        S[i][j] = sum(Q[i][k] * K[j][k] for k in range(d_head)) / math.sqrt(d_head) if j <= i else None
for i in range(len(ids)):
    print("      " + "  ".join("  -inf " if S[i][j] is None else f"{S[i][j]:+.3f}" for j in range(len(ids))))

print("\n【4】softmax → 注意力权重（每行和为 1；第 3 行就是要读出的关键）")
ATT = []
for i in range(len(ids)):
    row = [S[i][j] if j <= i else float("-inf") for j in range(len(ids))]
    w = softmax(row)
    ATT.append(w)
    print("      " + "  ".join(f"{v:.4f}" for v in w))
print(f"      第 3 行：α1 + α2 = {ATT[2][0] + ATT[2][1]:.4f}（几乎全给了 法国、首都）")

print("\n【5】注意力输出 = Σ α_j · v_j，再过 W_O")
attn_out = []
for i in range(len(ids)):
    acc = [0.0] * d_head
    for j in range(len(ids)):
        acc = add(acc, [ATT[i][j] * v for v in V[j]])
    attn_out.append(mv(acc, W_O))
for t in range(len(ids)):
    show(f"attn[{t}]", attn_out[t])

print("\n【6】残差相加 h1 = h0 + attn")
h1 = [add(h0[t], attn_out[t]) for t in range(len(ids))]
for t in range(len(ids)):
    show(f"h1[{t}]", h1[t])

print("\n【7】前馈：a = RMSNorm(h1) → ReLU(a·W1) → ·W2，再看残差")
h2 = []
for t in range(len(ids)):
    a, _ = rmsnorm(h1[t])
    pre = mv(a, W1)
    act = [max(0.0, v) for v in pre]
    ffn = mv(act, W2)
    if t == len(ids) - 1:
        show("a (归一化后)", a)
        show("pre-activation", pre)
        show("ReLU 之后", act, "{:.4f}")
        show("ffn 输出", ffn)
    h2.append(add(h1[t], ffn))
print("  最后一个位置的 h2:")
show("h2[2]", h2[-1])

print("\n【8】最后一次 RMSNorm（决定读出的尺度）")
h_final, rms_last = rmsnorm(h2[-1])
show(f"h_final  rms={rms_last:.4f}", h_final)

print("\n【9】logits = W_U · h_final = E · h_final（与每个 token 的向量做点积）")
logits = mv(h_final, [[W_U[j][i] for j in range(len(VOCAB))] for i in range(d_head)])
for i, name in enumerate(VOCAB):
    print(f"      logit({name:<2}) = <E[{i}], h_final> = {logits[i]:+.4f}")

print("\n【10】softmax → 概率（T = 1）")
P1 = softmax(logits)
for i, name in enumerate(VOCAB):
    print(f"      P({name:<2}) = {P1[i]:.4f}")

lse = math.log(sum(math.exp(v) for v in logits))
print(f"\n【11】logsumexp = {lse:.4f}（softmax 的归一化常数）")
print("      log p_j = logit_j − logsumexp（这正是 API 返回的 logprobs）:")
for i, name in enumerate(VOCAB):
    print(f"      log P({name:<2}) = {logits[i]:+.4f} − {lse:.4f} = {logits[i] - lse:+.4f}")

print("\n【12】温度：logits/T 之后重新 softmax，以及 top_p=0.9 会留下几个候选")
order = sorted(range(len(VOCAB)), key=lambda i: -P1[i])
print("      T      概率（按 logits 大小排）                                      top_p=0.9 留几个")
for T in (0.5, 1.0, 2.0):
    pT = softmax([v / T for v in logits])
    pretty = "  ".join(f"{VOCAB[i]}={pT[i]:.4f}" for i in order)
    keep, c = 0, 0.0
    for i in order:
        keep += 1
        c += pT[i]
        if c >= 0.9:
            break
    print(f"      {T:<5}  {pretty:<58} {keep}")

print("\n【13】贪心 vs 采样（T=1）")
print("      贪心输出：", VOCAB[max(range(len(VOCAB)), key=lambda i: logits[i])])

print("\n【14】真实规模对照（Qwen3-8B 量级：d=4096，vocab=151936，36 层）")
d, Vv, L = 4096, 151936, 36
unembed_macs = d * Vv
ffn_macs = 3 * d * 12288
attn_macs = 4 * d * d
layer_macs = ffn_macs + attn_macs
print(f"      反嵌入矩阵参数量        : {unembed_macs/1e6:,.0f} M  （{unembed_macs*4/1e9:.2f} GB fp32）")
print(f"      每 token 反嵌入乘加次数 : {unembed_macs/1e9:.3f} G MACs = {2*unembed_macs/1e9:.3f} GFLOPs")
print(f"      单层 Transformer 乘加   : {layer_macs/1e6:,.0f} M MACs ≈ {2*layer_macs/1e9:.3f} GFLOPs")
print(f"      一次反嵌入 ≈ {unembed_macs/layer_macs:.2f} 层的计算量（占 {L} 层的 {100*unembed_macs/(layer_macs*L):.1f}%）")
