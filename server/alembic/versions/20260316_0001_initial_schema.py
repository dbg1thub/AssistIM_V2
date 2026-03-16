"""Initial schema aligned with backend architecture sections 27-47."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260316_0001"
down_revision = None
branch_labels = None
depends_on = None


UUID = sa.Uuid(as_uuid=False)


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("nickname", sa.String(length=64), nullable=False),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
    )
    op.create_index("idx_users_username", "users", ["username"], unique=False)

    op.create_table(
        "sessions",
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("avatar", sa.String(length=512), nullable=True),
        sa.Column("is_ai_session", sa.Boolean(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "friend_requests",
        sa.Column("sender_id", UUID, nullable=False),
        sa.Column("receiver_id", UUID, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["receiver_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_friend_requests_receiver_id", "friend_requests", ["receiver_id"], unique=False)
    op.create_index("idx_friend_requests_sender_id", "friend_requests", ["sender_id"], unique=False)

    op.create_table(
        "friends",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("friend_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["friend_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "friend_id", name="uq_friend_pair"),
    )
    op.create_index("idx_friends_user_id", "friends", ["user_id"], unique=False)

    op.create_table(
        "session_members",
        sa.Column("session_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("session_id", "user_id"),
        sa.UniqueConstraint("session_id", "user_id", name="uq_session_member"),
    )
    op.create_index("idx_session_members_session_id", "session_members", ["session_id"], unique=False)
    op.create_index("idx_session_members_user_id", "session_members", ["user_id"], unique=False)

    op.create_table(
        "messages",
        sa.Column("session_id", UUID, nullable=False),
        sa.Column("sender_id", UUID, nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["sender_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_messages_sender_id", "messages", ["sender_id"], unique=False)
    op.create_index("idx_messages_session_id", "messages", ["session_id"], unique=False)

    op.create_table(
        "message_reads",
        sa.Column("message_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("read_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("message_id", "user_id"),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_read"),
    )
    op.create_index("idx_message_reads_user_id", "message_reads", ["user_id"], unique=False)

    op.create_table(
        "groups",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("owner_id", UUID, nullable=False),
        sa.Column("session_id", UUID, nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )
    op.create_index("idx_groups_owner_id", "groups", ["owner_id"], unique=False)

    op.create_table(
        "group_members",
        sa.Column("group_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("joined_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )
    op.create_index("idx_group_members_group_id", "group_members", ["group_id"], unique=False)

    op.create_table(
        "moments",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_moments_user_id", "moments", ["user_id"], unique=False)

    op.create_table(
        "moment_likes",
        sa.Column("moment_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["moment_id"], ["moments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("moment_id", "user_id"),
        sa.UniqueConstraint("moment_id", "user_id", name="uq_moment_like"),
    )
    op.create_index("idx_moment_likes_moment_id", "moment_likes", ["moment_id"], unique=False)

    op.create_table(
        "moment_comments",
        sa.Column("moment_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["moment_id"], ["moments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_moment_comments_moment_id", "moment_comments", ["moment_id"], unique=False)

    op.create_table(
        "files",
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("file_url", sa.String(length=1024), nullable=False),
        sa.Column("file_type", sa.String(length=64), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("id", UUID, nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_files_user_id", "files", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_files_user_id", table_name="files")
    op.drop_table("files")
    op.drop_index("idx_moment_comments_moment_id", table_name="moment_comments")
    op.drop_table("moment_comments")
    op.drop_index("idx_moment_likes_moment_id", table_name="moment_likes")
    op.drop_table("moment_likes")
    op.drop_index("idx_moments_user_id", table_name="moments")
    op.drop_table("moments")
    op.drop_index("idx_group_members_group_id", table_name="group_members")
    op.drop_table("group_members")
    op.drop_index("idx_groups_owner_id", table_name="groups")
    op.drop_table("groups")
    op.drop_index("idx_message_reads_user_id", table_name="message_reads")
    op.drop_table("message_reads")
    op.drop_index("idx_messages_session_id", table_name="messages")
    op.drop_index("idx_messages_sender_id", table_name="messages")
    op.drop_table("messages")
    op.drop_index("idx_session_members_user_id", table_name="session_members")
    op.drop_index("idx_session_members_session_id", table_name="session_members")
    op.drop_table("session_members")
    op.drop_index("idx_friends_user_id", table_name="friends")
    op.drop_table("friends")
    op.drop_index("idx_friend_requests_sender_id", table_name="friend_requests")
    op.drop_index("idx_friend_requests_receiver_id", table_name="friend_requests")
    op.drop_table("friend_requests")
    op.drop_table("sessions")
    op.drop_index("idx_users_username", table_name="users")
    op.drop_table("users")
