"""로컬 임베딩 모델을 준비한다. 문서와 질문에 같은 모델을 사용한다."""

from dataclasses import dataclass

from langchain_huggingface import HuggingFaceEmbeddings


@dataclass(frozen=True)
class EmbeddingConfig:
    """임베딩 모델과 실행 설정."""

    model_name: str = "BAAI/bge-m3"
    device: str = "cpu"
    batch_size: int = 8
    normalize_embeddings: bool = True

    def __post_init__(self) -> None:
        if not self.model_name.strip():
            raise ValueError("model_name은 비워 둘 수 없습니다.")
        if self.batch_size <= 0:
            raise ValueError("batch_size는 0보다 커야 합니다.")


def create_embeddings(
    config: EmbeddingConfig | None = None,
) -> HuggingFaceEmbeddings:
    """모델을 로드한다. 반환 객체를 재사용해 반복 로드를 피한다.

    embed_documents(): 문자열 목록을 벡터 목록으로 변환한다.
    embed_query(): 질문 문자열을 벡터 하나로 변환한다.
    첫 실행에는 모델 다운로드가 필요할 수 있다.
    """
    config = config or EmbeddingConfig()

    return HuggingFaceEmbeddings(
        model_name=config.model_name,
        model_kwargs={
            "device": config.device,
        },
        encode_kwargs={
            "batch_size": config.batch_size,
            "normalize_embeddings": config.normalize_embeddings,
        },
        query_encode_kwargs={
            "normalize_embeddings": config.normalize_embeddings,
        },
    )
