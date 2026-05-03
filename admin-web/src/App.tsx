import {
  Activity,
  AlertCircle,
  CheckCircle2,
  Database,
  FileText,
  LayoutDashboard,
  Loader2,
  LogOut,
  RefreshCcw,
  Search,
  Server,
  Users
} from "lucide-react";
import { FormEvent, ReactNode, useMemo, useState } from "react";

import { AdminApiClient, ApiError, Fetcher, ListUsersParams } from "./api/adminApi";
import "./styles.css";

type PageKey = "overview" | "users" | "database" | "logs";

interface AppProps {
  fetcher?: Fetcher;
}

interface DashboardPayload {
  system?: Record<string, unknown>;
  users?: Record<string, unknown>;
  database?: Record<string, unknown>;
  chat?: {
    sessions?: Record<string, unknown>;
    messages?: Record<string, unknown>;
  };
  files?: Record<string, unknown>;
  realtime?: Record<string, unknown>;
  calls?: Record<string, unknown>;
  e2ee?: Record<string, unknown>;
  http?: Record<string, unknown>;
}

interface UserListPayload {
  total: number;
  page: number;
  size: number;
  items: Array<Record<string, unknown>>;
}

interface DatabaseStatusPayload {
  status?: string;
  dialect?: string;
  runtime_schema_complete?: boolean;
  runtime_schema_revision?: string;
  required_tables?: Record<string, boolean>;
}

interface LogFilesPayload {
  total?: number;
  files?: Array<Record<string, unknown>>;
  items?: Array<Record<string, unknown>>;
}

interface SessionState {
  baseUrl: string;
  token: string;
}

const navItems: Array<{ key: PageKey; label: string; icon: ReactNode }> = [
  { key: "overview", label: "概览", icon: <LayoutDashboard size={18} /> },
  { key: "users", label: "用户", icon: <Users size={18} /> },
  { key: "database", label: "数据库", icon: <Database size={18} /> },
  { key: "logs", label: "日志", icon: <FileText size={18} /> }
];

