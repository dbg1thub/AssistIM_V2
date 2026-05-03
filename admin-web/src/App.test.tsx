import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

const dashboardPayload = {
  system: { app_name: "AssistIM Test API", app_version: "test", uptime_seconds: 12 },
  users: { total: 3, online: 2 },
  database: { status: "ok", dialect: "sqlite" },
  chat: { sessions: { total: 5 }, messages: { total: 8 } },
  files: { total: 4 },
  realtime: { online_users: 2, bound_connections: 2 },
  calls: { active: 1 },
  e2ee: { encrypted_sessions: 2 },
  http: { total_requests: 6, error_requests: 1 },
  logs: { recent_warnings_errors: [] }
};

function mockFetch() {
  return vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
    const url = String(input);
    if (url.endsWith("/api/v1/admin/dashboard")) {
      return jsonResponse(dashboardPayload);
    }
    if (url.endsWith("/api/v1/admin/database/backups/prune")) {
      return jsonResponse({
        keep_last: 1,
        older_than_days: 30,
        include_failed: true,
        include_deleted: false,
        dry_run: readRequestBody(_init).dry_run,
        candidate_count: 1,
        processed_count: readRequestBody(_init).dry_run ? 0 : 1,
        file_deleted_count: readRequestBody(_init).dry_run ? 0 : 1,
        file_missing_count: 0,
        items: [
          {
            id: "backup-1",
            action: readRequestBody(_init).dry_run ? "would_delete" : "deleted",
            status_before: "completed",
            status_after: readRequestBody(_init).dry_run ? "completed" : "deleted",
            file_name: "backup.sqlite3"
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/database/backups/backup-1/verify")) {
      return jsonResponse({
        ...backupItem(),
        verification_status: "passed",
        verification_message: "sqlite integrity_check ok"
      });
    }
    if (url.endsWith("/api/v1/admin/database/backups/backup-1") && _init?.method === "DELETE") {
      return jsonResponse({
        ...backupItem(),
        status: "deleted",
        file_deleted: true,
        file_missing: false
      });
    }
    if (url.endsWith("/api/v1/admin/database/backups/backup-1")) {
      return jsonResponse(backupItem());
    }
    if (url.endsWith("/api/v1/admin/database/backups") && _init?.method === "POST") {
      return jsonResponse({
        ...backupItem(),
        id: "backup-2",
        file_name: "backup-new.sqlite3",
        created_at: "2026-05-03T11:00:00+00:00"
      });
    }
    if (url.includes("/api/v1/admin/database/backups")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [backupItem()]
      });
    }
    if (url.endsWith("/api/v1/admin/users/user-1")) {
      return jsonResponse({
        id: "user-1",
        username: "test1",
        nickname: "测试一",
        display_name: "测试一",
        email: "test1@example.com",
        phone: "13800000001",
        role: "admin",
        is_disabled: false,
        disabled_reason: "",
        status: "online",
        counts: { devices: 1, sessions: 2, friends: 3, files: 4 },
        devices: [
          {
            device_id: "device-1",
            device_name: "Windows",
            is_active: true,
            last_seen_at: "2026-05-03T10:00:00+00:00"
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/users/user-1/role")) {
      return jsonResponse({
        id: "user-1",
        username: "test1",
        nickname: "测试一",
        role: "user",
        is_disabled: false,
        status: "online"
      });
    }
    if (url.endsWith("/api/v1/admin/users/user-1/disable")) {
      return jsonResponse({
        id: "user-1",
        username: "test1",
        nickname: "测试一",
        role: "admin",
        is_disabled: true,
        disabled_reason: "manual check",
        status: "offline"
      });
    }
    if (url.endsWith("/api/v1/admin/users/user-1/enable")) {
      return jsonResponse({
        id: "user-1",
        username: "test1",
        nickname: "测试一",
        role: "admin",
        is_disabled: false,
        status: "offline"
      });
    }
    if (url.endsWith("/api/v1/admin/users/user-1/force-logout")) {
      return jsonResponse({ user_id: "user-1", username: "test1", disconnected: true });
    }
    if (url.includes("/api/v1/admin/users")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [
          {
            id: "user-1",
            username: "test1",
            nickname: "测试一",
            role: "admin",
            is_disabled: false,
            status: "online"
          }
        ]
      });
    }
    if (url.includes("/api/v1/admin/audit-logs/audit-1")) {
      return jsonResponse({
        id: "audit-1",
        actor_username: "admin",
        action: "admin.user.disable",
        target_type: "user",
        target_id: "user-1",
        request_method: "POST",
        request_path: "/api/v1/admin/users/user-1/disable",
        client_ip: "127.0.0.1",
        success: true,
        error_code: "",
        detail: { reason: "manual", token: "[redacted]" },
        created_at: "2026-05-03T10:00:00+00:00"
      });
    }
    if (url.includes("/api/v1/admin/audit-logs")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [
          {
            id: "audit-1",
            actor_username: "admin",
            action: "admin.user.disable",
            target_type: "user",
            target_id: "user-1",
            request_method: "POST",
            request_path: "/api/v1/admin/users/user-1/disable",
            client_ip: "127.0.0.1",
            success: true,
            error_code: "",
            detail: { reason: "manual" },
            created_at: "2026-05-03T10:00:00+00:00"
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/database/status")) {
      return jsonResponse({
        status: "ok",
        dialect: "sqlite",
        runtime_schema_complete: true,
        runtime_schema_revision: "runtime-revision",
        required_tables: { users: true, messages: true }
      });
    }
    if (url.endsWith("/api/v1/admin/logs/files")) {
      return jsonResponse({
        total: 1,
        files: [
          {
            file_name: "assistim.log",
            size_bytes: 2048,
            modified_at: "2026-05-03T00:00:00+00:00"
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/logs/files/assistim.log/download")) {
      return Promise.resolve(
        new Response("downloaded log content", {
          status: 200,
          headers: { "Content-Type": "text/plain; charset=utf-8" }
        })
      );
    }
    if (url.includes("/api/v1/admin/logs?")) {
      return jsonResponse({
        total: 1,
        limit: 50,
        items: [
          {
            file_name: "assistim.log",
            timestamp: "2026-05-03T10:00:00+00:00",
            level: "ERROR",
            logger: "client.network.http_client",
            message: "Network error: connection refused"
          }
        ]
      });
    }
    if (url.includes("/api/v1/admin/chat/sessions/session-1/messages")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 50,
        session: { id: "session-1", type: "private", name: "test1, test3" },
        items: [
          {
            id: "message-1",
            session_id: "session-1",
            sender_id: "user-1",
            sender_username: "test1",
            sender_nickname: "测试一",
            session_seq: 1,
            type: "text",
            content: "你好 test3",
            status: "sent",
            extra: {},
            created_at: "2026-05-03T10:00:00+00:00",
            updated_at: "2026-05-03T10:00:00+00:00"
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/chat/sessions/session-1")) {
      return jsonResponse(chatSessionDetail());
    }
    if (url.includes("/api/v1/admin/chat/sessions")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [chatSessionSummary()]
      });
    }
    if (url.includes("/api/v1/admin/contacts/friend-requests")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [
          {
            id: "request-1",
            sender_id: "user-1",
            receiver_id: "user-3",
            status: "pending",
            message: "加一下",
            sender: userSummary("user-1", "test1", "测试一"),
            receiver: userSummary("user-3", "test3", "测试三"),
            created_at: "2026-05-03T09:30:00+00:00",
            updated_at: "2026-05-03T09:30:00+00:00"
          }
        ]
      });
    }
    if (url.includes("/api/v1/admin/contacts/friendships")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [
          {
            id: "friendship-1",
            user_id: "user-1",
            friend_id: "user-3",
            user: userSummary("user-1", "test1", "测试一"),
            friend: userSummary("user-3", "test3", "测试三"),
            created_at: "2026-05-03T10:00:00+00:00",
            updated_at: "2026-05-03T10:00:00+00:00"
          }
        ]
      });
    }
    if (url.includes("/api/v1/admin/groups/group-1/members")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        group: { id: "group-1", name: "项目组", session_id: "session-group-1" },
        items: [
          {
            group_id: "group-1",
            user_id: "user-1",
            user: userSummary("user-1", "test1", "测试一"),
            role: "owner",
            group_nickname: "群主",
            note: "项目负责人",
            joined_at: "2026-05-03T08:00:00+00:00",
            session_member: {
              exists: true,
              last_read_seq: 8,
              last_read_message_id: "group-message-8",
              last_read_at: "2026-05-03T10:30:00+00:00"
            }
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/groups/group-1")) {
      return jsonResponse(groupDetail());
    }
    if (url.includes("/api/v1/admin/groups?") || url.endsWith("/api/v1/admin/groups")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [groupSummary()]
      });
    }
    if (url.includes("/api/v1/admin/moments/moment-1/comments")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        moment: { id: "moment-1", user_id: "user-3", content: "今天完成语音消息测试" },
        items: [
          {
            id: "comment-1",
            moment_id: "moment-1",
            user_id: "user-1",
            user: userSummary("user-1", "test1", "测试一"),
            content: "收到",
            created_at: "2026-05-03T10:05:00+00:00",
            updated_at: "2026-05-03T10:05:00+00:00"
          }
        ]
      });
    }
    if (url.includes("/api/v1/admin/moments/moment-1/likes")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        moment: { id: "moment-1", user_id: "user-3", content: "今天完成语音消息测试" },
        items: [
          {
            moment_id: "moment-1",
            user_id: "user-1",
            user: userSummary("user-1", "test1", "测试一"),
            created_at: "2026-05-03T10:06:00+00:00",
            updated_at: "2026-05-03T10:06:00+00:00"
          }
        ]
      });
    }
    if (url.endsWith("/api/v1/admin/moments/moment-1")) {
      return jsonResponse(momentSummary());
    }
    if (url.includes("/api/v1/admin/moments?") || url.endsWith("/api/v1/admin/moments")) {
      return jsonResponse({
        total: 1,
        page: 1,
        size: 20,
        items: [momentSummary()]
      });
    }
    if (url.endsWith("/api/v1/admin/chat/health")) {
      return jsonResponse({
        status: "warning",
        issue_count: 1,
        issues: [
          {
            issue_type: "message_without_session",
            severity: "error",
            session_id: "missing-session"
          }
        ],
        checks: { sessions: 5, messages: 8 }
      });
    }
    if (url.endsWith("/api/v1/admin/files/storage/status")) {
      return jsonResponse({
        status: "warning",
        storage_provider: "local",
        upload_dir: { exists: true, is_dir: true, readable: true, writable: true },
        database: {
          total_records: 4,
          local_records: 3,
          non_local_records: 1,
          local_size_bytes: 4096
        },
        disk: {
          total_files: 4,
          managed_files: 2,
          ignored_server_generated_files: 1,
          total_size_bytes: 8192,
          managed_size_bytes: 2048
        },
        issues: {
          total: 2,
          errors: 1,
          warnings: 1,
          missing_disk_files: 1,
          orphan_disk_files: 1,
          metadata_mismatches: 0,
          invalid_storage_keys: 0
        }
      });
    }
    if (url.endsWith("/api/v1/admin/files/storage/issues")) {
      return jsonResponse({
        total: 2,
        items: [
          {
            issue_type: "orphan_disk_file",
            severity: "warning",
            storage_provider: "local",
            storage_key: "orphan.txt",
            actual_size_bytes: 512
          },
          {
            issue_type: "missing_disk_file",
            severity: "error",
            file_id: "file-1",
            file_name: "report.pdf",
            storage_provider: "local",
            storage_key: "uploads/report.pdf",
            expected_size_bytes: 1024,
            actual_size_bytes: null,
            expected_checksum_sha256: "sha256-expected",
            actual_checksum_sha256: ""
          }
        ]
      });
    }
    if (url.includes("/api/v1/admin/") && url.endsWith("/health")) {
      return jsonResponse({
        status: "ok",
        issue_count: 0,
        issues: [],
        checks: { total: 1 }
      });
    }
    return jsonResponse({}, 404, 1001, "not found");
  });
}

