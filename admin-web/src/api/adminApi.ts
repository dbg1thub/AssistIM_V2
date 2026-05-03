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

export interface ListChatSessionsParams extends Record<string, unknown> {
  type?: string;
  keyword?: string;
  user_id?: string;
  page?: number;
  size?: number;
}

export interface ListChatMessagesParams extends Record<string, unknown> {
  type?: string;
  page?: number;
  size?: number;
}

export interface ListContactFriendRequestsParams extends Record<string, unknown> {
  status?: string;
  sender_id?: string;
  receiver_id?: string;
  page?: number;
  size?: number;
}

export interface ListContactFriendshipsParams extends Record<string, unknown> {
  user_id?: string;
  friend_id?: string;
  page?: number;
  size?: number;
}

export interface ListGroupsParams extends Record<string, unknown> {
  keyword?: string;
  owner_id?: string;
  page?: number;
  size?: number;
}

export interface ListGroupMembersParams extends Record<string, unknown> {
  role?: string;
  user_id?: string;
  page?: number;
  size?: number;
}

export interface ListMomentsParams extends Record<string, unknown> {
  keyword?: string;
  user_id?: string;
  page?: number;
  size?: number;
}

export interface ListMomentCommentsParams extends Record<string, unknown> {
  user_id?: string;
  page?: number;
  size?: number;
}

export interface ListMomentLikesParams extends Record<string, unknown> {
  user_id?: string;
  page?: number;
  size?: number;
}

export interface ListDatabaseBackupsParams extends Record<string, unknown> {
  page?: number;
  size?: number;
}

export interface PruneDatabaseBackupsParams extends Record<string, unknown> {
  dry_run: boolean;
  include_deleted: boolean;
  include_failed: boolean;
  keep_last?: number;
  older_than_days?: number;
}

export interface QueryLogsParams extends Record<string, unknown> {
  file_name?: string;
  level?: string;
  keyword?: string;
  created_from?: string;
  created_to?: string;
  limit?: number;
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

