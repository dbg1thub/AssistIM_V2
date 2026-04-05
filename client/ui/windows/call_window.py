"""Fluent voice/video call window backed by an aiortc engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon as FIF, FluentWidget, ToggleToolButton, ToolButton

from client.call.aiortc_voice_engine import AiortcVoiceEngine
from client.models.call import ActiveCallState
from client.models.call import CallMediaType
from client.ui.widgets.contact_shared import ContactAvatar


class _CallControl(QWidget):
    """Vertical call action button with one caption."""

    clicked = Signal()
    toggled = Signal(bool)

    def __init__(
        self,
        icon,
        label: str,
        *,
        checkable: bool = False,
        checked: bool = False,
        accent: str = "neutral",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        if checkable:
            self.button = ToggleToolButton(icon, self)
            self.button.setChecked(checked)
            self.button.toggled.connect(self.toggled.emit)
        else:
            self.button = ToolButton(icon, self)
            self.button.clicked.connect(self.clicked.emit)

        self.button.setObjectName(f"voiceCallControlButton_{accent}")
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.setFixedSize(68, 68)

        self.label = CaptionLabel(label, self)
        self.label.setObjectName("voiceCallControlLabel")
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.button, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignCenter)

    def set_label(self, text: str) -> None:
        self.label.setText(text)

    def set_icon(self, icon) -> None:
        self.button.setIcon(icon)

    def set_checked_quietly(self, checked: bool) -> None:
        self.button.blockSignals(True)
        self.button.setChecked(checked)
        self.button.blockSignals(False)


class _RoundedVideoPreview(QWidget):
    """Rounded preview surface that paints the current frame without edge bleed."""

    def __init__(self, radius: float = 10.0, parent=None) -> None:
        super().__init__(parent)
        self._radius = radius
        self._pixmap = QPixmap()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = QPixmap() if pixmap is None else pixmap
        self.update()

    def clear_pixmap(self) -> None:
        self._pixmap = QPixmap()
        self.update()

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        rect = self.rect()
        path.addRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        painter.setClipPath(path)
        if self._pixmap.isNull():
            painter.fillPath(path, Qt.GlobalColor.transparent)
            return
        scaled = self._pixmap.scaled(
            rect.size(),
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = (rect.width() - scaled.width()) // 2
        y = (rect.height() - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)


class CallWindow(FluentWidget):
    """Compact call window built with QFluentWidgets controls."""

    hangup_requested = Signal(str)
    signal_generated = Signal(str, object)

    def __init__(
        self,
        call: ActiveCallState,
        *,
        session_title: str,
        peer_label: str,
        avatar: str = "",
        avatar_seed: str = "",
        self_avatar: str = "",
        self_avatar_seed: str = "",
        self_label: str = "",
        ice_servers: list[dict[str, Any]],
        parent=None,
    ) -> None:
        self._is_video_call = call.media_type == CallMediaType.VIDEO.value
        super().__init__(parent)
        self._call = call
        self._session_title = session_title
        self._peer_label = peer_label
        self._avatar = str(avatar or "")
        self._avatar_seed = str(avatar_seed or "")
        self._self_avatar = str(self_avatar or "")
        self._self_avatar_seed = str(self_avatar_seed or "")
        self._self_label = str(self_label or "").strip() or "Me"
        self._media_started = False
        self._closing_programmatically = False
        self._call_started_at: datetime | None = call.answered_at
        self._call_connected = False
        self._has_audio_input = bool(QMediaDevices.audioInputs())
        self._has_audio_output = bool(QMediaDevices.audioOutputs())
        self._has_video_input = bool(QMediaDevices.videoInputs())
        self._default_audio_input = str(QMediaDevices.defaultAudioInput().description() or "").strip()
        self._default_video_input = str(QMediaDevices.defaultVideoInput().description() or "").strip() if self._has_video_input else ""
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._refresh_call_duration)

        self._engine = AiortcVoiceEngine(
            call.call_id,
            media_type=call.media_type,
            ice_servers=ice_servers,
            audio_input_name=self._default_audio_input if self._has_audio_input else None,
            video_input_name=self._default_video_input if self._has_video_input else None,
            parent=self,
        )
        self._engine.signal_generated.connect(self.signal_generated.emit)
        self._engine.state_changed.connect(self._on_engine_state_changed)
        self._engine.microphone_muted_changed.connect(self._on_microphone_muted_changed)
        self._engine.microphone_available_changed.connect(self._on_microphone_available_changed)
        self._engine.speaker_enabled_changed.connect(self._on_speaker_enabled_changed)
        self._engine.camera_enabled_changed.connect(self._on_camera_enabled_changed)
        self._engine.camera_available_changed.connect(self._on_camera_available_changed)
        self._engine.local_video_frame_changed.connect(self._on_local_video_frame_changed)
        self._engine.remote_video_frame_changed.connect(self._on_remote_video_frame_changed)

        self.setWindowTitle("")
        self.setObjectName("callWindow")
        self.setFixedSize(380, 680)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor("#272322", "#272322")

        root = QVBoxLayout(self)
        if self._is_video_call:
            root.setContentsMargins(0, 0, 0, 0)
        else:
            root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(0)

        self.header_status = BodyLabel("", self)
        self.header_status.setObjectName("callHeaderStatus")
        self.header_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.header_status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

        self.avatar_widget = ContactAvatar(100 if not self._is_video_call else 72, self)
        self.avatar_widget.set_avatar(
            self._avatar,
            fallback=(peer_label or session_title or "?")[:1],
            seed=self._avatar_seed,
        )

        self.name_label = BodyLabel(peer_label or session_title, self)
        self.name_label.setObjectName("callPeerName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = CaptionLabel("", self)
        self.status_label.setObjectName("callStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(12)
        center.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center.addWidget(self.avatar_widget, 0, Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignCenter)

        if self._is_video_call:
            self.remote_video_label = QLabel(self)
            self.remote_video_label.setObjectName("callRemoteVideo")
            self.remote_video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            root.addWidget(self.remote_video_label, 1)

            self.remote_placeholder_avatar = ContactAvatar(88, self)
            self.remote_placeholder_avatar.set_avatar(
                self._avatar,
                fallback=(peer_label or session_title or "?")[:1],
                seed=self._avatar_seed,
            )

            self.local_preview_container = QWidget(self)
            self.local_preview_container.setObjectName("callLocalPreviewContainer")
            self.local_preview_container.setFixedSize(108, 144)
            preview_layout = QVBoxLayout(self.local_preview_container)
            preview_layout.setContentsMargins(0, 0, 0, 0)
            preview_layout.setSpacing(0)

            self.local_preview_label = _RoundedVideoPreview(10, self.local_preview_container)
            self.local_preview_label.setObjectName("callLocalPreview")
            preview_layout.addWidget(self.local_preview_label, 1)

            self.local_preview_avatar = ContactAvatar(56, self.local_preview_container)
            self.local_preview_avatar.set_avatar(
                self._self_avatar,
                fallback=self._self_label[:1],
                seed=self._self_avatar_seed,
            )

            self.controls_container = QWidget(self)
            self.controls_container.setObjectName("callControlsContainer")
            self.avatar_widget.hide()
            self.name_label.hide()
            self.status_label.hide()
            self._set_remote_video_placeholder()
            self._set_local_video_placeholder()
        else:
            root.addStretch(2)
            root.addLayout(center)
            root.addStretch(5)
            self.header_status.hide()

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(24 if self._is_video_call else 28)
        controls.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.mic_control = _CallControl(
            FIF.MICROPHONE if self._has_audio_input else FIF.MUTE,
            "Mic on" if self._has_audio_input else "No mic",
            checkable=True,
            checked=False,
            accent="muted",
            parent=self,
        )
        self.end_control = _CallControl(FIF.PHONE, "End", accent="danger", parent=self)
        self.speaker_control = _CallControl(
            FIF.SPEAKERS if self._has_audio_output else FIF.MUTE,
            "Speaker on" if self._has_audio_output else "No speaker",
            checkable=True,
            checked=self._has_audio_output,
            accent="bright",
            parent=self,
        )
        self.camera_control = _CallControl(
            FIF.CAMERA if self._has_video_input else FIF.VIDEO,
            "Camera on" if self._has_video_input else "No camera",
            checkable=True,
            checked=self._has_video_input,
            accent="muted",
            parent=self,
        )

        self.mic_control.toggled.connect(self._on_mic_toggled)
        self.end_control.clicked.connect(self._emit_hangup)
        self.speaker_control.toggled.connect(self._on_speaker_toggled)
        self.camera_control.toggled.connect(self._on_camera_toggled)

        self.mic_control.button.setEnabled(self._has_audio_input)
        self.speaker_control.button.setEnabled(self._has_audio_output)
        self.camera_control.button.setEnabled(self._is_video_call and self._has_video_input)

        controls.addWidget(self.mic_control)
        controls.addWidget(self.end_control)
        controls.addWidget(self.speaker_control)
        if self._is_video_call:
            controls.insertWidget(2, self.camera_control)
            self.controls_container.setLayout(controls)
            self._layout_video_overlays()
        else:
            root.addLayout(controls)

        self.set_status_text(self._initial_status_text())
        self._apply_style()

    @property
    def call_id(self) -> str:
        return self._call.call_id

    def start_media(self, *, is_caller: bool) -> None:
        if self._media_started:
            return
        self._media_started = True
        self.set_status_text("Connecting...")
        self._engine.start(is_caller=is_caller)

    def prepare_media(self, *, is_caller: bool) -> None:
        self._engine.prepare(is_caller=is_caller)

    def activate_signaling(self) -> None:
        self._engine.activate_signaling()

    def sync_call_state(self, call: ActiveCallState) -> None:
        self._call = call
        if call.answered_at is not None:
            self._call_started_at = call.answered_at
        if call.status == "accepted":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Connecting...")
            return
        if call.status == "ringing":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Ringing...")
            return
        if call.status == "inviting":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Waiting...")

    def handle_offer(self, payload: dict[str, Any]) -> None:
        if not self._media_started:
            self._engine.preload_offer(payload)
            return
        self._engine.receive_offer(payload)

    def handle_answer(self, payload: dict[str, Any]) -> None:
        self._engine.receive_answer(payload)

    def handle_ice_candidate(self, payload: dict[str, Any]) -> None:
        self._engine.receive_ice_candidate(payload)

    def end_call(self) -> None:
        self._closing_programmatically = True
        self._duration_timer.stop()
        self._engine.close()
        self.close()

    def set_status_text(self, text: str) -> None:
        normalized = str(text or "").strip() or "Waiting..."
        if self._is_video_call:
            self.header_status.setText(normalized)
            return
        self.status_label.setText(normalized)

    def closeEvent(self, event) -> None:
        if not self._closing_programmatically:
            self._emit_hangup()
        self._duration_timer.stop()
        self._engine.close()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._center_on_screen()
        self._layout_video_overlays()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_is_video_call"):
            self._layout_video_overlays()

    def _emit_hangup(self) -> None:
        if self._closing_programmatically:
            return
        self.hangup_requested.emit(self._call.call_id)

    def _on_mic_toggled(self, checked: bool) -> None:
        self._engine.set_microphone_muted(bool(checked))

    def _on_speaker_toggled(self, checked: bool) -> None:
        self._engine.set_speaker_enabled(bool(checked))

    def _on_camera_toggled(self, checked: bool) -> None:
        self._engine.set_camera_enabled(bool(checked))

    def _on_microphone_muted_changed(self, muted: bool) -> None:
        if not self.mic_control.button.isEnabled():
            return
        self.mic_control.set_icon(FIF.MUTE if muted else FIF.MICROPHONE)
        self.mic_control.set_label("Mic off" if muted else "Mic on")
        self.mic_control.set_checked_quietly(muted)

    def _on_microphone_available_changed(self, available: bool) -> None:
        self.mic_control.button.setEnabled(bool(available))
        if available:
            self.mic_control.set_icon(FIF.MICROPHONE)
            self.mic_control.set_label("Mic on")
            self.mic_control.set_checked_quietly(False)
            return
        self.mic_control.set_icon(FIF.MUTE)
        self.mic_control.set_label("No mic")
        self.mic_control.set_checked_quietly(True)

    def _on_speaker_enabled_changed(self, enabled: bool) -> None:
        if not self.speaker_control.button.isEnabled():
            return
        self.speaker_control.set_icon(FIF.SPEAKERS if enabled else FIF.MUTE)
        self.speaker_control.set_label("Speaker on" if enabled else "Speaker off")
        self.speaker_control.set_checked_quietly(enabled)

    def _on_camera_enabled_changed(self, enabled: bool) -> None:
        if not self._is_video_call:
            return
        if self.camera_control.button.isEnabled():
            self.camera_control.set_icon(FIF.CAMERA if enabled else FIF.VIDEO)
            self.camera_control.set_label("Camera on" if enabled else "Camera off")
            self.camera_control.set_checked_quietly(enabled)
        if not enabled:
            self._set_local_video_placeholder()

    def _on_camera_available_changed(self, available: bool) -> None:
        if not self._is_video_call:
            return
        self.camera_control.button.setEnabled(bool(available))
        if available:
            self.camera_control.set_icon(FIF.CAMERA)
            self.camera_control.set_label("Camera on")
            self.camera_control.set_checked_quietly(True)
            return
        self.camera_control.set_icon(FIF.VIDEO)
        self.camera_control.set_label("No camera")
        self.camera_control.set_checked_quietly(False)
        self._set_local_video_placeholder()

    def _on_local_video_frame_changed(self, image: object) -> None:
        if not self._is_video_call:
            return
        if image is None:
            self._set_local_video_placeholder()
            return
        if not isinstance(image, QImage) or image.isNull():
            return
        target_size = self.local_preview_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        pixmap = QPixmap.fromImage(image)
        self.local_preview_label.set_pixmap(pixmap)
        self.local_preview_avatar.hide()

    def _on_remote_video_frame_changed(self, image: object) -> None:
        if not self._is_video_call:
            return
        if image is None:
            self._set_remote_video_placeholder()
            return
        if not isinstance(image, QImage) or image.isNull():
            return
        target_size = self.remote_video_label.size()
        if target_size.width() <= 0 or target_size.height() <= 0:
            return
        pixmap = QPixmap.fromImage(image)
        self.remote_video_label.setPixmap(
            pixmap.scaled(
                target_size,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.remote_video_label.setText("")
        self.remote_placeholder_avatar.hide()

    def _on_engine_state_changed(self, text: str) -> None:
        normalized = str(text or "").strip()
        lowered = normalized.lower()

        if lowered == "in call":
            self._mark_call_connected()
            return
        if self._call_connected and lowered not in {
            "call ended",
            "connection disconnected",
            "connection failed",
            "connection closed",
        }:
            return
        if lowered in {
            "opening microphone",
            "microphone ready",
            "creating offer",
            "received offer",
            "remote answer applied",
        }:
            self.set_status_text("Connecting...")
            return
        if lowered == "waiting for caller":
            self.set_status_text("Waiting...")
            return
        if lowered == "call ended":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Call ended")
            return
        if lowered in {"speaker enabled", "speaker disabled", "mic muted", "mic active", "camera active", "camera off", "camera ready"}:
            return
        if lowered.startswith("remote audio received") or lowered == "remote audio connected":
            if self._call_connected:
                return
            self.set_status_text("Connecting...")
            return
        if lowered == "connection connecting":
            self.set_status_text("Connecting...")
            return
        if lowered == "connection connected":
            self.set_status_text("Connecting...")
            return
        if lowered == "connection new":
            self.set_status_text(self._initial_status_text())
            return
        if lowered == "connection disconnected":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Disconnected")
            return
        if lowered == "connection failed":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Connection failed")
            return
        if lowered == "connection closed":
            self._duration_timer.stop()
            self._call_connected = False
            self.set_status_text("Call ended")

    def _initial_status_text(self) -> str:
        if self._call.status == "accepted":
            return "Connecting..."
        if self._call.status == "ringing":
            return "Ringing..."
        return "Waiting..."

    def _set_remote_video_placeholder(self) -> None:
        if not self._is_video_call:
            return
        self.remote_video_label.setPixmap(QPixmap())
        self.remote_video_label.setText("")
        self.remote_placeholder_avatar.show()

    def _set_local_video_placeholder(self) -> None:
        if not self._is_video_call:
            return
        self.local_preview_label.clear_pixmap()
        self.local_preview_avatar.show()

    def _mark_call_connected(self, *, force: bool = False) -> None:
        if self._call_connected and not force:
            return
        self._call_connected = True
        self._call_started_at = datetime.now()
        self._refresh_call_duration()
        if not self._duration_timer.isActive():
            self._duration_timer.start()

    def _refresh_call_duration(self) -> None:
        if not self._call_connected or self._call_started_at is None:
            return
        started_at = self._call_started_at
        now = datetime.now(started_at.tzinfo) if started_at.tzinfo is not None else datetime.now()
        elapsed = max(0, int((now - started_at).total_seconds()))
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            self.set_status_text(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
            return
        self.set_status_text(f"{minutes:02d}:{seconds:02d}")

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QWidget#callWindow {
                background:
                    qradialgradient(cx:0.5, cy:0.35, radius:0.95, fx:0.5, fy:0.35,
                        stop:0 rgba(117, 109, 103, 150),
                        stop:0.56 rgba(54, 49, 47, 235),
                        stop:1 rgba(33, 31, 30, 250));
            }
            QLabel#callPeerName {
                color: #F6F3F1;
                font-size: 18px;
                font-weight: 600;
            }
            QLabel#callStatus, QLabel#callHeaderStatus {
                color: rgba(255, 255, 255, 0.88);
                font-size: 13px;
            }
            QLabel#callRemoteVideo {
                background: #121212;
                color: transparent;
            }
            QWidget#callLocalPreviewContainer {
                background: rgba(92, 92, 92, 0.88);
                border-radius: 10px;
                border: 1px solid rgba(255, 255, 255, 0.08);
            }
            QLabel#callLocalPreview {
                background: transparent;
                color: transparent;
            }
            QWidget#callControlsContainer {
                background: transparent;
            }
            QToolButton#voiceCallControlButton_muted {
                background: rgba(95, 95, 95, 0.42);
                border: none;
                border-radius: 34px;
            }
            QToolButton#voiceCallControlButton_muted:hover {
                background: rgba(110, 110, 110, 0.55);
            }
            QToolButton#voiceCallControlButton_muted:disabled {
                background: rgba(78, 78, 78, 0.24);
                color: rgba(255, 255, 255, 0.32);
            }
            QToolButton#voiceCallControlButton_bright {
                background: rgba(255, 255, 255, 0.96);
                border: none;
                border-radius: 34px;
            }
            QToolButton#voiceCallControlButton_bright:hover {
                background: rgba(255, 255, 255, 1.0);
            }
            QToolButton#voiceCallControlButton_bright:disabled {
                background: rgba(255, 255, 255, 0.18);
                color: rgba(255, 255, 255, 0.4);
            }
            QToolButton#voiceCallControlButton_danger {
                background: #FF5858;
                border: none;
                border-radius: 34px;
            }
            QToolButton#voiceCallControlButton_danger:hover {
                background: #FF6A6A;
            }
            QLabel#voiceCallControlLabel {
                color: rgba(255, 255, 255, 0.9);
                font-size: 12px;
            }
            """
        )

    def _layout_video_overlays(self) -> None:
        if not self._is_video_call:
            return
        if not all(
            hasattr(self, name)
            for name in (
                "remote_video_label",
                "header_status",
                "local_preview_container",
                "local_preview_avatar",
                "remote_placeholder_avatar",
                "controls_container",
            )
        ):
            return
        rect = self.rect()
        title_bar_height = max(36, int(getattr(getattr(self, "titleBar", None), "height", lambda: 36)()))
        content_rect = rect.adjusted(0, title_bar_height, 0, 0)
        self.remote_video_label.setGeometry(content_rect)

        top_margin = 8
        side_margin = 18
        self.header_status.adjustSize()
        self.header_status.move(
            max(0, (rect.width() - self.header_status.width()) // 2),
            max(0, (title_bar_height - self.header_status.height()) // 2),
        )
        self.header_status.raise_()

        preview_size = self.local_preview_container.size()
        self.local_preview_container.move(
            max(side_margin, rect.width() - preview_size.width() - side_margin),
            content_rect.top() + top_margin,
        )
        self.local_preview_container.raise_()
        self.local_preview_label.setGeometry(self.local_preview_container.rect())
        self.local_preview_avatar.move(
            max(0, (preview_size.width() - self.local_preview_avatar.width()) // 2),
            max(0, (preview_size.height() - self.local_preview_avatar.height()) // 2),
        )
        self.local_preview_avatar.raise_()

        self.remote_placeholder_avatar.move(
            max(0, (content_rect.width() - self.remote_placeholder_avatar.width()) // 2),
            content_rect.top() + max(0, (content_rect.height() - self.remote_placeholder_avatar.height()) // 2) - 28,
        )
        self.remote_placeholder_avatar.raise_()

        controls_width = self.controls_container.sizeHint().width()
        controls_height = self.controls_container.sizeHint().height()
        self.controls_container.setGeometry(
            max(0, (rect.width() - controls_width) // 2),
            max(content_rect.top(), rect.height() - controls_height - 34),
            controls_width,
            controls_height,
        )
        self.controls_container.raise_()
        title_bar = getattr(self, "titleBar", None)
        if title_bar is not None:
            title_bar.show()
            title_bar.raise_()

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.screenAt(self.pos())
        if screen is None and self.parentWidget() is not None:
            screen = QGuiApplication.screenAt(self.parentWidget().window().frameGeometry().center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geometry.center())
        self.move(frame.topLeft())
