import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ClipboardList,
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

import {
  ADMIN_HEALTH_REQUESTS,
  AdminApiClient,
  AdminHealthRequestKey,
  ApiError,
  Fetcher,
  ListAuditLogsParams,
  ListUsersParams
} from "./api/adminApi";
import "./styles.css";

type PageKey = "overview" | "health" | "audit" | "users" | "database" | "logs";
type HealthStatus = "ok" | "warning" | "error" | "unknown";

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

interface HealthModulePayload {
  status?: string;
  issue_count?: number;
  issues?: unknown;
  checks?: Record<string, unknown>;
  total?: number;
  items?: Array<Record<string, unknown>>;
  database?: Record<string, unknown>;
  disk?: Record<string, unknown>;
}

interface HealthModuleReport {
  key: string;
  label: string;
  status: HealthStatus;
  issueCount: number;
  issues: Array<Record<string, unknown>>;
  checks: Record<string, unknown>;
}

interface AuditLogItem {
  [key: string]: unknown;
  id: string;
  actor_username?: string;
  action?: string;
  target_type?: string;
  target_id?: string;
  request_path?: string;
  request_method?: string;
  client_ip?: string;
  success?: boolean;
  error_code?: string;
  detail?: unknown;
  created_at?: string;
}

interface AuditLogListPayload {
  total: number;
  page: number;
  size: number;
  items: AuditLogItem[];
}

interface AuditFilters {
  actor_username: string;
  action: string;
  target_type: string;
  target_id: string;
  success: "" | "true" | "false";
  created_from: string;
  created_to: string;
}

interface SessionState {
  baseUrl: string;
  token: string;
}

const navItems: Array<{ key: PageKey; label: string; icon: ReactNode }> = [
  { key: "overview", label: "概览", icon: <LayoutDashboard size={18} /> },
  { key: "health", label: "巡检", icon: <Activity size={18} /> },
  { key: "audit", label: "审计", icon: <ClipboardList size={18} /> },
  { key: "users", label: "用户", icon: <Users size={18} /> },
  { key: "database", label: "数据库", icon: <Database size={18} /> },
  { key: "logs", label: "日志", icon: <FileText size={18} /> }
];

const defaultAuditFilters: AuditFilters = {
  actor_username: "",
  action: "",
  target_type: "",
  target_id: "",
  success: "",
  created_from: "",
  created_to: ""
};

const healthModuleDefinitions: Array<{
  key: string;
  label: string;
  requests: AdminHealthRequestKey[];
}> = [
  { key: "auth", label: "认证", requests: ["auth"] },
  { key: "database", label: "数据库", requests: ["database"] },
  { key: "chat", label: "聊天", requests: ["chat"] },
  { key: "contacts", label: "联系人", requests: ["contacts"] },
  { key: "groups", label: "群组", requests: ["groups"] },
  { key: "moments", label: "朋友圈", requests: ["moments"] },
  { key: "realtime", label: "实时连接", requests: ["realtime"] },
  { key: "calls", label: "通话", requests: ["calls"] },
  { key: "http", label: "HTTP", requests: ["http"] },
  { key: "rateLimits", label: "限流", requests: ["rateLimits"] },
  { key: "e2ee", label: "端到端加密", requests: ["e2ee"] },
  { key: "fileStorage", label: "文件存储", requests: ["fileStorageStatus", "fileStorageIssues"] }
];

const healthRequestsByKey = new Map(ADMIN_HEALTH_REQUESTS.map((request) => [request.key, request]));

