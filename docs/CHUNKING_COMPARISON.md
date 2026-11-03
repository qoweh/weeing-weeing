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

## 실제 모델 검색 품질 비교

`scripts/verify_rag_e2e.py --chunking legacy|structured`로 평가 색인에 사용할
방식을 선택한다. 기본값은 `legacy`이며 웹 업로드의 설정은 바꾸지 않는다.
두 실행은 같은 평가 문서·질의, 모델, 후보 수, 최종 k, 관련도 하한을 사용해야 한다.
다음은 기존 후보 하한 `0.02`를 고정한 PowerShell 예시다.

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONUTF8 = "1"
$env:HF_HUB_OFFLINE = "1"
$env:TRANSFORMERS_OFFLINE = "1"
$env:EMBEDDING_MODEL = "BAAI/bge-m3"
$env:RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
$env:RAG_CANDIDATE_K = "30"
$env:RAG_MIN_RELEVANCE = "0.02"
$env:OMP_NUM_THREADS = "4"
$env:MKL_NUM_THREADS = "4"
$env:TOKENIZERS_PARALLELISM = "false"
uv run --no-sync python scripts/verify_rag_e2e.py --chunking legacy --backends qdrant,chroma --reranker-batch-size 2 --out outputs/rag_e2e/legacy-min-0.02.md
uv run --no-sync python scripts/verify_rag_e2e.py --chunking structured --backends qdrant,chroma --reranker-batch-size 2 --out outputs/rag_e2e/structured-min-0.02.md
```

각 실행은 백엔드별 임시 저장소에서 색인·멱등·갱신과 검색을 검사한다.
보고서의 청킹 방식·청크 수와 함께 정상 질의의 Hit@1·Hit@5·MRR, 범위 밖
질의의 거절·오반환을 비교한다. 정답 판정은 기대 문서와 키워드 기반이므로
본문 앞에 추가한 문맥·제목만으로 정답이 된 경우가 없는지도 확인해야 한다.
임베딩 캐시가 기본으로 켜져 있으므로 처리 시간을 청킹 방식의 속도 우열로 해석하지 않는다.

캐시 사용 시 첫 색인 후 평가 질의의 벡터를 미리 계산하고 임베딩 모델 참조를
해제한다. 리랭커와 두 모델을 동시에 메모리에 유지하는 부담을 줄이기 위한
평가 도구 동작이다. 이후에는 같은 입력의 벡터만 재사용하며, 캐시에 없는 입력은
오류로 처리한다. 검색·재색인·갱신 검사는 그대로 수행한다.
`--keep-embedding-model`은 이전처럼 모델을 유지하고, `--no-embedding-cache`는
사전 계산·모델 해제도 끈다. 실행한 메모리 관리 방식은 보고서에 기록된다.
`--reranker-batch-size`의 기본값은 16이다. 위 예시는 메모리가 작은 CPU 환경에서
배치 2를 사용하며, 후보 수·입력 길이를 줄이지 않는다. 비교 실행 양쪽의 배치 크기를
같게 맞추고 결과 보고서의 실행 설정을 확인한다.

2026-10-30의 [실제 모델 재평가 결과](rag_e2e/report-2026-10-30-chunking-comparison.md)에서
리랭커 Hit@1은 23/30→24/30, Hit@5는 30/30 유지, MRR은 0.869→0.878이었다.
범위 밖 거절은 5/6으로 같았고 정상 질의 2개의 순위가 내려갔다. 이 결과는
동일한 36개 질의와 하한 `0.02` 조건의 비교이며 운영 기준값 확정은 아니다.
