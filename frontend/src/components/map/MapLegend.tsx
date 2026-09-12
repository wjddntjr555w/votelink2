import type { MapViewData } from "../../api/types";

const UNKNOWN_TEXT = "—";

/** `range_text` 는 백엔드 `MapView` 의 @property 라 JSON에 없다(model_dump 은
 * 필드만 내보낸다) — 프런트에서 같은 서식으로 다시 계산한다. */
function fmt(value: number, digits: number, signed: boolean): string {
  const s = value.toFixed(digits);
  return signed && value >= 0 ? `+${s}` : s;
}

function rangeText(map: MapViewData): string {
  if (map.v_min === null || map.v_max === null) {
    return `${UNKNOWN_TEXT} (${map.total}곳 중 0곳)`;
  }
  const lo = fmt(map.v_min, 1, map.metric.signed);
  const hi = fmt(map.v_max, 1, map.metric.signed);
  return `${lo} ~ ${hi}${map.metric.unit} (${map.total}곳 중 ${map.known}곳)`;
}

export function MapLegend({ map }: { map: MapViewData }) {
  return (
    <aside className="map-legend">
      <h2>{map.metric.label}</h2>
      {/* 색만 보여주면 크기를 알 수 없다 — 실제 min/max 와 분모를 적는다. */}
      <p className="mono small">{rangeText(map)}</p>
      <ul>
        {map.legend.map((stop, i) =>
          stop.fill.startsWith("url(") ? (
            <li key={i}>
              <i className="map-swatch map-swatch--hatch" />
              {stop.label}
            </li>
          ) : (
            <li key={i}>
              <i className="map-swatch" style={{ background: stop.fill }} />
              {stop.label}
            </li>
          ),
        )}
      </ul>
      <p className="muted small">
        {map.metric.scale === "divergent" ? "발산 스케일 (중심 기준 양쪽)" : "순차 스케일"}
      </p>
    </aside>
  );
}
