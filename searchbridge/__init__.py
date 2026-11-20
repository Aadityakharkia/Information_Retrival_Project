"""SearchBridge AI — an intelligent information retrieval system for smart document search."""
from .documents import Document, load_cranfield, load_directory, load_jsonl
from .engine import EngineConfig, SearchEngine, SearchResponse

__version__ = "1.0.0"
__all__ = ["Document", "SearchEngine", "EngineConfig", "SearchResponse",
           "load_cranfield", "load_directory", "load_jsonl"]
