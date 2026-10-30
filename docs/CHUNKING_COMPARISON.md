# 청킹 방식 비교 실험

웹의 신규 문서 색인은 구조 기반 방식을 사용한다. 이미 색인된 문서는 자동으로
바뀌지 않는다. 아래 비교 도구는 PDF를 두 방식으로 청킹해 Markdown 두 개를
만들며 PostgreSQL과 벡터 DB는 읽거나 변경하지 않는다.

```bash
PYTHONPATH=src uv run --no-sync python scripts/compare_chunking.py \
  path/to/document.pdf --output-dir storage/chunking-comparison \
  --doc-id DOCUMENT-ID --version 1.0 --doc-type manual --asset-id ASSET-ID
```

출력 폴더에 `<문서 ID>-기존.md`와 `<문서 ID>-구조기반.md`가 생긴다. 같은
문서 ID로 다시 실행하면 해당 두 파일을 덮어쓴다. 출력에는 문서 본문이 포함되므로
공유 전에 문서의 공개 범위를 확인한다.

새 방식은 페이지 내 `제N조(제목)`과 `P01 / P06 - 제목` 형태를 인식한다.
구조 경계에서 먼저 자르고, 긴 구간은 기존 분할기로 나누며 제목을 반복한다.
문서 ID와 인식된 절을 본문 앞에 추가한다. 인식하지 못한 구간은 기존 방식으로
처리한다. 표 행이 크기 제한보다 크면 기존 방식과 같이 행 보존을 우선한다.

페이지가 바뀌는 조항·사례는 자동으로 하나로 합치지 않으며, 모든 PDF 형식을
인식하는 것은 아니다. 기존 PDF 파서의 여백·표 추출 설정을 그대로 사용한다.
Markdown 비교만으로 검색 성능 개선이 입증되는 것은 아니다. 검색 품질은 격리된
평가 데이터로 두 방식을 비교해야 한다. `DocumentIndexer(store, chunking="legacy")`와
`DocumentIndexer(store, chunking="structured")`로 방식을 명시해 독립된 저장소에서
평가할 수 있다. 기본 `DocumentIndexer`와 기존 RAG 평가 경로는 기존 방식을 유지한다.
