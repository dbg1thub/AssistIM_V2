import { describe, expect, it, vi } from "vitest";

import { ADMIN_HEALTH_REQUESTS, AdminApiClient, ApiError } from "./adminApi";

describe("AdminApiClient", () => {
  it("normalizes the base URL, sends bearer token, and unwraps success data", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { ok: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://127.0.0.1:8000/",
      token: "token-value",
      fetcher: fetchMock
    });

    await expect(client.getDashboard()).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/v1/admin/dashboard", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
  });

  it("builds query strings for list endpoints", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { items: [] } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await client.listUsers({ keyword: "test", role: "admin", page: 2, size: 10 });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/admin/users?keyword=test&role=admin&page=2&size=10",
      {
        headers: { Authorization: "Bearer token-value" },
        method: "GET"
      }
    );
  });

  it("loads user detail and sends user-management operations", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { ok: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await client.getUserDetail("user-1");
    await client.setUserRole("user-1", "user");
    await client.disableUser("user-1", "manual check");
    await client.enableUser("user-1");
    await client.forceLogoutUser("user-1");

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/users/user-1", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/users/user-1/role", {
      body: JSON.stringify({ role: "user" }),
      headers: { Authorization: "Bearer token-value", "Content-Type": "application/json" },
      method: "PATCH"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/users/user-1/disable", {
      body: JSON.stringify({ reason: "manual check" }),
      headers: { Authorization: "Bearer token-value", "Content-Type": "application/json" },
      method: "POST"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/users/user-1/enable", {
      headers: { Authorization: "Bearer token-value" },
      method: "POST"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/users/user-1/force-logout", {
      headers: { Authorization: "Bearer token-value" },
      method: "POST"
    });
  });

  it("manages database backup API calls", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { ok: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await client.listDatabaseBackups({ page: 2, size: 10 });
    await client.getDatabaseBackup("backup-1");
    await client.createDatabaseBackup();
    await client.verifyDatabaseBackup("backup-1");
    await client.deleteDatabaseBackup("backup-1");
    await client.pruneDatabaseBackups({
      keep_last: 3,
      older_than_days: 30,
      include_failed: true,
      include_deleted: false,
      dry_run: true
    });

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/database/backups?page=2&size=10", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/database/backups/backup-1", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/database/backups", {
      headers: { Authorization: "Bearer token-value" },
      method: "POST"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/database/backups/backup-1/verify", {
      headers: { Authorization: "Bearer token-value" },
      method: "POST"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/database/backups/backup-1", {
      headers: { Authorization: "Bearer token-value" },
      method: "DELETE"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/database/backups/prune", {
      body: JSON.stringify({
        keep_last: 3,
        older_than_days: 30,
        include_failed: true,
        include_deleted: false,
        dry_run: true
      }),
      headers: { Authorization: "Bearer token-value", "Content-Type": "application/json" },
      method: "POST"
    });
    expect(client.getDatabaseBackupDownloadUrl("backup-1")).toBe(
      "http://localhost:8000/api/v1/admin/database/backups/backup-1/download"
    );
  });

  it("loads file storage inspection endpoints", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { ok: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await client.getFileStorageStatus();
    await client.listFileStorageIssues();

    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/files/storage/status", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/files/storage/issues", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
  });

  it("queries and downloads server logs with bearer token", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/v1/admin/logs/files/assistim.log/download")) {
        return new Response("downloaded log content", {
          status: 200,
          headers: { "Content-Type": "text/plain; charset=utf-8" }
        });
      }
      return new Response(JSON.stringify({ code: 0, message: "success", data: { items: [] } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      });
    });
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await client.queryLogs({
      file_name: "assistim.log",
      level: "ERROR",
      keyword: "Network error",
      created_from: "2026-05-03T00:00:00+00:00",
      created_to: "2026-05-03T23:59:59+00:00",
      limit: 50
    });
    await expect(client.downloadLogFile("assistim.log")).resolves.toBe("downloaded log content");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/admin/logs?file_name=assistim.log&level=ERROR&keyword=Network+error&created_from=2026-05-03T00%3A00%3A00%2B00%3A00&created_to=2026-05-03T23%3A59%3A59%2B00%3A00&limit=50",
      {
        headers: { Authorization: "Bearer token-value" },
        method: "GET"
      }
    );
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/logs/files/assistim.log/download", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
  });

  it("builds query strings for audit log filters and loads detail", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { items: [] } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await client.listAuditLogs({
      actor_username: "admin",
      action: "admin.user.disable",
      target_type: "user",
      target_id: "user-1",
      success: true,
      created_from: "2026-05-01T00:00:00+00:00",
      created_to: "2026-05-03T00:00:00+00:00",
      page: 2,
      size: 50
    });
    await client.getAuditLog("audit-1");

    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/admin/audit-logs?actor_username=admin&action=admin.user.disable&target_type=user&target_id=user-1&success=true&created_from=2026-05-01T00%3A00%3A00%2B00%3A00&created_to=2026-05-03T00%3A00%3A00%2B00%3A00&page=2&size=50",
      {
        headers: { Authorization: "Bearer token-value" },
        method: "GET"
      }
    );
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/audit-logs/audit-1", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
  });

  it("requests configured admin health endpoints", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 0, message: "success", data: { status: "ok" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "token-value",
      fetcher: fetchMock
    });

    await Promise.all(ADMIN_HEALTH_REQUESTS.map((request) => client.getHealthCheck(request.path)));

    expect(fetchMock).toHaveBeenCalledTimes(13);
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/auth/health", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/api/v1/admin/files/storage/issues", {
      headers: { Authorization: "Bearer token-value" },
      method: "GET"
    });
  });

  it("throws ApiError with server code and message", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 1004, message: "authorization required" }), {
        status: 401,
        headers: { "Content-Type": "application/json" }
      })
    );
    const client = new AdminApiClient({
      baseUrl: "http://localhost:8000",
      token: "bad-token",
      fetcher: fetchMock
    });

    await expect(client.getDashboard()).rejects.toMatchObject({
      name: "ApiError",
      status: 401,
      code: 1004,
      message: "authorization required"
    });
  });
});
