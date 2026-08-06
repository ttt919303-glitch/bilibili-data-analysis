from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sklearn.feature_extraction.text import TfidfVectorizer

from data_utils import parse_number


DOCUMENT_FIELDS = (
    ("标题", "title"),
    ("UP主", "up_name"),
    ("视频链接", "video_url"),
    ("播放量", "play_count"),
    ("点赞", "like_count"),
    ("投币", "coin_count"),
    ("收藏", "favorite_count"),
    ("分享", "share_count"),
    ("评论", "comment_count"),
    ("发布时间", "publish_time"),
)
NUMBER_FIELDS = {"play_count", "like_count", "coin_count", "favorite_count", "share_count", "comment_count"}


class TfidfEmbeddings(Embeddings):
    def __init__(self, vectorizer: TfidfVectorizer | None = None) -> None:
        self.vectorizer = vectorizer or TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self._fitted = vectorizer is not None

    def fit(self, texts: list[str]) -> None:
        self.vectorizer.fit(texts)
        self._fitted = True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self._fitted:
            self.fit(texts)
        return self.vectorizer.transform(texts).toarray().tolist()

    def embed_query(self, text: str) -> list[float]:
        if not self._fitted:
            raise RuntimeError("TF-IDF embeddings must be fitted before retrieval")
        return self.vectorizer.transform([text]).toarray()[0].tolist()


class EmptyRetriever(BaseRetriever):
    def _get_relevant_documents(self, _query: str, *, run_manager=None) -> list[Document]:
        return []


@dataclass(frozen=True)
class KnowledgeBaseSession:
    retriever: BaseRetriever
    document_count: int
    selected_date: str
    source: str


def _document_value(row: pd.Series, field: str) -> str:
    value = row.get(field, "")
    if field in NUMBER_FIELDS:
        return str(parse_number(value))
    return "" if pd.isna(value) else str(value).strip()


def build_video_documents(data: pd.DataFrame) -> list[Document]:
    documents = []
    for _, row in data.iterrows():
        content = "\n".join(f"{label}：{_document_value(row, field)}" for label, field in DOCUMENT_FIELDS)
        documents.append(
            Document(
                page_content=content,
                metadata={
                    "title": _document_value(row, "title"),
                    "up_name": _document_value(row, "up_name"),
                    "video_url": _document_value(row, "video_url"),
                    "publish_time": _document_value(row, "publish_time"),
                },
            )
        )
    return documents


def _fingerprint(data: pd.DataFrame, selected_date: str, source: str) -> str:
    payload = data.fillna("").to_csv(index=False).encode("utf-8")
    return hashlib.sha256(selected_date.encode() + b"\0" + source.encode() + b"\0" + payload).hexdigest()


def _write_json_atomic(path: Path, value: dict) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary_path.replace(path)


class KnowledgeBaseService:
    def __init__(self, index_root: Path) -> None:
        self.index_root = Path(index_root)

    def prepare(self, data: pd.DataFrame, selected_date: str, source: str) -> KnowledgeBaseSession:
        date_dir = self.index_root / selected_date
        date_dir.mkdir(parents=True, exist_ok=True)
        index_path = date_dir / "index.joblib"
        metadata_path = date_dir / "metadata.json"
        fingerprint = _fingerprint(data, selected_date, source)

        documents: list[Document]
        vectorizer: TfidfVectorizer | None = None
        if index_path.exists() and metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            if metadata.get("fingerprint") == fingerprint:
                stored = joblib.load(index_path)
                documents = stored["documents"]
                vectorizer = stored["vectorizer"]
            else:
                documents = build_video_documents(data)
        else:
            documents = build_video_documents(data)

        if not documents:
            return KnowledgeBaseSession(EmptyRetriever(), 0, selected_date, source)

        split_documents = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=50).split_documents(documents)
        embeddings = TfidfEmbeddings(vectorizer)
        if vectorizer is None:
            embeddings.fit([document.page_content for document in split_documents])
            temporary_index = index_path.with_suffix(".joblib.tmp")
            joblib.dump({"documents": documents, "vectorizer": embeddings.vectorizer}, temporary_index)
            temporary_index.replace(index_path)
            _write_json_atomic(
                metadata_path,
                {
                    "fingerprint": fingerprint,
                    "selected_date": selected_date,
                    "source": source,
                    "document_count": len(documents),
                },
            )

        store = InMemoryVectorStore.from_documents(split_documents, embeddings)
        retriever = store.as_retriever(search_kwargs={"k": min(5, len(split_documents))})
        return KnowledgeBaseSession(retriever, len(documents), selected_date, source)
