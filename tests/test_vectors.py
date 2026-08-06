"""Tests for the semantic search layer.

These tests never download the real e5 model: VectorStore.rebuild()/search()
already accept an `encoder` override for exactly this purpose, and the
internal _encode_passages/_encode_queries prefixing is tested by swapping in
a recording fake SentenceTransformer.
"""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from ardupilot_mcp.vectors import EMBEDDING_DIM, VectorStore


class _RecordingModel:
    """Fake SentenceTransformer that records what it was asked to encode."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, batch_size=64, show_progress_bar=False, convert_to_numpy=True):
        self.calls.append(list(texts))
        return np.zeros((len(texts), EMBEDDING_DIM), dtype="float32")


def _store(tmp_path) -> VectorStore:
    return VectorStore(
        path=tmp_path / "vectors.lance",
        model_cache_path=tmp_path / "model-cache",
    )


def test_encode_passages_adds_passage_prefix(tmp_path):
    store = _store(tmp_path)
    fake_model = _RecordingModel()
    store._model = fake_model  # bypass lazy real-model loading

    store._encode_passages(["RC_OPTIONS: RC options"])

    assert fake_model.calls == [["passage: RC_OPTIONS: RC options"]]


def test_encode_queries_adds_query_prefix(tmp_path):
    store = _store(tmp_path)
    fake_model = _RecordingModel()
    store._model = fake_model

    store._encode_queries(["why is my plane climbing"])

    assert fake_model.calls == [["query: why is my plane climbing"]]
