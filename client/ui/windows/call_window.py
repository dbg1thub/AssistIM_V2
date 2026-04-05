"""Fluent voice-call window backed by an aiortc engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CaptionLabel, FluentIcon as FIF, FluentWidget, ToggleToolButton, ToolButton

from client.call.aiortc_voice_engine import AiortcVoiceEngine
from client.models.call import ActiveCallState
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
        """Update the caption."""
        self.label.setText(text)

    def set_icon(self, icon) -> None:
        """Update the displayed icon."""
        self.button.setIcon(icon)

    def set_checked_quietly(self, checked: bool) -> None:
        """Update the check state without re-emitting toggled."""
        self.button.blockSignals(True)
        self.button.setChecked(checked)
        self.button.blockSignals(False)


class CallWindow(FluentWidget):
    """Compact voice-call window built with QFluentWidgets controls."""

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
        ice_servers: list[dict[str, Any]],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._call = call
        self._session_title = session_title
        self._peer_label = peer_label
        self._avatar = str(avatar or "")
        self._avatar_seed = str(avatar_seed or "")
        self._media_started = False
        self._closing_programmatically = False
        self._call_started_at: datetime | None = call.answered_at
        self._call_connected = False
        self._has_audio_input = bool(QMediaDevices.audioInputs())
        self._has_audio_output = bool(QMediaDevices.audioOutputs())
        self._default_audio_input = str(QMediaDevices.defaultAudioInput().description() or "").strip()
        self._duration_timer = QTimer(self)
        self._duration_timer.setInterval(1000)
        self._duration_timer.timeout.connect(self._refresh_call_duration)

        self._engine = AiortcVoiceEngine(
            call.call_id,
            ice_servers=ice_servers,
            audio_input_name=self._default_audio_input if self._has_audio_input else None,
            parent=self,
        )
        self._engine.signal_generated.connect(self.signal_generated.emit)
        self._engine.state_changed.connect(self._on_engine_state_changed)
        self._engine.microphone_muted_changed.connect(self._on_microphone_muted_changed)
        self._engine.microphone_available_changed.connect(self._on_microphone_available_changed)
        self._engine.speaker_enabled_changed.connect(self._on_speaker_enabled_changed)

        self.setWindowTitle("")
        self.setObjectName("voiceCallWindow")
        self.setFixedSize(380, 680)
        self.setMicaEffectEnabled(False)
        self.setCustomBackgroundColor("#272322", "#272322")

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 28, 28, 28)
        root.setSpacing(0)

        root.addStretch(2)

        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(12)
        center.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.avatar_widget = ContactAvatar(100, self)
        self.avatar_widget.set_avatar(
            self._avatar,
            fallback=(peer_label or session_title or "?")[:1],
            seed=self._avatar_seed,
        )

        self.name_label = BodyLabel(peer_label or session_title, self)
        self.name_label.setObjectName("voiceCallPeerName")
        self.name_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.status_label = CaptionLabel("", self)
        self.status_label.setObjectName("voiceCallStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        center.addWidget(self.avatar_widget, 0, Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.name_label, 0, Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignCenter)
        root.addLayout(center)

        root.addStretch(5)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(28)
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

        self.mic_control.toggled.connect(self._on_mic_toggled)
        self.end_control.clicked.connect(self._emit_hangup)
        self.speaker_control.toggled.connect(self._on_speaker_toggled)

        self.mic_control.button.setEnabled(self._has_audio_input)
        self.speaker_control.button.setEnabled(self._has_audio_output)

        controls.addWidget(self.mic_control)
        controls.addWidget(self.end_control)
        controls.addWidget(self.speaker_control)
        root.addLayout(controls)

        self.set_status_text(self._initial_status_text())
        self._apply_style()

    @property
    def call_id(self) -> str:
        """Return the active call id."""
        return self._call.call_id

    def start_media(self, *, is_caller: bool) -> None:
        """Start one aiortc media session."""
        if self._media_started:
            return
        self._media_started = True
        self.set_status_text("Connecting...")
        self._engine.start(is_caller=is_caller)

    def prepare_media(self, *, is_caller: bool) -> None:
        """Prewarm local media to reduce post-accept connection delay."""
        self._engine.prepare(is_caller=is_caller)

    def activate_signaling(self) -> None:
        """Flush queued signaling without marking the media session as started."""
        self._engine.activate_signaling()

    def sync_call_state(self, call: ActiveCallState) -> None:
        """Update the window with the latest signaling state snapshot."""
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
        """Apply one inbound SDP offer."""
        if not self._media_started:
            self._engine.preload_offer(payload)
            return
        self._engine.receive_offer(payload)

    def handle_answer(self, payload: dict[str, Any]) -> None:
        """Apply one inbound SDP answer."""
        self._engine.receive_answer(payload)

    def handle_ice_candidate(self, payload: dict[str, Any]) -> None:
        """Apply one inbound ICE candidate."""
        if not self._media_started:
            self._engine.receive_ice_candidate(payload)
            return
        self._engine.receive_ice_candidate(payload)

    def end_call(self) -> None:
        """Close the call window programmatically."""
        self._closing_programmatically = True
        self._duration_timer.stop()
        self._engine.close()
        self.close()

    def set_status_text(self, text: str) -> None:
        """Update the status line."""
        self.status_label.setText(str(text or "").strip() or "Waiting...")

    def closeEvent(self, event) -> None:
        """Forward manual close actions to the signaling layer."""
        if not self._closing_programmatically:
            self._emit_hangup()
        self._duration_timer.stop()
        self._engine.close()
        super().closeEvent(event)

    def showEvent(self, event) -> None:
        """Center the call window on the most relevant screen."""
        super().showEvent(event)
        self._center_on_screen()

    def _emit_hangup(self) -> None:
        """Request one hangup from the outer controller."""
        if self._closing_programmatically:
            return
        self.hangup_requested.emit(self._call.call_id)

    def _on_mic_toggled(self, checked: bool) -> None:
        """Toggle the microphone mute state."""
        self._engine.set_microphone_muted(bool(checked))

    def _on_speaker_toggled(self, checked: bool) -> None:
        """Toggle the speaker state."""
        self._engine.set_speaker_enabled(bool(checked))

    def _on_microphone_muted_changed(self, muted: bool) -> None:
        """Reflect microphone state back into the button."""
        if not self.mic_control.button.isEnabled():
            return
        self.mic_control.set_icon(FIF.MUTE if muted else FIF.MICROPHONE)
        self.mic_control.set_label("Mic off" if muted else "Mic on")
        self.mic_control.set_checked_quietly(muted)

    def _on_microphone_available_changed(self, available: bool) -> None:
        """Disable the microphone button when capture is unavailable."""
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
        """Reflect speaker state back into the button."""
        if not self.speaker_control.button.isEnabled():
            return
        self.speaker_control.set_icon(FIF.SPEAKERS if enabled else FIF.MUTE)
        self.speaker_control.set_label("Speaker on" if enabled else "Speaker off")
        self.speaker_control.set_checked_quietly(enabled)

    def _on_engine_state_changed(self, text: str) -> None:
        """Keep the top status line focused on call stage only."""
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
        if lowered in {"speaker enabled", "speaker disabled", "mic muted", "mic active"}:
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
            return

    def _initial_status_text(self) -> str:
        """Map current signaling state to the initial label."""
        if self._call.status == "accepted":
            return "Connecting..."
        if self._call.status == "ringing":
            return "Ringing..."
        return "Waiting..."

    def _mark_call_connected(self, *, force: bool = False) -> None:
        """Switch the status line into duration mode."""
        if self._call_connected and not force:
            return
        self._call_connected = True
        self._call_started_at = datetime.now()
        self._refresh_call_duration()
        if not self._duration_timer.isActive():
            self._duration_timer.start()

    def _refresh_call_duration(self) -> None:
        """Render one mm:ss or hh:mm:ss duration label."""
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
        """Apply the compact dark Fluent visual treatment."""
        self.setStyleSheet(
            """
            QWidget#voiceCallWindow {
                background:
                    qradialgradient(cx:0.5, cy:0.35, radius:0.95, fx:0.5, fy:0.35,
                        stop:0 rgba(117, 109, 103, 150),
                        stop:0.56 rgba(54, 49, 47, 235),
                        stop:1 rgba(33, 31, 30, 250));
            }
            QLabel#voiceCallPeerName {
                color: #F6F3F1;
                font-size: 18px;
                font-weight: 600;
            }
            QLabel#voiceCallStatus {
                color: rgba(255, 255, 255, 0.82);
                font-size: 13px;
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

    def _center_on_screen(self) -> None:
        """Place the window at the center of the current screen work area."""
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
