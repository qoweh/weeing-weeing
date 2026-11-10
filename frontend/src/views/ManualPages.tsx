import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type DragEvent,
} from "react";

type Manual = {
  doc_id: string;
  doc_version: string;
  source_sha256: string;
  upload_id?: string | null;
  title?: string;
  asset_id?: string;
  uploaded_at?: string;
  indexed_at?: string;
  status: string;
  doc_type?: string;
  file?: string;
  search_excerpt?: { before: string; match: string; after: string };
};
type ManualRow = ReturnType<typeof toManualRow>;
type PageActions = {
  onNavigate: (page: string) => void;
  onSessionExpired: () => void;
  onBusyChange: (busy: boolean) => void;
};

import { deleteDocument, listDocuments, uploadDocument } from "../api/client";
import DeleteDocumentDialog from "../components/ui/DeleteDocumentDialog";
import DocumentPdfModal from "../components/ui/DocumentPdfModal";
import Button from "../components/ui/Button";
import PageTitle from "../components/ui/PageTitle";
import { documentVersionFromFilename } from "../components/ui/documentVersion";
import ReplaceDocumentDialog from "../components/ui/ReplaceDocumentDialog";
import {
  Filters,
  filterRows,
  LibraryTable,
  dateLabel,
} from "../components/ui/library";
import { canControl } from "../components/auth/permissions";

