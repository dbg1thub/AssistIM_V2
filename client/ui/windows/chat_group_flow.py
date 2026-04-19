"""Coordinator for the private-chat to group-chat creation flow."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog
from qfluentwidgets import InfoBar

from client.core.i18n import tr
from client.ui.windows.group_creation_dialogs import StartGroupChatDialog


class ChatGroupFlowCoordinator:
    """Own the dialog, selection, and post-create jump flow for chat-originated group creation."""

    def __init__(
        self,
        *,
        auth_controller,
        contact_controller,
        dialog_refs: set[QDialog],
        window_provider,
        schedule_ui_task,
        close_chat_info_drawer,
        open_group_session,
    ) -> None:
        self._auth_controller = auth_controller
        self._contact_controller = contact_controller
        self._dialog_refs = dialog_refs
        self._window_provider = window_provider
        self._schedule_ui_task = schedule_ui_task
        self._close_chat_info_drawer = close_chat_info_drawer
        self._open_group_session = open_group_session
        self._start_group_dialog: QDialog | None = None
        self._dialog_loading = False

    async def show_start_group_dialog(self, session) -> None:
        """Load contacts and open the frameless modal used to start one new group chat."""
        if self._raise_existing_dialog():
            return
        if self._dialog_loading:
            return
        self._dialog_loading = True
        try:
            counterpart_id = self._resolve_counterpart_id(session)
            if not counterpart_id:
                InfoBar.warning(
                    tr("chat.group_picker.title", "Start Group Chat"),
                    tr("chat.group_picker.no_counterpart", "Unable to resolve the current private chat participant."),
                    parent=self._window_provider(),
                    duration=2200,
                )
                return
            try:
                contacts = await self._contact_controller.load_contacts()
            except Exception:
                InfoBar.error(
                    tr("chat.group_picker.title", "Start Group Chat"),
                    tr("chat.group_picker.load_failed", "Unable to load contacts right now."),
                    parent=self._window_provider(),
                    duration=2200,
                )
                raise

            fixed_contact = next((contact for contact in contacts if contact.id == counterpart_id), None)
            if fixed_contact is None:
                InfoBar.warning(
                    tr("chat.group_picker.title", "Start Group Chat"),
                    tr("chat.group_picker.no_counterpart", "Unable to resolve the current private chat participant."),
                    parent=self._window_provider(),
                    duration=2200,
                )
                return

            dialog = StartGroupChatDialog(
                self._contact_controller,
                self._merge_group_picker_contacts(contacts),
                fixed_contact=fixed_contact,
                parent=self._window_provider(),
            )
            dialog.group_created.connect(self.handle_group_created)
            self._start_group_dialog = dialog
            dialog.destroyed.connect(lambda *_args: setattr(self, "_start_group_dialog", None))
            self._show_dialog(dialog)
        finally:
            self._dialog_loading = False

    def handle_group_created(self, group: object) -> None:
        """Jump from the current private chat into the newly created group."""
        self._close_chat_info_drawer()
        session_id = str(getattr(group, "session_id", "") or "")
        if not session_id:
            InfoBar.warning(
                tr("chat.group_picker.title", "Start Group Chat"),
                tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
                parent=self._window_provider(),
                duration=2200,
            )
            return

        self._schedule_ui_task(
            self.open_created_group_session(group),
            f"open created group {session_id}",
        )

    async def open_created_group_session(self, group: object) -> None:
        """Open the freshly created group session and report failures."""
        session_id = str(getattr(group, "session_id", "") or "")
        opened = await self._open_group_session(session_id)
        if opened:
            return

        InfoBar.warning(
            tr("chat.group_picker.title", "Start Group Chat"),
            tr("main_window.contact_jump.unavailable_message", "Unable to open this conversation right now."),
            parent=self._window_provider(),
            duration=2200,
        )

    def _resolve_counterpart_id(self, session) -> str:
        """Resolve the other participant id for the current direct chat."""
        extra = dict(getattr(session, "extra", {}) or {})
        counterpart_id = str(extra.get("counterpart_id", "") or "").strip()
        if counterpart_id:
            return counterpart_id

        current_user = self._auth_controller.current_user or {}
        current_user_id = str(current_user.get("id", "") or "")
        for participant_id in getattr(session, "participant_ids", []) or []:
            normalized_id = str(participant_id or "").strip()
            if not normalized_id or normalized_id == current_user_id:
                continue
            return normalized_id
        return ""

    @staticmethod
    def _merge_group_picker_contacts(contacts):
        """Return deduplicated friends including the active private-chat participant."""
        deduped = {}
        for contact in contacts:
            if contact.id:
                deduped[contact.id] = contact

        return sorted(
            deduped.values(),
            key=lambda item: item.display_name.lower(),
        )

    def _show_dialog(self, dialog: QDialog) -> None:
        """Keep one non-blocking modal dialog alive while it is visible."""
        self._dialog_refs.add(dialog)
        dialog.finished.connect(lambda _result=0, dlg=dialog: self._dialog_refs.discard(dlg))
        dialog.finished.connect(dialog.deleteLater)
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()

    def _raise_existing_dialog(self) -> bool:
        dialog = self._start_group_dialog
        if dialog is None:
            return False
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        return True
