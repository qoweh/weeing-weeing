"""RAG에 쓰는 모델(임베딩·리랭커)을 미리 받는다. 새 PC에서 한 번 실행한다.

검색·리랭킹은 실행 중에 모델을 내려받지 않는다(리랭커는 local_files_only). 그래서
처음에는 이 명령으로 Hugging Face 캐시에 모델을 받아 둔다. LLM은 상용 API(Claude)라
받을 것이 없다.

입력: .env(EMBEDDING_MODEL·RERANKER_MODEL)
출력: ~/.cache/huggingface(임베딩·리랭커)
종료 코드: 0 모두 받음 / 1 받지 못한 모델 있음

    make models   # 약 4.5GB: bge-m3 2.2GB·리랭커 2.3GB
"""

import argparse
import sys
from pathlib import Path

from weeing_weeing.config import get_settings

# sentence-transformers가 쓰지 않는 다른 형식의 가중치(onnx 등)는 받지 않는다.
SKIP = ["*.onnx", "onnx/*", "*.msgpack", "*.h5", "*.ot"]


def download_hf(model_id: str) -> Path:
    from huggingface_hub import snapshot_download

    return Path(snapshot_download(model_id, ignore_patterns=SKIP))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.parse_args(argv)

    settings = get_settings()
    hf_models = [m for m in (settings.embedding_model, settings.reranker_model) if m]
    failed: list[str] = []
    for model_id in hf_models:
        if Path(model_id).exists():
            print(f"[건너뜀] {model_id}: 로컬 경로")
            continue
        print(f"[받는 중] {model_id}")
        try:
            print(f"  → {download_hf(model_id)}")
        except Exception as exc:  # 네트워크·권한·없는 모델 ID
            print(f"  실패: {type(exc).__name__}: {exc}")
            failed.append(model_id)

    if failed:
        print(f"받지 못함: {', '.join(failed)}")
        return 1
    print("완료")
    return 0


if __name__ == "__main__":
    sys.exit(main())