  getUserDetail<T = unknown>(userId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/users/${encodeURIComponent(userId)}`);
  }

  setUserRole<T = unknown>(userId: string, role: string): Promise<T> {
    return this.request<T>(`/api/v1/admin/users/${encodeURIComponent(userId)}/role`, {
      body: { role },
      method: "PATCH"
    });
  }

  disableUser<T = unknown>(userId: string, reason: string): Promise<T> {
    return this.request<T>(`/api/v1/admin/users/${encodeURIComponent(userId)}/disable`, {
      body: { reason },
      method: "POST"
    });
  }

  enableUser<T = unknown>(userId: string): Promise<T> {
    return this.request<T>(`/api/v1/admin/users/${encodeURIComponent(userId)}/enable`, {
      method: "POST"
    });
  }

  forceLogoutUser<T = unknown>(userId: string): Promise<T> {
    return this.request<T>(`/api/v1/admin/users/${encodeURIComponent(userId)}/force-logout`, {
      method: "POST"
    });
  }

  listAuditLogs<T = unknown>(params: ListAuditLogsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/audit-logs", params);
  }

  getAuditLog<T = unknown>(logId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/audit-logs/${encodeURIComponent(logId)}`);
  }

  listChatSessions<T = unknown>(params: ListChatSessionsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/chat/sessions", params);
  }

  getChatSession<T = unknown>(sessionId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/chat/sessions/${encodeURIComponent(sessionId)}`);
  }

  listChatMessages<T = unknown>(sessionId: string, params: ListChatMessagesParams = {}): Promise<T> {
    return this.get<T>(`/api/v1/admin/chat/sessions/${encodeURIComponent(sessionId)}/messages`, params);
  }

  listContactFriendRequests<T = unknown>(params: ListContactFriendRequestsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/contacts/friend-requests", params);
  }

  listContactFriendships<T = unknown>(params: ListContactFriendshipsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/contacts/friendships", params);
  }

  listGroups<T = unknown>(params: ListGroupsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/groups", params);
  }

  getGroup<T = unknown>(groupId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/groups/${encodeURIComponent(groupId)}`);
  }

  listGroupMembers<T = unknown>(groupId: string, params: ListGroupMembersParams = {}): Promise<T> {
    return this.get<T>(`/api/v1/admin/groups/${encodeURIComponent(groupId)}/members`, params);
  }

  listMoments<T = unknown>(params: ListMomentsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/moments", params);
  }

  getMoment<T = unknown>(momentId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/moments/${encodeURIComponent(momentId)}`);
  }

  listMomentComments<T = unknown>(momentId: string, params: ListMomentCommentsParams = {}): Promise<T> {
    return this.get<T>(`/api/v1/admin/moments/${encodeURIComponent(momentId)}/comments`, params);
  }

  listMomentLikes<T = unknown>(momentId: string, params: ListMomentLikesParams = {}): Promise<T> {
    return this.get<T>(`/api/v1/admin/moments/${encodeURIComponent(momentId)}/likes`, params);
  }

  getDatabaseStatus<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/database/status");
  }

  getFileStorageStatus<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/files/storage/status");
  }

  listFileStorageIssues<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/files/storage/issues");
  }

  listDatabaseBackups<T = unknown>(params: ListDatabaseBackupsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/database/backups", params);
  }

  getDatabaseBackup<T = unknown>(backupId: string): Promise<T> {
    return this.get<T>(`/api/v1/admin/database/backups/${encodeURIComponent(backupId)}`);
  }

  createDatabaseBackup<T = unknown>(): Promise<T> {
    return this.request<T>("/api/v1/admin/database/backups", { method: "POST" });
  }

  verifyDatabaseBackup<T = unknown>(backupId: string): Promise<T> {
    return this.request<T>(`/api/v1/admin/database/backups/${encodeURIComponent(backupId)}/verify`, {
      method: "POST"
    });
  }

  deleteDatabaseBackup<T = unknown>(backupId: string): Promise<T> {
    return this.request<T>(`/api/v1/admin/database/backups/${encodeURIComponent(backupId)}`, {
      method: "DELETE"
    });
  }

  pruneDatabaseBackups<T = unknown>(params: PruneDatabaseBackupsParams): Promise<T> {
    return this.request<T>("/api/v1/admin/database/backups/prune", {
      body: params,
      method: "POST"
    });
  }

  getDatabaseBackupDownloadUrl(backupId: string): string {
    return this.url(`/api/v1/admin/database/backups/${encodeURIComponent(backupId)}/download`);
  }

  listLogFiles<T = unknown>(): Promise<T> {
    return this.get<T>("/api/v1/admin/logs/files");
  }

  queryLogs<T = unknown>(params: QueryLogsParams = {}): Promise<T> {
    return this.get<T>("/api/v1/admin/logs", params);
  }

  async downloadLogFile(fileName: string): Promise<string> {
    const headers: Record<string, string> = { Authorization: `Bearer ${this.token}` };
    const response = await this.fetcher(
      this.url(`/api/v1/admin/logs/files/${encodeURIComponent(fileName)}/download`),
      {
        headers,
        method: "GET"
      }
    );
    const text = await response.text();
    if (!response.ok) {
      throw new ApiError(text || `HTTP ${response.status}`, {
        status: response.status,
        code: response.status
      });
    }
    return text;
  }

  getHealthCheck<T = unknown>(path: AdminHealthPath): Promise<T> {
    return this.get<T>(path);
  }

  private async get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
    return this.request<T>(path, { method: "GET", params });
  }

  private async request<T>(
    path: string,
    options: { body?: Record<string, unknown>; method: string; params?: Record<string, unknown> }
  ): Promise<T> {
    const headers: Record<string, string> = { Authorization: `Bearer ${this.token}` };
    const init: RequestInit = {
      headers,
      method: options.method
    };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    const response = await this.fetcher(this.url(path, options.params), init);
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
