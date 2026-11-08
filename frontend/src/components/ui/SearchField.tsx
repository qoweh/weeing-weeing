import type { ComponentPropsWithoutRef } from "react";

type Props = Omit<ComponentPropsWithoutRef<"input">, "type" | "value"> & {
  value: string;
  // Enter 키와 오른쪽 엔터(↵) 버튼이 똑같이 호출한다.
  onSearch?: () => void;
};

// 검색 입력칸. 글자가 있으면 오른쪽에 엔터 버튼이 나타나고, 누르면 Enter와 같은 검색을 실행한다.
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
      {value && onSearch && (
        <button
          type="button"
          className="search-field__enter"
          aria-label="검색 실행"
          title="검색 (Enter)"
          onClick={onSearch}
        />
      )}
    </span>
  );
}
