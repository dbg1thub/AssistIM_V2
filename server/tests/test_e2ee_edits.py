from __future__ import annotations


def test_edit_message_preserves_encrypted_extra_payload(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice", "Alice")
    bob = user_factory("bob", "Bob")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={
            "participant_ids": [bob["user"]["id"]],
            "encryption_mode": "e2ee_private",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    original_extra = {
        "encryption": {
            "enabled": True,
            "scheme": "x25519-aesgcm-v1",
            "content_ciphertext": "cipher-original",
            "sender_device_id": "device-alice",
            "sender_identity_key_public": "pub-alice",
            "recipient_user_id": bob["user"]["id"],
            "recipient_device_id": "device-bob",
            "recipient_prekey_type": "signed",
            "recipient_prekey_id": 1,
            "nonce": "nonce-original",
            "local_plaintext": "local:original",
            "local_plaintext_version": "v1",
            "decryption_state": "missing_private_key",
            "recovery_action": "reprovision_device",
            "local_device_id": "device-bob",
            "target_device_id": "device-bob",
            "can_decrypt": False,
        }
    }
    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000027",
            "content": "cipher-original",
            "message_type": "text",
            "extra": original_extra,
        },
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_id = send_message_response.json()["data"]["message_id"]

    updated_extra = {
        "encryption": {
            "enabled": True,
            "scheme": "x25519-aesgcm-v1",
            "content_ciphertext": "cipher-updated",
            "sender_device_id": "device-alice",
            "sender_identity_key_public": "pub-alice",
            "recipient_user_id": bob["user"]["id"],
            "recipient_device_id": "device-bob",
            "recipient_prekey_type": "signed",
            "recipient_prekey_id": 1,
            "nonce": "nonce-updated",
            "local_plaintext": "local:updated",
            "decryption_state": "missing_private_key",
            "recovery_action": "reprovision_device",
            "local_device_id": "device-bob",
            "target_device_id": "device-bob",
            "can_decrypt": False,
        }
    }
    edit_response = client.put(
        f"/api/v1/messages/{message_id}",
        json={
            "content": "cipher-updated",
            "extra": updated_extra,
        },
        headers=auth_header(alice["access_token"]),
    )
    assert edit_response.status_code == 200
    edit_payload = edit_response.json()["data"]
    assert edit_payload["content"] == "cipher-updated"
    assert edit_payload["status"] == "edited"
    assert edit_payload["extra"]["encryption"]["content_ciphertext"] == "cipher-updated"
    assert edit_payload["extra"]["encryption"]["recipient_prekey_type"] == "signed"
    assert "local_plaintext" not in edit_payload["extra"]["encryption"]
    assert "local_plaintext_version" not in edit_payload["extra"]["encryption"]
    assert "decryption_state" not in edit_payload["extra"]["encryption"]
    assert "recovery_action" not in edit_payload["extra"]["encryption"]
    assert "local_device_id" not in edit_payload["extra"]["encryption"]
    assert "target_device_id" not in edit_payload["extra"]["encryption"]
    assert "can_decrypt" not in edit_payload["extra"]["encryption"]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    assert history_payload[0]["message_id"] == message_id
    assert history_payload[0]["content"] == "cipher-updated"
    assert history_payload[0]["extra"]["encryption"]["content_ciphertext"] == "cipher-updated"
    assert "local_plaintext" not in history_payload[0]["extra"]["encryption"]
    assert "local_plaintext_version" not in history_payload[0]["extra"]["encryption"]
    assert "decryption_state" not in history_payload[0]["extra"]["encryption"]
    assert "recovery_action" not in history_payload[0]["extra"]["encryption"]
    assert "local_device_id" not in history_payload[0]["extra"]["encryption"]
    assert "target_device_id" not in history_payload[0]["extra"]["encryption"]
    assert "can_decrypt" not in history_payload[0]["extra"]["encryption"]


def test_send_message_strips_local_only_encrypted_attachment_fields(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_attachment", "Alice Attachment")
    bob = user_factory("bob_attachment", "Bob Attachment")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={
            "participant_ids": [bob["user"]["id"]],
            "encryption_mode": "e2ee_private",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    send_message_response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000029",
            "content": "https://cdn.example/files/blob.bin",
            "message_type": "file",
            "extra": {
                "local_path": "C:/secret/plan.pdf",
                "uploading": False,
                "url": "https://cdn.example/files/blob.bin",
                "file_type": "application/pdf",
                "size": 128,
                "media": {"duration": 3},
                "attachment_encryption": {
                    "enabled": True,
                    "scheme": "aesgcm-file+x25519-v1",
                    "sender_device_id": "device-alice",
                    "sender_identity_key_public": "pub-alice",
                    "recipient_user_id": bob["user"]["id"],
                    "recipient_device_id": "device-bob",
                    "recipient_prekey_type": "signed",
                    "recipient_prekey_id": 1,
                    "metadata_ciphertext": "metadata-ciphertext",
                    "nonce": "nonce-attachment",
                    "encrypted_size_bytes": 256,
                    "local_metadata": "local:metadata",
                    "local_plaintext_version": "v1",
                    "decryption_state": "missing_private_key",
                    "recovery_action": "reprovision_device",
                    "local_device_id": "device-bob",
                    "target_device_id": "device-bob",
                    "can_decrypt": False,
                },
            },
        },
        headers=auth_header(alice["access_token"]),
    )
    assert send_message_response.status_code == 200
    message_payload = send_message_response.json()["data"]
    attachment_extra = message_payload["extra"]["attachment_encryption"]
    assert attachment_extra["scheme"] == "aesgcm-file+x25519-v1"
    assert attachment_extra["encrypted_size_bytes"] == 256
    assert "local_metadata" not in attachment_extra
    assert "local_plaintext_version" not in attachment_extra
    assert "decryption_state" not in attachment_extra
    assert "recovery_action" not in attachment_extra
    assert "local_device_id" not in attachment_extra
    assert "target_device_id" not in attachment_extra
    assert "can_decrypt" not in attachment_extra
    assert "local_path" not in message_payload["extra"]
    assert "uploading" not in message_payload["extra"]
    assert "url" not in message_payload["extra"]
    assert "name" not in message_payload["extra"]
    assert "file_type" not in message_payload["extra"]
    assert "size" not in message_payload["extra"]
    assert "media" not in message_payload["extra"]

    history_response = client.get(
        f"/api/v1/sessions/{session_id}/messages",
        headers=auth_header(alice["access_token"]),
    )
    assert history_response.status_code == 200
    history_payload = history_response.json()["data"]
    history_attachment_extra = history_payload[0]["extra"]["attachment_encryption"]
    assert history_attachment_extra["scheme"] == "aesgcm-file+x25519-v1"
    assert history_attachment_extra["encrypted_size_bytes"] == 256
    assert "local_metadata" not in history_attachment_extra
    assert "local_plaintext_version" not in history_attachment_extra
    assert "decryption_state" not in history_attachment_extra
    assert "recovery_action" not in history_attachment_extra
    assert "local_device_id" not in history_attachment_extra
    assert "target_device_id" not in history_attachment_extra
    assert "can_decrypt" not in history_attachment_extra
    assert "local_path" not in history_payload[0]["extra"]
    assert "uploading" not in history_payload[0]["extra"]
    assert "url" not in history_payload[0]["extra"]
    assert "name" not in history_payload[0]["extra"]
    assert "file_type" not in history_payload[0]["extra"]
    assert "size" not in history_payload[0]["extra"]
    assert "media" not in history_payload[0]["extra"]



def test_direct_session_rejects_group_text_encryption_scheme(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_direct_scheme", "Alice Direct Scheme")
    bob = user_factory("bob_direct_scheme", "Bob Direct Scheme")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={
            "participant_ids": [bob["user"]["id"]],
            "encryption_mode": "e2ee_private",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000031",
            "content": "groupcipher:oops",
            "message_type": "text",
            "extra": {
                "encryption": {
                    "enabled": True,
                    "scheme": "group-sender-key-v1",
                    "content_ciphertext": "groupcipher:oops",
                    "sender_device_id": "device-alice",
                    "sender_key_id": "group-key-1",
                }
            },
        },
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "invalid text encryption scheme" in response.json()["message"]


def test_group_session_rejects_direct_attachment_encryption_scheme(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_group_attachment_scheme", "Alice Group Attachment Scheme")
    bob = user_factory("bob_group_attachment_scheme", "Bob Group Attachment Scheme")
    charlie = user_factory("charlie_group_attachment_scheme", "Charlie Group Attachment Scheme")

    create_group_response = client.post(
        "/api/v1/groups",
        json={
            "name": "Team",
            "member_ids": [bob["user"]["id"], charlie["user"]["id"]],
            "encryption_mode": "e2ee_group",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_group_response.status_code == 201
    session_id = create_group_response.json()["data"]["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000032",
            "content": "https://cdn.example/files/direct-style.bin",
            "message_type": "file",
            "extra": {
                "attachment_encryption": {
                    "enabled": True,
                    "scheme": "aesgcm-file+x25519-v1",
                    "sender_device_id": "device-alice",
                    "recipient_device_id": "device-bob",
                    "encrypted_size_bytes": 512,
                }
            },
        },
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "invalid attachment encryption scheme" in response.json()["message"]



def test_direct_text_encryption_requires_prekey_metadata(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_direct_required", "Alice Direct Required")
    bob = user_factory("bob_direct_required", "Bob Direct Required")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={
            "participant_ids": [bob["user"]["id"]],
            "encryption_mode": "e2ee_private",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000033",
            "content": "cipher-required",
            "message_type": "text",
            "extra": {
                "encryption": {
                    "enabled": True,
                    "scheme": "x25519-aesgcm-v1",
                    "sender_device_id": "device-alice",
                    "sender_identity_key_public": "pub-alice",
                    "recipient_user_id": bob["user"]["id"],
                    "recipient_device_id": "device-bob",
                    "recipient_prekey_type": "signed",
                    "content_ciphertext": "cipher-required",
                    "nonce": "nonce-required",
                }
            },
        },
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "recipient_prekey_id" in response.json()["message"]


def test_group_text_encryption_requires_fanout(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_group_required", "Alice Group Required")
    bob = user_factory("bob_group_required", "Bob Group Required")
    charlie = user_factory("charlie_group_required", "Charlie Group Required")

    create_group_response = client.post(
        "/api/v1/groups",
        json={
            "name": "Team",
            "member_ids": [bob["user"]["id"], charlie["user"]["id"]],
            "encryption_mode": "e2ee_group",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_group_response.status_code == 201
    session_id = create_group_response.json()["data"]["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000034",
            "content": "groupcipher:required",
            "message_type": "text",
            "extra": {
                "encryption": {
                    "enabled": True,
                    "scheme": "group-sender-key-v1",
                    "session_id": session_id,
                    "sender_device_id": "device-alice",
                    "sender_key_id": "group-key-required",
                    "content_ciphertext": "groupcipher:required",
                    "nonce": "nonce-required",
                    "fanout": [],
                }
            },
        },
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "fanout list" in response.json()["message"]


def test_direct_attachment_encryption_requires_metadata_ciphertext(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_direct_attachment_required", "Alice Direct Attachment Required")
    bob = user_factory("bob_direct_attachment_required", "Bob Direct Attachment Required")

    create_session_response = client.post(
        "/api/v1/sessions/direct",
        json={
            "participant_ids": [bob["user"]["id"]],
            "encryption_mode": "e2ee_private",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_session_response.status_code == 200
    session_id = create_session_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000035",
            "content": "https://cdn.example/files/required.bin",
            "message_type": "file",
            "extra": {
                "attachment_encryption": {
                    "enabled": True,
                    "scheme": "aesgcm-file+x25519-v1",
                    "sender_device_id": "device-alice",
                    "sender_identity_key_public": "pub-alice",
                    "recipient_user_id": bob["user"]["id"],
                    "recipient_device_id": "device-bob",
                    "recipient_prekey_type": "signed",
                    "recipient_prekey_id": 7,
                    "nonce": "nonce-required",
                }
            },
        },
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "metadata_ciphertext" in response.json()["message"]


def test_group_attachment_encryption_requires_fanout(
    client,
    user_factory,
    auth_header,
) -> None:
    alice = user_factory("alice_group_attachment_required", "Alice Group Attachment Required")
    bob = user_factory("bob_group_attachment_required", "Bob Group Attachment Required")
    charlie = user_factory("charlie_group_att_req", "Charlie Group Attachment Required")

    create_group_response = client.post(
        "/api/v1/groups",
        json={
            "name": "Team",
            "member_ids": [bob["user"]["id"], charlie["user"]["id"]],
            "encryption_mode": "e2ee_group",
        },
        headers=auth_header(alice["access_token"]),
    )
    assert create_group_response.status_code == 201
    session_id = create_group_response.json()["data"]["session_id"]

    response = client.post(
        f"/api/v1/sessions/{session_id}/messages",
        json={
            "msg_id": "10000000-0000-4000-8000-000000000036",
            "content": "https://cdn.example/files/group-required.bin",
            "message_type": "file",
            "extra": {
                "attachment_encryption": {
                    "enabled": True,
                    "scheme": "aesgcm-file+group-sender-key-v1",
                    "session_id": session_id,
                    "sender_device_id": "device-alice",
                    "sender_key_id": "group-key-required",
                    "metadata_ciphertext": "meta-required",
                    "nonce": "nonce-required",
                    "fanout": [],
                }
            },
        },
        headers=auth_header(alice["access_token"]),
    )

    assert response.status_code == 422
    assert "fanout list" in response.json()["message"]
