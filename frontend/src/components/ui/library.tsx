import { useState, type ReactNode } from "react";

type FiltersState = { period: string; docType: string };
type Excerpt = { before: string; match: string; after: string };
type LibraryRow = {
  id: string;
  name: string;
  asset?: string;
  issue?: string;
  author?: string;
  date?: string;
  doc_type?: string;
  incidentId?: string | null;
  reportId?: string;
  status?: string;
  tone?: string;
  search_excerpt?: Excerpt;
  [key: string]: unknown;
};

import Button from "./Button";
import "./library.scss";

function escapeRegExp(text: string) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// 검색어와 일치하는 부분을 노란 원형 강조 표시로 감싼다.
function highlightText(text: string, term: string) {
  // macOS 파일명은 한글이 자모로 분해(NFD)되어 있어 조합형(NFC)으로 맞춰 비교한다.
  const value = String(text ?? "").normalize("NFC");
  const keyword = term.normalize("NFC");
  if (!keyword) return value;
  const pattern = new RegExp(`(${escapeRegExp(keyword)})`, "gi");
  // split에 묶음 괄호를 쓰면 홀수 번째 조각이 일치한 부분이다.
  return value.split(pattern).map((part, index) =>
    index % 2 ? (
      <mark key={index} className="search-hit">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

export function Filters({
  query,
  setQuery,
  filters,
  setFilters,
  report = false,
  onRefresh,
  loading,
  children,
}: {
  query: string;
  setQuery: (value: string) => void;
  filters: FiltersState;
  setFilters: (value: FiltersState) => void;
  report?: boolean;
  onRefresh: () => void;
  loading: boolean;
  children?: ReactNode;
}) {
  return (
    <div
      className={`library-filters ${report ? "library-filters--report" : "library-filters--manual"}`}
    >
      <input
        aria-label={report ? "보고서 검색" : "문서 검색"}
        placeholder={
          report
            ? "⌕  보고서 번호, 사건, 설비 모델 검색"
            : "⌕  문서명, 설비 모델 검색"
        }
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <select
        aria-label={report ? "발생 기간" : "등록 기간"}
        value={filters.period}
        onChange={(e) => setFilters({ ...filters, period: e.target.value })}
      >
        <option value="">{report ? "발생 기간" : "등록 기간"}</option>
        <option value="7">최근 7일</option>
        <option value="30">최근 30일</option>
        <option value="90">최근 90일</option>
      </select>
      {!report && (
        <select
          aria-label="문서 종류"
          value={filters.docType}
          onChange={(e) => setFilters({ ...filters, docType: e.target.value })}
        >
          <option value="" disabled>
            문서종류
          </option>
          <option value="all">전체</option>
          <option value="manual">매뉴얼</option>
          <option value="sop">규정·SOP</option>
          <option value="rule">룰베이스</option>
        </select>
      )}
      <Button
        onClick={() => {
          setQuery("");
          setFilters({ period: "", docType: "" });
        }}
      >
        필터 초기화
      </Button>
      <Button onClick={onRefresh} disabled={loading}>
        목록 새로고침
      </Button>
      {children}
    </div>
  );
}
export function filterRows<T extends LibraryRow>(
  rows: T[],
  query: string,
  filters: FiltersState,
) {
  return rows.filter(
    (r) =>
      (!query.trim() ||
        [r.name, r.asset, r.issue, r.author].some((v) =>
          String(v ?? "")
            .toLowerCase()
            .includes(query.trim().toLowerCase()),
        )) &&
      (!filters.docType ||
        filters.docType === "all" ||
        r.doc_type === filters.docType) &&
      (!filters.period ||
        (r.date &&
          new Date(r.date).getTime() >=
            Date.now() - Number(filters.period) * 86400000)),
  );
}
export function dateLabel(value: string | null | undefined, time = false) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("ko-KR", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        ...(time ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
      }).format(date);
}
// 본문에서 찾은 문장 한 줄. 검색어가 잘리지 않도록 앞 문맥은 짧게 줄인다.
function ExcerptBand({ excerpt }: { excerpt: Excerpt }) {
  const before =
    excerpt.before.length > 40
      ? `…${excerpt.before.slice(-40)}`
      : excerpt.before;
  return (
    <span className="library-excerpt">
      {before}
      <mark className="search-hit">{excerpt.match}</mark>
      {excerpt.after}
    </span>
  );
}
export function LibraryTable<T extends LibraryRow>({
  rows,
  report = false,
  title,
  compact = false,
  onOpen,
  highlight = "",
  initialSort = { key: "date", direction: -1 },
  totalCount,
  alwaysPaginate = false,
  hint = "열 제목을 클릭하여 오름차순 / 내림차순 정렬",
  emptyTitle,
  emptyHint,
}: {
  rows: T[];
  report?: boolean;
  title: string;
  compact?: boolean;
  onOpen: (row: T) => void;
  highlight?: string;
  initialSort?: { key: string; direction: number };
  totalCount?: number;
  alwaysPaginate?: boolean;
  hint?: string;
  emptyTitle?: string;
  emptyHint?: string;
}) {
  const documentTypes: Record<string, string> = {
    manual: "매뉴얼",
    sop: "규정·SOP",
    rule: "룰베이스",
  };
  const [sort, setSort] = useState(initialSort);
  const [page, setPage] = useState(1);
  const pages = Math.max(1, Math.ceil(rows.length / 10));
  const current = Math.min(page, pages);
  const sorted = rows
    .map((row, index) => ({ ...row, number: index + 1 }))
    .sort(
      (a, b) =>
        String(
          sort.key === "doc_type"
            ? documentTypes[a.doc_type || ""] || a.doc_type || ""
            : (a[sort.key] ?? ""),
        ).localeCompare(
          String(
            sort.key === "doc_type"
              ? documentTypes[b.doc_type || ""] || b.doc_type || ""
              : (b[sort.key] ?? ""),
          ),
          "ko",
          { numeric: true },
        ) * sort.direction,
    )
    .map((row, index) => ({
      ...row,
      number:
        sort.key === "number" && sort.direction === -1
          ? rows.length - index
          : index + 1,
    }));
  const columns = report
    ? [
        ["number", "번호"],
        ["name", "보고서 번호"],
        ["issue", "사건"],
        ["asset", "설비 모델"],
        ["date", "발생 시각"],
        ["author", "작성자"],
        ["status", "문서 상태"],
      ]
    : [
        ["number", "번호"],
        ["name", "문서명"],
        ["asset", "적용 설비"],
        ["doc_type", "문서 종류"],
        ["version", "버전"],
        ["date", "등록일"],
        ["status", "처리 상태"],
      ];
  return (
    <section
      className={`library-section ${compact ? "library-section--compact" : ""}`}
      aria-label={title}
    >
      <div className="library-summary">
        <h2>
          {title} <span>{totalCount ?? rows.length}건</span>
        </h2>
        <p>{hint}</p>
      </div>
      <div
        className="library-table-scroll"
        role="region"
        aria-label={`${title} 표`}
        tabIndex={0}
      >
        <table
          className={`library-table ${report ? "library-table--report" : "library-table--manual"}`}
        >
          <thead>
            <tr>
              {columns.map(([key, label]) => (
                <th
                  key={key}
                  aria-sort={
                    sort.key === key
                      ? sort.direction === 1
                        ? "ascending"
                        : "descending"
                      : "none"
                  }
                >
                  <button
                    onClick={() => {
                      setSort({
                        key,
                        direction: sort.key === key ? -sort.direction : 1,
                      });
                      setPage(1);
                    }}
                  >
                    {label}
                    {sort.key === key && (
                      <img
                        src="/assets/ICONS/50b37.svg"
                        alt=""
                        style={{
                          transform:
                            sort.direction === 1 ? "rotate(180deg)" : undefined,
                        }}
                      />
                    )}
                  </button>
                </th>
              ))}
              {!report && <th>관리</th>}
            </tr>
          </thead>
          <tbody>
            {sorted.slice((current - 1) * 10, current * 10).map((r, i) => (
              <tr
                key={r.id}
                className={
                  [
                    (report ? compact && r.incidentId : onOpen)
                      ? "library-table__clickable-row"
                      : "",
                    highlight && r.search_excerpt ? "library-row--excerpt" : "",
                  ]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
                tabIndex={
                  (report ? compact && r.incidentId : onOpen) ? 0 : undefined
                }
                onClick={
                  (report ? compact && r.incidentId : onOpen)
                    ? (event) => {
                        if (
                          event.target instanceof Element &&
                          !event.target.closest("button")
                        )
                          onOpen(r);
                      }
                    : undefined
                }
                onKeyDown={
                  (report ? compact && r.incidentId : onOpen)
                    ? (event) => {
                        if (
                          event.target === event.currentTarget &&
                          (event.key === "Enter" || event.key === " ")
                        ) {
                          event.preventDefault();
                          onOpen(r);
                        }
                      }
                    : undefined
                }
              >
                {columns.map(([key]) => (
                  <td key={key}>
                    {key === "number" ? (
                      <>
                        {String(r.number).padStart(2, "0")}
                        {highlight && r.search_excerpt && (
                          <ExcerptBand excerpt={r.search_excerpt} />
                        )}
                      </>
                    ) : key === "name" ? (
                      report && !r.incidentId && !r.reportId ? (
                        r.name
                      ) : (
                        <button
                          className={
                            report
                              ? "library-link"
                              : "library-link library-link--ellipsis"
                          }
                          title={report ? undefined : r.name}
                          onClick={() => onOpen(r)}
                        >
                          {highlightText(r.name, highlight)}
                        </button>
                      )
                    ) : key === "doc_type" ? (
                      documentTypes[r.doc_type || ""] || r.doc_type || "—"
                    ) : key === "issue" && report && r.incidentId ? (
                      <button
                        className="library-link"
                        onClick={() => onOpen(r)}
                        aria-label={`${r.issue || "사건"} 보고서 초안 열기`}
                      >
                        {r.issue || "—"}
                      </button>
                    ) : key === "date" ? (
                      dateLabel(r.date, report)
                    ) : key === "status" && report && r.incidentId ? (
                      <button
                        onClick={() => onOpen(r)}
                        className={`library-status library-status--${r.tone || "neutral"}`}
                      >
                        {r.status}
                      </button>
                    ) : (
                      String(r[key] || "—")
                    )}
                  </td>
                ))}
                {!report && (
                  <td>
                    <Button className="library-view" onClick={() => onOpen(r)}>
                      보기
                    </Button>
                  </td>
                )}
              </tr>
            ))}
            {!rows.length && (
              <tr>
                <td
                  colSpan={columns.length + (report ? 0 : 1)}
                  className="library-empty"
                >
                  {emptyTitle ? (
                    <>
                      <span
                        className="library-empty__icon"
                        aria-hidden="true"
                      />
                      <strong>{emptyTitle}</strong>
                      {emptyHint && <small>{emptyHint}</small>}
                    </>
                  ) : (
                    <>표시할 {report ? "정비 이력이" : "문서가"} 없습니다.</>
                  )}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {(!compact || alwaysPaginate || pages > 1) && (
        <div className="library-pagination">
          <Button
            aria-label="이전 페이지"
            disabled={current === 1}
            onClick={() => setPage(current - 1)}
          >
            ‹
          </Button>
          <span>
            {current} / {pages}
          </span>
          <Button
            aria-label="다음 페이지"
            disabled={current === pages}
            onClick={() => setPage(current + 1)}
          >
            ›
          </Button>
        </div>
      )}
    </section>
  );
}