function backupItem() {
  return {
    id: "backup-1",
    created_by_username: "admin",
    status: "completed",
    database_dialect: "sqlite",
    backup_format: "sqlite",
    storage_key: "database_backups/backup.sqlite3",
    file_name: "backup.sqlite3",
    size_bytes: 2048,
    checksum_sha256: "abc123",
    error_message: "",
    verification_status: "pending",
    verification_message: "",
    verified_at: "",
    started_at: "2026-05-03T10:00:00+00:00",
    finished_at: "2026-05-03T10:00:01+00:00",
    duration_ms: 1000,
    created_at: "2026-05-03T10:00:00+00:00"
  };
}

function chatSessionSummary() {
  return {
    id: "session-1",
    type: "private",
    name: "test1, test3",
    avatar: "",
    is_ai_session: false,
    encryption_mode: "e2ee_private",
    member_count: 2,
    message_count: 1,
    last_message_seq: 1,
    last_event_seq: 0,
    last_message: {
      id: "message-1",
      session_id: "session-1",
      sender_id: "user-1",
      session_seq: 1,
      type: "text",
      content: "你好 test3",
      status: "sent",
      created_at: "2026-05-03T10:00:00+00:00"
    },
    created_at: "2026-05-03T09:00:00+00:00",
    updated_at: "2026-05-03T10:00:00+00:00"
  };
}

