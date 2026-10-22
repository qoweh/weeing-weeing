"""매뉴얼 PDF를 파싱·청킹·임베딩하고 결과 요약을 출력한다.

입력: data/manuals/BTT-MANUAL_v2.0.pdf
출력: 터미널에 청크 수, 벡터 차원, 검증 결과 표시
"""

import math
from pathlib import Path

from weeing_weeing.rag.chunker import ChunkerConfig, chunk_documents
from weeing_weeing.rag.embedder import EmbeddingConfig, create_embeddings
from weeing_weeing.rag.pdf_parser import ParserConfig, parse_pdf


def main() -> None:
    project_root = Path(__file__).resolve().parents[3]
    pdf_path = project_root / "data/manuals/BTT-MANUAL_v2.0.pdf"

    # 1. 파싱
    documents = parse_pdf(
        pdf_path,
        doc_id="BTT-MANUAL",
        doc_version="v2.0",
        doc_type="manual",
        config=ParserConfig(
            margin_top=45,
            margin_bottom=50,
            infer_table_columns=True,
            single_row_as_quote=True,
        ),
    )

    # 2. 청킹
    chunks = chunk_documents(
        documents,
        config=ChunkerConfig(
            chunk_size=1000,
            chunk_overlap=150,
        ),
    )

    if not chunks:
        raise ValueError("임베딩할 청크가 없습니다.")

    print(f"파싱·청킹 완료: {len(documents)}페이지 → {len(chunks)}개 청크")

    # 3. 모델 로드: 이후 문서와 질문 임베딩에서 재사용
    print("임베딩 모델 로드 중...")
    embeddings = create_embeddings(
        EmbeddingConfig(
            model_name="BAAI/bge-m3",
            device="cpu",
            batch_size=8,
            normalize_embeddings=True,
        )
    )

    # 4. 청크의 본문만 임베딩
    print("문서 임베딩 중...")
    vectors = embeddings.embed_documents(
        [chunk.page_content for chunk in chunks]
    )

    # 5. 벡터 수·차원·값 검증
    if len(vectors) != len(chunks):
        raise ValueError("청크 수와 벡터 수가 다릅니다.")

    dimension = len(vectors[0])
    if dimension == 0:
        raise ValueError("빈 벡터가 생성됐습니다.")

    for index, vector in enumerate(vectors):
        if len(vector) != dimension:
            raise ValueError(f"{index}번 벡터의 차원이 다릅니다.")
        if not all(math.isfinite(value) for value in vector):
            raise ValueError(f"{index}번 벡터에 NaN 또는 무한대가 있습니다.")
        if not any(value != 0 for value in vector):
            raise ValueError(f"{index}번 벡터가 모두 0입니다.")

    print(f"임베딩 완료: {len(vectors)}개 벡터, 각 {dimension}차원")
    print(f"첫 청크 출처: {chunks[0].metadata}")
    print(f"첫 벡터 앞 5개 값: {vectors[0][:5]}")


if __name__ == "__main__":
    main()