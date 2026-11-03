# 임베딩·리랭크 API 선정

RAG 검색에 쓰는 임베딩·리랭커를 무엇으로 돌리는지, 왜 그렇게 정했는지, 다른 후보는 무엇인지 정리한다.
결정은 [DECISIONS](DECISIONS.md) D-31, 데이터가 외부로 나가는 문제는 [AI_DATA_SECURITY](AI_DATA_SECURITY.md).
가격·모델명은 **2026-11-03 공식 페이지 기준**이다. 바뀌기 쉬우므로 쓰기 전에 아래 출처를 다시 확인한다.

## 결론

| 항목 | 지금 설정(기본) | 키가 생기면 |
|---|---|---|
| 임베딩 | `EMBEDDING_PROVIDER=hashing`: 형태소 토큰 해시 벡터. **외부 호출·토큰 0** | `EMBEDDING_PROVIDER=voyage`, `voyage-4-lite`(1024차원) |
| 리랭커 | `RERANKER_MODEL=`(빈 값): 끔. RRF 순위 그대로, **토큰 0** | `RERANKER_MODEL=rerank-3-lite` |
| 키워드 검색 | Kiwi BM25(기존 그대로, 로컬 계산) | 그대로 |
| 로컬 AI 모델 | 없음(bge-m3·bge-reranker-v2-m3·torch 제거) | 없음 |

- 로컬 모델(가중치 다운로드)은 쓰지 않는다. 서버 디스크·메모리를 아끼고 배포 이미지를 줄인다.
- 지금 가진 키는 Claude(Anthropic)뿐이다. **Anthropic은 임베딩 모델을 제공하지 않는다**("Anthropic does not offer its own embedding model", Anthropic 문서). 그래서 Claude 키로는 임베딩을 만들 수 없다.
- 토큰을 가장 적게 쓰는 방법은 임베딩·리랭크에 API를 아예 쓰지 않는 것이다. 그래서 기본값은 해시 임베딩 + BM25 + 리랭커 끔이다. 검색 품질은 의미 검색보다 낮다(아래 "hashing의 한계").
- Claude로 리랭킹(LLM에게 후보 순서 매기기)도 가능하지만 검색마다 후보 본문 전체를 토큰으로 보내 비용이 가장 크다. 넣지 않았다.

## 설정

`.env`(값 설명은 `.env.example`의 RAG 절):

```bash
# 기본: 비용 0
EMBEDDING_PROVIDER=hashing
EMBEDDING_MODEL=
EMBEDDING_DIM=1024
RERANKER_MODEL=

# Voyage로 바꿀 때
EMBEDDING_PROVIDER=voyage
EMBEDDING_MODEL=voyage-4-lite        # 비우면 voyage-4-lite
EMBEDDING_DIM=1024                   # 256·512·1024·2048
VOYAGE_API_KEY=...                   # Voyage 대시보드(dash.voyageai.com)에서 발급. 커밋 금지
RERANKER_MODEL=rerank-3-lite         # 선택. 비우면 리랭킹 끔
```

- 컬렉션에는 `공급자:모델:차원`(예: `hashing:hashing-kiwi-v1:1024`)이 기록된다. 공급자·모델·차원을 바꾸면 이전 벡터와 섞을 수 없어서 `StoreMismatchError`가 난다. 새 `RAG_COLLECTION` 이름을 쓰고 웹에서 문서를 다시 등록한다.
- 키 확인과 실제 API 스모크 테스트는 본인 터미널에서 한다: `RAG_LIVE_API_TESTS=1 uv run --no-sync pytest tests/rag/test_live_embedding_api.py`(문서 3개·질의 4번, 수백 토큰).
- 팀 키는 Voyage 대시보드(dash.voyageai.com, `pa-…`)에서 받고 기본 주소(`https://api.voyageai.com/v1`)를 쓴다. MongoDB Atlas > AI Models에서 만든 키는 `VOYAGE_BASE_URL=https://ai.mongodb.com/v1`. 키와 주소가 안 맞으면 HTTP 403("This API key cannot access this endpoint")이다. 2026-11-03 Voyage 대시보드 키로 `voyage-4-lite`·`rerank-3-lite` 라이브 스모크 6개 통과.
- API 호출에는 타임아웃(`VOYAGE_TIMEOUT_S`, 기본 30초)과 429·5xx 재시도 2회가 걸려 있다. 그래도 실패하면 예외를 낸다. 문서 등록은 실패 상태로 남고, 분석은 `FAILED`, 챗봇은 "검색 불가"가 된다. 키는 로그·오류 메시지에 남기지 않는다.

## 왜 Voyage인가 (키를 쓸 때)

