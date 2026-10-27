"""카탈로그와 저장소를 맞춘다. 바뀐 문서만 다시 색인하고, 빠진 문서는 지운다.

    항목마다  sha = sha256(파일)
              저장소에 같은 버전·sha·문서 메타데이터가 있고 complete → unchanged (건너뜀)
              없거나 다름 → indexer.index_file(path, metadata) → added / updated
    저장소에는 있는데 카탈로그에 없는 문서(report 제외) → delete_document → removed

- 같은 상태에서 다시 실행하면 아무것도 바뀌지 않는다(멱등).
- 색인이 쓰기 전에 실패하면 기존 색인이 남는다. 쓰다가 끊긴 문서는 complete=False라
  다음 실행에서 다시 색인한다.
- 문서 하나가 실패해도 나머지는 계속 처리하고, 실패는 리포트에 남긴다.
- 보고서(doc_type=report)는 승인 보고서 반영 경로(#29)로 들어오므로 지우지 않는다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from weeing_weeing.rag.catalog import Catalog, CatalogEntry, file_sha256
from weeing_weeing.rag.interface import Indexer
from weeing_weeing.rag.store import DOC_LEVEL_KEYS, DocInfo, VectorStore


@dataclass
class SyncReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)  # doc_id → 오류 메시지

    @property
    def ok(self) -> bool:
        return not self.failed


def index_metadata(entry: CatalogEntry, sha: str) -> dict[str, str]:
    """Indexer.index_file에 넘기는 값. 청크 메타데이터에 그대로 들어가야 변경 감지가 된다."""
    standard = {
        "doc_id": entry.doc_id,
        "doc_version": entry.doc_version,
        "doc_type": entry.doc_type,
        "status": entry.status,
        "title": entry.title,
        "source_path": entry.path,
        "source_sha256": sha,
    }
    return {**entry.extra, **standard}  # extra가 표준 키를 덮어쓰지 못하게


def _is_current(info: DocInfo | None, metadata: dict[str, str]) -> bool:
    if info is None or info.chunk_count == 0 or not info.complete:
        return False
    if info.doc_version != metadata["doc_version"]:
        return False
    return all(info.metadata.get(k) == metadata[k] for k in DOC_LEVEL_KEYS)


def sync(
    catalog: Catalog,
    indexer: Indexer | None,
    store: VectorStore,
    *,
    force: bool = False,
    dry_run: bool = False,
    still_listed: Callable[[str], bool] | None = None,
) -> SyncReport:
    """force: 바뀌지 않은 문서도 모두 다시 색인한다(청킹·파서를 바꿨을 때).
    모델·차원·토크나이저를 바꿨으면 저장소를 recreate=True로 만든 뒤 force로 부른다.
    dry_run: 무엇이 바뀔지만 계산한다. 이때 indexer는 None이어도 된다.
    still_listed: 지우기 직전에 목록을 다시 확인한다. 동기화하는 동안 다른 프로세스(업로드
    API)가 새로 완료한 문서를 지우지 않게 한다.
    """
    if indexer is None and not dry_run:
        raise ValueError("indexer 없이 실제 동기화를 할 수 없다(dry_run만 가능)")
    report = SyncReport()
    stored = store.documents()

    for entry in catalog.documents:
        try:
            metadata = index_metadata(entry, file_sha256(catalog.file(entry)))
            info = stored.get(entry.doc_id)
            if not force and _is_current(info, metadata):
                report.unchanged.append(entry.doc_id)
                continue
            if not dry_run:
                count = indexer.index_file(catalog.file(entry), metadata)
                _check_indexed(store, entry.doc_id, metadata, count)
            (report.updated if info else report.added).append(entry.doc_id)
        except Exception as exc:  # 한 문서 실패로 나머지를 멈추지 않는다
            report.failed[entry.doc_id] = f"{type(exc).__name__}: {exc}"

    listed = {e.doc_id for e in catalog.documents}
    for doc_id, info in sorted(stored.items()):
        if doc_id in listed or info.metadata.get("doc_type") == "report":
            continue
        try:
            if still_listed is not None and still_listed(doc_id):
                continue
            if not dry_run:
                store.delete_document(doc_id)
            report.removed.append(doc_id)
        except Exception as exc:
            report.failed[doc_id] = f"{type(exc).__name__}: {exc}"
    return report


def _check_indexed(store: VectorStore, doc_id: str, metadata: dict, count: int) -> None:
    """Indexer가 청크를 만들었고 metadata를 청크에 넣었는지 확인한다.

    넣지 않았다면 다음 실행에서 변경 감지가 안 돼 매번 다시 색인하게 된다.
    """
    if count <= 0:
        raise ValueError("청크를 하나도 만들지 못했다")
    info = store.documents(where={"doc_id": doc_id}).get(doc_id)
    if not _is_current(info, metadata):
        raise ValueError(
            "색인 후 저장소 상태가 카탈로그와 다르다. "
            "Indexer가 metadata를 청크 메타데이터에 그대로 넣는지 확인"
        )