function chatSessionDetail() {
  return {
    ...chatSessionSummary(),
    members: [
      {
        user_id: "user-1",
        username: "test1",
        nickname: "测试一",
        joined_at: "2026-05-03T09:00:00+00:00",
        last_read_seq: 1,
        last_read_message_id: "message-1",
        last_read_at: "2026-05-03T10:01:00+00:00"
      },
      {
        user_id: "user-3",
        username: "test3",
        nickname: "测试三",
        joined_at: "2026-05-03T09:00:00+00:00",
        last_read_seq: 0,
        last_read_message_id: "",
        last_read_at: ""
      }
    ]
  };
}

function userSummary(id: string, username: string, nickname: string) {
  return {
    id,
    username,
    nickname,
    avatar: "",
    is_disabled: false,
    exists: true
  };
}

function groupSummary() {
  return {
    id: "group-1",
    name: "项目组",
    owner_id: "user-1",
    owner: userSummary("user-1", "test1", "测试一"),
    session_id: "session-group-1",
    session: {
      id: "session-group-1",
      exists: true,
      type: "group",
      name: "项目组",
      is_ai_session: false,
      encryption_mode: "none",
      last_message_seq: 8,
      last_event_seq: 2
    },
    announcement: "今天同步进度",
    announcement_message_id: "group-message-7",
    announcement_author_id: "user-1",
    announcement_published_at: "2026-05-03T09:30:00+00:00",
    avatar_kind: "generated",
    avatar_file_id: "file-avatar-1",
    avatar_file: {
      id: "file-avatar-1",
      exists: true,
      storage_provider: "local",
      storage_key: "avatars/group-1.png",
      file_name: "group-1.png",
      file_type: "image/png",
      size_bytes: 1024
    },
    avatar_version: 2,
    member_count: 2,
    session_member_count: 2,
    created_at: "2026-05-03T08:00:00+00:00",
    updated_at: "2026-05-03T10:00:00+00:00"
  };
}

