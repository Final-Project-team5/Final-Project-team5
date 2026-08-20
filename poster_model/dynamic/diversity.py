"""후보 다양성 계약 — Spec 수준에서 "정말 다른 디자인인가"를 잰다.

Step 5 에서 확인한 목적을 Planner 경로에서도 유지하기 위한 것이다.

```text
✗ 같은 layout + 색만 변경
✗ 같은 layout + size_step 만 조금 변경
✗ 사실상 동일한 RenderSpec 반복

○ 주요 design axis 가 구조적으로 다른 후보
```

**픽셀을 보지 않는다.** RenderSpec 만으로 판정하므로 렌더 전에 걸러 낼 수 있고,
Step 5 의 fixture 비교와 **같은 축 표**를 쓴다 (단일 출처).

이 모듈은 판정만 한다 — 부족하면 `insufficient_diversity` 를 돌려줄 뿐,
후보를 다시 만들거나 고치지 않는다. 자동 retry 는 여기 없다.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Any, Mapping, Sequence, Tuple

#: 색 관련 축. 여기만 달라진 것은 "다른 디자인"으로 치지 않는다
COLOR_AXES: Tuple[str, ...] = (
    "palette.strategy",
    "palette.roles",
    "palette.background_tone",
    "palette.spot_path",
    "palette.spot_min",
)

#: 구조 축을 범주로 묶는다 — 어느 관점에서 갈렸는지 설명할 수 있어야 한다
AXIS_CATEGORIES: Mapping[str, Tuple[str, ...]] = {
    "composition": ("grid.columns", "grid.margin_density", "grid.gutter_scale",
                    "grid.baseline_scale", "zones.type", "zones.product",
                    "zones.overlap_intent"),
    "product treatment": ("product.fit", "product.area_cap", "product.anchor",
                          "product.bleed", "product.rotation", "product.grounding"),
    "hierarchy": ("type.measure_cols", "type.break_strategy", "type.scale_step",
                  "type.role_count", "headline.face", "headline.size_step",
                  "headline.line_ratio", "headline.tracking", "copy.count",
                  "copy.layers", "copy.orientations"),
    "graphic language": ("motif.shape", "motif.min_repeats", "motif.instances",
                         "motif.pattern", "background.mode", "background.material",
                         "background.lighting", "background.texture",
                         "background.whitespace"),
}

#: "실제로 다른 설계인지" 확인하는 하한. **품질 점수가 아니다** (E12 §11)
MIN_DIFFERING_AXES = 8
#: 그중 색이 아닌 축이 최소 몇 개여야 하는가
MIN_STRUCTURAL_AXES = 6


def spec_axes(raw: Mapping[str, Any]) -> dict:
    """RenderSpec 에서 비교용 축을 뽑는다. Step 5 와 **같은 표**다."""
    z, p, t = raw["zones"], raw["product"], raw["typography"]
    pal, m, bg = raw["palette"], raw["motif"], raw["background"]
    head = next((r for r in t["roles"] if r["id"] == "headline"), t["roles"][0])
    return {
        "grid.columns": raw["grid"]["columns"],
        "grid.margin_density": raw["grid"]["margin_density"],
        "grid.gutter_scale": raw["grid"]["gutter_scale"],
        "grid.baseline_scale": raw["grid"]["baseline_scale"],
        "zones.type": (z["type"]["col_start"], z["type"]["col_span"]),
        "zones.product": (z["product"]["col_start"], z["product"]["col_span"]),
        "zones.overlap_intent": z["overlap_intent"],
        "product.fit": p["fit"],
        "product.area_cap": p.get("area_cap"),
        "product.anchor": (p["anchor"]["x"], p["anchor"]["y"]),
        "product.bleed": tuple(p.get("bleed", ())),
        "product.rotation": p["rotation"],
        "product.grounding": p["grounding"],
        "background.mode": bg["mode"],
        "background.material": bg["material"],
        "background.lighting": bg["lighting"],
        "background.texture": bg["texture"],
        "background.whitespace": bg["whitespace_strategy"],
        "type.measure_cols": t["measure_cols"],
        "type.break_strategy": t["break_strategy"],
        "type.scale_step": t["scale_step"],
        "type.role_count": len(t["roles"]),
        "headline.face": f"{head['family']}/{head['weight']}",
        "headline.size_step": head["size_step"],
        "headline.line_ratio": head["line_ratio"],
        "headline.tracking": head.get("tracking_em", 0.0),
        "palette.strategy": pal["strategy"],
        "palette.roles": tuple(pal["roles"]),
        "palette.background_tone": pal.get("background_tone"),
        "palette.spot_path": pal["rhythm"]["spot_path"],
        "palette.spot_min": pal["rhythm"]["spot_min_regions"],
        "motif.shape": m["shape"],
        "motif.min_repeats": m["min_repeats"],
        "motif.instances": len(m.get("instances", ())),
        "motif.pattern": (m.get("pattern") or {}).get("repeat", 0),
        "copy.count": len(raw["copy_blocks"]),
        "copy.orientations": tuple(sorted({b.get("orientation", "horizontal")
                                           for b in raw["copy_blocks"]})),
        "copy.layers": tuple(sorted({b["layer"] for b in raw["copy_blocks"]})),
    }


@dataclass(frozen=True)
class PairDiversity:
    a: str
    b: str
    differing: Tuple[str, ...]
    structural: Tuple[str, ...]
    categories: Tuple[str, ...]      # 실제로 갈린 범주
    sufficient: bool

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b,
                "differing": len(self.differing),
                "structural": len(self.structural),
                "categories": list(self.categories),
                "sufficient": self.sufficient,
                "axes": list(self.differing)}


@dataclass(frozen=True)
class DiversityReport:
    sufficient: bool
    pairs: Tuple[PairDiversity, ...]
    code: str = ""                   # "" | "insufficient_diversity" | "single_candidate"
    detail: str = ""

    def weakest(self):
        return min(self.pairs, key=lambda p: len(p.structural)) if self.pairs else None

    def as_dict(self) -> dict:
        return {"sufficient": self.sufficient, "code": self.code, "detail": self.detail,
                "pairs": [p.as_dict() for p in self.pairs]}


def compare_axes(name_a: str, axes_a: Mapping, name_b: str, axes_b: Mapping,
                 min_axes: int = MIN_DIFFERING_AXES,
                 min_structural: int = MIN_STRUCTURAL_AXES) -> PairDiversity:
    differing = tuple(k for k in axes_a if axes_a[k] != axes_b.get(k))
    structural = tuple(k for k in differing if k not in COLOR_AXES)
    cats = tuple(cat for cat, fields in AXIS_CATEGORIES.items()
                 if any(f in structural for f in fields))
    return PairDiversity(
        a=name_a, b=name_b, differing=differing, structural=structural, categories=cats,
        sufficient=len(differing) >= min_axes and len(structural) >= min_structural,
    )


def check_diversity(result, min_axes: int = MIN_DIFFERING_AXES,
                    min_structural: int = MIN_STRUCTURAL_AXES) -> DiversityReport:
    """후보 집합이 **실제로 다른 설계**인지 본다.

    후보가 하나면 비교 대상이 없다 — 실패가 아니라 `single_candidate` 로 적는다.
    """
    cands = list(getattr(result, "candidates", result))
    if len(cands) < 2:
        return DiversityReport(sufficient=True, pairs=(), code="single_candidate",
                               detail="후보가 하나라 비교 대상이 없다")

    axes = {c.id: spec_axes(dict(c.render_spec)) for c in cands}
    pairs = tuple(
        compare_axes(a.id, axes[a.id], b.id, axes[b.id], min_axes, min_structural)
        for a, b in combinations(cands, 2)
    )
    weak = [p for p in pairs if not p.sufficient]
    if weak:
        worst = min(weak, key=lambda p: len(p.structural))
        return DiversityReport(
            sufficient=False, pairs=pairs, code="insufficient_diversity",
            detail=(f"{worst.a} ↔ {worst.b} 가 갈린 축 {len(worst.differing)}개 "
                    f"(색 제외 {len(worst.structural)}개) — 하한 {min_axes}/{min_structural}. "
                    "같은 레이아웃에서 색이나 크기만 바뀐 후보일 수 있다"),
        )
    return DiversityReport(sufficient=True, pairs=pairs)


__all__ = [
    "COLOR_AXES",
    "AXIS_CATEGORIES",
    "MIN_DIFFERING_AXES",
    "MIN_STRUCTURAL_AXES",
    "spec_axes",
    "compare_axes",
    "check_diversity",
    "PairDiversity",
    "DiversityReport",
]
