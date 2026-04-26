import asyncio
import importlib.util

import pytest

from client.services import local_ai_memory_store as memory_store_module
from client.services.local_ai_memory_store import (
    AIMemoryItem,
    InMemoryAIMemoryStore,
    LanceDBAIMemoryStore,
    LocalAIMemoryStoreConfig,
    LocalAIMemoryStoreError,
    build_ai_memory_filter_expression,
    build_ai_memory_id,
)


def test_ai_memory_item_normalizes_and_builds_stable_identity() -> None:
    item = AIMemoryItem(
        owner_scope=" account:test1 ",
        source_type=" file_summary ",
        source_id=" attachment-1 ",
        chunk_id=" chunk-0 ",
        title=" notes.md ",
        text="  明天下午三点确认方案。 ",
        vector=(1, 0, 0),
        embedding_model_id=" jina-embeddings-v3 ",
        metadata={"file_name": "notes.md"},
    )

    assert item.owner_scope == "account:test1"
    assert item.source_type == "file_summary"
    assert item.source_id == "attachment-1"
    assert item.chunk_id == "chunk-0"
    assert item.title == "notes.md"
    assert item.text == "明天下午三点确认方案。"
    assert item.vector == (1.0, 0.0, 0.0)
    assert item.embedding_model_id == "jina-embeddings-v3"
    assert item.memory_id == build_ai_memory_id(
        owner_scope="account:test1",
        source_type="file_summary",
        source_id="attachment-1",
        chunk_id="chunk-0",
    )

    record = item.to_record()

    assert record["memory_id"] == item.memory_id
    assert record["embedding_dim"] == 3
    assert record["metadata_json"] == '{"file_name":"notes.md"}'


def test_ai_memory_item_rejects_invalid_payload() -> None:
    with pytest.raises(LocalAIMemoryStoreError) as exc_info:
        AIMemoryItem(
            owner_scope="account:test1",
            source_type="file_summary",
            source_id="attachment-1",
            text="",
            vector=(1, 0, 0),
            embedding_model_id="jina",
        )
    assert exc_info.value.code == "AI_MEMORY_ITEM_INVALID"

    with pytest.raises(LocalAIMemoryStoreError) as exc_info:
        AIMemoryItem(
            owner_scope="account:test1",
            source_type="file_summary",
            source_id="attachment-1",
            text="摘要",
            vector=(),
            embedding_model_id="jina",
        )
    assert exc_info.value.code == "AI_MEMORY_ITEM_INVALID"


def test_in_memory_ai_memory_store_upserts_searches_and_deletes() -> None:
    async def scenario() -> None:
        store = InMemoryAIMemoryStore()
        await store.upsert_items(
            [
                AIMemoryItem(
                    owner_scope="account:test1",
                    source_type="private_document_chunk",
                    source_id="doc-1",
                    chunk_id="0",
                    title="方案文档",
                    text="明天下午三点确认语义检索方案。",
                    vector=(1, 0, 0),
                    embedding_model_id="jina-v1",
                ),
                AIMemoryItem(
                    owner_scope="account:test1",
                    source_type="voice_transcript",
                    source_id="voice-1",
                    text="晚上八点语音复盘。",
                    vector=(0, 1, 0),
                    embedding_model_id="jina-v1",
                ),
                AIMemoryItem(
                    owner_scope="account:test2",
                    source_type="private_document_chunk",
                    source_id="doc-2",
                    chunk_id="0",
                    title="其他账号文档",
                    text="不应该被 test1 检索到。",
                    vector=(1, 0, 0),
                    embedding_model_id="jina-v1",
                ),
            ]
        )

        results = await store.search(
            query_vector=(0.9, 0.1, 0),
            owner_scope="account:test1",
            source_types=("private_document_chunk",),
            embedding_model_id="jina-v1",
            limit=5,
            min_score=0.1,
        )

        assert [result.item.source_id for result in results] == ["doc-1"]
        assert results[0].score > 0.98

        await store.upsert_item(
            AIMemoryItem(
                owner_scope="account:test1",
                source_type="private_document_chunk",
                source_id="doc-1",
                chunk_id="0",
                title="方案文档",
                text="已经更新成晚上八点确认方案。",
                vector=(0, 1, 0),
                embedding_model_id="jina-v1",
            )
        )

        updated_results = await store.search(
            query_vector=(0, 1, 0),
            owner_scope="account:test1",
            source_types=("private_document_chunk",),
            embedding_model_id="jina-v1",
            limit=5,
            min_score=0.1,
        )
        assert [result.item.text for result in updated_results] == ["已经更新成晚上八点确认方案。"]

        await store.delete_source(
            owner_scope="account:test1",
            source_type="private_document_chunk",
            source_id="doc-1",
        )

        deleted_results = await store.search(
            query_vector=(0, 1, 0),
            owner_scope="account:test1",
            source_types=("private_document_chunk",),
            embedding_model_id="jina-v1",
            limit=5,
            min_score=0.1,
        )
        assert deleted_results == []

    asyncio.run(scenario())


def test_ai_memory_filter_expression_escapes_values() -> None:
    assert build_ai_memory_filter_expression(
        owner_scope="account:test'1",
        source_types=("file_summary", "voice_transcript"),
        embedding_model_id="jina-v1",
    ) == "owner_scope = 'account:test''1' AND source_type IN ('file_summary', 'voice_transcript') AND embedding_model_id = 'jina-v1'"


def test_lancedb_store_reports_missing_dependency(tmp_path) -> None:
    if importlib.util.find_spec("lancedb") is not None:
        pytest.skip("lancedb is installed in this environment")

    store = LanceDBAIMemoryStore(LocalAIMemoryStoreConfig(db_path=str(tmp_path), table_name="ai_memory_test"))

    with pytest.raises(LocalAIMemoryStoreError) as exc_info:
        store._connect_sync()

    assert exc_info.value.code == "AI_MEMORY_VECTOR_DB_UNAVAILABLE"


def test_lancedb_store_does_not_misclassify_import_hook_failures(tmp_path, monkeypatch) -> None:
    store = LanceDBAIMemoryStore(LocalAIMemoryStoreConfig(db_path=str(tmp_path), table_name="ai_memory_test"))

    def fail_import(name: str):
        assert name == "lancedb"
        raise AttributeError("'_SixMetaPathImporter' object has no attribute '_path'")

    monkeypatch.setattr(memory_store_module.importlib, "import_module", fail_import)

    with pytest.raises(AttributeError, match="_SixMetaPathImporter"):
        store._connect_sync()
