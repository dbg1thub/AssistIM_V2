import asyncio
from datetime import datetime

from client.core.image_summary import IMAGE_SUMMARY_EXTRA_KEY
from client.core.voice_transcription import VOICE_TRANSCRIPT_EXTRA_KEY
from client.events.event_bus import EventBus
from client.managers.ai_assist_manager import AIAssistManager
from client.managers.ai_task_manager import AITaskSnapshot, AITaskState
from client.managers.message_artifact_preparer import MessageArtifactPreparationManager, MessageArtifactPreparer
from client.models.message import ChatMessage, MessageStatus, MessageType, Session
from client.services.local_voice_transcription_service import LocalVoiceTranscriptionResult


class _FakeMessageManager:
    def __init__(self) -> None:
        self.local_paths = {
            "m-voice": "D:/voice/m-voice.m4a",
            "m-image": "D:/images/whiteboard.png",
        }
        self.download_attachment_calls: list[str] = []
        self.update_voice_transcript_calls: list[tuple[str, dict]] = []
        self.update_image_summary_calls: list[tuple[str, dict]] = []
        self.messages: dict[str, ChatMessage] = {}

    async def download_attachment(self, message_id: str) -> str:
        self.download_attachment_calls.append(message_id)
        return self.local_paths.get(message_id, f"D:/media/{message_id}")

    async def update_message_voice_transcript(self, message_id: str, transcript: dict):
        payload = dict(transcript or {})
        self.update_voice_transcript_calls.append((message_id, payload))
        message = self.messages.get(message_id)
        if message is None:
            return None
        extra = dict(message.extra or {})
        extra[VOICE_TRANSCRIPT_EXTRA_KEY] = payload
        message.extra = extra
        return message

    async def update_message_image_summary(self, message_id: str, summary: dict):
        payload = dict(summary or {})
        self.update_image_summary_calls.append((message_id, payload))
        message = self.messages.get(message_id)
        if message is None:
            return None
        extra = dict(message.extra or {})
        extra[IMAGE_SUMMARY_EXTRA_KEY] = payload
        message.extra = extra
        return message


class _FakeVoiceRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    async def transcribe(self, local_path: str, *, duration_seconds: int | None = None):
        self.calls.append((local_path, duration_seconds))
        return LocalVoiceTranscriptionResult(
            text="语音里说周日下午三点见。",
            language="zh",
            language_probability=0.93,
            duration_seconds=5,
            metadata={"engine": "faster-whisper", "model_id": "small"},
        )


class _FakeTaskManager:
    def __init__(
        self,
        *,
        image_content: str = "图片里是一张会议白板，写着周五前确认预算。",
        voice_content: str = "语音摘要：对方在确认周日下午三点见面。",
    ) -> None:
        self.image_content = image_content
        self.voice_content = voice_content
        self.requests = []

    async def run_once(self, request):
        self.requests.append(request)
        if request.metadata.get("source") == "voice_summary":
            content = self.voice_content
        else:
            content = self.image_content
        return AITaskSnapshot(
            task_id=request.task_id,
            session_id=request.session_id,
            task_type=getattr(request.task_type, "value", request.task_type),
            state=AITaskState.DONE,
            content=content,
        )


class _FakeReplyTaskManager:
    def __init__(self) -> None:
        self.requests = []

    async def run_once(self, request):
        self.requests.append(request)
        return AITaskSnapshot(
            task_id=request.task_id,
            session_id=request.session_id,
            task_type=getattr(request.task_type, "value", request.task_type),
            state=AITaskState.DONE,
            content="可以，我看到了。\n我按图里的内容继续推进。\n这会儿我不方便确认。\n我晚点再回复你。",
        )


def _session() -> Session:
    return Session(session_id="s1", name="Alice", session_type="direct")


def _voice_message() -> ChatMessage:
    return ChatMessage(
        "m-voice",
        "s1",
        "peer",
        "voice.m4a",
        message_type=MessageType.VOICE,
        status=MessageStatus.RECEIVED,
        timestamp=datetime(2026, 4, 24, 10, 0, 0),
        extra={"duration": 5},
    )


def _image_message() -> ChatMessage:
    return ChatMessage(
        "m-image",
        "s1",
        "peer",
        "/uploads/whiteboard.png",
        message_type=MessageType.IMAGE,
        status=MessageStatus.RECEIVED,
        timestamp=datetime(2026, 4, 24, 10, 0, 0),
        extra={"name": "whiteboard.png", "mime_type": "image/png"},
    )