export default function App({ fetcher }: AppProps) {
  const [session, setSession] = useState<SessionState | null>(null);
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8000");
  const [token, setToken] = useState("");
  const [activePage, setActivePage] = useState<PageKey>("overview");
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [users, setUsers] = useState<UserListPayload | null>(null);
  const [databaseStatus, setDatabaseStatus] = useState<DatabaseStatusPayload | null>(null);
  const [logFiles, setLogFiles] = useState<LogFilesPayload | null>(null);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const client = useMemo(() => {
    if (!session) {
      return null;
    }
    return new AdminApiClient({ baseUrl: session.baseUrl, token: session.token, fetcher });
  }, [fetcher, session]);

  async function connect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextSession = { baseUrl: baseUrl.trim(), token: token.trim() };
    const nextClient = new AdminApiClient({ ...nextSession, fetcher });
    setLoading(true);
    setError("");
    try {
      const payload = await nextClient.getDashboard<DashboardPayload>();
      setDashboard(payload);
      setSession(nextSession);
      setActivePage("overview");
    } catch (currentError) {
      setSession(null);
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function openPage(page: PageKey) {
    if (!client) {
      return;
    }
    setActivePage(page);
    setError("");
    try {
      if (page === "overview" && !dashboard) {
        setDashboard(await client.getDashboard<DashboardPayload>());
      }
      if (page === "users" && !users) {
        setUsers(await client.listUsers<UserListPayload>({ page: 1, size: 20 }));
      }
      if (page === "database" && !databaseStatus) {
        setDatabaseStatus(await client.getDatabaseStatus<DatabaseStatusPayload>());
      }
      if (page === "logs" && !logFiles) {
        setLogFiles(await client.listLogFiles<LogFilesPayload>());
      }
    } catch (currentError) {
      setError(readableError(currentError));
    }
  }

  async function refreshPage() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      if (activePage === "overview") {
        setDashboard(await client.getDashboard<DashboardPayload>());
      }
      if (activePage === "users") {
        const params: ListUsersParams = { page: 1, size: 20 };
        if (keyword.trim()) {
          params.keyword = keyword.trim();
        }
        setUsers(await client.listUsers<UserListPayload>(params));
      }
      if (activePage === "database") {
        setDatabaseStatus(await client.getDatabaseStatus<DatabaseStatusPayload>());
      }
      if (activePage === "logs") {
        setLogFiles(await client.listLogFiles<LogFilesPayload>());
      }
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  if (!session || !client) {
    return (
      <main className="login-shell">
        <section className="login-panel" aria-labelledby="login-title">
          <div className="brand-row">
            <span className="brand-mark">
              <Server size={24} />
            </span>
            <div>
              <h1 id="login-title">AssistIM 管理看板</h1>
              <p>连接后端管理员接口</p>
            </div>
          </div>
          <form className="login-form" onSubmit={connect}>
            <label>
              <span>服务端地址</span>
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                placeholder="http://127.0.0.1:8000"
                required
              />
            </label>
            <label>
              <span>访问令牌</span>
              <textarea
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="Bearer token 内容"
                rows={5}
                required
              />
            </label>
            {error ? <ErrorBanner message={error} /> : null}
            <button className="primary-button" type="submit" disabled={loading}>
              {loading ? <Loader2 className="spin" size={18} /> : <CheckCircle2 size={18} />}
              连接
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark compact">
            <Server size={20} />
          </span>
          <span>AssistIM</span>
        </div>
        <nav aria-label="管理页面">
          {navItems.map((item) => (
            <button
              key={item.key}
              className={activePage === item.key ? "nav-button active" : "nav-button"}
              type="button"
              onClick={() => void openPage(item.key)}
            >
              {item.icon}
              {item.label}
            </button>
          ))}
        </nav>
        <button className="nav-button logout" type="button" onClick={() => setSession(null)}>
          <LogOut size={18} />
          退出
        </button>
      </aside>
      <main className="workspace">
        <header className="topbar">
          <div>
            <span className="caption">当前服务</span>
            <strong>{session.baseUrl}</strong>
          </div>
          <button className="icon-button" type="button" onClick={() => void refreshPage()} aria-label="刷新">
            {loading ? <Loader2 className="spin" size={18} /> : <RefreshCcw size={18} />}
          </button>
        </header>
        {error ? <ErrorBanner message={error} /> : null}
        {activePage === "overview" ? <OverviewPage dashboard={dashboard} /> : null}
        {activePage === "users" ? (
          <UsersPage
            payload={users}
            keyword={keyword}
            setKeyword={setKeyword}
            search={() => void refreshPage()}
          />
        ) : null}
        {activePage === "database" ? <DatabasePage payload={databaseStatus} /> : null}
        {activePage === "logs" ? <LogsPage payload={logFiles} /> : null}
      </main>
    </div>
  );
}

function OverviewPage({ dashboard }: { dashboard: DashboardPayload | null }) {
  const system = dashboard?.system ?? {};
  const users = dashboard?.users ?? {};
  const database = dashboard?.database ?? {};
  const chat = dashboard?.chat ?? {};
  const files = dashboard?.files ?? {};
  const realtime = dashboard?.realtime ?? {};
  const calls = dashboard?.calls ?? {};
  const e2ee = dashboard?.e2ee ?? {};
  const http = dashboard?.http ?? {};
  return (
    <section className="page-section">
      <PageTitle title="概览" subtitle={String(system.app_name ?? "AssistIM API")} />
      <div className="metric-grid">
        <MetricCard label="用户总数" value={users.total} />
        <MetricCard label="在线用户" value={users.online ?? realtime.online_users} />
        <MetricCard label="会话" value={readNested(chat, ["sessions", "total"])} />
        <MetricCard label="消息" value={readNested(chat, ["messages", "total"])} />
        <MetricCard label="文件" value={files.total} />
        <MetricCard label="活跃通话" value={calls.active} />
        <MetricCard label="加密会话" value={e2ee.encrypted_sessions} />
        <MetricCard label="HTTP 错误" value={http.error_requests} tone={Number(http.error_requests ?? 0) > 0 ? "warn" : "ok"} />
      </div>
      <div className="info-grid">
        <InfoBlock title="系统" rows={[
          ["版本", system.app_version],
          ["运行秒数", system.uptime_seconds],
          ["数据库", database.status]
        ]} />
        <InfoBlock title="实时" rows={[
          ["在线用户", realtime.online_users],
          ["连接数", realtime.bound_connections],
          ["请求数", http.total_requests]
        ]} />
      </div>
    </section>
  );
}

function UsersPage({
  payload,
  keyword,
  setKeyword,
  search
}: {
  payload: UserListPayload | null;
  keyword: string;
  setKeyword: (value: string) => void;
  search: () => void;
}) {
  return (
    <section className="page-section">
      <PageTitle title="用户" subtitle={`共 ${payload?.total ?? 0} 个用户`} />
      <div className="toolbar">
        <label className="search-field">
          <Search size={17} />
          <input value={keyword} onChange={(event) => setKeyword(event.target.value)} placeholder="搜索用户名、昵称、邮箱或手机号" />
        </label>
        <button className="secondary-button" type="button" onClick={search}>
          <Search size={17} />
          搜索
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户名</th>
              <th>昵称</th>
              <th>角色</th>
              <th>状态</th>
              <th>账号</th>
            </tr>
          </thead>
          <tbody>
            {(payload?.items ?? []).map((user) => (
              <tr key={String(user.id)}>
                <td>{String(user.username ?? "")}</td>
                <td>{String(user.nickname ?? "")}</td>
                <td>{String(user.role ?? "")}</td>
                <td>{String(user.status ?? "")}</td>
                <td>{user.is_disabled ? "已禁用" : "正常"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DatabasePage({ payload }: { payload: DatabaseStatusPayload | null }) {
  const tables = Object.entries(payload?.required_tables ?? {});
  return (
    <section className="page-section">
      <PageTitle title="数据库" subtitle={String(payload?.dialect ?? "")} />
      <div className="metric-grid compact-grid">
        <MetricCard label="状态" value={payload?.status} tone={payload?.status === "ok" ? "ok" : "warn"} />
        <MetricCard label="Schema" value={payload?.runtime_schema_complete ? "完整" : "需检查"} tone={payload?.runtime_schema_complete ? "ok" : "warn"} />
        <MetricCard label="Revision" value={payload?.runtime_schema_revision} />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>表</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {tables.map(([table, exists]) => (
              <tr key={table}>
                <td>{table}</td>
                <td>{exists ? "存在" : "缺失"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function LogsPage({ payload }: { payload: LogFilesPayload | null }) {
  const files = payload?.files ?? payload?.items ?? [];
  return (
    <section className="page-section">
      <PageTitle title="日志" subtitle={`共 ${payload?.total ?? files.length} 个文件`} />
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>更新时间</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => (
              <tr key={String(file.file_name ?? file.name)}>
                <td>{String(file.file_name ?? file.name ?? "")}</td>
                <td>{formatBytes(file.size_bytes)}</td>
                <td>{String(file.modified_at ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PageTitle({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="page-title">
      <div>
        <h1>{title}</h1>
        <p>{subtitle}</p>
      </div>
      <Activity size={22} />
    </div>
  );
}

function MetricCard({ label, value, tone = "neutral" }: { label: string; value: unknown; tone?: "neutral" | "ok" | "warn" }) {
  return (
    <article className={`metric-card ${tone}`}>
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </article>
  );
}

function InfoBlock({ title, rows }: { title: string; rows: Array<[string, unknown]> }) {
  return (
    <article className="info-block">
      <h2>{title}</h2>
      {rows.map(([label, value]) => (
        <div className="info-row" key={label}>
          <span>{label}</span>
          <strong>{displayValue(value)}</strong>
        </div>
      ))}
    </article>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error-banner" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
    </div>
  );
}

function readableError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "请求失败";
}

function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  return String(value);
}

function readNested(source: Record<string, unknown>, path: string[]): unknown {
  let current: unknown = source;
  for (const key of path) {
    if (!current || typeof current !== "object") {
      return undefined;
    }
    current = (current as Record<string, unknown>)[key];
  }
  return current;
}

function formatBytes(value: unknown): string {
  const bytes = Number(value ?? 0);
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
