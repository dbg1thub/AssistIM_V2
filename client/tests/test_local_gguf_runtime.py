from __future__ import annotations

import asyncio
import sys
import threading
import types

from client.services import local_gguf_runtime as runtime_module


def test_local_gguf_runtime_reports_missing_model(tmp_path) -> None:
    runtime = runtime_module.LocalGGUFRuntime(
        runtime_module.LocalGGUFConfig(model_path=str(tmp_path / "missing.gguf"))
    )

    async def scenario() -> None:
        try:
            await runtime.health_check()
        except runtime_module.LocalGGUFRuntimeError as exc:
            assert exc.code == "AI_MODEL_NOT_FOUND"
        else:
            raise AssertionError("missing model should fail health_check")

    asyncio.run(scenario())


def test_local_gguf_runtime_lazily_reports_missing_llama_cpp(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"fake")
    runtime = runtime_module.LocalGGUFRuntime(
        runtime_module.LocalGGUFConfig(model_path=str(model_path))
    )
    monkeypatch.setitem(sys.modules, "llama_cpp", None)

    async def scenario() -> None:
        try:
            await runtime.load()
        except runtime_module.LocalGGUFRuntimeError as exc:
            assert exc.code == "AI_PROVIDER_UNAVAILABLE"
        else:
            raise AssertionError("missing llama-cpp-python should fail load")

    asyncio.run(scenario())


def test_local_gguf_runtime_streams_with_stub_llama_cpp(monkeypatch, tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"fake")

    class StubLlama:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def create_chat_completion(self, **kwargs):
            if kwargs.get("stream"):
                return iter(
                    [
                        {"choices": [{"delta": {"content": "he"}}]},
                        {"choices": [{"delta": {"content": "llo"}, "finish_reason": "stop"}]},
                    ]
                )
            return {
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 2},
            }

    llama_cpp = types.ModuleType("llama_cpp")
    llama_cpp.Llama = StubLlama
    monkeypatch.setitem(sys.modules, "llama_cpp", llama_cpp)

    runtime = runtime_module.LocalGGUFRuntime(
        runtime_module.LocalGGUFConfig(model_path=str(model_path), model_id="stub-model")
    )

    async def scenario() -> None:
        once = await runtime.generate_once(
            task_id="task-once",
            messages=[{"role": "user", "content": "hello"}],
        )
        assert once["content"] == "hello"

        chunks = [
            chunk.content
            async for chunk in runtime.stream_chat(
                task_id="task-stream",
                messages=[{"role": "user", "content": "hello"}],
            )
        ]
        assert chunks == ["he", "llo"]

    asyncio.run(scenario())


def test_local_gguf_runtime_warmup_shares_single_load_task_and_reports_loading(tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"fake")
    runtime = runtime_module.LocalGGUFRuntime(
        runtime_module.LocalGGUFConfig(model_path=str(model_path), model_id="stub-model")
    )
    load_started = threading.Event()
    allow_finish = threading.Event()
    load_calls = 0

    def fake_load_sync(_model_path):
        nonlocal load_calls
        load_calls += 1
        load_started.set()
        allow_finish.wait(timeout=5)
        return object()

    runtime._load_sync = fake_load_sync  # type: ignore[method-assign]

    async def scenario() -> None:
        first = asyncio.create_task(runtime.warmup())
        await asyncio.to_thread(load_started.wait, 5)

        info_during = await runtime.get_model_info()
        second = asyncio.create_task(runtime.load())
        await asyncio.sleep(0)
        allow_finish.set()
        await asyncio.gather(first, second)
        info_after = await runtime.get_model_info()

        assert info_during.loading is True
        assert info_during.loaded is False
        assert info_after.loading is False
        assert info_after.loaded is True
        assert load_calls == 1

    asyncio.run(scenario())
