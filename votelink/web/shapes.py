"""지도 칸의 배치 좌표. **격자와 실제 경계 사이의 이음매다.**

`data/shared/reference/emd_boundaries.geojson` 이 있으면 그걸 쓰고, 없으면 격자를 만든다.
템플릿과 라우트는 둘 다 `svg_path` 만 보므로, 나중에 경계 파일 한 장을 떨구면
화면 코드는 바뀌지 않는다 (`docs/40-webapp-spec.md §11`).

A-001이 기준선에 대해 쓴 것과 같은 수법이다 — "지금 없으면 None, 나중에 들어오면
코드 변경 없이 채워진다". 실제로 그때 분석기 코드는 한 줄도 바뀌지 않았다.

**격자 칸을 손으로 배치하지 않는다.** `geo_code` 오름차순 고정이다. 대충 실제 위치처럼
놓는 것은 근거 없는 지리를 지어내는 것이고, 배치가 판단이 되는 순간 그건
`data/shared/reference/` 에 있어야 할 데이터가 된다.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, ConfigDict

BOUNDARIES_PATH = Path("data/shared/reference/emd_boundaries.geojson")

CANVAS = 300.0
"""SVG viewBox 한 변. 좌표계는 이 안에서만 의미가 있다."""

_INSET = 4.0
"""격자 칸 사이 여백. 칸 경계가 붙어 보이지 않게 한다."""

_CODE_KEYS = ("geo_code", "adm_cd", "ADM_CD", "admCd", "EMD_CD", "emd_cd")
"""GeoJSON feature 에서 행정동코드를 찾을 property 이름 후보.