def test_message_artifact_preparer_transcribes_voice_for_media_context() -> None:
    async def scenario() -> None:
        fake_message_manager = _FakeMessageManager()
        fake_voice_runtime = _FakeVoiceRuntime()
        message = _voice_message()
        fake_message_manager.messages[message.message_id] = message
        preparer = MessageArtifactPreparer(
            message_manager=fake_message_manager,
            voice_transcription_runtime=fake_voice_runtime,
            task_manager=_FakeTaskManager(),
        )

        updated = await preparer.prepare_message(message, session=_session())

        assert updated.extra[VOICE_TRANSCRIPT_EXTRA_KEY]["status"] == "ready"
        assert updated.extra[VOICE_TRANSCRIPT_EXTRA_KEY]["text"] == "语音里说周日下午三点见。"
        assert fake_message_manager.download_attachment_calls == ["m-voice"]
        assert fake_voice_runtime.calls == [("D:/voice/m-voice.m4a", 5)]

    asyncio.run(scenario())


def test_message_artifact_preparer_summarizes_long_voice_transcript_for_media_context() -> None:
    class LongVoiceRuntime(_FakeVoiceRuntime):
        async def transcribe(self, local_path: str, *, duration_seconds: int | None = None):
            self.calls.append((local_path, duration_seconds))
            return LocalVoiceTranscriptionResult(
                text=" ".join([f"第{index}项需要继续确认预算和时间" for index in range(90)]),
                language="zh",
                language_probability=0.91,
                duration_seconds=20,
                metadata={"engine": "faster-whisper", "model_id": "small"},
            )

    async def scenario() -> None:
        fake_message_manager = _FakeMessageManager()
        fake_voice_runtime = LongVoiceRuntime()
        fake_task_manager = _FakeTaskManager(voice_content="对方在集中确认预算、时间和后续负责人。")
        message = _voice_message()
        message.extra["duration"] = 20
        fake_message_manager.messages[message.message_id] = message
        preparer = MessageArtifactPreparer(
            message_manager=fake_message_manager,
            voice_transcription_runtime=fake_voice_runtime,
            task_manager=fake_task_manager,
        )

        updated = await preparer.prepare_message(message, session=_session())

        payload = updated.extra[VOICE_TRANSCRIPT_EXTRA_KEY]
        assert payload["status"] == "ready"
        assert payload["summary_status"] == "ready"
        assert payload["summary_text"] == "对方在集中确认预算、时间和后续负责人。"
        assert payload["summary_engine"] == "local_llm"
        assert fake_task_manager.requests[0].metadata["source"] == "voice_summary"
        assert fake_task_manager.requests[0].metadata["message_id"] == "m-voice"

    asyncio.run(scenario())


def test_message_artifact_preparer_summarizes_image_for_media_context() -> None:
    async def scenario() -> None:
        fake_message_manager = _FakeMessageManager()
        fake_task_manager = _FakeTaskManager()
        message = _image_message()
        fake_message_manager.messages[message.message_id] = message
        preparer = MessageArtifactPreparer(
            message_manager=fake_message_manager,
            voice_transcription_runtime=_FakeVoiceRuntime(),
            task_manager=fake_task_manager,
        )

        updated = await preparer.prepare_message(message, session=_session())

        assert updated.extra[IMAGE_SUMMARY_EXTRA_KEY]["status"] == "ready"
        assert updated.extra[IMAGE_SUMMARY_EXTRA_KEY]["text"] == "图片里是一张会议白板，写着周五前确认预算。"
        assert fake_message_manager.download_attachment_calls == ["m-image"]
        assert fake_task_manager.requests[0].metadata["source"] == "image_summary"
        assert fake_task_manager.requests[0].attachments[0]["local_path"] == "D:/images/whiteboard.png"

    asyncio.run(scenario())


def test_message_artifact_preparation_manager_prepares_recent_image_before_next_reply_suggestion() -> None:
    async def scenario() -> None:
        event_bus = EventBus()
        fake_message_manager = _FakeMessageManager()
        message = _image_message()
        fake_message_manager.messages[message.message_id] = message
        preparer = MessageArtifactPreparer(
            message_manager=fake_message_manager,
            voice_transcription_runtime=_FakeVoiceRuntime(),
            task_manager=_FakeTaskManager(),
        )
        manager = MessageArtifactPreparationManager(
            event_bus=event_bus,
            preparer=preparer,
            session_loader=lambda session_id: _session(),
        )
        await manager.initialize()
        try:
            await event_bus.emit("message_received", {"message": message})
            await manager.drain()

            reply_task_manager = _FakeReplyTaskManager()
            assist = AIAssistManager(task_manager=reply_task_manager)
            state = await assist.suggest_replies(_session(), [message], current_user_id="me")

            assert state.anchor_message_id == "m-image"
            assert "[图片摘要: 图片里是一张会议白板，写着周五前确认预算。]" in reply_task_manager.requests[0].messages[0]["content"]
        finally:
            await manager.close()

    asyncio.run(scenario())
