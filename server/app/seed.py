"""Seed demo data for local development and testing."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.database import Base
from app.models.file import StoredFile
from app.models.group import Group, GroupMember
from app.models.message import Message, MessageRead
from app.models.moment import Moment, MomentComment, MomentLike
from app.models.session import ChatSession, SessionMember
from app.models.user import FriendRequest, Friendship, User
from app.utils.password import hash_password


DEMO_PASSWORD = "Passw0rd!"
SEED_NAMESPACE = uuid.UUID("1f5e7f2f-d39f-4338-8cc7-c3b6f0908f0a")
SEED_FILE_NAME = "seed-demo-note.txt"


def seed_uuid(name: str) -> str:
    return str(uuid.uuid5(SEED_NAMESPACE, name))


def build_engine(database_url: str):
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, future=True, connect_args=connect_args)


def ensure_user(
    db: Session,
    *,
    seed_name: str,
    username: str,
    nickname: str,
    created_at: datetime,
    avatar: str | None = None,
    status: str = "online",
) -> User:
    user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
    if user is None:
        user = User(id=seed_uuid(seed_name), username=username)

    user.password_hash = hash_password(DEMO_PASSWORD)
    user.nickname = nickname
    user.avatar = avatar
    user.status = status
    user.created_at = created_at
    user.updated_at = created_at
    db.add(user)
    db.flush()
    return user


def ensure_entity_by_id(db: Session, model_cls, entity_id: str, **fields):
    entity = db.get(model_cls, entity_id)
    if entity is None:
        entity = model_cls(id=entity_id, **fields)
    else:
        for key, value in fields.items():
            setattr(entity, key, value)
    db.add(entity)
    db.flush()
    return entity


def ensure_composite_entity(db: Session, model_cls, key_fields: dict[str, str], **fields):
    entity = db.get(model_cls, key_fields)
    if entity is None:
        entity = model_cls(**key_fields, **fields)
    else:
        for key, value in fields.items():
            setattr(entity, key, value)
    db.add(entity)
    db.flush()
    return entity


def ensure_session(
    db: Session,
    *,
    session_id: str,
    name: str,
    session_type: str,
    member_ids: list[str],
    created_at: datetime,
    updated_at: datetime,
    avatar: str | None = None,
    is_ai_session: bool = False,
) -> ChatSession:
    session = ensure_entity_by_id(
        db,
        ChatSession,
        session_id,
        type=session_type,
        name=name,
        avatar=avatar,
        is_ai_session=is_ai_session,
        created_at=created_at,
        updated_at=updated_at,
    )

    existing_members = {
        item.user_id: item
        for item in db.execute(select(SessionMember).where(SessionMember.session_id == session_id)).scalars().all()
    }
    desired_members = set(member_ids)

    for member_id in desired_members:
        ensure_composite_entity(
            db,
            SessionMember,
            {"session_id": session_id, "user_id": member_id},
            joined_at=created_at,
        )

    for member_id, member in existing_members.items():
        if member_id not in desired_members:
            db.delete(member)

    db.flush()
    return session


def ensure_group(
    db: Session,
    *,
    group_id: str,
    session_id: str,
    owner_id: str,
    name: str,
    member_roles: dict[str, str],
    created_at: datetime,
) -> Group:
    group = ensure_entity_by_id(
        db,
        Group,
        group_id,
        name=name,
        owner_id=owner_id,
        session_id=session_id,
        created_at=created_at,
        updated_at=created_at,
    )

    existing_members = {
        item.user_id: item
        for item in db.execute(select(GroupMember).where(GroupMember.group_id == group_id)).scalars().all()
    }
    desired_members = set(member_roles)

    for member_id, role in member_roles.items():
        ensure_composite_entity(
            db,
            GroupMember,
            {"group_id": group_id, "user_id": member_id},
            role=role,
            joined_at=created_at,
        )

    for member_id, member in existing_members.items():
        if member_id not in desired_members:
            db.delete(member)

    db.flush()
    return group


def reset_database(db: Session) -> None:
    for model_cls in (
        MessageRead,
        GroupMember,
        Friendship,
        FriendRequest,
        MomentLike,
        MomentComment,
        StoredFile,
        Message,
        Group,
        SessionMember,
        Moment,
        ChatSession,
        User,
    ):
        db.query(model_cls).delete()
    db.commit()


def count_rows(db: Session, model_cls) -> int:
    return len(db.execute(select(model_cls)).scalars().all())


def seed_demo_data(
    *,
    database_url: str | None = None,
    upload_dir: str | None = None,
    reset: bool = False,
) -> dict:
    settings = get_settings()
    resolved_database_url = database_url or settings.database_url
    resolved_upload_dir = Path(upload_dir or settings.upload_dir)
    resolved_upload_dir.mkdir(parents=True, exist_ok=True)

    engine = build_engine(resolved_database_url)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)

    with session_factory() as db:
        if reset:
            reset_database(db)

        base_time = datetime(2026, 1, 1, 9, 0, 0)
        alice = ensure_user(db, seed_name="user:demo_alice", username="demo_alice", nickname="Demo Alice", created_at=base_time)
        bob = ensure_user(db, seed_name="user:demo_bob", username="demo_bob", nickname="Demo Bob", created_at=base_time + timedelta(minutes=1))
        carla = ensure_user(db, seed_name="user:demo_carla", username="demo_carla", nickname="Demo Carla", created_at=base_time + timedelta(minutes=2))
        derek = ensure_user(db, seed_name="user:demo_derek", username="demo_derek", nickname="Demo Derek", created_at=base_time + timedelta(minutes=3), status="offline")

        ensure_entity_by_id(
            db,
            Friendship,
            seed_uuid("friendship:alice:bob"),
            user_id=alice.id,
            friend_id=bob.id,
            created_at=base_time + timedelta(minutes=4),
            updated_at=base_time + timedelta(minutes=4),
        )
        ensure_entity_by_id(
            db,
            Friendship,
            seed_uuid("friendship:bob:alice"),
            user_id=bob.id,
            friend_id=alice.id,
            created_at=base_time + timedelta(minutes=4),
            updated_at=base_time + timedelta(minutes=4),
        )
        ensure_entity_by_id(
            db,
            Friendship,
            seed_uuid("friendship:alice:carla"),
            user_id=alice.id,
            friend_id=carla.id,
            created_at=base_time + timedelta(minutes=5),
            updated_at=base_time + timedelta(minutes=5),
        )
        ensure_entity_by_id(
            db,
            Friendship,
            seed_uuid("friendship:carla:alice"),
            user_id=carla.id,
            friend_id=alice.id,
            created_at=base_time + timedelta(minutes=5),
            updated_at=base_time + timedelta(minutes=5),
        )
        ensure_entity_by_id(
            db,
            FriendRequest,
            seed_uuid("friend_request:derek:alice"),
            sender_id=derek.id,
            receiver_id=alice.id,
            status="pending",
            message="Can you add me to the project workspace?",
            created_at=base_time + timedelta(minutes=6),
            updated_at=base_time + timedelta(minutes=6),
        )

        private_session = ensure_session(
            db,
            session_id=seed_uuid("session:alice:bob"),
            name="Demo Alice & Bob",
            session_type="private",
            member_ids=[alice.id, bob.id],
            created_at=base_time + timedelta(minutes=7),
            updated_at=base_time + timedelta(minutes=10),
        )
        group_session = ensure_session(
            db,
            session_id=seed_uuid("session:core-team"),
            name="AssistIM Core Team",
            session_type="group",
            member_ids=[alice.id, bob.id, carla.id],
            created_at=base_time + timedelta(minutes=11),
            updated_at=base_time + timedelta(minutes=13),
        )

        private_messages = [
            ensure_entity_by_id(
                db,
                Message,
                seed_uuid("message:alice-bob:1"),
                session_id=private_session.id,
                sender_id=alice.id,
                type="text",
                content="Morning. I pushed the desktop chat fixes.",
                status="read",
                created_at=base_time + timedelta(minutes=8),
                updated_at=base_time + timedelta(minutes=8),
            ),
            ensure_entity_by_id(
                db,
                Message,
                seed_uuid("message:alice-bob:2"),
                session_id=private_session.id,
                sender_id=bob.id,
                type="text",
                content="Received. I'll verify the sync flow next.",
                status="read",
                created_at=base_time + timedelta(minutes=9),
                updated_at=base_time + timedelta(minutes=9),
            ),
            ensure_entity_by_id(
                db,
                Message,
                seed_uuid("message:alice-bob:3"),
                session_id=private_session.id,
                sender_id=alice.id,
                type="text",
                content="Please also check the PostgreSQL migration path.",
                status="sent",
                created_at=base_time + timedelta(minutes=10),
                updated_at=base_time + timedelta(minutes=10),
            ),
        ]
        team_messages = [
            ensure_entity_by_id(
                db,
                Message,
                seed_uuid("message:team:1"),
                session_id=group_session.id,
                sender_id=carla.id,
                type="text",
                content="Demo seed data is ready for QA.",
                status="read",
                created_at=base_time + timedelta(minutes=12),
                updated_at=base_time + timedelta(minutes=12),
            ),
            ensure_entity_by_id(
                db,
                Message,
                seed_uuid("message:team:2"),
                session_id=group_session.id,
                sender_id=alice.id,
                type="text",
                content="Let's validate auth, chat, and group permissions.",
                status="sent",
                created_at=base_time + timedelta(minutes=13),
                updated_at=base_time + timedelta(minutes=13),
            ),
        ]

        ensure_composite_entity(
            db,
            MessageRead,
            {"message_id": private_messages[0].id, "user_id": bob.id},
            read_at=base_time + timedelta(minutes=8, seconds=30),
        )
        ensure_composite_entity(
            db,
            MessageRead,
            {"message_id": private_messages[1].id, "user_id": alice.id},
            read_at=base_time + timedelta(minutes=9, seconds=30),
        )
        ensure_composite_entity(
            db,
            MessageRead,
            {"message_id": team_messages[0].id, "user_id": alice.id},
            read_at=base_time + timedelta(minutes=12, seconds=30),
        )
        ensure_composite_entity(
            db,
            MessageRead,
            {"message_id": team_messages[0].id, "user_id": bob.id},
            read_at=base_time + timedelta(minutes=12, seconds=40),
        )

        ensure_group(
            db,
            group_id=seed_uuid("group:core-team"),
            session_id=group_session.id,
            owner_id=alice.id,
            name="AssistIM Core Team",
            member_roles={
                alice.id: "owner",
                bob.id: "member",
                carla.id: "member",
            },
            created_at=base_time + timedelta(minutes=11),
        )

        moment_alice = ensure_entity_by_id(
            db,
            Moment,
            seed_uuid("moment:alice:1"),
            user_id=alice.id,
            content="Backend API and PostgreSQL migration are ready for integration.",
            created_at=base_time + timedelta(minutes=20),
            updated_at=base_time + timedelta(minutes=20),
        )
        moment_bob = ensure_entity_by_id(
            db,
            Moment,
            seed_uuid("moment:bob:1"),
            user_id=bob.id,
            content="Added message history validation and unread counter checks.",
            created_at=base_time + timedelta(minutes=21),
            updated_at=base_time + timedelta(minutes=21),
        )
        ensure_composite_entity(
            db,
            MomentLike,
            {"moment_id": moment_alice.id, "user_id": carla.id},
            created_at=base_time + timedelta(minutes=20, seconds=30),
            updated_at=base_time + timedelta(minutes=20, seconds=30),
        )
        ensure_composite_entity(
            db,
            MomentLike,
            {"moment_id": moment_bob.id, "user_id": alice.id},
            created_at=base_time + timedelta(minutes=21, seconds=30),
            updated_at=base_time + timedelta(minutes=21, seconds=30),
        )
        ensure_entity_by_id(
            db,
            MomentComment,
            seed_uuid("moment-comment:alice:carla"),
            moment_id=moment_alice.id,
            user_id=carla.id,
            content="I'll use this dataset for the desktop smoke test.",
            created_at=base_time + timedelta(minutes=20, seconds=45),
            updated_at=base_time + timedelta(minutes=20, seconds=45),
        )

        seed_file_path = resolved_upload_dir / SEED_FILE_NAME
        seed_file_path.write_text(
            "AssistIM demo seed file. Safe to delete and regenerate.\n",
            encoding="utf-8",
        )
        ensure_entity_by_id(
            db,
            StoredFile,
            seed_uuid("file:alice:demo-note"),
            user_id=alice.id,
            file_url=f"/uploads/{SEED_FILE_NAME}",
            file_type="text/plain",
            file_name=SEED_FILE_NAME,
            created_at=base_time + timedelta(minutes=22),
            updated_at=base_time + timedelta(minutes=22),
        )

        db.commit()

        summary = {
            "database_url": resolved_database_url,
            "upload_dir": str(resolved_upload_dir),
            "demo_password": DEMO_PASSWORD,
            "users": ["demo_alice", "demo_bob", "demo_carla", "demo_derek"],
            "counts": {
                "users": count_rows(db, User),
                "friend_requests": count_rows(db, FriendRequest),
                "friendships": count_rows(db, Friendship),
                "sessions": count_rows(db, ChatSession),
                "messages": count_rows(db, Message),
                "groups": count_rows(db, Group),
                "moments": count_rows(db, Moment),
                "files": count_rows(db, StoredFile),
            },
        }

    engine.dispose()
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for AssistIM backend.")
    parser.add_argument("--database-url", default=None, help="Override the target database URL.")
    parser.add_argument("--upload-dir", default=None, help="Override the upload directory used for demo files.")
    parser.add_argument("--reset", action="store_true", help="Delete existing app data before seeding.")
    args = parser.parse_args()

    summary = seed_demo_data(database_url=args.database_url, upload_dir=args.upload_dir, reset=args.reset)
    print(json.dumps(summary, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
