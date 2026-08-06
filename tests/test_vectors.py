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


def _rows(*specs) -> list[dict]:
    """specs: (param_id, name, vehicle, firmware_version, text) tuples."""
    return [
        {"param_id": pid, "name": name, "vehicle": vehicle,
         "firmware_version": fw, "text": text}
        for pid, name, vehicle, fw, text in specs
    ]


def test_rebuild_and_search_roundtrip(tmp_path):
    store = _store(tmp_path)
    rows = _rows(
        (1, "RC_OPTIONS", "plane", "4.8.0", "RC input options"),
        (2, "LOG_BITMASK", "plane", "4.8.0", "Log bitmask control"),
    )

    n = store.rebuild(rows, vehicle="plane", encoder=_identity_encoder)
    assert n == 2

    hits = store.search(
        "RC input options", k=5, vehicles=["plane"], encoder=_identity_encoder
    )
    assert hits[0]["param_id"] == 1


def test_rebuild_replaces_only_the_given_vehicle(tmp_path):
    # ADR-0001: the index holds one version per vehicle. Rebuilding plane
    # must not touch copter's rows.
    store = _store(tmp_path)
    store.rebuild(
        _rows((1, "RC_OPTIONS", "plane", "4.6.3", "old plane text")),
        vehicle="plane", encoder=_identity_encoder,
    )
    store.rebuild(
        _rows((2, "RC_OPTIONS", "copter", "4.8.0", "copter text")),
        vehicle="copter", encoder=_identity_encoder,
    )

    # Re-ingest plane at a new version — old plane row gone, copter intact.
    store.rebuild(
        _rows((3, "RC_OPTIONS", "plane", "4.8.0", "new plane text")),
        vehicle="plane", encoder=_identity_encoder,
    )

    hits = store.search(
        "new plane text", k=10, vehicles=None, encoder=_identity_encoder
    )
    ids = {h["param_id"] for h in hits}
    assert ids == {2, 3}  # id 1 (old plane) is gone; copter (2) untouched


def test_rebuild_with_empty_rows_clears_that_vehicle(tmp_path):
    store = _store(tmp_path)
    store.rebuild(
        _rows((1, "RC_OPTIONS", "plane", "4.8.0", "text")),
        vehicle="plane", encoder=_identity_encoder,
    )
    store.rebuild(
        _rows((2, "RC_OPTIONS", "copter", "4.8.0", "text")),
        vehicle="copter", encoder=_identity_encoder,
    )

    n = store.rebuild([], vehicle="plane", encoder=_identity_encoder)

    assert n == 0
    hits = store.search("text", k=10, vehicles=None, encoder=_identity_encoder)
    assert [h["param_id"] for h in hits] == [2]


def test_search_vehicles_filters_to_given_vehicles(tmp_path):
    store = _store(tmp_path)
    store.rebuild(
        _rows((1, "RC_OPTIONS", "plane", "4.8.0", "RC input options")),
        vehicle="plane", encoder=_identity_encoder,
    )
    store.rebuild(
        _rows((2, "RC_OPTIONS", "copter", "4.8.0", "RC input options")),
        vehicle="copter", encoder=_identity_encoder,
    )
    store.rebuild(
        _rows((3, "RC_OPTIONS", "rover", "4.8.0", "RC input options")),
        vehicle="rover", encoder=_identity_encoder,
    )

    hits = store.search(
        "RC input options", k=10, vehicles=["plane", "rover"], encoder=_identity_encoder
    )

    assert {h["param_id"] for h in hits} == {1, 3}


def test_search_vehicles_none_searches_everything_in_the_table(tmp_path):
    store = _store(tmp_path)
    store.rebuild(
        _rows((1, "RC_OPTIONS", "plane", "4.8.0", "RC input options")),
        vehicle="plane", encoder=_identity_encoder,
    )
    store.rebuild(
        _rows((2, "RC_OPTIONS", "copter", "4.8.0", "RC input options")),
        vehicle="copter", encoder=_identity_encoder,
    )

    hits = store.search(
        "RC input options", k=10, vehicles=None, encoder=_identity_encoder
    )

    assert {h["param_id"] for h in hits} == {1, 2}


def test_search_vehicle_with_special_characters(tmp_path):
    store = _store(tmp_path)
    tricky_vehicle = "plane'; DROP TABLE parameters; --"
    store.rebuild(
        _rows((1, "RC_OPTIONS", tricky_vehicle, "4.8.0", "RC input options")),
        vehicle=tricky_vehicle, encoder=_identity_encoder,
    )
    store.rebuild(
        _rows((2, "RC_OPTIONS", "copter", "4.8.0", "RC input options")),
        vehicle="copter", encoder=_identity_encoder,
    )

    hits = store.search(
        "RC input options", k=5, vehicles=[tricky_vehicle], encoder=_identity_encoder
    )

    assert [h["param_id"] for h in hits] == [1]

    # And rebuilding that same tricky vehicle only replaces its own rows.
    store.rebuild(
        _rows((3, "RC_OPTIONS", tricky_vehicle, "4.8.0", "updated text")),
        vehicle=tricky_vehicle, encoder=_identity_encoder,
    )
    hits = store.search(
        "updated text", k=10, vehicles=None, encoder=_identity_encoder
    )
    assert {h["param_id"] for h in hits} == {2, 3}


def test_search_returns_empty_when_no_table(tmp_path):
    store = _store(tmp_path)
    assert store.search("anything", encoder=_identity_encoder) == []
