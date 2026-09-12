import { useMemo, useState } from "react";

interface Props {
  emdGroups: [string, [string, string][]][];
  selected: string[];
  onChange: (codes: string[]) => void;
}

/** 동 이름으로 고르는 shuttle 위젯 (P-004, P-005 §9) — 옛 `_emd_shuttle.html` 의 순수
 * React 이식. 왼쪽에서 자치구·이름으로 걸러 체크 → 추가 → 오른쪽에 자치구별로 모인다.
 * `selected` 는 부모(`CycleFormPage`/`CycleEditPage`)가 들고 있는 `emd_pick` 그 자체다 —
 * 제출값은 이 위젯이 아니라 그 상태가 진실이다. */
export function EmdShuttle({ emdGroups, selected, onChange }: Props) {
  const [sigunguFilter, setSigunguFilter] = useState("");
  const [nameFilter, setNameFilter] = useState("");
  const [checkedLeft, setCheckedLeft] = useState<Set<string>>(new Set());
  const [checkedRight, setCheckedRight] = useState<Set<string>>(new Set());

  const meta = useMemo(() => {
    const m = new Map<string, { name: string; sigungu: string }>();
    for (const [sigungu, items] of emdGroups) {
      for (const [code, name] of items) m.set(code, { name, sigungu });
    }
    return m;
  }, [emdGroups]);

  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const leftItems = useMemo(() => {
    const q = nameFilter.trim().toLowerCase();
    const out: { code: string; name: string; sigungu: string }[] = [];
    for (const [sigungu, items] of emdGroups) {
      if (sigunguFilter && sigungu !== sigunguFilter) continue;
      for (const [code, name] of items) {
        if (selectedSet.has(code)) continue;
        if (q && !name.toLowerCase().includes(q)) continue;
        out.push({ code, name, sigungu });
      }
    }
    return out;
  }, [emdGroups, sigunguFilter, nameFilter, selectedSet]);

  const rightGroups = useMemo(() => {
    const groups = new Map<string, { code: string; name: string }[]>();
    for (const code of selected) {
      const m = meta.get(code) ?? { name: code, sigungu: "기타" };
      if (!groups.has(m.sigungu)) groups.set(m.sigungu, []);
      groups.get(m.sigungu)!.push({ code, name: m.name });
    }
    for (const list of groups.values()) list.sort((a, b) => (a.name < b.name ? -1 : 1));
    return [...groups.entries()].sort(([a], [b]) => (a < b ? -1 : 1));
  }, [selected, meta]);

  const addChecked = () => {
    const next = new Set(selected);
    checkedLeft.forEach((code) => next.add(code));
    onChange([...next]);
    setCheckedLeft(new Set());
  };

  const removeChecked = () => {
    const next = selected.filter((code) => !checkedRight.has(code));
    onChange(next);
    setCheckedRight(new Set());
  };

  return (
    <div className="shuttle" id="emd-shuttle">
      <div className="shuttle__pane">
        <div className="shuttle__filters">
          <select
            aria-label="자치구로 거르기"
            value={sigunguFilter}
            onChange={(e) => setSigunguFilter(e.target.value)}
          >
            <option value="">자치구 전체</option>
            {emdGroups.map(([sigungu, items]) => (
              <option key={sigungu} value={sigungu}>
                {sigungu} ({items.length})
              </option>
            ))}
          </select>
          <input
            type="search"
            placeholder="동 이름 검색"
            aria-label="동 이름 검색"
            value={nameFilter}
            onChange={(e) => setNameFilter(e.target.value)}
          />
        </div>
        <ul className="shuttle__list">
          {leftItems.map((item) => (
            <li key={item.code} className="shuttle__item">
              <label>
                <input
                  type="checkbox"
                  checked={checkedLeft.has(item.code)}
                  onChange={(e) => {
                    const next = new Set(checkedLeft);
                    if (e.target.checked) next.add(item.code);
                    else next.delete(item.code);
                    setCheckedLeft(next);
                  }}
                />
                <span>{item.name}</span>
                <span className="muted small">{item.sigungu} · {item.code}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>

      <div className="shuttle__actions">
        <button type="button" aria-label="선택한 동 추가" onClick={addChecked}>&raquo;</button>
        <button type="button" aria-label="선택한 동 제거" onClick={removeChecked}>&laquo;</button>
      </div>

      <div className="shuttle__pane">
        <p className="muted small">선택된 관할 <strong>{selected.length}</strong>개</p>
        <div className="shuttle__chosen">
          {rightGroups.map(([sigungu, items]) => (
            <div key={sigungu} className="shuttle__group">
              <h4>{sigungu}</h4>
              <ul>
                {items.map((item) => (
                  <li key={item.code} className="shuttle__item">
                    <label>
                      <input
                        type="checkbox"
                        checked={checkedRight.has(item.code)}
                        onChange={(e) => {
                          const next = new Set(checkedRight);
                          if (e.target.checked) next.add(item.code);
                          else next.delete(item.code);
                          setCheckedRight(next);
                        }}
                      />
                      <span>{item.name}</span>
                      <span className="muted small">{item.code}</span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
