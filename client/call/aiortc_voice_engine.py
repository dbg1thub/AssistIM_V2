"""aiortc-based voice-call engine boundary."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import sys
import time
from collections.abc import Callable, Coroutine
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtMultimedia import QAudioFormat, QAudioSink, QMediaDevices


try:  # pragma: no cover - optional runtime dependency
    from aiortc import RTCConfiguration, RTCIceCandidate, RTCIceServer, RTCPeerConnection, RTCSessionDescription
    from aiortc.contrib.media import MediaPlayer
    from aiortc.mediastreams import MediaStreamError
    from aiortc.sdp import candidate_from_sdp, candidate_to_sdp
    import aioice.ice as aioice_ice
    from av import AudioResampler

    AIORTC_AVAILABLE = True
    AIORTC_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - exercised via runtime fallback
    RTCConfiguration = None  # type: ignore[assignment]
    RTCPeerConnection = None  # type: ignore[assignment]
    RTCSessionDescription = None  # type: ignore[assignment]
    RTCIceCandidate = None  # type: ignore[assignment]
    RTCIceServer = None  # type: ignore[assignment]
    MediaPlayer = None  # type: ignore[assignment]
    MediaStreamError = Exception  # type: ignore[assignment]
    candidate_from_sdp = None  # type: ignore[assignment]
    candidate_to_sdp = None  # type: ignore[assignment]
    AudioResampler = None  # type: ignore[assignment]
    AIORTC_AVAILABLE = False
    AIORTC_IMPORT_ERROR = exc


logger = logging.getLogger(__name__)


_AIOICE_HOST_ADDRESS_FILTER_INSTALLED = False


def _install_aioice_host_address_filter() -> None:
    """Skip obviously bad ICE host addresses to reduce gather latency on Windows."""
    global _AIOICE_HOST_ADDRESS_FILTER_INSTALLED
    if _AIOICE_HOST_ADDRESS_FILTER_INSTALLED or not AIORTC_AVAILABLE:
        return

    original_get_host_addresses = aioice_ice.get_host_addresses

    def _filtered_get_host_addresses(use_ipv4: bool, use_ipv6: bool) -> list[str]:
        raw_addresses = list(original_get_host_addresses(use_ipv4=use_ipv4, use_ipv6=use_ipv6))
        filtered: list[str] = []
        ipv4_candidates: list[str] = []
        ipv6_candidates: list[str] = []

        for raw in raw_addresses:
            try:
                parsed = ipaddress.ip_address(raw)
            except ValueError:
                continue
            if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified:
                continue
            if parsed.version == 4:
                ipv4_candidates.append(raw)
            else:
                ipv6_candidates.append(raw)

        if sys.platform.startswith("win") and ipv4_candidates:
            filtered.extend(ipv4_candidates)
        else:
            filtered.extend(ipv4_candidates)
            filtered.extend(ipv6_candidates)

        logger.info("Filtered ICE host addresses from %s to %s", raw_addresses, filtered)
        return filtered

    aioice_ice.get_host_addresses = _filtered_get_host_addresses
    _AIOICE_HOST_ADDRESS_FILTER_INSTALLED = True


class _QtRemoteAudioOutput(QObject):
    """Best-effort remote audio playback through QtMultimedia."""

    _TARGET_BUFFER_SIZE_BYTES = 12 * 1024
    _MAX_PENDING_BUFFER_BYTES = 24 * 1024
    _TRIMMED_PENDING_BUFFER_BYTES = 12 * 1024

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sink: QAudioSink | None = None
        self._io_device = None
        self._audio_format: QAudioFormat | None = None
        self._resampler = None
        self._enabled = True
        self._pending_audio = bytearray()
        self._drain_timer = QTimer(self)
        self._drain_timer.setInterval(2)
        self._drain_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._drain_timer.timeout.connect(self._drain_pending_audio)

    def is_available(self) -> bool:
        """Return whether the system currently exposes an audio output device."""
        return bool(QMediaDevices.audioOutputs())

    def set_enabled(self, enabled: bool) -> None:
        """Toggle playback without tearing down the entire sink."""
        self._enabled = bool(enabled)
        if self._sink is None:
            return
        self._sink.setVolume(1.0 if self._enabled else 0.0)
        if not self._enabled:
            self._pending_audio.clear()

    def consume_frame(self, frame) -> bool:
        """Convert one aiortc frame and push it into the default output device."""
        if frame is None or not self.is_available():
            return False
        if not self._ensure_sink():
            return False

        chunks = self._resample_frame(frame)
        wrote_audio = False
        for chunk in chunks:
            if not chunk:
                continue
            wrote_audio = True
            if self._enabled:
                self._pending_audio.extend(chunk)
        if len(self._pending_audio) > self._MAX_PENDING_BUFFER_BYTES:
            overflow = len(self._pending_audio) - self._TRIMMED_PENDING_BUFFER_BYTES
            del self._pending_audio[:overflow]
        if self._enabled and self._pending_audio:
            self._drain_pending_audio()
        return wrote_audio

    def close(self) -> None:
        """Release the sink and any derived conversion state."""
        self._drain_timer.stop()
        self._pending_audio.clear()
        if self._sink is not None:
            try:
                self._sink.stop()
            except Exception:
                logger.debug("Failed to stop QAudioSink cleanly", exc_info=True)
        self._sink = None
        self._io_device = None
        self._audio_format = None
        self._resampler = None

    def _ensure_sink(self) -> bool:
        """Create one sink bound to the current default output device."""
        if self._sink is not None and self._io_device is not None and self._audio_format is not None:
            return True

        if not self.is_available():
            return False

        output_device = QMediaDevices.defaultAudioOutput()
        audio_format = self._select_output_format(output_device)
        if audio_format is None:
            return False

        sink = QAudioSink(output_device, audio_format, self)
        sink.setBufferSize(self._TARGET_BUFFER_SIZE_BYTES)
        io_device = sink.start()
        if io_device is None:
            sink.deleteLater()
            return False

        self._audio_format = audio_format
        self._sink = sink
        self._io_device = io_device
        self._resampler = self._build_resampler(audio_format)
        self.set_enabled(self._enabled)
        self._drain_timer.start()
        return True

    def _select_output_format(self, output_device) -> QAudioFormat | None:
        """Pick one device-supported PCM format that is easy to feed from aiortc."""
        preferred = output_device.preferredFormat()
        preferred_rate = int(preferred.sampleRate() or 48000)
        preferred_channels = int(preferred.channelCount() or 2)

        candidates = [
            self._build_audio_format(preferred_rate, preferred_channels, QAudioFormat.SampleFormat.Int16),
            self._build_audio_format(preferred_rate, 1, QAudioFormat.SampleFormat.Int16),
            self._build_audio_format(48000, 2, QAudioFormat.SampleFormat.Int16),
            self._build_audio_format(48000, 1, QAudioFormat.SampleFormat.Int16),
        ]
        for candidate in candidates:
            if output_device.isFormatSupported(candidate):
                return candidate

        if preferred.sampleFormat() != QAudioFormat.SampleFormat.Unknown:
            return preferred
        return None

    @staticmethod
    def _build_audio_format(sample_rate: int, channel_count: int, sample_format) -> QAudioFormat:
        """Construct one QAudioFormat value object."""
        audio_format = QAudioFormat()
        audio_format.setSampleRate(max(8000, int(sample_rate or 48000)))
        audio_format.setChannelCount(1 if int(channel_count or 1) <= 1 else 2)
        audio_format.setSampleFormat(sample_format)
        return audio_format

    @staticmethod
    def _qt_sample_format_to_av(sample_format) -> str:
        """Map Qt sample-format enums into av resampler names."""
        if sample_format == QAudioFormat.SampleFormat.Float:
            return "flt"
        if sample_format == QAudioFormat.SampleFormat.Int32:
            return "s32"
        if sample_format == QAudioFormat.SampleFormat.UInt8:
            return "u8"
        return "s16"

    def _build_resampler(self, audio_format: QAudioFormat):
        """Create one av resampler matching the chosen Qt output format."""
        if AudioResampler is None:
            return None
        channel_count = int(audio_format.channelCount() or 1)
        layout = "mono" if channel_count <= 1 else "stereo"
        return AudioResampler(
            format=self._qt_sample_format_to_av(audio_format.sampleFormat()),
            layout=layout,
            rate=int(audio_format.sampleRate() or 48000),
        )

    def _resample_frame(self, frame) -> list[bytes]:
        """Convert one incoming audio frame into sink-ready PCM chunks."""
        if self._resampler is None:
            array = frame.to_ndarray()
            return [array.tobytes()] if hasattr(array, "tobytes") else []

        converted = self._resampler.resample(frame)
        if converted is None:
            return []
        if not isinstance(converted, list):
            converted = [converted]

        chunks: list[bytes] = []
        for item in converted:
            array = item.to_ndarray()
            if hasattr(array, "tobytes"):
                chunks.append(array.tobytes())
        return chunks

    def _drain_pending_audio(self) -> None:
        """Write buffered PCM into the active sink without overrunning it."""
        if self._sink is None or self._io_device is None or not self._pending_audio:
            return

        while self._pending_audio:
            bytes_free = int(self._sink.bytesFree() or 0)
            if bytes_free <= 0:
                return

            chunk = bytes(memoryview(self._pending_audio)[:bytes_free])
            written = int(self._io_device.write(chunk) or 0)
            if written <= 0:
                return
            del self._pending_audio[:written]


class AiortcVoiceEngine(QObject):
    """Minimal aiortc boundary for 1:1 voice calls."""

    state_changed = Signal(str)
    signal_generated = Signal(str, object)
    error_reported = Signal(str)
    microphone_muted_changed = Signal(bool)
    microphone_available_changed = Signal(bool)
    speaker_enabled_changed = Signal(bool)

    def __init__(
        self,
        call_id: str,
        *,
        ice_servers: list[dict[str, Any]] | None = None,
        audio_input_name: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._call_id = str(call_id or "")
        self._ice_servers = self._normalize_ice_servers(ice_servers)
        self._audio_input_name = str(audio_input_name or "").strip()
        self._peer_connection = None
        self._audio_transceiver = None
        self._player = None
        self._local_audio_track = None
        self._remote_audio_output = _QtRemoteAudioOutput(parent=self)
        self._remote_audio_started = False
        self._speaker_enabled = self._remote_audio_output.is_available()
        self._microphone_muted = False
        self._microphone_available = bool(self._audio_input_name)
        self._signaling_ready = False
        self._offer_sent = False
        self._pending_signals: list[tuple[str, dict[str, Any]]] = []
        self._pending_remote_ice: list[Any] = []
        self._tasks: set[asyncio.Task] = set()
        self._operation_lock: asyncio.Lock | None = None
        self._timing_origin = time.perf_counter()
        self._timing_markers: set[str] = set()
        self._remote_ice_added_count = 0
        self._local_ice_sent_count = 0

    def prepare(self, *, is_caller: bool) -> None:
        """Prewarm local media and optionally pre-create the caller offer."""
        self._log_timing("prepare_called", role="caller" if is_caller else "callee")
        self._launch(lambda: self._prepare(is_caller=is_caller), "prepare aiortc voice engine")

    def start(self, *, is_caller: bool) -> None:
        """Start local capture and optionally create the first offer."""
        self._signaling_ready = True
        self._log_timing("start_called", role="caller" if is_caller else "callee")
        self._launch(lambda: self._start(is_caller=is_caller), "start aiortc voice engine")

    def activate_signaling(self) -> None:
        """Allow queued signaling to be emitted before the call is accepted."""
        self._signaling_ready = True
        self._log_timing("activate_signaling")
        self._flush_pending_signals()

    def receive_offer(self, payload: dict[str, Any]) -> None:
        """Apply one inbound offer."""
        self._launch(lambda: self._receive_offer(payload), "receive voice offer")

    def preload_offer(self, payload: dict[str, Any]) -> None:
        """Apply the remote offer early without creating the answer yet."""
        self._launch(lambda: self._preload_offer(payload), "preload voice offer")

    def receive_answer(self, payload: dict[str, Any]) -> None:
        """Apply one inbound answer."""
        self._launch(lambda: self._receive_answer(payload), "receive voice answer")

    def receive_ice_candidate(self, payload: dict[str, Any]) -> None:
        """Apply one inbound ICE candidate."""
        self._launch(lambda: self._receive_ice_candidate(payload), "receive voice ice candidate")

    def set_microphone_muted(self, muted: bool) -> None:
        """Mute or unmute the local microphone track when available."""
        if not self._microphone_available:
            self.microphone_muted_changed.emit(True)
            return
        self._microphone_muted = bool(muted)
        audio_track = self._local_audio_track
        if audio_track is not None:
            audio_track.enabled = not self._microphone_muted
        self.microphone_muted_changed.emit(self._microphone_muted)
        self.state_changed.emit("Mic muted" if self._microphone_muted else "Mic active")

    def set_speaker_enabled(self, enabled: bool) -> None:
        """Toggle the local speaker state hint."""
        self._speaker_enabled = bool(enabled)
        self._remote_audio_output.set_enabled(self._speaker_enabled)
        self.speaker_enabled_changed.emit(self._speaker_enabled)
        if self._speaker_enabled:
            self.state_changed.emit("Speaker enabled")
        else:
            self.state_changed.emit("Speaker disabled")

    def close(self) -> None:
        """Stop capture and close the peer connection."""
        self._release_media_resources()
        self._launch(self._close, "close aiortc voice engine")

    def _launch(self, coroutine_factory: Callable[[], Coroutine[Any, Any, Any]], context: str) -> None:
        """Start one tracked asyncio task."""
        try:
            asyncio.get_running_loop()
            task = asyncio.create_task(coroutine_factory())
        except RuntimeError as exc:
            raise RuntimeError(str(exc) or f"Unable to {context}") from exc
        self._tasks.add(task)
        task.add_done_callback(lambda finished, label=context: self._finalize_task(finished, label))

    def _finalize_task(self, task: asyncio.Task, context: str) -> None:
        """Drop finished tasks and surface failures."""
        self._tasks.discard(task)
        try:
            task.result()
        except asyncio.CancelledError:
            return
        except MediaStreamError:
            return
        except Exception as exc:  # pragma: no cover - runtime bridge
            raise RuntimeError(str(exc) or f"Failed to {context}") from exc

    async def _start(self, *, is_caller: bool) -> None:
        """Initialize the peer connection and local audio capture."""
        async with self._get_operation_lock():
            if not AIORTC_AVAILABLE:
                missing_reason = str(AIORTC_IMPORT_ERROR or "aiortc is not installed")
                raise RuntimeError(f"aiortc runtime is unavailable: {missing_reason}")

            await self._ensure_peer_connection()

            if is_caller:
                if self._local_audio_track is None:
                    self.state_changed.emit("Opening microphone")
                    await self._ensure_local_audio_track()
                if getattr(self._peer_connection, "localDescription", None) is None:
                    self.state_changed.emit("Creating offer")
                    self._log_timing("create_offer_start")
                    offer = await self._peer_connection.createOffer()
                    self._log_timing("create_offer_done")
                    self._log_timing("set_local_offer_start")
                    await self._peer_connection.setLocalDescription(offer)
                    self._log_timing("set_local_offer_done")
                    self._log_timing("offer_created_start")
                if not self._offer_sent and not self._has_pending_signal("call_offer"):
                    self._emit_local_description("call_offer")
                self._flush_pending_signals()
            else:
                remote_description = getattr(self._peer_connection, "remoteDescription", None)
                if remote_description is not None and getattr(remote_description, "type", None) == "offer":
                    self.state_changed.emit("Opening microphone")
                    await self._ensure_local_audio_track()
                    await self._flush_pending_remote_ice()
                    self._normalize_transceivers_for_answer()
                    self._log_timing("create_answer_start")
                    answer = await self._peer_connection.createAnswer()
                    self._log_timing("create_answer_done")
                    self._log_timing("set_local_answer_start")
                    await self._peer_connection.setLocalDescription(answer)
                    self._log_timing("set_local_answer_done")
                    self._log_timing("answer_created_start")
                    self._emit_local_description("call_answer")
                else:
                    self.state_changed.emit("Waiting for caller")
                self._flush_pending_signals()

    async def _prepare(self, *, is_caller: bool) -> None:
        """Pre-create local media state before the call is formally accepted."""
        async with self._get_operation_lock():
            if not AIORTC_AVAILABLE:
                return
            await self._ensure_peer_connection()
            if not is_caller:
                await self._ensure_local_audio_capture()
                return
            await self._ensure_local_audio_track()
            if getattr(self._peer_connection, "localDescription", None) is None:
                self.state_changed.emit("Creating offer")
                self._log_timing("create_offer_start")
                offer = await self._peer_connection.createOffer()
                self._log_timing("create_offer_done")
                self._log_timing("set_local_offer_start")
                await self._peer_connection.setLocalDescription(offer)
                self._log_timing("set_local_offer_done")
                self._log_timing("offer_created_prepare")
                self._emit_local_description("call_offer")

    async def _receive_offer(self, payload: dict[str, Any]) -> None:
        async with self._get_operation_lock():
            if not AIORTC_AVAILABLE:
                return
            await self._ensure_peer_connection()
            remote = self._session_description_from_payload(payload)
            if remote is None:
                return
            self.state_changed.emit("Received offer")
            self._log_timing("offer_received")
            self._log_timing("set_remote_offer_start")
            await self._peer_connection.setRemoteDescription(remote)
            self._log_timing("set_remote_offer_done")
            self._log_timing("offer_applied")
            self.state_changed.emit("Opening microphone")
            await self._ensure_local_audio_track()
            await self._flush_pending_remote_ice()
            self._normalize_transceivers_for_answer()
            self._log_timing("create_answer_start")
            answer = await self._peer_connection.createAnswer()
            self._log_timing("create_answer_done")
            self._log_timing("set_local_answer_start")
            await self._peer_connection.setLocalDescription(answer)
            self._log_timing("set_local_answer_done")
            self._log_timing("answer_created_receive_offer")
            self._emit_local_description("call_answer")

    async def _preload_offer(self, payload: dict[str, Any]) -> None:
        async with self._get_operation_lock():
            if not AIORTC_AVAILABLE:
                return
            await self._ensure_peer_connection()
            remote = self._session_description_from_payload(payload)
            if remote is None:
                return
            remote_description = getattr(self._peer_connection, "remoteDescription", None)
            if remote_description is not None and getattr(remote_description, "type", None) == "offer":
                return
            self.state_changed.emit("Received offer")
            self._log_timing("offer_preload_received")
            self._log_timing("set_remote_offer_start")
            await self._peer_connection.setRemoteDescription(remote)
            self._log_timing("set_remote_offer_done")
            self._log_timing("offer_preload_applied")
            await self._flush_pending_remote_ice()

    async def _receive_answer(self, payload: dict[str, Any]) -> None:
        async with self._get_operation_lock():
            if not AIORTC_AVAILABLE:
                return
            if self._peer_connection is None:
                return
            remote = self._session_description_from_payload(payload)
            if remote is None:
                return
            self._log_timing("set_remote_answer_start")
            await self._peer_connection.setRemoteDescription(remote)
            self._log_timing("set_remote_answer_done")
            self._log_timing("answer_received")
            await self._flush_pending_remote_ice()
            self.state_changed.emit("Remote answer applied")

    async def _receive_ice_candidate(self, payload: dict[str, Any]) -> None:
        async with self._get_operation_lock():
            if not AIORTC_AVAILABLE:
                return
            if self._peer_connection is None or candidate_from_sdp is None:
                return
            candidate_payload = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
            candidate_sdp = str(candidate_payload.get("candidate") or "").strip()
            if not candidate_sdp:
                return
            candidate = candidate_from_sdp(candidate_sdp.removeprefix("candidate:"))
            sdp_mid = candidate_payload.get("sdpMid")
            sdp_mline_index = candidate_payload.get("sdpMLineIndex")
            if sdp_mid not in {None, ""}:
                candidate.sdpMid = str(sdp_mid)
            if sdp_mline_index not in {None, ""}:
                try:
                    candidate.sdpMLineIndex = int(sdp_mline_index)
                except (TypeError, ValueError):
                    return
            if getattr(candidate, "sdpMid", None) in {None, ""} and getattr(candidate, "sdpMLineIndex", None) is None:
                candidate.sdpMLineIndex = 0
            username_fragment = candidate_payload.get("usernameFragment")
            if username_fragment is not None:
                candidate.usernameFragment = username_fragment
            remote_description = getattr(self._peer_connection, "remoteDescription", None)
            if remote_description is None:
                self._pending_remote_ice.append(candidate)
                if len(self._pending_remote_ice) <= 3:
                    self._log_timing("remote_ice_buffered", index=len(self._pending_remote_ice))
                return
            try:
                await self._peer_connection.addIceCandidate(candidate)
                self._remote_ice_added_count += 1
                if self._remote_ice_added_count <= 3:
                    self._log_timing("remote_ice_added", index=self._remote_ice_added_count)
            except ValueError:
                logger.debug("Dropped invalid remote ICE candidate during addIceCandidate", exc_info=True)
                return

    async def _ensure_peer_connection(self) -> None:
        """Create the peer connection once and bind event handlers."""
        if self._peer_connection is not None or RTCPeerConnection is None:
            return

        _install_aioice_host_address_filter()

        config = None
        if self._ice_servers and RTCConfiguration is not None and RTCIceServer is not None:
            rtc_ice_servers = []
            for server in self._ice_servers:
                rtc_ice_servers.append(
                    RTCIceServer(
                        urls=list(server.get("urls") or []),
                        username=str(server.get("username") or ""),
                        credential=str(server.get("credential") or ""),
                    )
                )
            config = RTCConfiguration(rtc_ice_servers)
        self._peer_connection = RTCPeerConnection(configuration=config)
        server_summary = "|".join(
            ",".join(str(url or "") for url in server.get("urls") or [])
            for server in self._ice_servers
        )
        self._log_timing("peer_connection_created", ice_servers=len(self._ice_servers), servers=server_summary)
        peer_connection = self._peer_connection

        @peer_connection.on("icecandidate")
        async def on_ice_candidate(candidate) -> None:
            if candidate is None or candidate_to_sdp is None:
                return
            self._local_ice_sent_count += 1
            if self._local_ice_sent_count <= 3:
                self._log_timing("local_ice_candidate", index=self._local_ice_sent_count)
            candidate_payload = {
                "candidate": "candidate:" + candidate_to_sdp(candidate),
            }
            if getattr(candidate, "sdpMid", None) not in {None, ""}:
                candidate_payload["sdpMid"] = candidate.sdpMid
            if getattr(candidate, "sdpMLineIndex", None) is not None:
                candidate_payload["sdpMLineIndex"] = candidate.sdpMLineIndex
            if getattr(candidate, "usernameFragment", None) is not None:
                candidate_payload["usernameFragment"] = candidate.usernameFragment
            if "sdpMid" not in candidate_payload and "sdpMLineIndex" not in candidate_payload:
                candidate_payload["sdpMLineIndex"] = 0
            payload = {
                "call_id": self._call_id,
                "candidate": candidate_payload,
            }
            self._emit_or_queue_signal("call_ice", payload)

        @peer_connection.on("connectionstatechange")
        async def on_connection_state_change() -> None:
            state = str(getattr(peer_connection, "connectionState", "") or "unknown")
            self._log_timing("connection_state", state=state)
            self.state_changed.emit(f"Connection {state}")

        @peer_connection.on("iceconnectionstatechange")
        async def on_ice_connection_state_change() -> None:
            state = str(getattr(peer_connection, "iceConnectionState", "") or "unknown")
            self._log_timing("ice_connection_state", state=state)
            if state in {"connected", "completed"}:
                self.state_changed.emit("Connection connected")

        @peer_connection.on("track")
        async def on_track(track) -> None:
            if track.kind == "audio":
                self._log_timing("remote_audio_track")
                if self._speaker_enabled:
                    self.state_changed.emit("Remote audio connected")
                else:
                    self.state_changed.emit("Remote audio received (speaker off)")
                self._launch(lambda current_track=track: self._play_remote_audio(current_track), "play remote audio")

    async def _ensure_local_audio_track(self) -> None:
        """Attach the local microphone to the peer connection once."""
        if self._peer_connection is None:
            return
        await self._ensure_local_audio_capture()
        audio_track = self._local_audio_track
        if audio_track is None:
            await self._ensure_recvonly_audio_transceiver()
            return

        audio_track.enabled = not self._microphone_muted
        transceiver = self._ensure_audio_transceiver("sendrecv")
        sender = getattr(transceiver, "sender", None)
        if sender is not None:
            sender.replaceTrack(audio_track)
        current_direction = str(getattr(transceiver, "direction", "") or "")
        if current_direction == "recvonly":
            transceiver.direction = "sendrecv"
        elif current_direction == "inactive":
            transceiver.direction = "sendonly"
        self._audio_transceiver = transceiver
        self.state_changed.emit("Microphone ready")

    async def _ensure_local_audio_capture(self) -> None:
        """Open the local microphone once without necessarily attaching it yet."""
        if self._player is not None and self._local_audio_track is not None:
            return
        if MediaPlayer is None:
            self._local_audio_track = None
            await self._ensure_recvonly_audio_transceiver()
            return
        if not self._audio_input_name:
            self._set_microphone_available(False)
            self._local_audio_track = None
            await self._ensure_recvonly_audio_transceiver()
            self.state_changed.emit("No microphone detected, receive-only mode")
            return

        try:
            player_options = None
            player_format = None
            if sys.platform.startswith("win"):
                player_format = "dshow"
                player_options = {
                    "audio_buffer_size": "20",
                    "rtbufsize": "64k",
                    "fflags": "nobuffer",
                }
            player = MediaPlayer(
                f"audio={self._audio_input_name}",
                format=player_format,
                options=player_options,
            )
            audio_track = getattr(player, "audio", None)
            if audio_track is None:
                raise RuntimeError("No local microphone track is available")
        except Exception as exc:
            self._set_microphone_available(False)
            self._local_audio_track = None
            await self._ensure_recvonly_audio_transceiver()
            self.state_changed.emit("Microphone unavailable, receive-only mode")
            raise RuntimeError(str(exc) or "Unable to open local microphone") from exc

        self._set_microphone_available(True)
        self._player = player
        self._local_audio_track = audio_track
        self._log_timing("local_audio_capture_ready")

    async def _ensure_recvonly_audio_transceiver(self) -> None:
        """Negotiate audio even when local capture is unavailable."""
        if self._peer_connection is None:
            return
        self._audio_transceiver = self._ensure_audio_transceiver("recvonly")

    def _ensure_audio_transceiver(self, preferred_direction: str):
        """Return one audio transceiver, creating it explicitly when needed."""
        existing = self._resolve_audio_transceiver()
        if existing is not None:
            current_direction = str(getattr(existing, "direction", "") or "")
            if preferred_direction == "sendrecv":
                if current_direction == "recvonly":
                    existing.direction = "sendrecv"
                elif current_direction == "inactive":
                    existing.direction = "sendonly"
            elif preferred_direction == "recvonly" and current_direction not in {"sendrecv", "sendonly"}:
                existing.direction = "recvonly"
            return existing
        return self._peer_connection.addTransceiver("audio", direction=preferred_direction)

    def _resolve_audio_transceiver(self):
        """Return the negotiated audio transceiver when one already exists."""
        if self._peer_connection is None:
            return None
        transceivers = getattr(self._peer_connection, "getTransceivers", None)
        if transceivers is None:
            return self._audio_transceiver
        for transceiver in transceivers():
            if getattr(transceiver, "kind", None) == "audio":
                return transceiver
        return self._audio_transceiver

    def _normalize_transceivers_for_answer(self) -> None:
        """Ensure aiortc answer generation does not trip on stray local transceivers."""
        if self._peer_connection is None:
            return
        get_transceivers = getattr(self._peer_connection, "getTransceivers", None)
        remote_description = getattr(self._peer_connection, "remoteDescription", None)
        if get_transceivers is None or remote_description is None:
            return

        remote_mids: set[str] = set()
        media_sections = getattr(remote_description, "media", [])
        for media in media_sections:
            mux_id = str(getattr(getattr(media, "rtp", None), "muxId", "") or "")
            if mux_id:
                remote_mids.add(mux_id)

        snapshot: list[str] = []
        for transceiver in get_transceivers():
            mid = str(getattr(transceiver, "mid", "") or "")
            direction = str(getattr(transceiver, "direction", "") or "")
            offer_direction = getattr(transceiver, "_offerDirection", None)
            sender = getattr(transceiver, "sender", None)
            sender_track = getattr(sender, "track", None)
            snapshot.append(
                f"kind={getattr(transceiver, 'kind', None)} mid={mid or '<none>'} "
                f"direction={direction or '<none>'} offer={offer_direction or '<none>'} "
                f"sender_track={'yes' if sender_track is not None else 'no'}"
            )
            if offer_direction is not None:
                continue
            if mid and mid in remote_mids:
                continue
            transceiver.direction = "inactive"
            transceiver._offerDirection = "inactive"

        logger.info("Answer transceiver snapshot for call %s: %s", self._call_id, "; ".join(snapshot))

    def _get_operation_lock(self) -> asyncio.Lock:
        """Create one shared async lock for signaling mutations."""
        if self._operation_lock is None:
            self._operation_lock = asyncio.Lock()
        return self._operation_lock

    @staticmethod
    def _normalize_ice_servers(ice_servers: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """Normalize structured ICE server config into aiortc-friendly payloads."""
        normalized: list[dict[str, Any]] = []
        for server in list(ice_servers or []):
            if not isinstance(server, dict):
                continue
            urls = [str(url or "").strip() for url in list(server.get("urls") or []) if str(url or "").strip()]
            if not urls:
                continue
            normalized.append(
                {
                    "urls": urls,
                    "username": str(server.get("username") or "").strip(),
                    "credential": str(server.get("credential") or "").strip(),
                }
            )
        return normalized

    def _set_microphone_available(self, available: bool) -> None:
        """Update the current microphone availability state."""
        normalized = bool(available)
        if self._microphone_available == normalized:
            return
        self._microphone_available = normalized
        self.microphone_available_changed.emit(normalized)

    def _emit_local_description(self, event_type: str) -> None:
        """Forward one local SDP description through the signaling layer."""
        local_description = getattr(self._peer_connection, "localDescription", None)
        if local_description is None:
            return
        self._emit_session_description(event_type, local_description)

    def _emit_session_description(self, event_type: str, session_description) -> None:
        """Forward one explicit SDP description through the signaling layer."""
        if session_description is None:
            return
        self._emit_or_queue_signal(
            event_type,
            {
                "call_id": self._call_id,
                "sdp": {
                    "type": session_description.type,
                    "sdp": session_description.sdp,
                },
            },
        )

    def _emit_or_queue_signal(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit signaling immediately when active, otherwise buffer it."""
        if self._signaling_ready:
            if event_type == "call_offer":
                self._offer_sent = True
            self.signal_generated.emit(event_type, payload)
            return
        self._pending_signals.append((event_type, payload))

    def _flush_pending_signals(self) -> None:
        """Emit any signaling generated during prewarm in original order."""
        if not self._signaling_ready or not self._pending_signals:
            return
        pending = list(self._pending_signals)
        self._pending_signals.clear()
        for event_type, payload in pending:
            if event_type == "call_offer":
                self._offer_sent = True
            self._log_timing("signal_flushed", event_type=event_type)
            self.signal_generated.emit(event_type, payload)

    def _has_pending_signal(self, event_type: str) -> bool:
        """Return whether one signaling message of the given type is queued."""
        target = str(event_type or "")
        return any(current_type == target for current_type, _payload in self._pending_signals)

    async def _flush_pending_remote_ice(self) -> None:
        """Apply buffered ICE only after a remote description exists."""
        if self._peer_connection is None or not self._pending_remote_ice:
            return
        pending = list(self._pending_remote_ice)
        self._pending_remote_ice.clear()
        for candidate in pending:
            try:
                await self._peer_connection.addIceCandidate(candidate)
            except ValueError:
                logger.debug("Dropped buffered invalid remote ICE candidate", exc_info=True)

    def _session_description_from_payload(self, payload: dict[str, Any]):
        """Build one aiortc session description from signaling payload."""
        if RTCSessionDescription is None:
            return None
        sdp_payload = payload.get("sdp") if isinstance(payload.get("sdp"), dict) else {}
        sdp_type = str(sdp_payload.get("type") or "").strip()
        sdp = str(sdp_payload.get("sdp") or "").strip()
        if not sdp_type or not sdp:
            return None
        return RTCSessionDescription(sdp=sdp, type=sdp_type)

    async def _play_remote_audio(self, track) -> None:
        """Drain one inbound remote audio track into the Qt output device."""
        if not self._remote_audio_output.is_available():
            self.state_changed.emit("Remote audio received (no output device)")
            return

        while True:
            try:
                frame = await track.recv()
            except MediaStreamError:
                break

            wrote_audio = self._remote_audio_output.consume_frame(frame)
            if wrote_audio and self._speaker_enabled and not self._remote_audio_started:
                self._remote_audio_started = True
                self._log_timing("first_remote_audio_frame")
                self.state_changed.emit("In call")

    async def _close(self) -> None:
        """Release aiortc resources."""
        current_task = asyncio.current_task()
        for task in list(self._tasks):
            if task is current_task:
                continue
            if not task.done():
                task.cancel()

        if self._peer_connection is not None:
            await self._peer_connection.close()
            self._peer_connection = None
        self._release_media_resources()
        self._signaling_ready = False
        self._offer_sent = False
        self._pending_signals.clear()
        self._pending_remote_ice.clear()

        self.state_changed.emit("Call ended")

    def _release_media_resources(self) -> None:
        """Release local capture and playback resources immediately."""
        if self._player is not None:
            audio_track = getattr(self._player, "audio", None)
            video_track = getattr(self._player, "video", None)
            for track in (audio_track, video_track):
                if track is None:
                    continue
                try:
                    track.stop()
                except Exception:
                    logger.debug("Failed to stop MediaPlayer track cleanly", exc_info=True)
            self._player = None
        self._local_audio_track = None

        self._remote_audio_output.close()
        self._remote_audio_started = False

    def _log_timing(self, stage: str, **extra: Any) -> None:
        """Log one engine-local timeline checkpoint for the active call."""
        normalized_stage = str(stage or "").strip()
        if not normalized_stage:
            return
        dedupe = {
            "peer_connection_created",
            "local_audio_capture_ready",
            "offer_applied",
            "offer_preload_applied",
            "answer_received",
            "first_remote_audio_frame",
        }
        if normalized_stage in dedupe and normalized_stage in self._timing_markers:
            return
        self._timing_markers.add(normalized_stage)
        delta_ms = int((time.perf_counter() - self._timing_origin) * 1000)
        details = " ".join(f"{key}={value}" for key, value in extra.items() if value not in {None, ""})
        suffix = f" {details}" if details else ""
        logger.info("[voice-engine] call_id=%s t=+%dms stage=%s%s", self._call_id, delta_ms, normalized_stage, suffix)
