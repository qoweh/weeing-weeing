import type { ComponentPropsWithoutRef } from "react";

type Props = Omit<ComponentPropsWithoutRef<"input">, "type" | "value"> & {
  value: string;
  // Enter 키로 호출한다.
  onSearch?: () => void;
};

// 검색 입력칸. Enter 키를 누르면 onSearch를 실행한다.
export default function SearchField({
  value,
  onSearch,
  onKeyDown,
  className = "",
  ...props
}: Props) {
  return (
    <span className={`search-field ${className}`}>
      <input
        {...props}
        type="search"
        value={value}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          // 한글 입력 중 조합을 확정하는 Enter는 검색으로 보지 않는다.
          if (event.key === "Enter" && !event.nativeEvent.isComposing)
            onSearch?.();
        }}
      />
    </span>
  );
}