1. **Anthropic 공식 문서가 안내하는 공급자.** Claude 문서의 임베딩 가이드가 Voyage AI(MongoDB)를 예로 들고 사용법을 싣는다.
2. **싸다.** `voyage-4-lite`는 1M 토큰당 $0.02이고 4세대 모델에 **무료 2억 토큰**이 있다. 이 프로젝트의 문서(매뉴얼·SOP·룰 정의서·승인 보고서)를 몇 번 다시 색인해도 무료 범위 안이다. 질의는 한 번에 수십 토큰이다.
3. **임베딩과 리랭커를 키 하나로.** 리랭커 `rerank-3-lite`도 $0.02/1M이다. 공급자를 하나로 두면 키·계약·보안 검토가 하나로 줄어든다.
4. **다국어·출력 차원 선택.** `voyage-4` 계열은 다국어 검색을 목표로 하고 256~2048차원을 고를 수 있다. 문서·질의를 구분하는 `input_type`을 지원해 검색에 맞다.
5. **OpenAI 등은 키가 하나 더 필요하다.** 가격은 비슷하지만 공급자가 늘어난다.

주의: Atlas 조직 설정에 "보낸 데이터를 Voyage 모델 개선에 쓸 수 있다"는 항목이 있다. 실제 설비 문서를 보내기 전에 조직 설정에서 끈다([AI_DATA_SECURITY](AI_DATA_SECURITY.md)).

## 후보 비교

| 공급자 | 임베딩 모델(가격 / 1M 토큰) | 리랭커 | 장점 | 걸리는 점 |
|---|---|---|---|---|
| **Voyage AI (MongoDB)** | `voyage-4-lite` $0.02, `voyage-4` $0.06, `voyage-4-large` $0.12. 무료 2억 토큰 | `rerank-3-lite` $0.02, `rerank-3` $0.05 | Anthropic 권장, 리랭커 포함, 다국어, 차원 선택 | 데이터 학습 수집 설정을 꺼야 함. 키 1개 추가 |
| OpenAI | `text-embedding-3-small` $0.02, `-3-large` $0.13 | 없음 | 널리 쓰여 자료가 많음 | 리랭커 없음. 키 1개 추가 |
| Google Gemini | `gemini-embedding-001` $0.15, `gemini-embedding-2` $0.20(배치는 절반) | 없음 | 무료 티어 있음 | **무료 티어 입력은 제품 개선에 쓰인다**(공식 가격표). 유료가 Voyage보다 비쌈 |
| Cohere | Embed 5 Fast·Pro | Rerank 5 Fast·Pro | 임베딩·리랭커 품질로 알려짐 | 가격표가 전용 인스턴스(월 $2,000~) 중심. 체험 키는 운영·상업 사용 불가 |
| Upstage (국내) | Embed 2 | 없음 | 한국어 특화, 국내 업체 | 공식 가격을 확인하지 못함(가격 추적 사이트 기준 $0.02 안팎, 미확인) |
| 클라우드 경유(AWS Bedrock 등) | 공급자별 | 공급자별 | 자기 클라우드 계정·리전 안에서 처리, 기존 AWS 계약 활용 | 계정 설정·권한·과금 구조가 따로 필요. 가격은 이번에 확인하지 않음 |
| 오픈 가중치 자가 호스팅 | `voyage-4-nano`(Apache 2.0), bge-m3 등 | bge-reranker 등 | 데이터가 밖으로 안 나감 | **로컬 모델을 쓰지 않기로 해서 제외**(서버 자원·배포 크기) |
| Anthropic(Claude) | 없음 | LLM 리랭킹만 가능 | 지금 있는 키 | 임베딩 불가. LLM 리랭킹은 토큰 비용이 가장 큼 |

## hashing의 한계

- 단어(형태소)가 겹쳐야 가깝다. "트레이가 멈춤"과 "이송 정지" 같은 동의 표현은 못 찾는다.
- 키워드 검색(BM25)과 성격이 비슷해서 hybrid 검색의 이득이 작다.
- 예전 로컬 모델 실측(bge-m3 + 리랭커, MRR 0.917, [RAG_E2E](RAG_E2E.md))과 같은 품질을 기대하지 않는다. 품질이 필요해지면 Voyage로 바꾸고 `make rag-e2e`로 다시 잰다.

## 출처 (2026-11-03 확인)

- Anthropic, [Embeddings](https://platform.claude.com/docs/en/build-with-claude/embeddings): 자체 임베딩 모델 없음, Voyage 모델 목록·차원·input_type
- Voyage AI, [Pricing](https://docs.voyageai.com/docs/pricing), [Embeddings](https://docs.voyageai.com/docs/embeddings), [Reranker](https://docs.voyageai.com/docs/reranker): 가격·무료 토큰·요청 한도
- MongoDB, [Model training data](https://www.mongodb.com/docs/voyageai/management/model-training-data/): Atlas Embedding API 데이터의 모델 개선 사용 설정
- OpenAI, [API Pricing](https://developers.openai.com/api/docs/pricing)
- Google, [Gemini API pricing](https://aistudio.google.com/docs/pricing): 임베딩 가격, 무료 티어 데이터 사용
- Cohere, [Pricing](https://cohere.com/pricing)
- Upstage 가격 변경 추적(비공식): [pricingsaas.com](https://pricingsaas.com/companies/upstage.api/diffs/2026W31)
