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
        database: { local_records: 3 },
        disk: { managed_files: 2 },
        issues: { total: 1, warnings: 1, errors: 0 }
      });
    }
    if (url.endsWith("/api/v1/admin/files/storage/issues")) {
      return jsonResponse({
        total: 1,
        items: [
          {
            issue_type: "orphan_disk_file",
            severity: "warning",
            storage_key: "orphan.txt"
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