function groupDetail() {
  return {
    ...groupSummary(),
    announcement_message: {
      id: "group-message-7",
      session_id: "session-group-1",
      sender_id: "user-1",
      session_seq: 7,
      type: "text",
      content: "今天同步进度",
      status: "sent",
      created_at: "2026-05-03T09:30:00+00:00",
      updated_at: "2026-05-03T09:30:00+00:00"
    },
    members: [
      {
        group_id: "group-1",
        user_id: "user-1",
        user: userSummary("user-1", "test1", "测试一"),
        role: "owner",
        group_nickname: "群主",
        note: "项目负责人",
        joined_at: "2026-05-03T08:00:00+00:00",
        session_member: {
          exists: true,
          last_read_seq: 8,
          last_read_message_id: "group-message-8",
          last_read_at: "2026-05-03T10:30:00+00:00"
        }
      }
    ]
  };
}

function momentSummary() {
  return {
    id: "moment-1",
    user_id: "user-3",
    author: userSummary("user-3", "test3", "测试三"),
    content: "今天完成语音消息测试",
    comment_count: 1,
    like_count: 1,
    created_at: "2026-05-03T10:00:00+00:00",
    updated_at: "2026-05-03T10:00:00+00:00"
  };
}

function readRequestBody(init?: RequestInit): Record<string, unknown> {
  if (typeof init?.body !== "string") {
    return {};
  }
  return JSON.parse(init.body) as Record<string, unknown>;
}

