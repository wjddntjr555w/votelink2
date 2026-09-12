import type { MapViewData } from "../../api/types";

/** 격자 배치 SVG. 좌표·색·범례는 전부 `viewmodel.py::build_map` 이 계산해서 낸 값을
 * 그대로 그린다 — 여기서는 산술을 하지 않는다(원칙은 Jinja 시절 map.html 과 같다). */
export function MapCanvas({ map }: { map: MapViewData }) {
  return (
    <svg className="map-svg" viewBox={map.view_box} role="img" aria-label={`${map.metric.label} 지도`}>
      <defs>
        {/* 값 없음은 색이 아니라 무늬다 — 발산 스케일에서 중립색은 0.0 과 구분되지 않는다. */}
        <pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <rect width="7" height="7" className="hatch-bg" />
          <line x1="0" y1="0" x2="0" y2="7" className="hatch-line" />
        </pattern>
      </defs>
      {map.cells.map((cell) => (
        <g key={cell.geo_code} className={cell.css_class}>
          <path d={cell.svg_path} fill={cell.fill}>
            <title>{cell.title}</title>
          </path>
          <text x={cell.label_x} y={cell.label_y} textAnchor="middle">
            <tspan x={cell.label_x} dy="-0.2em">
              {cell.geo_name}
            </tspan>
            <tspan x={cell.label_x} dy="1.3em" className="val">
              {cell.text}
            </tspan>
          </text>
        </g>
      ))}
    </svg>
  );
}