const labels: Record<string, string> = {
  completed: "등록 완료",
  queued: "대기 중",
  processing: "처리 중",
  failed: "등록 실패",
  superseded: "이전 버전",
  deleting: "삭제 중",
  delete_failed: "삭제 실패",
};
function toManualRow(r: Manual) {
  return {
    ...r,
    id: `${r.doc_id}:${r.doc_version}`,
    name: r.title || r.doc_id,
    asset: r.asset_id,
    version: `v${r.doc_version}`,
    date: r.uploaded_at || r.indexed_at,
    status: labels[r.status] || r.status,
  };
}
export function ManualPage({
  user,
  onNavigate,
  onSessionExpired,
  onBusyChange,
}: PageActions & { user: { role: string; is_admin?: boolean } }) {
  const canManage = canControl(user);
  const [deleting, setDeleting] = useState<ManualRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [rows, setRows] = useState<ManualRow[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [reload, setReload] = useState(0);
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState({ period: "", docType: "" });
  const [selected, setSelected] = useState<ManualRow | null>(null);
  const [search, setSearch] = useState<{
    term: string;
    reload: number;
    items: ManualRow[];
    error: string;
  }>({ term: "", reload: -1, items: [], error: "" });
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    listDocuments()
      .then((data) => {
        if (active) setRows(data.map(toManualRow));
      })
      .catch((e) => {
        if (active) {
          setError(
            e instanceof Error ? e.message : "문서 처리에 실패했습니다.",
          );
          if (e instanceof Error && "status" in e && e.status === 401)
            onSessionExpired();
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [reload, onSessionExpired]);
  const term = query.trim();
  // Enter 키·엔터 버튼으로 검색하면 입력 대기(300ms) 없이 바로 서버에 요청한다.
  const searchNow = useRef(false);
  const [searchTick, setSearchTick] = useState(0);
  const searchPending =
    Boolean(term) && (search.term !== term || search.reload !== reload);
  useEffect(() => {
    if (!term) return;
    let cancelled = false;
    const delay = searchNow.current ? 0 : 300;
    searchNow.current = false;
    // 입력이 멈춘 뒤 300ms 후에만 서버 검색을 요청한다(Enter·엔터 버튼은 즉시).
    const timer = setTimeout(() => {
      listDocuments(term)
        .then((data) => {
          if (!cancelled)
            setSearch({
              term,
              reload,
              items: data.map(toManualRow),
              error: "",
            });
        })
        .catch((failure) => {
          if (cancelled) return;
          if (failure.status === 401) onSessionExpired();
          setSearch({ term, reload, items: [], error: failure.message });
        });
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [term, reload, searchTick, onSessionExpired]);
  async function removeDocument() {
    if (!deleting || deleteBusy || !canManage) return;
    const target = deleting;
    setDeleteBusy(true);
    onBusyChange?.(true);
    setError("");
    setNotice("");
    try {
      await deleteDocument(target);
      setRows((items) => items.filter((item) => item.id !== target.id));
      setSelected(null);
      setNotice(`‘${target.name}’ 문서와 검색 자료를 삭제했습니다.`);
      setReload((n) => n + 1);
    } catch (e) {
      if (e instanceof Error && "status" in e && e.status === 401)
        onSessionExpired();
      setError(e instanceof Error ? e.message : "문서 처리에 실패했습니다.");
    } finally {
      setDeleting(null);
      setDeleteBusy(false);
      onBusyChange?.(false);
    }
  }
  return (
    <div className="library-page" aria-label="매뉴얼 · 문서 관리">
      <PageTitle>문서내역</PageTitle>
      <Filters
        query={query}
        setQuery={setQuery}
        filters={filters}
        setFilters={setFilters}
        onRefresh={() => setReload((n) => n + 1)}
        onSearch={() => {
          searchNow.current = true;
          setSearchTick((n) => n + 1);
        }}
        loading={loading}
      >
        {canManage && (
          <Button
            variant="primary"
            className="library-upload"
            onClick={() => onNavigate("manual-upload")}
          >
            문서 등록
          </Button>
        )}
      </Filters>
      {notice && <p role="status">{notice}</p>}
      {loading || searchPending ? (
        <p role="status">
          {loading ? "문서를 불러오는 중입니다." : "문서를 검색하고 있습니다."}
        </p>
      ) : error || (term && search.error) ? (
        <p className="workspace-error" role="alert">
          {error || search.error}{" "}
          <Button onClick={() => setReload((n) => n + 1)}>다시 시도</Button>
        </p>
      ) : (
        <LibraryTable
          title="전체"
          rows={filterRows(term ? search.items : rows, "", filters)}
          highlight={term}
          onOpen={setSelected}
        />
      )}
      {deleting && (
        <DeleteDocumentDialog
          doc={deleting}
          busy={deleteBusy}
          onCancel={() => setDeleting(null)}
          onConfirm={removeDocument}
        />
      )}
      {selected && (
        <DocumentPdfModal
          key={selected.id}
          doc={selected}
          onClose={() => setSelected(null)}
          onSessionExpired={onSessionExpired}
          onDelete={canManage ? () => setDeleting(selected) : undefined}
        />
      )}
    </div>
  );
}
export function ManualUploadPage({
  onNavigate,
  onSessionExpired,
  onBusyChange,
}: PageActions) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [version, setVersion] = useState("1.0");
  const [file, setFile] = useState<File | null>(null);
  const [replacement, setReplacement] = useState<{
    docId: string;
    existingVersions: string[];
    newVersion: string;
  } | null>(null);
  const [pendingUpload, setPendingUpload] = useState<FormData | null>(null);
  const dragDepth = useRef(0);
  const formRef = useRef<HTMLFormElement>(null);

  async function uploadFormData(
    data: FormData,
    file: FormDataEntryValue | null,
    confirmedReplacement = false,
  ) {
    if (busy) return;
    setError("");
    if (
      !(file instanceof File) ||
      !file.size ||
      !file.name.toLowerCase().endsWith(".pdf") ||
      file.size > 200 * 1024 * 1024
    ) {
      setError("20 MB 이하의 비어 있지 않은 PDF 파일을 선택하세요.");
      return;
    }
    for (const name of ["doc_id", "doc_version", "asset_id"]) {
      const value = String(data.get(name)).trim();
      if (!value) {
        setError("필수 항목을 입력하세요.");
        return;
      }
      data.set(name, value);
    }
    setBusy(true);
    onBusyChange(true);
    try {
      if (!confirmedReplacement) {
        const docId = String(data.get("doc_id"));
        const docVersion = String(data.get("doc_version"));
        const existing = (await listDocuments()) as Manual[];
        const existingVersions = [
          ...new Set(
            existing
              .filter(
                (document) =>
                  document.doc_id === docId &&
                  document.doc_version !== docVersion,
              )
              .map((document) => document.doc_version),
          ),
        ];

        if (existingVersions.length) {
          setPendingUpload(data);
          setReplacement({ docId, existingVersions, newVersion: docVersion });
          return;
        }
      }

      await uploadDocument(data);
      onNavigate("manuals");
    } catch (e) {
      setError(e instanceof Error ? e.message : "문서 처리에 실패했습니다.");
      if (e instanceof Error && "status" in e && e.status === 401)
        onSessionExpired();
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  }

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const data = new FormData(e.currentTarget);
    await uploadFormData(data, data.get("file"));
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    if (!event.dataTransfer.types.includes("Files")) return;
    event.preventDefault();
    if (busy) return;
    setDragging(false);
    dragDepth.current = 0;
    const file = event.dataTransfer.files[0];
    const form = formRef.current;
    if (!file || !form) return;
    const fileInput = form.elements.namedItem("file");
    if (!(fileInput instanceof HTMLInputElement)) return;
    fileInput.files = event.dataTransfer.files;
    setFile(file);
    const droppedVersion = documentVersionFromFilename(file.name);
    setVersion(droppedVersion);
    const id = form.elements.namedItem("doc_id");
    if (id instanceof HTMLInputElement && !id.value.trim())
      id.value = file.name
        .replace(/\.pdf$/i, "")
        .trim()
        .replace(/\s+/g, "-");
    setError("");
  }

  return (
    <div
      className={`manual-upload-page ${dragging ? "manual-upload-page--dragging" : ""}`}
      onDragEnter={(event) => {
        if (!event.dataTransfer.types.includes("Files") || busy) return;
        event.preventDefault();
        dragDepth.current += 1;
        setDragging(true);
      }}
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDragLeave={(event) => {
        if (
          event.relatedTarget instanceof Node &&
          event.currentTarget.contains(event.relatedTarget)
        )
          return;
        event.preventDefault();
        dragDepth.current = 0;
        setDragging(false);
      }}
      onDrop={handleDrop}
    >
      {dragging && (
        <div className="library-drop-overlay">PDF 파일을 놓아 선택하세요</div>
      )}
      <form
        ref={formRef}
        id="manual-upload-form"
        onSubmit={submit}
        className="manual-upload-card"
      >
        <h1>문서 등록</h1>
        <fieldset disabled={busy}>
          <div className="manual-upload-fields">
            <label className="manual-upload-file">
              PDF 파일
              <span
                className={`manual-upload-drop ${file ? (/\.pdf$/i.test(file.name) ? "manual-upload-drop--ready" : "manual-upload-drop--invalid") : ""}`}
              >
                <span className="manual-upload-drop__icon" aria-hidden="true">
                  {file ? (/\.pdf$/i.test(file.name) ? "PDF" : "DOC") : ""}
                </span>
                {file ? (
                  <span className="manual-upload-drop__text">
                    <strong>{file.name}</strong>
                    <small>
                      {/\.pdf$/i.test(file.name)
                        ? `${(file.size / 1048576).toFixed(1)} MB · PDF 파일`
                        : "PDF가 아닌 파일입니다"}
                    </small>
                  </span>
                ) : (
                  <span className="manual-upload-drop__text">
                    <strong>
                      PDF 파일을 끌어다 놓거나 클릭하여 선택하세요
                    </strong>
                    <small>PDF 파일 · 최대 20 MB</small>
                  </span>
                )}
                {file && (
                  <span className="manual-upload-drop__again">다시 선택</span>
                )}
                <input
                  type="file"
                  name="file"
                  accept=".pdf,application/pdf"
                  required
                  onChange={(event) => {
                    const picked = event.target.files?.[0] ?? null;
                    setFile(picked);
                    setVersion(documentVersionFromFilename(picked?.name ?? ""));
                  }}
                />
              </span>
            </label>
            <label>
              문서 ID
              <input
                name="doc_id"
                placeholder="예: BLDC-001-MANUAL (카탈로그 문서 ID는 쓸 수 없음)"
                pattern="[^:\s]+"
                title="공백과 콜론 없이 입력하세요"
                required
              />
            </label>
            <label>
              문서 버전
              <input
                name="doc_version"
                value={version}
                onChange={(event) => setVersion(event.target.value)}
                required
              />
            </label>
            <label>
              문서 종류
              <select name="doc_type" defaultValue="manual">
                <option value="manual">매뉴얼</option>
                <option value="sop">규정·SOP</option>
                <option value="rule">룰베이스</option>
              </select>
            </label>
            <label>
              적용 설비 ID
              <input name="asset_id" defaultValue="BLDC-001" required />
            </label>
          </div>
        </fieldset>
        {error && (
          <p className="workspace-error" role="alert">
            {error}
          </p>
        )}
        {replacement && (
          <ReplaceDocumentDialog
            docId={replacement.docId}
            existingVersions={replacement.existingVersions}
            newVersion={replacement.newVersion}
            onCancel={() => {
              setReplacement(null);
              setPendingUpload(null);
            }}
            onConfirm={async () => {
              if (!pendingUpload) return;
              const pendingFile = pendingUpload.get("file");
              setReplacement(null);
              setPendingUpload(null);
              await uploadFormData(pendingUpload, pendingFile, true);
            }}
          />
        )}
      </form>
      <div className="manual-upload-back">
        <Button
          type="button"
          disabled={busy}
          onClick={() => onNavigate("manuals")}
        >
          목록
        </Button>
        <Button
          type="submit"
          form="manual-upload-form"
          variant="primary"
          disabled={busy}
        >
          문서 등록 실행{" "}
          {busy && (
            <span className="manual-upload-spinner" aria-label="등록 중" />
          )}
        </Button>
      </div>
    </div>
  );
}