실제 경계 파일이 들어오면 이 목록을 늘려야 할 수 있다. 못 찾으면 조용히 넘어가지 않고
어느 이름을 찾았는지 밝히며 실패한다.
"""


class ShapeError(ValueError):
    """경계 파일을 이해할 수 없다. 격자로 조용히 후퇴하지 않는다 —
    파일을 놓아둔 사람은 그게 쓰이기를 기대한다."""


class EmdShape(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    geo_code: str
    geo_name: str
    svg_path: str
    """SVG `<path d="...">` 값."""
    label_x: float
    label_y: float


class ShapeSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    shapes: list[EmdShape]
    is_real_boundary: bool
    """거짓이면 화면이 '실제 경계가 아니다' 고지를 띄운다. 파일이 들어오면 자동으로 사라진다."""
    view_box: str


def shapes_for(codes_and_names: list[tuple[str, str]], *, path: Path | None = None) -> ShapeSet:
    """행정동 (코드, 이름) 목록을 SVG 도형으로. 코드 오름차순으로 정렬해 배치한다."""
    ordered = sorted(codes_and_names, key=lambda pair: pair[0])
    target = path or BOUNDARIES_PATH
    if target.exists():
        return ShapeSet(
            shapes=_from_geojson(ordered, target),
            is_real_boundary=True,
            view_box=f"0 0 {CANVAS:g} {CANVAS:g}",
        )
    return ShapeSet(
        shapes=_grid(ordered),
        is_real_boundary=False,
        view_box=f"0 0 {CANVAS:g} {CANVAS:g}",
    )


# --- 격자 -----------------------------------------------------------------------


def _grid(ordered: list[tuple[str, str]]) -> list[EmdShape]:
    """정사각형에 가까운 격자. 9개면 3×3이다."""
    if not ordered:
        return []
    cols = math.ceil(math.sqrt(len(ordered)))
    rows = math.ceil(len(ordered) / cols)
    cell_w = CANVAS / cols
    cell_h = CANVAS / rows

    shapes = []
    for index, (code, name) in enumerate(ordered):
        col = index % cols
        row = index // cols
        x = col * cell_w + _INSET / 2
        y = row * cell_h + _INSET / 2
        w = cell_w - _INSET
        h = cell_h - _INSET
        shapes.append(
            EmdShape(
                geo_code=code,
                geo_name=name,
                svg_path=f"M {x:.1f} {y:.1f} h {w:.1f} v {h:.1f} h {-w:.1f} Z",
                label_x=round(x + w / 2, 1),
                label_y=round(y + h / 2, 1),
            )
        )
    return shapes


# --- 실제 경계 -------------------------------------------------------------------


def _from_geojson(ordered: list[tuple[str, str]], path: Path) -> list[EmdShape]:
    """FeatureCollection 을 SVG path 로. 등장방형 도법 + 전체 bbox 에 맞춰 확대한다.

    도법을 정교하게 고르지 않는 이유: 행정동 9개가 덮는 범위는 위경도 0.1도 남짓이라
    어떤 도법을 써도 화면에서 구분되지 않는다. 위도에 따른 경도 압축(cos)만 보정한다.
    """
    raw = json.loads(path.read_text(encoding="utf-8"))
    by_code = _index_features(raw, path)

    wanted = {code: by_code.get(code) for code, _ in ordered}
    missing = sorted(code for code, rings in wanted.items() if rings is None)
    if missing:
        raise ShapeError(f"경계 파일에 없는 행정동코드: {missing} ({path})")

    all_points = [pt for rings in wanted.values() for ring in rings for pt in ring]
    project = _projector(all_points)

    shapes = []
    for code, name in ordered:
        rings = wanted[code]
        parts = []
        for ring in rings:
            xy = [project(lon, lat) for lon, lat in ring]
            head = f"M {xy[0][0]:.1f} {xy[0][1]:.1f}"
            rest = " ".join(f"L {x:.1f} {y:.1f}" for x, y in xy[1:])
            parts.append(f"{head} {rest} Z".strip())
        cx, cy = _centroid([project(lon, lat) for lon, lat in rings[0]])
        shapes.append(
            EmdShape(
                geo_code=code,
                geo_name=name,
                svg_path=" ".join(parts),
                label_x=round(cx, 1),
                label_y=round(cy, 1),
            )
        )
    return shapes


def _index_features(raw: dict, path: Path) -> dict[str, list[list[tuple[float, float]]]]:
    features = raw.get("features") or []
    if not features:
        raise ShapeError(f"경계 파일에 feature 가 없다: {path}")

    table: dict[str, list[list[tuple[float, float]]]] = {}
    for feature in features:
        props = feature.get("properties") or {}
        code = next((str(props[k]) for k in _CODE_KEYS if k in props), None)
        if code is None:
            raise ShapeError(
                f"feature 에서 행정동코드를 찾을 수 없다: {sorted(props)[:8]} ({path}). "
                f"찾아본 이름: {list(_CODE_KEYS)} — shapes.py 의 _CODE_KEYS 를 늘려라"
            )
        table[code] = _rings(feature.get("geometry") or {})
    return table


def _rings(geometry: dict) -> list[list[tuple[float, float]]]:
    """Polygon / MultiPolygon 의 바깥 링만. 구멍(내부 링)은 그리지 않는다."""
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        return [[(float(x), float(y)) for x, y in coords[0]]] if coords else []
    if kind == "MultiPolygon":
        return [[(float(x), float(y)) for x, y in poly[0]] for poly in coords if poly]
    raise ShapeError(f"지원하지 않는 geometry: {kind!r} (Polygon / MultiPolygon 만)")


def _projector(points: list[tuple[float, float]]):
    """전체 bbox 를 캔버스에 꽉 채우되 종횡비를 유지하는 변환을 만든다."""
    lons = [lon for lon, _ in points]
    lats = [lat for _, lat in points]
    lon0, lon1 = min(lons), max(lons)
    lat0, lat1 = min(lats), max(lats)
    mid_lat = math.radians((lat0 + lat1) / 2)
    kx = math.cos(mid_lat) or 1.0

    span_x = (lon1 - lon0) * kx or 1e-9
    span_y = (lat1 - lat0) or 1e-9
    scale = min((CANVAS - _INSET) / span_x, (CANVAS - _INSET) / span_y)
    pad_x = (CANVAS - span_x * scale) / 2
    pad_y = (CANVAS - span_y * scale) / 2

    def project(lon: float, lat: float) -> tuple[float, float]:
        x = (lon - lon0) * kx * scale + pad_x
        y = CANVAS - ((lat - lat0) * scale + pad_y)  # SVG 는 y가 아래로 자란다
        return x, y

    return project


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(x for x, _ in points) / len(points),
        sum(y for _, y in points) / len(points),
    )
