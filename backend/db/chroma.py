import chromadb
from chromadb.config import Settings
from chromadb.errors import NotFoundError

_client: chromadb.Client | None = None


def get_chroma_client():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path="./chroma_data",
            settings=Settings(anonymized_telemetry=False),
        )
    return _client


def get_or_create_collection(name: str):
    client = get_chroma_client()
    try:
        return client.get_collection(name)
    except (ValueError, NotFoundError):
        return client.create_collection(name, metadata={"hnsw:space": "cosine"})


def delete_collection(name: str) -> None:
    try:
        get_chroma_client().delete_collection(name)
    except (ValueError, NotFoundError):
        pass