export default function App({ fetcher }: AppProps) {
  const [session, setSession] = useState<SessionState | null>(null);
  const [baseUrl, setBaseUrl] = useState("http://127.0.0.1:8000");
  const [token, setToken] = useState("");
  const [activePage, setActivePage] = useState<PageKey>("overview");
  const [dashboard, setDashboard] = useState<DashboardPayload | null>(null);
  const [users, setUsers] = useState<UserListPayload | null>(null);
  const [databaseStatus, setDatabaseStatus] = useState<DatabaseStatusPayload | null>(null);
  const [logFiles, setLogFiles] = useState<LogFilesPayload | null>(null);
  const [healthReports, setHealthReports] = useState<HealthModuleReport[] | null>(null);
  const [healthRefreshedAt, setHealthRefreshedAt] = useState("");
  const [expandedHealthModules, setExpandedHealthModules] = useState<Record<string, boolean>>({});
  const [auditLogs, setAuditLogs] = useState<AuditLogListPayload | null>(null);
  const [auditFilters, setAuditFilters] = useState<AuditFilters>(defaultAuditFilters);
  const [selectedAuditLog, setSelectedAuditLog] = useState<AuditLogItem | null>(null);
  const [auditDetailLoading, setAuditDetailLoading] = useState(false);
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
    const shouldLoad =
      (page === "overview" && !dashboard) ||
      (page === "health" && !healthReports) ||
      (page === "audit" && !auditLogs) ||
      (page === "users" && !users) ||
      (page === "database" && !databaseStatus) ||
      (page === "logs" && !logFiles);
    if (!shouldLoad) {
      return;
    }
    setLoading(true);
    try {
      if (page === "overview" && !dashboard) {
        setDashboard(await client.getDashboard<DashboardPayload>());
      }
      if (page === "health" && !healthReports) {
        setHealthReports(await loadHealthReports(client));
        setHealthRefreshedAt(new Date().toLocaleString());
      }
      if (page === "audit" && !auditLogs) {
        setAuditLogs(await loadAuditLogs(client, auditFilters));
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
    } finally {
      setLoading(false);
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
      if (activePage === "health") {
        setHealthReports(await loadHealthReports(client));
        setHealthRefreshedAt(new Date().toLocaleString());
      }
      if (activePage === "audit") {
        setAuditLogs(await loadAuditLogs(client, auditFilters));
        setSelectedAuditLog(null);
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

  async function searchAuditLogs() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setAuditLogs(await loadAuditLogs(client, auditFilters));
      setSelectedAuditLog(null);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function openAuditLogDetail(logId: string) {
    if (!client) {
      return;
    }
    setAuditDetailLoading(true);
    setError("");
    try {
      setSelectedAuditLog(await client.getAuditLog<AuditLogItem>(logId));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setAuditDetailLoading(false);
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
        {activePage === "health" ? (
          <HealthPage
            reports={healthReports}
            refreshedAt={healthRefreshedAt}
            expanded={expandedHealthModules}
            toggleExpanded={(key) =>
              setExpandedHealthModules((current) => ({ ...current, [key]: !current[key] }))
            }
          />
        ) : null}
        {activePage === "audit" ? (
          <AuditPage
            payload={auditLogs}
            filters={auditFilters}
            setFilter={(key, value) => setAuditFilters((current) => ({ ...current, [key]: value }))}
            search={() => void searchAuditLogs()}
            selectedLog={selectedAuditLog}
            detailLoading={auditDetailLoading}
            openDetail={(logId) => void openAuditLogDetail(logId)}
          />
        ) : null}
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

function HealthPage({
  reports,
  refreshedAt,
  expanded,
  toggleExpanded
}: {
  reports: HealthModuleReport[] | null;
  refreshedAt: string;
  expanded: Record<string, boolean>;
  toggleExpanded: (key: string) => void;
}) {
  const items = reports ?? [];
  const issueTotal = items.reduce((total, item) => total + item.issueCount, 0);
  const warningModules = items.filter((item) => item.status === "warning" || item.status === "error").length;

  return (
    <section className="page-section">
      <PageTitle title="巡检" subtitle={refreshedAt ? `最近刷新 ${refreshedAt}` : "读取后端只读巡检接口"} />
      <div className="metric-grid compact-grid">
        <MetricCard label="模块" value={items.length || "-"} />
        <MetricCard label="异常模块" value={warningModules} tone={warningModules > 0 ? "warn" : "ok"} />
        <MetricCard label="问题总数" value={issueTotal} tone={issueTotal > 0 ? "warn" : "ok"} />
      </div>
      <div className="health-grid">
        {items.map((report) => {
          const isExpanded = Boolean(expanded[report.key]);
          return (
            <article className="health-card" key={report.key}>
              <div className="health-card-header">
                <div>
                  <h2>{report.label}</h2>
                  <span className={`status-badge ${report.status}`}>{healthStatusLabel(report.status)}</span>
                </div>
                <strong>{report.issueCount}</strong>
              </div>
              <div className="health-checks">
                {Object.entries(report.checks).slice(0, 6).map(([key, value]) => (
                  <div className="health-check" key={key}>
                    <span>{key}</span>
                    <strong>{compactValue(value)}</strong>
                  </div>
                ))}
              </div>
              <button
                className="link-button"
                type="button"
                onClick={() => toggleExpanded(report.key)}
                aria-expanded={isExpanded}
                aria-label={`${isExpanded ? "收起" : "展开"}${report.label}详情`}
              >
                {isExpanded ? "收起详情" : "展开详情"}
              </button>
              {isExpanded ? (
                <div className="issue-list">
                  {report.issues.length > 0 ? (
                    report.issues.map((issue, index) => (
                      <div className="issue-row" key={`${report.key}-${index}`}>
                        <span className={`severity-dot ${String(issue.severity ?? "warning")}`} />
                        <div>
                          <strong>{String(issue.issue_type ?? issue.code ?? "issue")}</strong>
                          <p>{issueSummary(issue)}</p>
                        </div>
                      </div>
                    ))
                  ) : (
                    <p className="empty-text">暂无问题</p>
                  )}
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
    </section>
  );
}

function AuditPage({
  payload,
  filters,
  setFilter,
  search,
  selectedLog,
  detailLoading,
  openDetail
}: {
  payload: AuditLogListPayload | null;
  filters: AuditFilters;
  setFilter: (key: keyof AuditFilters, value: string) => void;
  search: () => void;
  selectedLog: AuditLogItem | null;
  detailLoading: boolean;
  openDetail: (logId: string) => void;
}) {
  const logs = payload?.items ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    search();
  }

  return (
    <section className="page-section">
      <PageTitle title="审计" subtitle={`共 ${payload?.total ?? 0} 条记录`} />
      <form className="filter-panel" onSubmit={submit}>
        <label>
          <span>操作人</span>
          <input
            value={filters.actor_username}
            onChange={(event) => setFilter("actor_username", event.target.value)}
            placeholder="admin"
          />
        </label>
        <label>
          <span>动作</span>
          <input
            value={filters.action}
            onChange={(event) => setFilter("action", event.target.value)}
            placeholder="admin.user.disable"
          />
        </label>
        <label>
          <span>目标类型</span>
          <input
            value={filters.target_type}
            onChange={(event) => setFilter("target_type", event.target.value)}
            placeholder="user"
          />
        </label>
        <label>
          <span>目标 ID</span>
          <input
            value={filters.target_id}
            onChange={(event) => setFilter("target_id", event.target.value)}
            placeholder="user id"
          />
        </label>
        <label>
          <span>结果</span>
          <select value={filters.success} onChange={(event) => setFilter("success", event.target.value)}>
            <option value="">全部</option>
            <option value="true">成功</option>
            <option value="false">失败</option>
          </select>
        </label>
        <label>
          <span>开始时间</span>
          <input
            value={filters.created_from}
            onChange={(event) => setFilter("created_from", event.target.value)}
            placeholder="2026-05-01T00:00:00+00:00"
          />
        </label>
        <label>
          <span>结束时间</span>
          <input
            value={filters.created_to}
            onChange={(event) => setFilter("created_to", event.target.value)}
            placeholder="2026-05-03T00:00:00+00:00"
          />
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          筛选
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>操作人</th>
              <th>动作</th>
              <th>目标</th>
              <th>结果</th>
              <th>路径</th>
              <th>客户端 IP</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => (
              <tr key={log.id}>
                <td>{String(log.created_at ?? "")}</td>
                <td>{String(log.actor_username ?? "")}</td>
                <td>{String(log.action ?? "")}</td>
                <td>{auditTarget(log)}</td>
                <td>{log.success ? "成功" : "失败"}</td>
                <td>{String(log.request_path ?? "")}</td>
                <td>{String(log.client_ip ?? "")}</td>
                <td>
                  <button
                    className="table-action-button"
                    type="button"
                    onClick={() => openDetail(log.id)}
                    aria-label="查看审计详情"
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detailLoading ? <p className="empty-text">正在读取详情...</p> : null}
      {selectedLog ? <AuditDetailPanel log={selectedLog} /> : null}
    </section>
  );
}

function AuditDetailPanel({ log }: { log: AuditLogItem }) {
  return (
    <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{String(log.action ?? "")}</h2>
          <p>{String(log.created_at ?? "")}</p>
        </div>
        <span className={`status-badge ${log.success ? "ok" : "error"}`}>{log.success ? "成功" : "失败"}</span>
      </div>
      <div className="info-grid">
        <InfoBlock title="请求" rows={[
          ["请求方法", log.request_method],
          ["请求路径", log.request_path],
          ["客户端 IP", log.client_ip]
        ]} />
        <InfoBlock title="目标" rows={[
          ["操作人", log.actor_username],
          ["目标类型", log.target_type],
          ["目标 ID", log.target_id],
          ["错误码", log.error_code]
        ]} />
      </div>
      <div className="json-block">
        <span>detail</span>
        <pre>{JSON.stringify(log.detail ?? {}, null, 2)}</pre>
      </div>
    </article>
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

function loadAuditLogs(client: AdminApiClient, filters: AuditFilters): Promise<AuditLogListPayload> {
  return client.listAuditLogs<AuditLogListPayload>(auditParams(filters));
}

function auditParams(filters: AuditFilters): ListAuditLogsParams {
  const params: ListAuditLogsParams = { page: 1, size: 20 };
  for (const key of ["actor_username", "action", "target_type", "target_id", "created_from", "created_to"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  if (filters.success) {
    params.success = filters.success === "true";
  }
  return params;
}

async function loadHealthReports(client: AdminApiClient): Promise<HealthModuleReport[]> {
  return Promise.all(
    healthModuleDefinitions.map(async (definition) => {
      try {
        const payloads = await Promise.all(
          definition.requests.map(async (key) => {
            const request = healthRequest(key);
            return [key, await client.getHealthCheck<HealthModulePayload>(request.path)] as const;
          })
        );
        return buildHealthReport(definition, payloads);
      } catch (error) {
        return {
          key: definition.key,
          label: definition.label,
          status: "error",
          issueCount: 1,
          checks: { request: "failed" },
          issues: [
            {
              issue_type: "health_request_failed",
              severity: "error",
              message: readableError(error)
            }
          ]
        };
      }
    })
  );
}

function healthRequest(key: AdminHealthRequestKey) {
  const request = healthRequestsByKey.get(key);
  if (!request) {
    throw new Error(`Unknown health request: ${key}`);
  }
  return request;
}

function buildHealthReport(
  definition: (typeof healthModuleDefinitions)[number],
  payloads: Array<readonly [AdminHealthRequestKey, HealthModulePayload]>
): HealthModuleReport {
  const primaryPayload = payloads[0]?.[1] ?? {};
  const issues = payloads.flatMap(([, payload]) => extractHealthIssues(payload));
  const issueCount = Math.max(
    issues.length,
    ...payloads.flatMap(([, payload]) => [
      numberValue(payload.issue_count),
      Array.isArray(payload.items) ? numberValue(payload.total) : 0,
      objectValue(payload.issues) ? numberValue(objectValue(payload.issues)?.total) : 0
    ])
  );
  return {
    key: definition.key,
    label: definition.label,
    status: normalizeHealthStatus(primaryPayload.status, issueCount),
    issueCount,
    issues,
    checks: collectHealthChecks(payloads)
  };
}

function extractHealthIssues(payload: HealthModulePayload): Array<Record<string, unknown>> {
  if (Array.isArray(payload.issues)) {
    return payload.issues.filter(isRecord);
  }
  if (Array.isArray(payload.items)) {
    return payload.items.filter(isRecord);
  }
  return [];
}

function collectHealthChecks(
  payloads: Array<readonly [AdminHealthRequestKey, HealthModulePayload]>
): Record<string, unknown> {
  const checks: Record<string, unknown> = {};
  for (const [key, payload] of payloads) {
    if (isRecord(payload.checks)) {
      Object.assign(checks, payload.checks);
    }
    if (key === "fileStorageStatus") {
      const database = objectValue(payload.database);
      const disk = objectValue(payload.disk);
      const issues = objectValue(payload.issues);
      checks.local_records = database?.local_records;
      checks.managed_files = disk?.managed_files;
      checks.storage_issues = issues?.total;
    }
    if (key === "fileStorageIssues") {
      checks.issue_rows = payload.total ?? payload.items?.length ?? 0;
    }
  }
  return Object.fromEntries(Object.entries(checks).filter(([, value]) => value !== undefined));
}

function normalizeHealthStatus(value: unknown, issueCount: number): HealthStatus {
  const status = String(value ?? "").toLowerCase();
  if (status === "ok") {
    return issueCount > 0 ? "warning" : "ok";
  }
  if (status === "warning" || status === "error") {
    return status;
  }
  return issueCount > 0 ? "warning" : "unknown";
}

function healthStatusLabel(status: HealthStatus): string {
  if (status === "ok") {
    return "正常";
  }
  if (status === "warning") {
    return "有问题";
  }
  if (status === "error") {
    return "请求失败";
  }
  return "无数据";
}

function displayValue(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  return String(value);
}

function auditTarget(log: AuditLogItem): string {
  const targetType = String(log.target_type ?? "");
  const targetId = String(log.target_id ?? "");
  if (!targetType && !targetId) {
    return "-";
  }
  return [targetType, targetId].filter(Boolean).join(": ");
}

function compactValue(value: unknown): string {
  if (value === undefined || value === null || value === "") {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function issueSummary(issue: Record<string, unknown>): string {
  const entries = Object.entries(issue)
    .filter(([key]) => !["issue_type", "code", "severity"].includes(key))
    .slice(0, 6);
  if (!entries.length) {
    return "-";
  }
  return entries.map(([key, value]) => `${key}: ${compactValue(value)}`).join(" · ");
}

function numberValue(value: unknown): number {
  const number = Number(value ?? 0);
  return Number.isFinite(number) ? number : 0;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return isRecord(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
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
