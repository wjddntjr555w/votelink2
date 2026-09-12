// 외부 아이콘 폰트·CDN을 쓰지 않는다는 원칙(런타임 외부 요청 0건)을 유지하려고
// 직접 그린 인라인 SVG. votelink/web/templates/_icons.html 과 같은 세트.
const PATHS: Record<string, string> = {
  dashboard:
    "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  map: "M9 4 3 6v14l6-2 6 2 6-2V4l-6 2-6-2ZM9 4v14M15 6v14",
  news: "M3 4h18v16H3zM7 8h10M7 12h10M7 16h6",
  compare: "M12 3v18M5 7 2 15a3 3 0 0 0 6 0ZM19 7l-3 8a3 3 0 0 0 6 0Z",
  nation: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18ZM3 12h18M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z",
  cycle: "M3 4h18v17H3zM3 9h18M8 2v4M16 2v4",
  ops: "M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z",
  audit: "M4 5h16M4 12h16M4 19h10",
  bell: "M6 9a6 6 0 0 1 12 0c0 5 2 6 2 6H4s2-1 2-6ZM10 20a2 2 0 0 0 4 0",
};

export function Icon({ name, size = 16 }: { name: keyof typeof PATHS; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
