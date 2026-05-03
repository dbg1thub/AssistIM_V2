export type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export interface AdminApiClientOptions {
  baseUrl: string;
  token: string;
  fetcher?: Fetcher;
}

export interface ListUsersParams extends Record<string, unknown> {
  keyword?: string;
  role?: string;
  disabled?: boolean | "";
  page?: number;
  size?: number;
}

export interface ListAuditLogsParams extends Record<string, unknown> {
  actor_username?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  success?: boolean | "";
  created_from?: string;
  created_to?: string;
  page?: number;
  size?: number;
}

export const ADMIN_HEALTH_REQUESTS = [
  { key: "auth", path: "/api/v1/admin/auth/health" },
  { key: "database", path: "/api/v1/admin/database/health" },
  { key: "chat", path: "/api/v1/admin/chat/health" },
  { key: "contacts", path: "/api/v1/admin/contacts/health" },
  { key: "groups", path: "/api/v1/admin/groups/health" },
  { key: "moments", path: "/api/v1/admin/moments/health" },
  { key: "realtime", path: "/api/v1/admin/realtime/health" },
  { key: "calls", path: "/api/v1/admin/calls/health" },
  { key: "http", path: "/api/v1/admin/http/health" },
  { key: "rateLimits", path: "/api/v1/admin/rate-limits/health" },
  { key: "e2ee", path: "/api/v1/admin/e2ee/health" },
  { key: "fileStorageStatus", path: "/api/v1/admin/files/storage/status" },
  { key: "fileStorageIssues", path: "/api/v1/admin/files/storage/issues" }
] as const;

export type AdminHealthRequestKey = (typeof ADMIN_HEALTH_REQUESTS)[number]["key"];
export type AdminHealthPath = (typeof ADMIN_HEALTH_REQUESTS)[number]["path"];

interface ApiEnvelope<T> {
  code: number;
  message: string;
  data: T;
}

export class ApiError extends Error {
  status: number;
  code: number | string;

  constructor(message: string, options: { status: number; code: number | string }) {
    super(message);
    this.name = "ApiError";
    this.status = options.status;
    this.code = options.code;
  }
}

export class AdminApiClient {
  private readonly baseUrl: string;
  private readonly token: string;
  private readonly fetcher: Fetcher;

  constructor(options: AdminApiClientOptions) {
    this.baseUrl = normalizeBaseUrl(options.baseUrl);
    this.token = options.token.trim();
    this.fetcher = options.fetcher ?? fetch;
  }

  getDashboard<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/dashboard");
  }

  listUsers<T = unknown>(params: ListUsersParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/users", params);
  }

  listAuditLogs<T = unknown>(params: ListAuditLogsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/audit-logs", params);
  }

  getAuditLog<T = unknown>(logId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/audit-logs/${encodeURIComponent(logId)}`);
  }

  getDatabaseStatus<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/database/status");
  }

  listLogFiles<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/logs/files");
  }

  getHealthCheck<T = unknown>(path: AdminHealthPath): Promise<T> {
    return this.get<T>(path);
  }

  private async get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
    const response = await this.fetcher(this.url(path, params), {
      headers: { Authorization: `Bearer ${this.token}` },
      method: "GET"
    });
    const payload = await parseEnvelope<T>(response);
    if (!response.ok || payload.code !== 0) {
      throw new ApiError(payload.message || `HTTP ${response.status}`, {
        status: response.status,
        code: payload.code
      });
    }
    return payload.data;
  }

  private url(path: string, params?: Record<string, unknown>): string {
    const url = new URL(path, this.baseUrl);
    for (const [key, value] of Object.entries(params ?? {})) {
      if (value === undefined || value === null || value === "") {
        continue;
      }
      url.searchParams.set(key, String(value));
    }
    return url.toString();
  }
}

async function parseEnvelope<T>(response: Response): Promise<ApiEnvelope<T>> {
  try {
    return (await response.json()) as ApiEnvelope<T>;
  } catch {
    return {
      code: response.status || -1,
      message: response.statusText || "请求失败",
      data: undefined as T
    };
  }
}

function normalizeBaseUrl(value: string): string {
  const trimmed = value.trim();
  return trimmed.endsWith("/") ? trimmed : `${trimmed}/`;
}
