"""命中部位概率推导：预瞄中心 + 二维高斯散布 + 正面轮廓积分。

产物写入 ``data/tables/scenarios.json`` 的自定义情景（``probability_preset`` =
``volume-aim``），本脚本只负责**复现**该分布，不参与运行期计算。

模型（参数全部显式，可审计）：

- 人体正面轮廓：身高 1.75 m，中线 x=0，按部位划分矩形区间（见 :data:`PARTS`）；
- 胸腹分界：0.98–1.52 m 的躯干按「胸:腹 = 1:2」求解，得分界 1.348 m，
  与剑突解剖高度（1.30–1.35 m）吻合；
- 预瞄点：1.30 m（胸腹交界，背心中央偏上）；
- 弹着点：以预瞄点为中心的二维高斯，垂直标准差 ``SIGMA_V``，水平
  ``SIGMA_H_RATIO × SIGMA_V``；
- 部位概率 = 该部位轮廓内的高斯质量 / 全轮廓高斯质量。

参数取值的依据：

- ``SIGMA_V = 0.28 m``：20 m 处约 0.8°、10 m 处约 1.6° 的垂直瞄准误差；
- ``SIGMA_H_RATIO = 0.50``：横向误差为垂直的一半（垂直受后坐主导，横向仅跟枪误差）。
  该校准使上臂+前臂合计 19.6%，与官方 default 的 19.1% 独立吻合。

用法::

    python tools/derive_hit_probabilities.py            # 打印分布
    python tools/derive_hit_probabilities.py --json     # 输出可直接写入情景表的 JSON
"""

from __future__ import annotations

import argparse
import json
import math
from typing import Dict, List, Tuple

HEIGHT = 1.75
TORSO_BOTTOM = 0.98
TORSO_TOP = 1.52
CHEST_TO_ABDOMEN = 1.0 / 2.0  # 胸:腹 = 1:2
AIM_Y = 1.30
SIGMA_V = 0.28
SIGMA_H_RATIO = 0.50
GRID_STEP = 0.005

#: 躯干分界高度：由「胸:腹 = 1:2」与宽度解得
TORSO_SPLIT_Y = (TORSO_TOP * 0.32 * 2 + TORSO_BOTTOM * 0.30) / (0.32 * 2 + 0.30)

#: (部位, x 下界, x 上界, y 下界, y 上界)；只写右半侧，左半镜像
PARTS: List[Tuple[str, float, float, float, float]] = [
    ("head", 0.000, 0.0775, 1.520, 1.750),
    ("chest", 0.000, 0.1600, TORSO_SPLIT_Y, 1.520),
    ("abdomen", 0.000, 0.1500, 0.980, TORSO_SPLIT_Y),
    ("upperArm", 0.140, 0.2400, 1.130, 1.470),
    ("lowerArm", 0.160, 0.2450, 0.820, 1.180),
    ("thigh", 0.020, 0.1700, 0.520, 0.980),
    ("calf", 0.015, 0.1250, 0.000, 0.520),
]

#: 重叠区归属优先级：肢体覆盖躯干边缘
PRIORITY = {"head": 0, "upperArm": 1, "lowerArm": 1, "thigh": 1, "calf": 1,
            "chest": 2, "abdomen": 2}

PART_ORDER = ("head", "chest", "abdomen", "upperArm", "lowerArm", "thigh", "calf")


def build_grid(step: float = GRID_STEP) -> List[Tuple[str, float, float]]:
    """离散化右半侧正面轮廓，返回 ``[(部位, x, y)]``。"""
    cells: List[Tuple[str, float, float]] = []
    for iy in range(int(HEIGHT / step) + 1):
        y = iy * step + step / 2
        for ix in range(int(0.30 / step) + 1):
            x = ix * step + step / 2
            best = None
            for name, x0, x1, y0, y1 in PARTS:
                if x0 <= x <= x1 and y0 <= y <= y1:
                    if best is None or PRIORITY[name] < PRIORITY[best]:
                        best = name
            if best is not None:
                cells.append((best, x, y))
    return cells


def compute(
    sigma_v: float = SIGMA_V,
    sigma_h_ratio: float = SIGMA_H_RATIO,
    aim_y: float = AIM_Y,
) -> Dict[str, float]:
    """返回归一化后的部位命中概率（键同官方 ``hitProbabilities``）。"""
    sigma_h = sigma_v * sigma_h_ratio
    acc: Dict[str, float] = {part: 0.0 for part in PART_ORDER}
    for part, x, y in build_grid():
        weight = math.exp(-0.5 * ((y - aim_y) / sigma_v) ** 2) * math.exp(
            -0.5 * (x / sigma_h) ** 2
        )
        # 右半侧 ×2；中线附近不重复计
        acc[part] += weight * (1.0 if x < GRID_STEP else 2.0)
    total = sum(acc.values())
    return {part: acc[part] / total for part in PART_ORDER}


def rounded(probs: Dict[str, float], digits: int = 4) -> Dict[str, float]:
    """四舍五入到 ``digits`` 位，并把残差并入最大项，保证合计为 1。"""
    out = {part: round(probs[part], digits) for part in PART_ORDER}
    diff = round(1.0 - sum(out.values()), digits)
    if diff:
        head = max(out, key=lambda p: out[p])
        out[head] = round(out[head] + diff, digits)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出情景表可直接使用的 JSON")
    args = parser.parse_args()

    probs = compute()
    table = rounded(probs)
    if args.json:
        print(json.dumps(table, ensure_ascii=False, indent=2))
        return

    print(f"躯干分界 {TORSO_SPLIT_Y:.4f} m（胸:腹 = 1:{1 / CHEST_TO_ABDOMEN:.0f}）")
    print(f"预瞄点 {AIM_Y:.2f} m，sigma_v={SIGMA_V:.2f} m，sigma_h={SIGMA_V * SIGMA_H_RATIO:.3f} m")
    print()
    print(f"{'部位':10s}{'概率':>9s}{'官方 default':>14s}{'体积基准':>11s}")
    official = {"head": 17.24, "chest": 30.46, "abdomen": 18.97, "upperArm": 12.00,
                "lowerArm": 7.11, "thigh": 7.11, "calf": 7.11}
    volume = {"head": 8.1, "chest": 28.3, "abdomen": 21.4, "upperArm": 5.6,
              "lowerArm": 4.4, "thigh": 20.0, "calf": 12.2}
    for part in PART_ORDER:
        print(f"{part:10s}{table[part] * 100:8.2f}%{official[part]:13.2f}%{volume[part]:10.2f}%")
    print(f"{'合计':10s}{sum(table.values()) * 100:8.2f}%")
    print()
    print(f"头 {table['head'] * 100:.2f}% / 躯干 {(table['chest'] + table['abdomen']) * 100:.2f}% "
          f"/ 臂 {(table['upperArm'] + table['lowerArm']) * 100:.2f}% "
          f"/ 腿 {(table['thigh'] + table['calf']) * 100:.2f}%")


if __name__ == "__main__":
    main()
