/** `Camp`(진영) → CSS 색상 변수. `tokens.css`의 `--camp-*` 를 코드에서 찾을 때 쓰는
 * 단일 지점 — 여러 컴포넌트가 각자 이 맵을 베껴 쓰면 팔레트를 바꿀 때 한 곳을
 * 놓치기 쉽다(대시보드에 후보 언급 관련 카드가 늘면서 실제로 세 번 복붙됐었다). */

export type CampKey = "conservative" | "progressive" | "centrist" | "other";

export const CAMP_COLOR: Record<CampKey, string> = {
  conservative: "var(--camp-conservative)",
  progressive: "var(--camp-progressive)",
  centrist: "var(--camp-centrist)",
  other: "var(--camp-other)",
};

/** `Lens.lineage`처럼 타입이 좁혀지지 않은 문자열에도 안전하게 쓴다. */
export function campColor(key: string): string {
  return CAMP_COLOR[key as CampKey] ?? CAMP_COLOR.other;
}
