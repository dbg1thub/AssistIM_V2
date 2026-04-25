from __future__ import annotations

import json

from client.services.local_model_resource_importer import (
    LocalModelImportError,
    LocalModelResourceImporter,
)


def _write_manifest(path, file_name: str = "known-model.gguf") -> None:
    path.write_text(
        json.dumps(
            {
                "models": [
                    {
                        "model_id": "known-model",
                        "file_name": file_name,
                        "parameter_billion": 2.0,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_import_chat_gguf_requires_manifest_file_name_and_replaces_target(tmp_path) -> None:
    models_dir = tmp_path / "models"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    source = tmp_path / "incoming" / "known-model.gguf"
    source.parent.mkdir()
    source.write_bytes(b"new chat model")
    target = models_dir / "known-model.gguf"
    target.parent.mkdir()
    target.write_bytes(b"old chat model")

    result = LocalModelResourceImporter(models_dir=models_dir, manifest_path=manifest_path).import_chat_gguf(source)

    assert result.kind == "chat"
    assert result.model_id == "known-model"
    assert result.target_path == target.resolve()
    assert target.read_bytes() == b"new chat model"
    assert list(models_dir.glob("*.tmp-*")) == []


def test_import_chat_gguf_rejects_unknown_manifest_file(tmp_path) -> None:
    models_dir = tmp_path / "models"
    manifest_path = tmp_path / "manifest.json"
    _write_manifest(manifest_path)
    source = tmp_path / "unknown.gguf"
    source.write_bytes(b"unknown")

    importer = LocalModelResourceImporter(models_dir=models_dir, manifest_path=manifest_path)
    try:
        importer.import_chat_gguf(source)
    except LocalModelImportError as exc:
        assert exc.code == "MODEL_NOT_IN_MANIFEST"
    else:
        raise AssertionError("unknown chat model should be rejected")

    assert not (models_dir / "unknown.gguf").exists()


def test_import_embedding_gguf_uses_fixed_embedding_target(tmp_path) -> None:
    source = tmp_path / "jina.gguf"
    source.write_bytes(b"embedding model")
    target = tmp_path / "models" / "jina-embeddings-v3-Q4_K_M.gguf"

    result = LocalModelResourceImporter(
        models_dir=tmp_path / "models",
        manifest_path=tmp_path / "manifest.json",
        embedding_target_path=target,
    ).import_embedding_gguf(source)

    assert result.kind == "embedding"
    assert result.model_id == "jina-embeddings-v3-Q4_K_M"
    assert result.target_path == target.resolve()
    assert target.read_bytes() == b"embedding model"


def test_import_faster_whisper_directory_requires_key_files(tmp_path) -> None:
    source = tmp_path / "small"
    source.mkdir()
    (source / "config.json").write_text("{}", encoding="utf-8")
    (source / "model.bin").write_bytes(b"model")
    target_root = tmp_path / "models" / "faster-whisper"

    importer = LocalModelResourceImporter(
        models_dir=tmp_path / "models",
        manifest_path=tmp_path / "manifest.json",
        voice_model_root=target_root,
    )
    try:
        importer.import_faster_whisper_directory(source)
    except LocalModelImportError as exc:
        assert exc.code == "VOICE_MODEL_INCOMPLETE"
        assert "tokenizer.json" in str(exc)
        assert "vocabulary.txt" in str(exc)
    else:
        raise AssertionError("incomplete faster-whisper directory should be rejected")

    assert not (target_root / "small").exists()


def test_import_faster_whisper_directory_accepts_parent_or_model_directory(tmp_path) -> None:
    parent = tmp_path / "downloaded"
    source = parent / "small"
    source.mkdir(parents=True)
    for filename in ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt"):
        (source / filename).write_bytes(filename.encode("utf-8"))
    (source / "nested").mkdir()
    (source / "nested" / "extra.txt").write_text("extra", encoding="utf-8")
    target_root = tmp_path / "models" / "faster-whisper"

    result = LocalModelResourceImporter(
        models_dir=tmp_path / "models",
        manifest_path=tmp_path / "manifest.json",
        voice_model_root=target_root,
    ).import_faster_whisper_directory(parent)

    assert result.kind == "voice"
    assert result.model_id == "small"
    assert result.target_path == (target_root / "small").resolve()
    assert (target_root / "small" / "model.bin").read_bytes() == b"model.bin"
    assert (target_root / "small" / "nested" / "extra.txt").read_text(encoding="utf-8") == "extra"
