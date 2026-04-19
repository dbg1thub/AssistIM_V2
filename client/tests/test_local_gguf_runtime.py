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
    create_calls: list[dict[str, object]] = []

    class StubLlama:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

        def create_chat_completion(self, **kwargs):
            create_calls.append(dict(kwargs))
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
            seed=17,
            response_format={"type": "json_object"},
        )
        assert once["content"] == "hello"

        chunks = [
            chunk.content
            async for chunk in runtime.stream_chat(
                task_id="task-stream",
                messages=[{"role": "user", "content": "hello"}],
                seed=19,
                response_format={"type": "json_object"},
            )
        ]
        assert chunks == ["he", "llo"]
        assert create_calls[0]["seed"] == 17
        assert create_calls[1]["seed"] == 19
        assert create_calls[0]["response_format"] == {"type": "json_object"}
        assert create_calls[1]["response_format"] == {"type": "json_object"}

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


def test_local_gguf_runtime_keeps_native_generation_serial_after_task_cancel(tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"fake")
    runtime = runtime_module.LocalGGUFRuntime(
        runtime_module.LocalGGUFConfig(model_path=str(model_path), model_id="stub-model")
    )
    runtime._llm = object()

    async def fake_load() -> None:
        return None

    runtime.load = fake_load  # type: ignore[method-assign]
    first_started = threading.Event()
    allow_first_finish = threading.Event()
    active_lock = threading.Lock()
    active_calls = 0
    max_active_calls = 0
    entered_prompts: list[str] = []

    def fake_stream_sync(messages, _temperature, _seed, _response_format, _max_tokens):
        nonlocal active_calls, max_active_calls
        prompt = str((messages or [{}])[0].get("content") or "")
        with active_lock:
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            entered_prompts.append(prompt)
        try:
            if len(entered_prompts) == 1:
                first_started.set()
                allow_first_finish.wait(timeout=5)
            yield {"choices": [{"delta": {"content": f"done:{prompt}"}, "finish_reason": "stop"}]}
        finally:
            with active_lock:
                active_calls -= 1

    runtime._stream_sync = fake_stream_sync  # type: ignore[method-assign]

    async def scenario() -> None:
        first = asyncio.create_task(
            runtime.generate_once(task_id="task-1", messages=[{"role": "user", "content": "first"}])
        )
        await asyncio.to_thread(first_started.wait, 5)

        first.cancel()
        second = asyncio.create_task(
            runtime.generate_once(task_id="task-2", messages=[{"role": "user", "content": "second"}])
        )
        await asyncio.sleep(0.05)
        assert entered_prompts == ["first"]

        allow_first_finish.set()
        try:
            await first
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("first task should propagate cancellation after native generation finishes")

        second_result = await second
        assert second_result["content"] == "done:second"
        assert entered_prompts == ["first", "second"]
        assert max_active_calls == 1

    asyncio.run(scenario())


def test_local_gguf_runtime_generate_once_honors_provider_cancel_between_chunks(tmp_path) -> None:
    model_path = tmp_path / "model.gguf"
    model_path.write_bytes(b"fake")
    runtime = runtime_module.LocalGGUFRuntime(
        runtime_module.LocalGGUFConfig(model_path=str(model_path), model_id="stub-model")
    )
    runtime._llm = object()

    async def fake_load() -> None:
        return None

    runtime.load = fake_load  # type: ignore[method-assign]
    first_chunk_sent = threading.Event()
    allow_second_chunk = threading.Event()

    def fake_stream_sync(_messages, _temperature, _seed, _response_format, _max_tokens):
        yield {"choices": [{"delta": {"content": "first"}}]}
        first_chunk_sent.set()
        allow_second_chunk.wait(timeout=5)
        yield {"choices": [{"delta": {"content": "second"}, "finish_reason": "stop"}]}

    runtime._stream_sync = fake_stream_sync  # type: ignore[method-assign]

    async def scenario() -> None:
        task = asyncio.create_task(
            runtime.generate_once(task_id="task-cancel", messages=[{"role": "user", "content": "hello"}])
        )
        await asyncio.to_thread(first_chunk_sent.wait, 5)
        await runtime.cancel("task-cancel")
        allow_second_chunk.set()

        try:
            await task
        except runtime_module.LocalGGUFRuntimeError as exc:
            assert exc.code == "AI_USER_CANCELLED"
        else:
            raise AssertionError("cancelled local generation should fail with AI_USER_CANCELLED")

    asyncio.run(scenario())
