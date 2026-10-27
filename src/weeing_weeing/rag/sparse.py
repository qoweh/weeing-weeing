"""키워드 검색용 sparse 인코더(Kiwi 형태소 BM25)와 파이썬 BM25 색인.

Qdrant는 sparse 벡터를 저장해 DB 안에서 IDF를 곱하고, Chroma는 같은 인코더와 같은 식으로
메모리에서 계산한다. 그래서 두 백엔드의 키워드 점수가 같다.

    문서 벡터: 토큰마다 BM25 TF 포화값 tf*(k1+1) / (tf + k1*(1 - b + b*len/avg_len))
    질의 벡터: 고유 토큰마다 1.0
    점수:     Σ 질의값 × 문서값 × idf,  idf = ln((N - n + 0.5)/(n + 0.5) + 1)

토크나이저 규칙(코드 정규식·사용자 사전·품사)을 바꾸면 NAME의 버전을 올린다.
컬렉션에 기록된 이름과 다르면 저장소가 재색인(make index ARGS=--recreate)을 요구한다.
"""

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from typing import Protocol

from kiwipiepy import Kiwi

from weeing_weeing.contracts import CODES

# BTT2-P01 같은 정식 코드, 매뉴얼의 짧은 표기 P01, 센서 ID S01~S07. 대소문자는 가리지
# 않는다(질의에 "p03"이라고 써도 맞게). Kiwi는 BTT2-P01을 BTT/2/-/P/01로 쪼개므로
# 형태소 분석 전에 뽑아낸다.
_CODE = re.compile(
    r"(?<![A-Za-z0-9])BTT2-[PMD]\d{2}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9-])[PMD]\d{2}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])S0[1-7](?![0-9])",
    re.IGNORECASE,
)
# Kiwi가 지나치게 나누는 도메인 용어. 검색 실패 사례가 나오면 늘린다.
USER_WORDS = ("광전센서", "외함", "버스전압", "첨도", "반구동측", "구동측")
# 명사(NNG·NNP), 외국어(SL), 한자(SH), 어근(XR). 동사·형용사(VV·VA)는 '하다·있다' 같은
# 흔한 말이 섞여 키워드 검색을 흐리므로 뺀다.
KEEP_TAGS = frozenset({"NNG", "NNP", "SL", "SH", "XR"})


@dataclass(frozen=True)
class SparseVec:
    indices: list[int]
    values: list[float]


class SparseEncoder(Protocol):
    name: str  # 컬렉션 metadata의 sparse_encoder에 기록

    def encode_documents(self, texts: list[str]) -> list[SparseVec]: ...

    def encode_query(self, text: str) -> SparseVec: ...


@cache
def _kiwi(user_words: tuple[str, ...]) -> Kiwi:
    """Kiwi는 로드 비용이 커서 프로세스당 하나만 만든다."""
    kiwi = Kiwi()
    for word in user_words:
        kiwi.add_user_word(word, "NNP")
    return kiwi


def normalize_code(code: str) -> str:
    """P01 → BTT2-P01. 센서 ID와 정식 코드는 그대로. 대문자로 맞춘다."""
    code = code.upper()
    return f"BTT2-{code}" if re.fullmatch(r"[PMD]\d{2}", code) else code


def extract_codes(text: str) -> list[str]:
    """본문에 나온 룰 코드(BTT2-…)를 정식 표기로, 나온 순서대로 중복 없이 돌려준다.

    짧은 표기(P01)와 소문자도 정식 코드로 바꾸고, 룰 정의서에 없는 코드(P99)와 센서 ID(S01)는 뺀다.
    청크 메타데이터 codes를 채워 where={"codes": …} 필터에 쓴다.
    """
    found = (normalize_code(m) for m in _CODE.findall(text))
    return list(dict.fromkeys(c for c in found if c in CODES))


def term_id(token: str) -> int:
    """토큰 → 32비트 term id. 파이썬 hash()는 실행마다 값이 달라서 쓰지 않는다."""
    return int.from_bytes(hashlib.blake2b(token.encode(), digest_size=4).digest())


class KiwiBm25Encoder:
    NAME = "kiwi-bm25-v2"  # v2: 코드 대소문자 무시

    def __init__(
        self,
        *,
        user_words: Sequence[str] = USER_WORDS,
        k1: float = 1.2,
        b: float = 0.75,
        avg_len: float = 256.0,  # FastEmbed BM25와 같은 방식(상수)
    ) -> None:
        self.name = self.NAME
        self._kiwi = _kiwi(tuple(user_words))
        self._k1, self._b, self._avg_len = k1, b, avg_len

    def tokenize(self, text: str) -> list[str]:
        codes = [normalize_code(m).lower() for m in _CODE.findall(text)]
        rest = _CODE.sub(" ", text)
        words = [
            t.form.lower() for t in self._kiwi.tokenize(rest) if t.tag in KEEP_TAGS
        ]
        return codes + words

    def _vector(self, weights: dict[str, float]) -> SparseVec:
        merged: dict[int, float] = {}
        for token, weight in weights.items():
            tid = term_id(token)
            merged[tid] = merged.get(tid, 0.0) + weight  # 해시 충돌은 합친다(드묾)
        indices = sorted(merged)
        return SparseVec(indices, [merged[i] for i in indices])

    def encode_document(self, text: str) -> SparseVec:
        tokens = self.tokenize(text)
        norm = self._k1 * (1 - self._b + self._b * len(tokens) / self._avg_len)
        return self._vector(
            {t: tf * (self._k1 + 1) / (tf + norm) for t, tf in Counter(tokens).items()}
        )

    def encode_documents(self, texts: list[str]) -> list[SparseVec]:
        return [self.encode_document(t) for t in texts]

    def encode_query(self, text: str) -> SparseVec:
        return self._vector(dict.fromkeys(self.tokenize(text), 1.0))


def idf(df: int, n: int) -> float:
    """Qdrant Modifier.IDF와 같은 식."""
    return math.log((n - df + 0.5) / (df + 0.5) + 1)


class Bm25Index:
    """메모리 BM25. 문서 벡터를 받아 질의 점수를 계산한다(IDF는 전체 코퍼스 기준)."""

    def __init__(self, docs: dict[str, SparseVec]) -> None:
        self._docs = {key: dict(zip(v.indices, v.values)) for key, v in docs.items()}
        self._df = Counter(i for vec in self._docs.values() for i in vec)

    def scores(self, query: SparseVec) -> dict[str, float]:
        """점수가 0보다 큰 문서만 돌려준다."""
        n = len(self._docs)
        weights = {
            i: q * idf(self._df[i], n)
            for i, q in zip(query.indices, query.values)
            if self._df[i]
        }
        found: dict[str, float] = {}
        for key, vec in self._docs.items():
            score = sum(w * vec[i] for i, w in weights.items() if i in vec)
            if score > 0:
                found[key] = score
        return found
