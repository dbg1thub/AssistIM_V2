from __future__ import annotations

import asyncio
import sys
import types

from client.services import local_embedding_gguf_runtime as runtime_module


def test_local_embedding_gguf_runtime_reports_missing_model(tmp_path) -> None:
    runtime = runtime_module.LocalEmbeddingGGUFRuntime(
        runtime_module.LocalEmbeddingGGUFConfig(model_path=str(tmp_path / "missing.gguf"))
    )

    async def scenario() -> None:
        try:
            await runtime.load()
        except runtime_module.LocalEmbeddingGGUFRuntimeError as exc:
            assert exc.code == "AI_EMBEDDING_MODEL_NOT_FOUND"
        else:
            raise AssertionError("missing embedding model should fail load")

    asyncio.run(scenario())


def test_local_embedding_gguf_runtime_lazily_reports_missing_llama_cpp(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "embedding.gguf"
    model_path.write_bytes(b"fake")
    runtime = runtime_module.LocalEmbeddingGGUFRuntime(
        runtime_module.LocalEmbeddingGGUFConfig(model_path=str(model_path))
    )
    monkeypatch.setitem(sys.modules, "llama_cpp.llama_embedding", None)

    async def scenario() -> None:
        try:
            await runtime.load()
        except runtime_module.LocalEmbeddingGGUFRuntimeError as exc:
            assert exc.code == "AI_EMBEDDING_PROVIDER_UNAVAILABLE"
        else:
            raise AssertionError("missing llama embedding support should fail load")

    asyncio.run(scenario())


def test_local_embedding_gguf_runtime_embeds_with_stub_llama_cpp(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "embedding.gguf"
    model_path.write_bytes(b"fake")

    class StubLlamaEmbedding:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def embed(self, texts):
            return [[float(index + 1), float(len(text))] for index, text in enumerate(list(texts or []))]

    llama_embedding_module = types.ModuleType("llama_cpp.llama_embedding")
    llama_embedding_module.LlamaEmbedding = StubLlamaEmbedding
    monkeypatch.setitem(sys.modules, "llama_cpp.llama_embedding", llama_embedding_module)

    runtime = runtime_module.LocalEmbeddingGGUFRuntime(
        runtime_module.LocalEmbeddingGGUFConfig(
            model_path=str(model_path),
            model_id="embed-model",
            context_size=1024,
            gpu_layers=4,
            cpu_threads=2,
            verbose=False,
        )
    )

    async def scenario() -> None:
        vectors = await runtime.embed_texts(["hello", "world!"])

        assert vectors == [(1.0, 5.0), (2.0, 6.0)]
        assert runtime._embedder.kwargs["n_ctx"] == 1024
        assert runtime._embedder.kwargs["n_gpu_layers"] == 4
        assert runtime._embedder.kwargs["n_threads"] == 2

    asyncio.run(scenario())
