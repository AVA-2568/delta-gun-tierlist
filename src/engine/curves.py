"""官方效果曲线求值。

上游曲线点格式（归一化后）为 ``[input, output, interpolation_mode, arrive_tangent, leave_tangent]``：

- ``RCIM_Linear``：线性插值。
- ``RCIM_Cubic``：Unreal 引擎的 cubic hermite。切线为 ``dy/dx``，
  因此在归一化参数 ``t`` 上需乘以区间宽度 ``dx``。

区间外一律取端点值（与引擎的 clamp 行为一致）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

LINEAR = "RCIM_Linear"
CUBIC = "RCIM_Cubic"

# 一条曲线点：(input, output, interpolation, arrive_tangent, leave_tangent)
CurvePoint = Tuple[float, float, str, float, float]


def _to_point(raw: Any) -> CurvePoint:
    """把字典或序列形式的曲线点统一成元组。"""
    if isinstance(raw, dict):
        return (
            float(raw.get("inputValue", raw.get("input", 0.0))),
            float(raw.get("outputValue", raw.get("output", 0.0))),
            str(raw.get("interpolationMode", LINEAR)),
            float(raw.get("arriveTangent", 0.0)),
            float(raw.get("leaveTangent", 0.0)),
        )
    values = list(raw)
    while len(values) < 5:
        values.append(0.0 if len(values) != 2 else LINEAR)
    return (
        float(values[0]),
        float(values[1]),
        str(values[2]) if values[2] is not None else LINEAR,
        float(values[3]),
        float(values[4]),
    )


class Curve:
    """不可变的效果曲线，支持线性与三次 Hermite 插值。"""

    __slots__ = ("points",)

    def __init__(self, points: Iterable[Any]):
        parsed: List[CurvePoint] = sorted((_to_point(p) for p in points), key=lambda p: p[0])
        if not parsed:
            raise ValueError("曲线至少需要一个点")
        self.points: List[CurvePoint] = parsed

    # ------------------------------------------------------------------ #
    @property
    def input_range(self) -> Tuple[float, float]:
        return self.points[0][0], self.points[-1][0]

    @property
    def output_range(self) -> Tuple[float, float]:
        values = [p[1] for p in self.points]
        return min(values), max(values)

    def is_identity(self) -> bool:
        """判断曲线是否为恒等映射（输出恒等于输入）。"""
        return all(abs(p[0] - p[1]) < 1e-9 for p in self.points)

    # ------------------------------------------------------------------ #
    def evaluate(self, x: float) -> float:
        """求值，区间外取端点。"""
        if x <= self.points[0][0]:
            return self.points[0][1]
        if x >= self.points[-1][0]:
            return self.points[-1][1]

        for index in range(len(self.points) - 1):
            x0, y0, _, _, leave = self.points[index]
            x1, y1, _, arrive, _ = self.points[index + 1]
            if x0 <= x <= x1:
                if x1 - x0 <= 1e-12:
                    return y1
                # 使用左端点的插值模式决定该段形状
                mode = self.points[index][2]
                if mode == CUBIC:
                    return _hermite(x, x0, y0, leave, x1, y1, arrive)
                span = x1 - x0
                return y0 + (y1 - y0) * (x - x0) / span
        return self.points[-1][1]

    def sample(self, start: float, stop: float, step: float) -> List[Tuple[float, float]]:
        """按步长采样，用于表格化导出。"""
        if step <= 0:
            raise ValueError("step 必须为正数")
        samples: List[Tuple[float, float]] = []
        count = int(round((stop - start) / step))
        for index in range(count + 1):
            x = start + index * step
            samples.append((round(x, 6), self.evaluate(x)))
        return samples

    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        return f"Curve(points={len(self.points)}, range={self.input_range})"


def _hermite(x: float, x0: float, y0: float, m0: float, x1: float, y1: float, m1: float) -> float:
    """Unreal RCIM_Cubic 等价的三次 Hermite 插值（切线为 dy/dx）。"""
    dx = x1 - x0
    t = (x - x0) / dx
    t2 = t * t
    t3 = t2 * t
    h00 = 2.0 * t3 - 3.0 * t2 + 1.0
    h10 = t3 - 2.0 * t2 + t
    h01 = -2.0 * t3 + 3.0 * t2
    h11 = t3 - t2
    return h00 * y0 + h10 * dx * m0 + h01 * y1 + h11 * dx * m1


class CurveLibrary:
    """曲线库：按 ID 缓存曲线对象，避免重复解析。"""

    def __init__(self, raw: Optional[Dict[str, Any]] = None):
        self._raw: Dict[str, Any] = dict(raw or {})
        self._cache: Dict[str, Curve] = {}

    def __contains__(self, curve_id: str) -> bool:
        return curve_id in self._raw

    def ids(self) -> List[str]:
        return sorted(self._raw.keys())

    def get(self, curve_id: str) -> Curve:
        cached = self._cache.get(curve_id)
        if cached is not None:
            return cached
        raw = self._raw.get(curve_id)
        if raw is None:
            raise KeyError(f"曲线不存在：{curve_id}")
        points = raw.get("points", []) if isinstance(raw, dict) else raw
        curve = Curve(points)
        self._cache[curve_id] = curve
        return curve

    def maybe(self, curve_id: Optional[str]) -> Optional[Curve]:
        if not curve_id or curve_id not in self._raw:
            return None
        return self.get(curve_id)

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._raw)


def apply_modifier(base: float, modifier: Optional[str], value: Optional[float]) -> float:
    """按官方 modifier 语义把数值作用到基础量上。

    - ``Addend``：加法，``base + value``。
    - ``Mult_A``：增量倍率，``base * (1 + value)``。
      已验证：枪管优势射程 ``Mult_A 0.3`` 使 M4A1 初速 ``575 → 747.5``（``×1.3``）；
      ``Mult_A 0.18`` 使 ``575 → 678.5``（``×1.18``）。两条均与官方候选配装数据逐位吻合。
    - ``Mult_C``：**纯倍率**，``base * value``。
      判定依据：上游 ``Mult_C`` 取值跨越 1.0（``0.88 / 0.92 / 1.04 / 1.16``），
      若按 ``(1+value)`` 解释则输出恒 >1（即任何该修饰符只会让目标变差），与
      「既有减后坐/减散布也有加重后坐」的配件分布矛盾；且 ``13020000173`` 的
      ``ShotDistance Mult_C 0.7`` 不参与初速（官方候选初速恰为 ``×1.18``，仅由 attr2 决定），
      说明 ``Mult_C`` 是独立于增量语义的缩放因子。
    - ``Initial``：绝对值覆盖（若为引用型则不改动，见 ``value_ref``）。
    """
    if value is None:
        return base
    if modifier == "Addend":
        return base + value
    if modifier == "Mult_A":
        return base * (1.0 + value)
    if modifier == "Mult_C":
        return base * value
    if modifier == "Initial":
        return value
    return base
