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
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.endsWith("/api/v1/admin/dashboard")) {
      return jsonResponse(dashboardPayload);
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
