import { useState } from 'react'
import Button from './Button'
import './library.scss'
import { dateLabel } from './libraryUtils'

export function Filters({
  query,
  setQuery,
  filters,
  setFilters,
  report = false,
  onRefresh,
  loading,
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
      {!report && (
        <select
          aria-label="문서 종류"
          value={filters.docType}
          onChange={(e) => setFilters({ ...filters, docType: e.target.value })}
        >
          <option value="" disabled>문서종류</option>
          <option value="all">전체</option>
          <option value="manual">매뉴얼</option>
          <option value="sop">규정·SOP</option>
          <option value="rule">룰베이스</option>
        </select>
      )}
      <Button
        onClick={() => {
          setQuery('')
          setFilters({ period: '', docType: '' })
        }}
      >
        필터 초기화
      </Button>
      <Button onClick={onRefresh} disabled={loading}>
        목록 새로고침
      </Button>
      {children}
    </div>
  )
}
export function LibraryTable({
  rows,
  report = false,
  history = false,
  title,
  compact = false,
  emptyMessage,
  onOpen,
}) {
  const documentTypes = { manual: '매뉴얼', sop: '규정·SOP', rule: '룰베이스' }
  const [sort, setSort] = useState({ key: history ? 'reviewedAt' : 'date', direction: -1 })
  const [page, setPage] = useState(1)
  const pages = Math.max(1, Math.ceil(rows.length / 10))
  const current = Math.min(page, pages)
  const sorted = rows
    .map((row, index) => ({ ...row, number: index + 1 }))
    .sort(
      (a, b) =>
        String(sort.key === 'doc_type' ? documentTypes[a.doc_type] || a.doc_type || '' : a[sort.key] ?? '').localeCompare(
          String(sort.key === 'doc_type' ? documentTypes[b.doc_type] || b.doc_type || '' : b[sort.key] ?? ''),
          'ko',
          { numeric: true },
        ) * sort.direction,
    )
    .map((row, index) => ({
      ...row,
      number: sort.key === 'number' && sort.direction === -1 ? rows.length - index : index + 1,
    }))
  const columns = history
    ? [
        ['number', '번호'],
        ['name', '보고서 번호'],
        ['issue', '사건'],
        ['asset', '설비 모델'],
        ['author', '작성자'],
        ['reviewAction', '내 최근 처리'],
        ['reviewedAt', '처리 시각'],
        ['status', '현재 상태'],
      ]
    : report
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
        ['doc_type', '문서 종류'],
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
        <table className={`library-table ${history ? 'library-table--history' : report ? 'library-table--report' : 'library-table--manual'}`}>
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
                      <span aria-hidden="true">{sort.direction === 1 ? '↑' : '↓'}</span>
                    )}
                  </button>
                </th>
              ))}
              {!report && <th>관리</th>}
            </tr>
          </thead>
          <tbody>
            {sorted.slice((current - 1) * 10, current * 10).map((r) => (
              <tr key={r.rowKey || r.id}>
                {columns.map(([key]) => (
                  <td key={key}>
                    {key === 'number' ? (
                      String(r.number).padStart(2, '0')
                    ) : key === 'name' && r.openable === false ? (
                      r.name
                    ) : key === 'name' ? (
                      <button
                        className="library-link"
                        onClick={() => onOpen(r)}
                      >
                        {r.name}
                      </button>
                    ) : key === 'doc_type' ? (
                      documentTypes[r.doc_type] || r.doc_type || '—'
                    ) : key === 'date' || key === 'reviewedAt' ? (
                      dateLabel(r[key], report || key === 'reviewedAt')
                    ) : key === 'reviewAction' ? (
                      <button className="library-link" onClick={() => onOpen(r, r.reviewVersion)} aria-label={`${r.name} ${r.reviewAction} 처리 버전 보기`}>{r.reviewAction}</button>
                    ) : key === 'author' && r.isOwn ? (
                      <>{r.author || '—'} <span className="library-own-badge">내가 작성</span></>
                    ) : key === 'status' && report && r.openable === false ? (
                      <span className={`library-status library-status--${r.tone || 'neutral'}`}>{r.status}</span>
                    ) : key === 'status' && report ? (
                      <button
                        onClick={() => onOpen(r)}
                        className={`library-status library-status--${r.tone || 'neutral'}`}
                      >
                        {history ? `v${r.currentVersion} ${r.status}` : r.status}
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
                <td colSpan={columns.length + (report ? 0 : 1)} className="library-empty">
                  {emptyMessage || `표시할 ${report ? '정비 이력이' : '문서가'} 없습니다.`}
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
