from langchain_core.documents import Document

from weeing_weeing.rag.chunker import ChunkerConfig
from weeing_weeing.rag.structured_chunker import structured_chunk_documents


def test_articles_and_cases_stay_with_their_content():
    page = Document(
        page_content=(
            "## 페이지 4\n\n제2장 안전\n제5조(정지)\n정지 내용\n"
            "제6조(허가)\n허가 내용\nP03 / P04 - 센서 점유\n점검 내용"
        ),
        metadata={"doc_id": "DOC", "section": "제2장 안전", "page": 4},
    )
    chunks = structured_chunk_documents([page])
    assert len(chunks) == 3
    assert "정지 내용" in chunks[0].page_content
    assert "제6조" not in chunks[0].page_content
    assert "제6조(허가)\n\n허가 내용" in chunks[1].page_content
    assert "P03 / P04" in chunks[2].page_content
    assert all(c.metadata["page"] == 4 for c in chunks)
    assert all(c.page_content.startswith("문맥: DOC > 제2장 안전") for c in chunks)


def test_long_article_keeps_heading_and_fallback_preserves_table():
    article = Document(
        page_content="제1조(길이)\n" + "\n".join(f"내용 {i} " * 8 for i in range(20)),
        metadata={"doc_id": "DOC", "page": 1},
    )
    chunks = structured_chunk_documents([article], config=ChunkerConfig(150, 20))
    assert len(chunks) > 1
    assert all("제1조(길이)" in c.page_content for c in chunks)
    assert all(len(c.page_content) <= 150 for c in chunks)
    table = Document(
        page_content="| 코드 | 내용 |\n| --- | --- |\n| P01 | 확인 |",
        metadata={"page": 2},
    )
    fallback = structured_chunk_documents([table])
    assert "| 코드 | 내용 |" in fallback[0].page_content
    assert "| P01 | 확인 |" in fallback[0].page_content
