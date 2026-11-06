// 글꼴마다 위치가 다른 텍스트 기호(‹ › → ↗) 대신 쓰는 아이콘.
// 글자와 같은 높이·색을 따르고 flex 안에서도 크기가 변하지 않아 정렬이 어긋나지 않는다.
const paths = {
  "chevron-left": "M10 3.5 5.5 8l4.5 4.5",
  "chevron-right": "M6 3.5 10.5 8 6 12.5",
  "arrow-right": "M3 8h10M9 4l4 4-4 4",
  "arrow-up-right": "M5 11l6-6M6 5h5v5",
} as const;

export default function Glyph({
  name,
  size = "1em",
}: {
  name: keyof typeof paths;
  size?: number | string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      style={{
        display: "inline-block",
        flex: "none",
        verticalAlign: "-0.15em",
      }}
    >
      <path d={paths[name]} />
    </svg>
  );
}