function jsonResponse(data: unknown, status = 200, code = 0, message = "success") {
  return Promise.resolve(
    new Response(JSON.stringify({ code, message, data }), {
      status,
      headers: { "Content-Type": "application/json" }
    })
  );
}

describe("Admin web shell", () => {
  it("connects with server URL and token, then renders dashboard overview", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));

    expect(await screen.findByRole("heading", { name: "概览" })).toBeInTheDocument();
    expect(screen.getByText("AssistIM Test API")).toBeInTheDocument();
    expect(screen.getByText("用户总数")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/dashboard", {
      headers: { Authorization: "Bearer admin-token" },
      method: "GET"
    });
  });

  it("switches between users, database, and logs pages", async () => {
    render(<App fetcher={mockFetch()} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "用户" }));
    expect(await screen.findByRole("heading", { name: "用户" })).toBeInTheDocument();
    expect(screen.getByText("test1")).toBeInTheDocument();
    expect(screen.getByText("admin")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "数据库" }));
    expect(await screen.findByRole("heading", { name: "数据库" })).toBeInTheDocument();
    expect(screen.getByText("runtime-revision")).toBeInTheDocument();
    expect(screen.getByText("users")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "日志" }));
    expect(await screen.findByRole("heading", { name: "日志" })).toBeInTheDocument();
    expect(screen.getByText("assistim.log")).toBeInTheDocument();
  });

  it("loads user detail and performs confirmed account operations", async () => {
    const fetchMock = mockFetch();
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "用户" }));
    expect(await screen.findByRole("heading", { name: "用户" })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "查看 test1 详情" }));

    expect(await screen.findByRole("heading", { name: "test1" })).toBeInTheDocument();
    expect(screen.getByText("test1@example.com")).toBeInTheDocument();
    expect(screen.getByText("device-1")).toBeInTheDocument();
    expect(screen.getByText("Windows")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "设为普通用户" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input).endsWith("/api/v1/admin/users/user-1/role") && init?.method === "PATCH"
        )
      ).toBe(true);
    });

    fireEvent.change(screen.getByLabelText("禁用原因"), {
      target: { value: "manual check" }
    });
    fireEvent.click(screen.getByRole("button", { name: "禁用用户" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input).endsWith("/api/v1/admin/users/user-1/disable") && init?.method === "POST"
        )
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "启用用户" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input).endsWith("/api/v1/admin/users/user-1/enable") && init?.method === "POST"
        )
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "强制下线" }));

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/api/v1/admin/users/user-1/force-logout") && init?.method === "POST"
        )
      ).toBe(true);
    });
    expect(confirmMock).toHaveBeenCalled();
    confirmMock.mockRestore();
  });

  it("manages database backups with confirmed actions and prune preview", async () => {
    const fetchMock = mockFetch();
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "备份" }));
    expect(await screen.findByRole("heading", { name: "备份" })).toBeInTheDocument();
    expect(await screen.findByText("backup.sqlite3")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "创建备份" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) => String(input).endsWith("/api/v1/admin/database/backups") && init?.method === "POST"
        )
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "查看备份详情" }));
    expect(await screen.findByText("checksum_sha256")).toBeInTheDocument();
    expect(screen.getByText("abc123")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "验证备份" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/api/v1/admin/database/backups/backup-1/verify") && init?.method === "POST"
        )
      ).toBe(true);
    });

    fireEvent.change(screen.getByLabelText("保留最近"), {
      target: { value: "1" }
    });
    fireEvent.change(screen.getByLabelText("早于天数"), {
      target: { value: "30" }
    });
    fireEvent.click(screen.getByLabelText("包含失败备份"));
    fireEvent.click(screen.getByRole("button", { name: "预览清理" }));
    expect(await screen.findByText("would_delete")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "执行清理" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/api/v1/admin/database/backups/prune") &&
            init?.method === "POST" &&
            readRequestBody(init).dry_run === false
        )
      ).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "删除备份" }));
    await waitFor(() => {
      expect(
        fetchMock.mock.calls.some(
          ([input, init]) =>
            String(input).endsWith("/api/v1/admin/database/backups/backup-1") && init?.method === "DELETE"
        )
      ).toBe(true);
    });
    expect(confirmMock).toHaveBeenCalled();
    confirmMock.mockRestore();
  });

  it("loads file storage status and filters issue rows", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "文件" }));
    expect(await screen.findByRole("heading", { name: "文件" })).toBeInTheDocument();
    expect(screen.getByText("本地记录")).toBeInTheDocument();
    expect(screen.getByText("磁盘托管文件")).toBeInTheDocument();
    expect(screen.getByText("uploads/report.pdf")).toBeInTheDocument();
    expect(screen.getByText("orphan.txt")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("问题类型"), {
      target: { value: "missing_disk_file" }
    });
    expect(screen.getByText("missing_disk_file")).toBeInTheDocument();
    expect(screen.queryByText("orphan.txt")).not.toBeInTheDocument();

    const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(requestedUrls).toContain("http://localhost:8000/api/v1/admin/files/storage/status");
    expect(requestedUrls).toContain("http://localhost:8000/api/v1/admin/files/storage/issues");
  });

  it("queries server log entries and downloads a selected log file", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "日志" }));
    expect(await screen.findByRole("heading", { name: "日志" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("日志文件"), {
      target: { value: "assistim.log" }
    });
    fireEvent.change(screen.getByLabelText("日志级别"), {
      target: { value: "ERROR" }
    });
    fireEvent.change(screen.getByLabelText("关键词"), {
      target: { value: "Network error" }
    });
    fireEvent.change(screen.getByLabelText("返回条数"), {
      target: { value: "50" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询日志" }));

    expect(await screen.findByText("Network error: connection refused")).toBeInTheDocument();
    expect(screen.getByText("client.network.http_client")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "下载 assistim.log" }));
    expect(await screen.findByText("已下载 assistim.log")).toBeInTheDocument();

    const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(requestedUrls.some((url) => url.includes("/api/v1/admin/logs?"))).toBe(true);
    expect(requestedUrls.some((url) => url.endsWith("/api/v1/admin/logs/files/assistim.log/download"))).toBe(true);
  });

  it("loads chat sessions, session detail, and message rows", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "聊天" }));
    expect(await screen.findByRole("heading", { name: "聊天" })).toBeInTheDocument();
    expect(screen.getByText("e2ee_private")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("会话类型"), {
      target: { value: "private" }
    });
    fireEvent.change(screen.getByLabelText("会话关键词"), {
      target: { value: "test3" }
    });
    fireEvent.change(screen.getByLabelText("成员用户 ID"), {
      target: { value: "user-3" }
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选会话" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("type=private"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("keyword=test3"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("user_id=user-3"))).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "查看会话详情" }));
    expect(await screen.findByRole("heading", { name: "test1, test3" })).toBeInTheDocument();
    expect(screen.getByText("test3")).toBeInTheDocument();
    expect(screen.getAllByText("你好 test3").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("消息类型"), {
      target: { value: "text" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询消息" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("/api/v1/admin/chat/sessions/session-1/messages"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("type=text"))).toBe(true);
    });
  });

  it("loads contact friend requests and friendship rows with filters", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "联系人" }));
    expect(await screen.findByRole("heading", { name: "联系人" })).toBeInTheDocument();
    expect(screen.getByText("好友请求")).toBeInTheDocument();
    expect(screen.getByText("好友关系")).toBeInTheDocument();
    expect(screen.getByText("pending")).toBeInTheDocument();
    expect(screen.getByText("加一下")).toBeInTheDocument();
    expect(screen.getAllByText("test3").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("请求状态"), {
      target: { value: "pending" }
    });
    fireEvent.change(screen.getByLabelText("发送人 ID"), {
      target: { value: "user-1" }
    });
    fireEvent.change(screen.getByLabelText("接收人 ID"), {
      target: { value: "user-3" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询请求" }));

    fireEvent.change(screen.getByLabelText("用户 ID"), {
      target: { value: "user-1" }
    });
    fireEvent.change(screen.getByLabelText("好友 ID"), {
      target: { value: "user-3" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询关系" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("status=pending"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("sender_id=user-1"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("receiver_id=user-3"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("friendships?user_id=user-1&friend_id=user-3"))).toBe(true);
    });
  });

  it("loads groups, group detail, and filtered member rows", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "群组" }));
    expect(await screen.findByRole("heading", { name: "群组" })).toBeInTheDocument();
    expect(screen.getByText("项目组")).toBeInTheDocument();
    expect(screen.getByText("今天同步进度")).toBeInTheDocument();
    expect(screen.getByText("generated")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("群关键词"), {
      target: { value: "team" }
    });
    fireEvent.change(screen.getByLabelText("群主 ID"), {
      target: { value: "user-1" }
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选群组" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("keyword=team"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("owner_id=user-1"))).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "查看群组详情" }));
    expect(await screen.findByRole("heading", { name: "项目组" })).toBeInTheDocument();
    expect(screen.getByText("group-1.png")).toBeInTheDocument();
    expect(screen.getByText("group-message-7")).toBeInTheDocument();
    expect(screen.getByText("项目负责人")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("成员角色"), {
      target: { value: "owner" }
    });
    fireEvent.change(screen.getByLabelText("成员用户 ID"), {
      target: { value: "user-1" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询成员" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("/api/v1/admin/groups/group-1/members"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("role=owner"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("user_id=user-1"))).toBe(true);
    });
  });

  it("loads moments, moment detail, comments, and likes with filters", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "朋友圈" }));
    expect(await screen.findByRole("heading", { name: "朋友圈" })).toBeInTheDocument();
    expect(screen.getByText("今天完成语音消息测试")).toBeInTheDocument();
    expect(screen.getAllByText("test3").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("动态关键词"), {
      target: { value: "语音" }
    });
    fireEvent.change(screen.getByLabelText("发布人 ID"), {
      target: { value: "user-3" }
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选动态" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("keyword=%E8%AF%AD%E9%9F%B3"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("user_id=user-3"))).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "查看动态详情" }));
    expect(await screen.findByRole("heading", { name: "moment-1" })).toBeInTheDocument();
    expect(screen.getByText("评论列表")).toBeInTheDocument();
    expect(screen.getByText("点赞列表")).toBeInTheDocument();
    expect(screen.getByText("收到")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("评论用户 ID"), {
      target: { value: "user-1" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询评论" }));

    fireEvent.change(screen.getByLabelText("点赞用户 ID"), {
      target: { value: "user-1" }
    });
    fireEvent.click(screen.getByRole("button", { name: "查询点赞" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("/api/v1/admin/moments/moment-1/comments"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("/api/v1/admin/moments/moment-1/likes"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("comments?user_id=user-1"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("likes?user_id=user-1"))).toBe(true);
    });
  });

  it("loads health inspection modules and expands issue details", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "巡检" }));
    expect(await screen.findByRole("heading", { name: "巡检" })).toBeInTheDocument();
    expect(await screen.findByText("聊天")).toBeInTheDocument();
    expect(screen.getByText("文件存储")).toBeInTheDocument();
    expect(screen.getAllByText("有问题").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "展开聊天详情" }));
    expect(screen.getByText("message_without_session")).toBeInTheDocument();
    expect(screen.getByText(/missing-session/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "展开文件存储详情" }));
    expect(screen.getByText("orphan_disk_file")).toBeInTheDocument();
    expect(screen.getByText(/orphan.txt/)).toBeInTheDocument();

    const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
    expect(requestedUrls).toContain("http://localhost:8000/api/v1/admin/auth/health");
    expect(requestedUrls).toContain("http://localhost:8000/api/v1/admin/files/storage/issues");
  });

  it("loads audit logs with filters and expands audit detail", async () => {
    const fetchMock = mockFetch();
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "admin-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));
    await screen.findByRole("heading", { name: "概览" });

    fireEvent.click(screen.getByRole("button", { name: "审计" }));
    expect(await screen.findByRole("heading", { name: "审计" })).toBeInTheDocument();
    expect(await screen.findByText("admin.user.disable")).toBeInTheDocument();
    expect(screen.getAllByText("成功").length).toBeGreaterThan(0);

    fireEvent.change(screen.getByLabelText("操作人"), {
      target: { value: "admin" }
    });
    fireEvent.change(screen.getByLabelText("动作"), {
      target: { value: "admin.user.disable" }
    });
    fireEvent.click(screen.getByRole("button", { name: "筛选" }));

    await waitFor(() => {
      const requestedUrls = fetchMock.mock.calls.map(([input]) => String(input));
      expect(requestedUrls.some((url) => url.includes("actor_username=admin"))).toBe(true);
      expect(requestedUrls.some((url) => url.includes("action=admin.user.disable"))).toBe(true);
    });

    fireEvent.click(screen.getByRole("button", { name: "查看审计详情" }));
    expect(await screen.findByText("请求路径")).toBeInTheDocument();
    expect(screen.getByText("/api/v1/admin/users/user-1/disable")).toBeInTheDocument();
    expect(screen.getByText(/redacted/)).toBeInTheDocument();
  });

  it("shows a readable error when the admin API rejects the token", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({}, 401, 1004, "authorization required"));
    render(<App fetcher={fetchMock} />);

    fireEvent.change(screen.getByLabelText("服务端地址"), {
      target: { value: "http://localhost:8000" }
    });
    fireEvent.change(screen.getByLabelText("访问令牌"), {
      target: { value: "bad-token" }
    });
    fireEvent.click(screen.getByRole("button", { name: "连接" }));

    const alert = await screen.findByRole("alert");
    expect(within(alert).getByText("authorization required")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("heading", { name: "概览" })).not.toBeInTheDocument());
  });
});
