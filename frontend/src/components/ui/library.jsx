import { useState } from 'react'
import Button from './Button'
import './library.scss'

export function Filters({
  rows,
  query,
  setQuery,
  filters,
  setFilters,
  report = false,
  children,
}) {
  return (
    <div className={`library-filters ${report ? 'library-filters--report' : 'library-filters--manual'}`}>
      <input
        aria-label={report ? '보고서 검색' : '문서 검색'}
        placeholder={
          report
            ? '⌕  보고서 번호, 사건, 설비 모델 검색'
            : '⌕  문서명, 설비 모델 검색'
        }
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      <select
        aria-label={report ? '발생 기간' : '등록 기간'}
        value={filters.period}
        onChange={(e) => setFilters({ ...filters, period: e.target.value })}
      >
        <option value="">{report ? '발생 기간' : '등록 기간'}</option>
        <option value="7">최근 7일</option>
        <option value="30">최근 30일</option>
        <option value="90">최근 90일</option>
      </select>
      <select
        aria-label="설비 모델"
        value={filters.asset}
        onChange={(e) => setFilters({ ...filters, asset: e.target.value })}
      >
        <option value="">설비 모델</option>
        {[...new Set(rows.map((r) => r.asset).filter(Boolean))]
          .sort()
          .map((a) => (
            <option key={a}>{a}</option>
          ))}
      </select>
      <select
        aria-label={report ? '문서 상태' : '처리 상태'}
        value={filters.status}
        onChange={(e) => setFilters({ ...filters, status: e.target.value })}
      >
        <option value="">{report ? '문서 상태' : '처리 상태'}</option>
        {[...new Set(rows.map((r) => r.status))].map((s) => (
          <option key={s}>{s}</option>
        ))}
      </select>
      <Button
        onClick={() => {
          setQuery('')
          setFilters({ period: '', asset: '', status: '' })
        }}
      >
        필터 초기화
      </Button>
      {children}
    </div>
  )
}
export function filterRows(rows, query, filters) {
  return rows.filter(
    (r) =>
      (!query.trim() ||
        [r.name, r.asset, r.issue, r.author].some((v) =>
          String(v ?? '')
            .toLowerCase()
            .includes(query.trim().toLowerCase()),
        )) &&
      (!filters.asset || r.asset === filters.asset) &&
      (!filters.status || r.status === filters.status) &&
      (!filters.period ||
        (r.date &&
          new Date(r.date).getTime() >=
            Date.now() - Number(filters.period) * 86400000)),
  )
}
export function dateLabel(value, time = false) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime())
    ? '—'
    : new Intl.DateTimeFormat('ko-KR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        ...(time ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}),
      }).format(date)
}
export function LibraryTable({
  rows,
  report = false,
  title,
  compact = false,
  onOpen,
}) {
  const [sort, setSort] = useState({ key: 'date', direction: -1 })
  const [page, setPage] = useState(1)
  const pages = Math.max(1, Math.ceil(rows.length / 10))
  const current = Math.min(page, pages)
  const sorted = rows
    .map((row, index) => ({ ...row, number: rows.length - index }))
    .sort(
      (a, b) =>
        String(a[sort.key] ?? '').localeCompare(
          String(b[sort.key] ?? ''),
          'ko',
          { numeric: true },
        ) * sort.direction,
    )
  const columns = report
    ? [
        ['number', '번호'],
        ['name', '보고서 번호'],
        ['issue', '사건'],
        ['asset', '설비 모델'],
        ['date', '발생 시각'],
        ['author', '작성자'],
        ['status', '문서 상태'],
      ]
    : [
        ['number', '번호'],
        ['name', '문서명'],
        ['asset', '적용 설비'],
        ['version', '버전'],
        ['date', '등록일'],
        ['status', '처리 상태'],
      ]
  return (
    <section
      className={`library-section ${compact ? 'library-section--compact' : ''}`}
      aria-label={title}
    >
      <div className="library-summary">
        <h2>
          {title} <span>{rows.length}건</span>
        </h2>
        <p>열 제목을 클릭하여 오름차순 / 내림차순 정렬</p>
      </div>
      <div className="library-table-scroll" role="region" aria-label={`${title} 표`} tabIndex={0}>
        <table className="library-table">
          <thead>
            <tr>
              {columns.map(([key, label]) => (
                <th
                  key={key}
                  aria-sort={
                    sort.key === key
                      ? sort.direction === 1
                        ? 'ascending'
                        : 'descending'
                      : 'none'
                  }
                >
                  <button
                    onClick={() => {
                      setSort({
                        key,
                        direction: sort.key === key ? -sort.direction : 1,
                      })
                      setPage(1)
                    }}
                  >
                    {label}
                    {sort.key === key && (
                      <img
                        src="/assets/ICONS/50b37.svg"
                        alt=""
                        style={{
                          transform:
                            sort.direction === 1 ? 'rotate(180deg)' : undefined,
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
              <tr key={r.id}>
                {columns.map(([key]) => (
                  <td key={key}>
                    {key === 'number' ? (
                      String(r.number).padStart(2, '0')
                    ) : key === 'name' ? (
                      <button
                        className="library-link"
                        onClick={() => onOpen(r)}
                      >
                        {r.name}
                      </button>
                    ) : key === 'date' ? (
                      dateLabel(r.date, report)
                    ) : key === 'status' && report ? (
                      <button
                        onClick={() => onOpen(r)}
                        className={`library-status library-status--${r.tone || 'neutral'}`}
                      >
                        {r.status}
                      </button>
                    ) : (
                      r[key] || '—'
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
                <td colSpan={7} className="library-empty">
                  표시할 {report ? '정비 이력이' : '문서가'} 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {(!compact || pages > 1) && (
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
  )
}
