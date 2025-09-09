# vector_store.py

from pathlib import Path
import pandas as pd
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain.docstore.document import Document
from config import Config
from logger import setup_logger

logger = setup_logger("VectorStoreService")

# simple in-process cache to avoid rebuilding FAISS repeatedly
_VECTOR_STORE = None


def _load_qa_dataframe(csv_path: Path) -> pd.DataFrame:
    """
    Loads a CSV with columns: question, answer
    Trims whitespace, drops empties/dups.
    """
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found at: {csv_path.resolve()}")

    # Your file uses exactly one comma per line (question,answer)
    df = pd.read_csv(csv_path)

    required = {"question", "answer"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise ValueError(f"CSV missing required columns: {', '.join(missing)}")

    df = df.dropna(subset=["question", "answer"]).copy()
    df["question"] = df["question"].astype(str).str.strip()
    df["answer"] = df["answer"].astype(str).str.strip()
    df = df.drop_duplicates(subset=["question", "answer"]).reset_index(drop=True)

    return df


def _to_documents(df: pd.DataFrame):
    """
    Build Documents that contain BOTH question and answer for better recall.
    """
    docs = []
    for row in df.itertuples(index=False):
        text = f"Q: {row.question}\nA: {row.answer}"
        docs.append(
            Document(
                page_content=text,
                metadata={"question": row.question, "answer": row.answer},
            )
        )
    return docs


def create_vector_store():
    """
    Builds a FAISS vector store from the CSV Q&A.
    Uses a compact, zero-cost embedding by default; can be overridden via Config.EMBED_MODEL.
    """
    global _VECTOR_STORE
    if _VECTOR_STORE is not None:
        return _VECTOR_STORE

    try:
        csv_path = Path("data/qa_pairs.csv")
        df = _load_qa_dataframe(csv_path)
        docs = _to_documents(df)
        logger.info(f"Loaded {len(docs)} Q&A documents from {csv_path}")

        model_name = getattr(
            Config, "EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
        )
        embeddings = HuggingFaceEmbeddings(model_name=model_name)

        _VECTOR_STORE = FAISS.from_documents(docs, embeddings)
        logger.info(f"Vector store created with embeddings: {model_name}")

        return _VECTOR_STORE

    except Exception as e:
        logger.error(f"Error creating vector store: {e}")
        raise
