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


def _identity_encoder(texts: list[str]) -> list[list[float]]:
    """Deterministic fake encoder: identical text -> identical vector."""
    vectors = []
    for t in texts:
        digest = hashlib.sha256(t.encode("utf-8")).digest()
        vectors.append([digest[i % len(digest)] / 255.0 for i in range(EMBEDDING_DIM)])
    return vectors


def test_rebuild_and_search_roundtrip(tmp_path):
    store = _store(tmp_path)
    rows = [
        {"param_id": 1, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": "4.8.0", "text": "RC input options"},
        {"param_id": 2, "name": "LOG_BITMASK", "vehicle": "plane",
         "firmware_version": "4.8.0", "text": "Log bitmask control"},
        {"param_id": 3, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": "4.6.3", "text": "RC input options"},
    ]

    n = store.rebuild(rows, encoder=_identity_encoder)
    assert n == 3

    hits = store.search(
        "RC input options", k=5, firmware_version="4.8.0", encoder=_identity_encoder
    )
    # Nearest match is the identical-text row; the 4.6.3 row is filtered out
    # entirely even though its text is also identical (wrong version).
    assert hits[0]["param_id"] == 1
    assert 3 not in [h["param_id"] for h in hits]


def test_search_firmware_version_with_special_characters(tmp_path):
    store = _store(tmp_path)
    tricky_version = "4.8.0'; DROP TABLE parameters; --"
    rows = [
        {"param_id": 1, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": tricky_version, "text": "RC input options"},
        {"param_id": 2, "name": "RC_OPTIONS", "vehicle": "plane",
         "firmware_version": "4.6.3", "text": "RC input options"},
    ]
    store.rebuild(rows, encoder=_identity_encoder)

    hits = store.search(
        "RC input options", k=5, firmware_version=tricky_version, encoder=_identity_encoder
    )

    assert [h["param_id"] for h in hits] == [1]
