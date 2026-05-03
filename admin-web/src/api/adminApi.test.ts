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
