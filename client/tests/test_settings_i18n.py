import os


def test_settings_interface_translates_fluentwidgets_builtin_text(monkeypatch) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
    from qfluentwidgets import FluentTranslator, RadioButton, SwitchButton

    from client.core.config import Language
    from client.core.i18n import current_locale, initialize_i18n
    import client.ui.windows.settings_interface as settings_module

    class _Capability:
        runtime_supports_gpu_offload = False
        missing_cuda_dependencies = ()
        gpu_free_memory_gb = 0.0
        gpu_total_memory_gb = 0.0
        gpu_name = ""

    monkeypatch.setattr(settings_module, "detect_local_ai_capabilities", lambda: _Capability())
    monkeypatch.setattr(settings_module, "installed_local_ai_model_specs", lambda: [])

    initialize_i18n(Language.CHINESE_SIMPLIFIED)
    app = QApplication.instance() or QApplication([])
    translator = FluentTranslator(current_locale())
    app.installTranslator(translator)
    app._test_fluent_translator = translator

    widget = settings_module.SettingsInterface()
    try:
        texts: set[str] = set()
        for widget_type in (QLabel, QPushButton, RadioButton, SwitchButton):
            for child in widget.findChildren(widget_type):
                text_getter = getattr(child, "text", None)
                if not callable(text_getter):
                    continue
                text = str(text_getter() or "").strip()
                if text:
                    texts.add(text)

        assert {"Choose color", "Custom color", "Default color", "Off", "On"}.isdisjoint(texts)
    finally:
        widget.deleteLater()
        app.removeTranslator(translator)
        initialize_i18n(Language.ENGLISH)
