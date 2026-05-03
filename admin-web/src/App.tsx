import {
  Activity,
  AlertCircle,
  Archive,
  CheckCircle2,
  ClipboardList,
  Database,
  FileText,
  HardDrive,
  Heart,
  LayoutDashboard,
  Loader2,
  LogOut,
  MessageSquare,
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
  ListChatMessagesParams,
  ListChatSessionsParams,
  ListContactFriendRequestsParams,
  ListContactFriendshipsParams,
  ListGroupMembersParams,
  ListGroupsParams,
  ListMomentCommentsParams,
  ListMomentLikesParams,
  ListMomentsParams,
  ListUsersParams,
  PruneDatabaseBackupsParams,
  QueryLogsParams
} from "./api/adminApi";
import "./styles.css";

type PageKey =
  | "overview"
  | "health"
  | "audit"
  | "chat"
  | "contacts"
  | "groups"
  | "moments"
  | "users"
  | "database"
  | "files"
  | "backups"
  | "logs";
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

interface UserDetailPayload extends Record<string, unknown> {
  id: string;
  username?: string;
  nickname?: string;
  display_name?: string;
  email?: string;
  phone?: string;
  role?: string;
  status?: string;
  is_disabled?: boolean;
  disabled_reason?: string;
  counts?: Record<string, unknown>;
  devices?: Array<Record<string, unknown>>;
}

interface DatabaseStatusPayload {
  status?: string;
  dialect?: string;
  runtime_schema_complete?: boolean;
  runtime_schema_revision?: string;
  required_tables?: Record<string, boolean>;
}

interface FileStorageStatusPayload {
  status?: string;
  storage_provider?: string;
  upload_dir?: Record<string, unknown>;
  database?: Record<string, unknown>;
  disk?: Record<string, unknown>;
  issues?: Record<string, unknown>;
}

interface FileStorageIssueItem extends Record<string, unknown> {
  issue_type?: string;
  severity?: string;
  file_id?: string;
  file_name?: string;
  storage_provider?: string;
  storage_key?: string;
  expected_size_bytes?: number;
  actual_size_bytes?: number | null;
}

interface FileStorageIssuesPayload {
  total: number;
  items: FileStorageIssueItem[];
}

interface DatabaseBackupItem extends Record<string, unknown> {
  id: string;
  created_by_username?: string;
  status?: string;
  database_dialect?: string;
  backup_format?: string;
  storage_key?: string;
  file_name?: string;
  size_bytes?: number;
  checksum_sha256?: string;
  error_message?: string;
  verification_status?: string;
  verification_message?: string;
  created_at?: string;
  duration_ms?: number;
}

interface DatabaseBackupListPayload {
  total: number;
  page: number;
  size: number;
  items: DatabaseBackupItem[];
}

interface DatabaseBackupPruneResult {
  candidate_count?: number;
  processed_count?: number;
  file_deleted_count?: number;
  file_missing_count?: number;
  dry_run?: boolean;
  items?: Array<Record<string, unknown>>;
}

interface BackupPruneForm {
  keep_last: string;
  older_than_days: string;
  include_failed: boolean;
  include_deleted: boolean;
}

interface LogFilesPayload {
  total?: number;
  files?: Array<Record<string, unknown>>;
  items?: Array<Record<string, unknown>>;
}

interface LogEntryItem extends Record<string, unknown> {
  file_name?: string;
  timestamp?: string | null;
  level?: string;
  logger?: string;
  message?: string;
}

interface LogQueryPayload {
  total: number;
  limit: number;
  items: LogEntryItem[];
}

interface LogFilters {
  file_name: string;
  level: string;
  keyword: string;
  created_from: string;
  created_to: string;
  limit: string;
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

interface ChatMessageItem extends Record<string, unknown> {
  id: string;
  session_id?: string;
  sender_id?: string;
  sender_username?: string;
  sender_nickname?: string;
  session_seq?: number;
  type?: string;
  content?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
}

interface ChatSessionItem extends Record<string, unknown> {
  id: string;
  type?: string;
  name?: string;
  encryption_mode?: string;
  member_count?: number;
  message_count?: number;
  last_message_seq?: number;
  last_event_seq?: number;
  last_message?: ChatMessageItem | null;
  created_at?: string;
  updated_at?: string;
}

interface ChatSessionDetailPayload extends ChatSessionItem {
  members?: Array<Record<string, unknown>>;
}

interface ChatSessionListPayload {
  total: number;
  page: number;
  size: number;
  items: ChatSessionItem[];
}

interface ChatMessageListPayload {
  total: number;
  page: number;
  size: number;
  session?: Record<string, unknown>;
  items: ChatMessageItem[];
}

interface ChatFilters {
  type: string;
  keyword: string;
  user_id: string;
}

interface ChatMessageFilters {
  type: string;
}

interface ContactUserSummary extends Record<string, unknown> {
  id?: string;
  username?: string;
  nickname?: string;
  exists?: boolean;
  is_disabled?: boolean;
}

interface ContactFriendRequestItem extends Record<string, unknown> {
  id: string;
  sender_id?: string;
  receiver_id?: string;
  status?: string;
  message?: string;
  sender?: ContactUserSummary;
  receiver?: ContactUserSummary;
  created_at?: string;
  updated_at?: string;
}

interface ContactFriendshipItem extends Record<string, unknown> {
  id: string;
  user_id?: string;
  friend_id?: string;
  user?: ContactUserSummary;
  friend?: ContactUserSummary;
  created_at?: string;
  updated_at?: string;
}

interface ContactFriendRequestListPayload {
  total: number;
  page: number;
  size: number;
  items: ContactFriendRequestItem[];
}

interface ContactFriendshipListPayload {
  total: number;
  page: number;
  size: number;
  items: ContactFriendshipItem[];
}

interface ContactRequestFilters {
  status: string;
  sender_id: string;
  receiver_id: string;
}

interface ContactFriendshipFilters {
  user_id: string;
  friend_id: string;
}

interface GroupUserSummary extends Record<string, unknown> {
  id?: string;
  username?: string;
  nickname?: string;
  exists?: boolean;
  is_disabled?: boolean;
}

interface GroupSessionSummary extends Record<string, unknown> {
  id?: string;
  exists?: boolean;
  type?: string;
  name?: string;
  is_ai_session?: boolean;
  encryption_mode?: string;
  last_message_seq?: number;
  last_event_seq?: number;
}

interface GroupFileSummary extends Record<string, unknown> {
  id?: string;
  exists?: boolean;
  storage_provider?: string;
  storage_key?: string;
  file_name?: string;
  file_type?: string;
  size_bytes?: number;
}

interface GroupMessageSummary extends Record<string, unknown> {
  id?: string;
  session_id?: string;
  sender_id?: string;
  session_seq?: number;
  type?: string;
  content?: string;
  status?: string;
  created_at?: string;
  updated_at?: string;
}

interface GroupItem extends Record<string, unknown> {
  id: string;
  name?: string;
  owner_id?: string;
  owner?: GroupUserSummary;
  session_id?: string;
  session?: GroupSessionSummary;
  announcement?: string;
  announcement_message_id?: string | null;
  announcement_author_id?: string | null;
  announcement_published_at?: string | null;
  announcement_message?: GroupMessageSummary | null;
  avatar_kind?: string;
  avatar_file_id?: string | null;
  avatar_file?: GroupFileSummary | null;
  avatar_version?: number;
  member_count?: number;
  session_member_count?: number;
  created_at?: string;
  updated_at?: string;
  members?: GroupMemberItem[];
}

interface GroupMemberItem extends Record<string, unknown> {
  group_id?: string;
  user_id?: string;
  user?: GroupUserSummary;
  role?: string;
  group_nickname?: string;
  note?: string;
  joined_at?: string;
  session_member?: {
    exists?: boolean;
    last_read_seq?: number;
    last_read_message_id?: string;
    last_read_at?: string | null;
  };
}

interface GroupListPayload {
  total: number;
  page: number;
  size: number;
  items: GroupItem[];
}

interface GroupMemberListPayload {
  total: number;
  page: number;
  size: number;
  group?: Record<string, unknown>;
  items: GroupMemberItem[];
}

interface GroupFilters {
  keyword: string;
  owner_id: string;
}

interface GroupMemberFilters {
  role: string;
  user_id: string;
}

interface MomentUserSummary extends Record<string, unknown> {
  id?: string;
  username?: string;
  nickname?: string;
  exists?: boolean;
  is_disabled?: boolean;
}

interface MomentItem extends Record<string, unknown> {
  id: string;
  user_id?: string;
  author?: MomentUserSummary;
  content?: string;
  comment_count?: number;
  like_count?: number;
  created_at?: string;
  updated_at?: string;
}

interface MomentCommentItem extends Record<string, unknown> {
  id: string;
  moment_id?: string;
  user_id?: string;
  user?: MomentUserSummary;
  content?: string;
  created_at?: string;
  updated_at?: string;
}

interface MomentLikeItem extends Record<string, unknown> {
  moment_id?: string;
  user_id?: string;
  user?: MomentUserSummary;
  created_at?: string;
  updated_at?: string;
}

interface MomentListPayload {
  total: number;
  page: number;
  size: number;
  items: MomentItem[];
}

interface MomentCommentListPayload {
  total: number;
  page: number;
  size: number;
  moment?: Record<string, unknown>;
  items: MomentCommentItem[];
}

interface MomentLikeListPayload {
  total: number;
  page: number;
  size: number;
  moment?: Record<string, unknown>;
  items: MomentLikeItem[];
}

interface MomentFilters {
  keyword: string;
  user_id: string;
}

interface MomentUserFilters {
  user_id: string;
}

interface SessionState {
  baseUrl: string;
  token: string;
}

const navItems: Array<{ key: PageKey; label: string; icon: ReactNode }> = [
  { key: "overview", label: "概览", icon: <LayoutDashboard size={18} /> },
  { key: "health", label: "巡检", icon: <Activity size={18} /> },
  { key: "audit", label: "审计", icon: <ClipboardList size={18} /> },
  { key: "chat", label: "聊天", icon: <MessageSquare size={18} /> },
  { key: "contacts", label: "联系人", icon: <Users size={18} /> },
  { key: "groups", label: "群组", icon: <Users size={18} /> },
  { key: "moments", label: "朋友圈", icon: <Heart size={18} /> },
  { key: "users", label: "用户", icon: <Users size={18} /> },
  { key: "database", label: "数据库", icon: <Database size={18} /> },
  { key: "files", label: "文件", icon: <HardDrive size={18} /> },
  { key: "backups", label: "备份", icon: <Archive size={18} /> },
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

const defaultBackupPruneForm: BackupPruneForm = {
  keep_last: "",
  older_than_days: "",
  include_failed: false,
  include_deleted: false
};

const defaultLogFilters: LogFilters = {
  file_name: "",
  level: "",
  keyword: "",
  created_from: "",
  created_to: "",
  limit: "100"
};

const defaultChatFilters: ChatFilters = {
  type: "",
  keyword: "",
  user_id: ""
};

const defaultChatMessageFilters: ChatMessageFilters = {
  type: ""
};

const defaultContactRequestFilters: ContactRequestFilters = {
  status: "",
  sender_id: "",
  receiver_id: ""
};

const defaultContactFriendshipFilters: ContactFriendshipFilters = {
  user_id: "",
  friend_id: ""
};

const defaultGroupFilters: GroupFilters = {
  keyword: "",
  owner_id: ""
};

const defaultGroupMemberFilters: GroupMemberFilters = {
  role: "",
  user_id: ""
};

const defaultMomentFilters: MomentFilters = {
  keyword: "",
  user_id: ""
};

const defaultMomentUserFilters: MomentUserFilters = {
  user_id: ""
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
  const [fileStorageStatus, setFileStorageStatus] = useState<FileStorageStatusPayload | null>(null);
  const [fileStorageIssues, setFileStorageIssues] = useState<FileStorageIssuesPayload | null>(null);
  const [fileStorageIssueType, setFileStorageIssueType] = useState("");
  const [logFiles, setLogFiles] = useState<LogFilesPayload | null>(null);
  const [logEntries, setLogEntries] = useState<LogQueryPayload | null>(null);
  const [logFilters, setLogFilters] = useState<LogFilters>(defaultLogFilters);
  const [logDownloadStatus, setLogDownloadStatus] = useState("");
  const [healthReports, setHealthReports] = useState<HealthModuleReport[] | null>(null);
  const [healthRefreshedAt, setHealthRefreshedAt] = useState("");
  const [expandedHealthModules, setExpandedHealthModules] = useState<Record<string, boolean>>({});
  const [auditLogs, setAuditLogs] = useState<AuditLogListPayload | null>(null);
  const [auditFilters, setAuditFilters] = useState<AuditFilters>(defaultAuditFilters);
  const [selectedAuditLog, setSelectedAuditLog] = useState<AuditLogItem | null>(null);
  const [auditDetailLoading, setAuditDetailLoading] = useState(false);
  const [chatSessions, setChatSessions] = useState<ChatSessionListPayload | null>(null);
  const [chatFilters, setChatFilters] = useState<ChatFilters>(defaultChatFilters);
  const [selectedChatSession, setSelectedChatSession] = useState<ChatSessionDetailPayload | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessageListPayload | null>(null);
  const [chatMessageFilters, setChatMessageFilters] = useState<ChatMessageFilters>(defaultChatMessageFilters);
  const [chatDetailLoading, setChatDetailLoading] = useState(false);
  const [contactFriendRequests, setContactFriendRequests] = useState<ContactFriendRequestListPayload | null>(null);
  const [contactFriendships, setContactFriendships] = useState<ContactFriendshipListPayload | null>(null);
  const [contactRequestFilters, setContactRequestFilters] =
    useState<ContactRequestFilters>(defaultContactRequestFilters);
  const [contactFriendshipFilters, setContactFriendshipFilters] =
    useState<ContactFriendshipFilters>(defaultContactFriendshipFilters);
  const [groups, setGroups] = useState<GroupListPayload | null>(null);
  const [groupFilters, setGroupFilters] = useState<GroupFilters>(defaultGroupFilters);
  const [selectedGroup, setSelectedGroup] = useState<GroupItem | null>(null);
  const [groupMembers, setGroupMembers] = useState<GroupMemberListPayload | null>(null);
  const [groupMemberFilters, setGroupMemberFilters] = useState<GroupMemberFilters>(defaultGroupMemberFilters);
  const [groupDetailLoading, setGroupDetailLoading] = useState(false);
  const [moments, setMoments] = useState<MomentListPayload | null>(null);
  const [momentFilters, setMomentFilters] = useState<MomentFilters>(defaultMomentFilters);
  const [selectedMoment, setSelectedMoment] = useState<MomentItem | null>(null);
  const [momentComments, setMomentComments] = useState<MomentCommentListPayload | null>(null);
  const [momentLikes, setMomentLikes] = useState<MomentLikeListPayload | null>(null);
  const [momentCommentFilters, setMomentCommentFilters] = useState<MomentUserFilters>(defaultMomentUserFilters);
  const [momentLikeFilters, setMomentLikeFilters] = useState<MomentUserFilters>(defaultMomentUserFilters);
  const [momentDetailLoading, setMomentDetailLoading] = useState(false);
  const [selectedUser, setSelectedUser] = useState<UserDetailPayload | null>(null);
  const [disableReason, setDisableReason] = useState("");
  const [userOperationLoading, setUserOperationLoading] = useState(false);
  const [databaseBackups, setDatabaseBackups] = useState<DatabaseBackupListPayload | null>(null);
  const [selectedBackup, setSelectedBackup] = useState<DatabaseBackupItem | null>(null);
  const [backupOperationLoading, setBackupOperationLoading] = useState(false);
  const [backupPruneForm, setBackupPruneForm] = useState<BackupPruneForm>(defaultBackupPruneForm);
  const [backupPruneResult, setBackupPruneResult] = useState<DatabaseBackupPruneResult | null>(null);
  const [backupDownloadUrl, setBackupDownloadUrl] = useState("");
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
      (page === "chat" && !chatSessions) ||
      (page === "contacts" && (!contactFriendRequests || !contactFriendships)) ||
      (page === "groups" && !groups) ||
      (page === "moments" && !moments) ||
      (page === "users" && !users) ||
      (page === "database" && !databaseStatus) ||
      (page === "files" && (!fileStorageStatus || !fileStorageIssues)) ||
      (page === "backups" && !databaseBackups) ||
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
      if (page === "chat" && !chatSessions) {
        setChatSessions(await loadChatSessions(client, chatFilters));
      }
      if (page === "contacts" && (!contactFriendRequests || !contactFriendships)) {
        const payload = await loadContactData(client, contactRequestFilters, contactFriendshipFilters);
        setContactFriendRequests(payload.requests);
        setContactFriendships(payload.friendships);
      }
      if (page === "groups" && !groups) {
        setGroups(await loadGroups(client, groupFilters));
      }
      if (page === "moments" && !moments) {
        setMoments(await loadMoments(client, momentFilters));
      }
      if (page === "users" && !users) {
        setUsers(await loadUsers(client, keyword));
      }
      if (page === "database" && !databaseStatus) {
        setDatabaseStatus(await client.getDatabaseStatus<DatabaseStatusPayload>());
      }
      if (page === "files" && (!fileStorageStatus || !fileStorageIssues)) {
        const payload = await loadFileStorageInspection(client);
        setFileStorageStatus(payload.status);
        setFileStorageIssues(payload.issues);
      }
      if (page === "backups" && !databaseBackups) {
        setDatabaseBackups(await loadDatabaseBackups(client));
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
      if (activePage === "chat") {
        setChatSessions(await loadChatSessions(client, chatFilters));
        setSelectedChatSession(null);
        setChatMessages(null);
      }
      if (activePage === "contacts") {
        const payload = await loadContactData(client, contactRequestFilters, contactFriendshipFilters);
        setContactFriendRequests(payload.requests);
        setContactFriendships(payload.friendships);
      }
      if (activePage === "groups") {
        setGroups(await loadGroups(client, groupFilters));
        setSelectedGroup(null);
        setGroupMembers(null);
      }
      if (activePage === "moments") {
        setMoments(await loadMoments(client, momentFilters));
        setSelectedMoment(null);
        setMomentComments(null);
        setMomentLikes(null);
      }
      if (activePage === "users") {
        setUsers(await loadUsers(client, keyword));
      }
      if (activePage === "database") {
        setDatabaseStatus(await client.getDatabaseStatus<DatabaseStatusPayload>());
      }
      if (activePage === "files") {
        const payload = await loadFileStorageInspection(client);
        setFileStorageStatus(payload.status);
        setFileStorageIssues(payload.issues);
      }
      if (activePage === "backups") {
        setDatabaseBackups(await loadDatabaseBackups(client));
        setSelectedBackup(null);
        setBackupPruneResult(null);
        setBackupDownloadUrl("");
      }
      if (activePage === "logs") {
        setLogFiles(await client.listLogFiles<LogFilesPayload>());
        if (logEntries) {
          setLogEntries(await loadLogEntries(client, logFilters));
        }
        setLogDownloadStatus("");
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

  async function searchChatSessions() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setChatSessions(await loadChatSessions(client, chatFilters));
      setSelectedChatSession(null);
      setChatMessages(null);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function openChatSession(sessionId: string) {
    if (!client) {
      return;
    }
    setChatDetailLoading(true);
    setError("");
    try {
      const [detail, messages] = await Promise.all([
        client.getChatSession<ChatSessionDetailPayload>(sessionId),
        loadChatMessages(client, sessionId, chatMessageFilters)
      ]);
      setSelectedChatSession(detail);
      setChatMessages(messages);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setChatDetailLoading(false);
    }
  }

  async function searchChatMessages() {
    if (!client || !selectedChatSession) {
      return;
    }
    setChatDetailLoading(true);
    setError("");
    try {
      setChatMessages(await loadChatMessages(client, selectedChatSession.id, chatMessageFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setChatDetailLoading(false);
    }
  }

  async function searchContactFriendRequests() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setContactFriendRequests(await loadContactFriendRequests(client, contactRequestFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function searchContactFriendships() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setContactFriendships(await loadContactFriendships(client, contactFriendshipFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function searchGroups() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setGroups(await loadGroups(client, groupFilters));
      setSelectedGroup(null);
      setGroupMembers(null);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function openGroupDetail(groupId: string) {
    if (!client) {
      return;
    }
    setGroupDetailLoading(true);
    setError("");
    try {
      const [detail, members] = await Promise.all([
        client.getGroup<GroupItem>(groupId),
        loadGroupMembers(client, groupId, groupMemberFilters)
      ]);
      setSelectedGroup(detail);
      setGroupMembers(members);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setGroupDetailLoading(false);
    }
  }

  async function searchGroupMembers() {
    if (!client || !selectedGroup) {
      return;
    }
    setGroupDetailLoading(true);
    setError("");
    try {
      setGroupMembers(await loadGroupMembers(client, selectedGroup.id, groupMemberFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setGroupDetailLoading(false);
    }
  }

  async function searchMoments() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setMoments(await loadMoments(client, momentFilters));
      setSelectedMoment(null);
      setMomentComments(null);
      setMomentLikes(null);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function openMomentDetail(momentId: string) {
    if (!client) {
      return;
    }
    setMomentDetailLoading(true);
    setError("");
    try {
      const [detail, comments, likes] = await Promise.all([
        client.getMoment<MomentItem>(momentId),
        loadMomentComments(client, momentId, momentCommentFilters),
        loadMomentLikes(client, momentId, momentLikeFilters)
      ]);
      setSelectedMoment(detail);
      setMomentComments(comments);
      setMomentLikes(likes);
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setMomentDetailLoading(false);
    }
  }

  async function searchMomentComments() {
    if (!client || !selectedMoment) {
      return;
    }
    setMomentDetailLoading(true);
    setError("");
    try {
      setMomentComments(await loadMomentComments(client, selectedMoment.id, momentCommentFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setMomentDetailLoading(false);
    }
  }

  async function searchMomentLikes() {
    if (!client || !selectedMoment) {
      return;
    }
    setMomentDetailLoading(true);
    setError("");
    try {
      setMomentLikes(await loadMomentLikes(client, selectedMoment.id, momentLikeFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setMomentDetailLoading(false);
    }
  }

  async function openUserDetail(userId: string) {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    try {
      setSelectedUser(await client.getUserDetail<UserDetailPayload>(userId));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function runUserOperation(operation: "role" | "disable" | "enable" | "forceLogout", role?: string) {
    if (!client || !selectedUser) {
      return;
    }
    const userId = selectedUser.id;
    const username = String(selectedUser.username ?? selectedUser.display_name ?? userId);
    const message = userOperationConfirmMessage(operation, username, role);
    if (!window.confirm(message)) {
      return;
    }
    setUserOperationLoading(true);
    setError("");
    try {
      if (operation === "role" && role) {
        setSelectedUser(mergeUserDetail(selectedUser, await client.setUserRole<UserDetailPayload>(userId, role)));
      }
      if (operation === "disable") {
        setSelectedUser(
          mergeUserDetail(selectedUser, await client.disableUser<UserDetailPayload>(userId, disableReason))
        );
      }
      if (operation === "enable") {
        setSelectedUser(mergeUserDetail(selectedUser, await client.enableUser<UserDetailPayload>(userId)));
      }
      if (operation === "forceLogout") {
        await client.forceLogoutUser(userId);
        setSelectedUser(await client.getUserDetail<UserDetailPayload>(userId));
      }
      setUsers(await loadUsers(client, keyword));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setUserOperationLoading(false);
    }
  }

  async function createBackup() {
    if (!client || !window.confirm("确认现在创建数据库备份？该操作会在服务端本地写入备份文件。")) {
      return;
    }
    setBackupOperationLoading(true);
    setError("");
    try {
      const backup = await client.createDatabaseBackup<DatabaseBackupItem>();
      setSelectedBackup(backup);
      setDatabaseBackups(await loadDatabaseBackups(client));
      setBackupDownloadUrl("");
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setBackupOperationLoading(false);
    }
  }

  async function openBackupDetail(backupId: string) {
    if (!client) {
      return;
    }
    setBackupOperationLoading(true);
    setError("");
    try {
      setSelectedBackup(await client.getDatabaseBackup<DatabaseBackupItem>(backupId));
      setBackupDownloadUrl("");
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setBackupOperationLoading(false);
    }
  }

  async function verifyBackup(backupId: string) {
    if (!client || !window.confirm("确认验证该数据库备份？验证会读取服务端备份文件但不会恢复数据库。")) {
      return;
    }
    setBackupOperationLoading(true);
    setError("");
    try {
      setSelectedBackup(await client.verifyDatabaseBackup<DatabaseBackupItem>(backupId));
      setDatabaseBackups(await loadDatabaseBackups(client));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setBackupOperationLoading(false);
    }
  }

  async function deleteBackup(backupId: string) {
    if (!client || !window.confirm("确认删除该数据库备份？这会删除服务端本地备份文件并标记记录为 deleted。")) {
      return;
    }
    setBackupOperationLoading(true);
    setError("");
    try {
      setSelectedBackup(await client.deleteDatabaseBackup<DatabaseBackupItem>(backupId));
      setDatabaseBackups(await loadDatabaseBackups(client));
      setBackupDownloadUrl("");
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setBackupOperationLoading(false);
    }
  }

  async function pruneBackups(dryRun: boolean) {
    if (!client) {
      return;
    }
    const params = backupPruneParams(backupPruneForm, dryRun);
    if (params.keep_last === undefined && params.older_than_days === undefined) {
      setError("清理条件需要填写保留最近或早于天数");
      return;
    }
    if (!dryRun && !window.confirm("确认执行数据库备份清理？该操作会删除符合条件的服务端本地备份文件。")) {
      return;
    }
    setBackupOperationLoading(true);
    setError("");
    try {
      setBackupPruneResult(await client.pruneDatabaseBackups<DatabaseBackupPruneResult>(params));
      if (!dryRun) {
        setDatabaseBackups(await loadDatabaseBackups(client));
      }
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setBackupOperationLoading(false);
    }
  }

  function showBackupDownloadUrl(backupId: string) {
    if (!client) {
      return;
    }
    setBackupDownloadUrl(client.getDatabaseBackupDownloadUrl(backupId));
  }

  async function searchLogs() {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    setLogDownloadStatus("");
    try {
      setLogEntries(await loadLogEntries(client, logFilters));
    } catch (currentError) {
      setError(readableError(currentError));
    } finally {
      setLoading(false);
    }
  }

  async function downloadLogFile(fileName: string) {
    if (!client) {
      return;
    }
    setLoading(true);
    setError("");
    setLogDownloadStatus("");
    try {
      const content = await client.downloadLogFile(fileName);
      triggerTextDownload(fileName, content);
      setLogDownloadStatus(`已下载 ${fileName}`);
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
        {activePage === "chat" ? (
          <ChatPage
            payload={chatSessions}
            filters={chatFilters}
            setFilter={(key, value) => setChatFilters((current) => ({ ...current, [key]: value }))}
            search={() => void searchChatSessions()}
            selectedSession={selectedChatSession}
            messages={chatMessages}
            messageFilters={chatMessageFilters}
            setMessageFilter={(key, value) => setChatMessageFilters((current) => ({ ...current, [key]: value }))}
            detailLoading={chatDetailLoading}
            openSession={(sessionId) => void openChatSession(sessionId)}
            searchMessages={() => void searchChatMessages()}
          />
        ) : null}
        {activePage === "contacts" ? (
          <ContactsPage
            requests={contactFriendRequests}
            friendships={contactFriendships}
            requestFilters={contactRequestFilters}
            friendshipFilters={contactFriendshipFilters}
            setRequestFilter={(key, value) => setContactRequestFilters((current) => ({ ...current, [key]: value }))}
            setFriendshipFilter={(key, value) =>
              setContactFriendshipFilters((current) => ({ ...current, [key]: value }))
            }
            searchRequests={() => void searchContactFriendRequests()}
            searchFriendships={() => void searchContactFriendships()}
          />
        ) : null}
        {activePage === "groups" ? (
          <GroupsPage
            payload={groups}
            filters={groupFilters}
            setFilter={(key, value) => setGroupFilters((current) => ({ ...current, [key]: value }))}
            search={() => void searchGroups()}
            selectedGroup={selectedGroup}
            members={groupMembers}
            memberFilters={groupMemberFilters}
            setMemberFilter={(key, value) => setGroupMemberFilters((current) => ({ ...current, [key]: value }))}
            detailLoading={groupDetailLoading}
            openGroup={(groupId) => void openGroupDetail(groupId)}
            searchMembers={() => void searchGroupMembers()}
          />
        ) : null}
        {activePage === "moments" ? (
          <MomentsPage
            payload={moments}
            filters={momentFilters}
            setFilter={(key, value) => setMomentFilters((current) => ({ ...current, [key]: value }))}
            search={() => void searchMoments()}
            selectedMoment={selectedMoment}
            comments={momentComments}
            likes={momentLikes}
            commentFilters={momentCommentFilters}
            likeFilters={momentLikeFilters}
            setCommentFilter={(key, value) => setMomentCommentFilters((current) => ({ ...current, [key]: value }))}
            setLikeFilter={(key, value) => setMomentLikeFilters((current) => ({ ...current, [key]: value }))}
            detailLoading={momentDetailLoading}
            openMoment={(momentId) => void openMomentDetail(momentId)}
            searchComments={() => void searchMomentComments()}
            searchLikes={() => void searchMomentLikes()}
          />
        ) : null}
        {activePage === "users" ? (
          <UsersPage
            payload={users}
            keyword={keyword}
            setKeyword={setKeyword}
            search={() => void refreshPage()}
            selectedUser={selectedUser}
            disableReason={disableReason}
            setDisableReason={setDisableReason}
            operationLoading={userOperationLoading}
            openUserDetail={(userId) => void openUserDetail(userId)}
            runUserOperation={(operation, role) => void runUserOperation(operation, role)}
          />
        ) : null}
        {activePage === "database" ? <DatabasePage payload={databaseStatus} /> : null}
        {activePage === "files" ? (
          <FilesPage
            status={fileStorageStatus}
            issues={fileStorageIssues}
            issueType={fileStorageIssueType}
            setIssueType={setFileStorageIssueType}
          />
        ) : null}
        {activePage === "backups" ? (
          <BackupsPage
            payload={databaseBackups}
            selectedBackup={selectedBackup}
            pruneForm={backupPruneForm}
            setPruneForm={(patch) => setBackupPruneForm((current) => ({ ...current, ...patch }))}
            pruneResult={backupPruneResult}
            downloadUrl={backupDownloadUrl}
            operationLoading={backupOperationLoading}
            createBackup={() => void createBackup()}
            openBackupDetail={(backupId) => void openBackupDetail(backupId)}
            verifyBackup={(backupId) => void verifyBackup(backupId)}
            deleteBackup={(backupId) => void deleteBackup(backupId)}
            pruneBackups={(dryRun) => void pruneBackups(dryRun)}
            showDownloadUrl={showBackupDownloadUrl}
          />
        ) : null}
        {activePage === "logs" ? (
          <LogsPage
            payload={logFiles}
            entries={logEntries}
            filters={logFilters}
            setFilter={(key, value) => setLogFilters((current) => ({ ...current, [key]: value }))}
            search={() => void searchLogs()}
            downloadStatus={logDownloadStatus}
            downloadLogFile={(fileName) => void downloadLogFile(fileName)}
          />
        ) : null}
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

function ChatPage({
  payload,
  filters,
  setFilter,
  search,
  selectedSession,
  messages,
  messageFilters,
  setMessageFilter,
  detailLoading,
  openSession,
  searchMessages
}: {
  payload: ChatSessionListPayload | null;
  filters: ChatFilters;
  setFilter: (key: keyof ChatFilters, value: string) => void;
  search: () => void;
  selectedSession: ChatSessionDetailPayload | null;
  messages: ChatMessageListPayload | null;
  messageFilters: ChatMessageFilters;
  setMessageFilter: (key: keyof ChatMessageFilters, value: string) => void;
  detailLoading: boolean;
  openSession: (sessionId: string) => void;
  searchMessages: () => void;
}) {
  const sessions = payload?.items ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    search();
  }

  return (
    <section className="page-section">
      <PageTitle title="聊天" subtitle={`共 ${payload?.total ?? 0} 个会话`} />
      <form className="filter-panel" onSubmit={submit}>
        <label>
          <span>会话类型</span>
          <select value={filters.type} onChange={(event) => setFilter("type", event.target.value)}>
            <option value="">全部</option>
            <option value="private">private</option>
            <option value="group">group</option>
          </select>
        </label>
        <label>
          <span>会话关键词</span>
          <input
            value={filters.keyword}
            onChange={(event) => setFilter("keyword", event.target.value)}
            placeholder="会话名或会话 ID"
          />
        </label>
        <label>
          <span>成员用户 ID</span>
          <input
            value={filters.user_id}
            onChange={(event) => setFilter("user_id", event.target.value)}
            placeholder="user id"
          />
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          筛选会话
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>会话 ID</th>
              <th>类型</th>
              <th>名称</th>
              <th>加密</th>
              <th>成员</th>
              <th>消息</th>
              <th>最后消息序号</th>
              <th>更新时间</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session) => (
              <tr key={session.id}>
                <td>{session.id}</td>
                <td>{String(session.type ?? "")}</td>
                <td>{String(session.name ?? "")}</td>
                <td>{String(session.encryption_mode ?? "")}</td>
                <td>{displayValue(session.member_count)}</td>
                <td>{displayValue(session.message_count)}</td>
                <td>{displayValue(session.last_message_seq)}</td>
                <td>{String(session.updated_at ?? "")}</td>
                <td>
                  <button
                    className="table-action-button"
                    type="button"
                    onClick={() => openSession(session.id)}
                    aria-label="查看会话详情"
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detailLoading ? <p className="empty-text">正在读取会话详情...</p> : null}
      {selectedSession ? (
        <ChatSessionDetailPanel
          session={selectedSession}
          messages={messages}
          messageFilters={messageFilters}
          setMessageFilter={setMessageFilter}
          searchMessages={searchMessages}
        />
      ) : null}
    </section>
  );
}

function ChatSessionDetailPanel({
  session,
  messages,
  messageFilters,
  setMessageFilter,
  searchMessages
}: {
  session: ChatSessionDetailPayload;
  messages: ChatMessageListPayload | null;
  messageFilters: ChatMessageFilters;
  setMessageFilter: (key: keyof ChatMessageFilters, value: string) => void;
  searchMessages: () => void;
}) {
  const members = session.members ?? [];
  const messageItems = messages?.items ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchMessages();
  }

  return (
    <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{String(session.name || session.id)}</h2>
          <p>{session.id}</p>
        </div>
        <span className="status-badge ok">{String(session.type ?? "")}</span>
      </div>
      <div className="info-grid">
        <InfoBlock title="会话" rows={[
          ["类型", session.type],
          ["加密模式", session.encryption_mode],
          ["成员数", session.member_count],
          ["消息数", session.message_count],
          ["最后消息序号", session.last_message_seq],
          ["最后事件序号", session.last_event_seq]
        ]} />
        <InfoBlock title="最后消息" rows={[
          ["消息 ID", session.last_message?.id],
          ["类型", session.last_message?.type],
          ["发送人", session.last_message?.sender_username || session.last_message?.sender_id],
          ["状态", session.last_message?.status],
          ["时间", session.last_message?.created_at],
          ["内容", session.last_message?.content]
        ]} />
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户 ID</th>
              <th>用户名</th>
              <th>昵称</th>
              <th>最后已读序号</th>
              <th>最后已读消息</th>
              <th>最后已读时间</th>
            </tr>
          </thead>
          <tbody>
            {members.map((member) => (
              <tr key={String(member.user_id)}>
                <td>{String(member.user_id ?? "")}</td>
                <td>{String(member.username ?? "")}</td>
                <td>{String(member.nickname ?? "")}</td>
                <td>{displayValue(member.last_read_seq)}</td>
                <td>{String(member.last_read_message_id ?? "")}</td>
                <td>{String(member.last_read_at ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="filter-panel" onSubmit={submit}>
        <label>
          <span>消息类型</span>
          <select value={messageFilters.type} onChange={(event) => setMessageFilter("type", event.target.value)}>
            <option value="">全部</option>
            <option value="text">text</option>
            <option value="image">image</option>
            <option value="file">file</option>
            <option value="voice">voice</option>
            <option value="system">system</option>
          </select>
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          查询消息
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Seq</th>
              <th>类型</th>
              <th>发送人</th>
              <th>状态</th>
              <th>时间</th>
              <th>内容</th>
            </tr>
          </thead>
          <tbody>
            {messageItems.map((message) => (
              <tr key={message.id}>
                <td>{displayValue(message.session_seq)}</td>
                <td>{String(message.type ?? "")}</td>
                <td>{String(message.sender_username || message.sender_nickname || message.sender_id || "")}</td>
                <td>{String(message.status ?? "")}</td>
                <td>{String(message.created_at ?? "")}</td>
                <td className="message-cell">{String(message.content ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {messages ? <p className="empty-text">{`匹配 ${messages.total ?? messageItems.length} 条消息`}</p> : null}
    </article>
  );
}

function ContactsPage({
  requests,
  friendships,
  requestFilters,
  friendshipFilters,
  setRequestFilter,
  setFriendshipFilter,
  searchRequests,
  searchFriendships
}: {
  requests: ContactFriendRequestListPayload | null;
  friendships: ContactFriendshipListPayload | null;
  requestFilters: ContactRequestFilters;
  friendshipFilters: ContactFriendshipFilters;
  setRequestFilter: (key: keyof ContactRequestFilters, value: string) => void;
  setFriendshipFilter: (key: keyof ContactFriendshipFilters, value: string) => void;
  searchRequests: () => void;
  searchFriendships: () => void;
}) {
  const requestItems = requests?.items ?? [];
  const friendshipItems = friendships?.items ?? [];

  function submitRequests(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchRequests();
  }

  function submitFriendships(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchFriendships();
  }

  return (
    <section className="page-section">
      <PageTitle
        title="联系人"
        subtitle={`请求 ${requests?.total ?? 0} 条 · 关系 ${friendships?.total ?? 0} 条`}
      />
      <article className="detail-panel">
        <div className="detail-header">
          <div>
            <h2>好友请求</h2>
            <p>查看用户之间的好友申请记录</p>
          </div>
        </div>
        <form className="filter-panel" onSubmit={submitRequests}>
          <label>
            <span>请求状态</span>
            <select value={requestFilters.status} onChange={(event) => setRequestFilter("status", event.target.value)}>
              <option value="">全部</option>
              <option value="pending">待处理</option>
              <option value="accepted">已接受</option>
              <option value="rejected">已拒绝</option>
              <option value="cancelled">已取消</option>
            </select>
          </label>
          <label>
            <span>发送人 ID</span>
            <input
              value={requestFilters.sender_id}
              onChange={(event) => setRequestFilter("sender_id", event.target.value)}
              placeholder="sender user id"
            />
          </label>
          <label>
            <span>接收人 ID</span>
            <input
              value={requestFilters.receiver_id}
              onChange={(event) => setRequestFilter("receiver_id", event.target.value)}
              placeholder="receiver user id"
            />
          </label>
          <button className="secondary-button" type="submit">
            <Search size={17} />
            查询请求
          </button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>状态</th>
                <th>发送人</th>
                <th>发送人 ID</th>
                <th>接收人</th>
                <th>接收人 ID</th>
                <th>附言</th>
                <th>创建时间</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {requestItems.map((request) => (
                <tr key={request.id}>
                  <td>
                    <span className={`status-badge ${contactStatusTone(request.status)}`}>
                      {String(request.status ?? "")}
                    </span>
                  </td>
                  <td>{contactUserName(request.sender, request.sender_id)}</td>
                  <td>{String(request.sender_id ?? request.sender?.id ?? "")}</td>
                  <td>{contactUserName(request.receiver, request.receiver_id)}</td>
                  <td>{String(request.receiver_id ?? request.receiver?.id ?? "")}</td>
                  <td className="message-cell">{String(request.message ?? "")}</td>
                  <td>{String(request.created_at ?? "")}</td>
                  <td>{String(request.updated_at ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!requestItems.length ? <p className="empty-text">暂无好友请求</p> : null}
      </article>
      <article className="detail-panel">
        <div className="detail-header">
          <div>
            <h2>好友关系</h2>
            <p>查看已建立的用户好友关系</p>
          </div>
        </div>
        <form className="filter-panel" onSubmit={submitFriendships}>
          <label>
            <span>用户 ID</span>
            <input
              value={friendshipFilters.user_id}
              onChange={(event) => setFriendshipFilter("user_id", event.target.value)}
              placeholder="user id"
            />
          </label>
          <label>
            <span>好友 ID</span>
            <input
              value={friendshipFilters.friend_id}
              onChange={(event) => setFriendshipFilter("friend_id", event.target.value)}
              placeholder="friend id"
            />
          </label>
          <button className="secondary-button" type="submit">
            <Search size={17} />
            查询关系
          </button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>用户 ID</th>
                <th>好友</th>
                <th>好友 ID</th>
                <th>创建时间</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {friendshipItems.map((friendship) => (
                <tr key={friendship.id}>
                  <td>{contactUserName(friendship.user, friendship.user_id)}</td>
                  <td>{String(friendship.user_id ?? friendship.user?.id ?? "")}</td>
                  <td>{contactUserName(friendship.friend, friendship.friend_id)}</td>
                  <td>{String(friendship.friend_id ?? friendship.friend?.id ?? "")}</td>
                  <td>{String(friendship.created_at ?? "")}</td>
                  <td>{String(friendship.updated_at ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!friendshipItems.length ? <p className="empty-text">暂无好友关系</p> : null}
      </article>
    </section>
  );
}

function GroupsPage({
  payload,
  filters,
  setFilter,
  search,
  selectedGroup,
  members,
  memberFilters,
  setMemberFilter,
  detailLoading,
  openGroup,
  searchMembers
}: {
  payload: GroupListPayload | null;
  filters: GroupFilters;
  setFilter: (key: keyof GroupFilters, value: string) => void;
  search: () => void;
  selectedGroup: GroupItem | null;
  members: GroupMemberListPayload | null;
  memberFilters: GroupMemberFilters;
  setMemberFilter: (key: keyof GroupMemberFilters, value: string) => void;
  detailLoading: boolean;
  openGroup: (groupId: string) => void;
  searchMembers: () => void;
}) {
  const items = payload?.items ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    search();
  }

  return (
    <section className="page-section">
      <PageTitle title="群组" subtitle={`共 ${payload?.total ?? 0} 个群组`} />
      <form className="filter-panel" onSubmit={submit}>
        <label>
          <span>群关键词</span>
          <input
            value={filters.keyword}
            onChange={(event) => setFilter("keyword", event.target.value)}
            placeholder="群名、群 ID 或会话 ID"
          />
        </label>
        <label>
          <span>群主 ID</span>
          <input
            value={filters.owner_id}
            onChange={(event) => setFilter("owner_id", event.target.value)}
            placeholder="owner user id"
          />
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          筛选群组
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>群名</th>
              <th>群主</th>
              <th>群主 ID</th>
              <th>会话 ID</th>
              <th>成员</th>
              <th>会话成员</th>
              <th>头像类型</th>
              <th>公告</th>
              <th>更新时间</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {items.map((group) => (
              <tr key={group.id}>
                <td>{String(group.name ?? "")}</td>
                <td>{groupUserName(group.owner, group.owner_id)}</td>
                <td>{String(group.owner_id ?? group.owner?.id ?? "")}</td>
                <td>{String(group.session_id ?? "")}</td>
                <td>{displayValue(group.member_count)}</td>
                <td>{displayValue(group.session_member_count)}</td>
                <td>{String(group.avatar_kind ?? "")}</td>
                <td className="message-cell">{String(group.announcement ?? "")}</td>
                <td>{String(group.updated_at ?? "")}</td>
                <td>
                  <button
                    className="table-action-button"
                    type="button"
                    onClick={() => openGroup(group.id)}
                    aria-label="查看群组详情"
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detailLoading ? <p className="empty-text">正在读取群组详情...</p> : null}
      {selectedGroup ? (
        <GroupDetailPanel
          group={selectedGroup}
          members={members}
          memberFilters={memberFilters}
          setMemberFilter={setMemberFilter}
          searchMembers={searchMembers}
        />
      ) : null}
    </section>
  );
}

function GroupDetailPanel({
  group,
  members,
  memberFilters,
  setMemberFilter,
  searchMembers
}: {
  group: GroupItem;
  members: GroupMemberListPayload | null;
  memberFilters: GroupMemberFilters;
  setMemberFilter: (key: keyof GroupMemberFilters, value: string) => void;
  searchMembers: () => void;
}) {
  const memberItems = members?.items ?? group.members ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchMembers();
  }

  return (
    <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{String(group.name || group.id)}</h2>
          <p>{group.id}</p>
        </div>
        <span className="status-badge ok">{String(group.session?.type ?? "group")}</span>
      </div>
      <div className="info-grid">
        <InfoBlock title="群组" rows={[
          ["群 ID", group.id],
          ["群主", groupUserName(group.owner, group.owner_id)],
          ["群主 ID", group.owner_id],
          ["会话 ID", group.session_id],
          ["成员数", group.member_count],
          ["会话成员数", group.session_member_count],
          ["创建时间", group.created_at],
          ["更新时间", group.updated_at]
        ]} />
        <InfoBlock title="会话" rows={[
          ["会话名称", group.session?.name],
          ["会话存在", boolLabel(group.session?.exists)],
          ["加密模式", group.session?.encryption_mode],
          ["最后消息序号", group.session?.last_message_seq],
          ["最后事件序号", group.session?.last_event_seq],
          ["AI 会话", boolLabel(group.session?.is_ai_session)]
        ]} />
        <InfoBlock title="头像" rows={[
          ["头像类型", group.avatar_kind],
          ["头像版本", group.avatar_version],
          ["文件 ID", group.avatar_file_id],
          ["文件名", group.avatar_file?.file_name],
          ["存储键", group.avatar_file?.storage_key],
          ["大小", formatBytes(group.avatar_file?.size_bytes)]
        ]} />
        <InfoBlock title="公告" rows={[
          ["公告", group.announcement],
          ["公告消息 ID", group.announcement_message_id],
          ["发布人 ID", group.announcement_author_id],
          ["发布时间", group.announcement_published_at],
          ["消息内容", group.announcement_message?.content],
          ["消息状态", group.announcement_message?.status]
        ]} />
      </div>
      <form className="filter-panel" onSubmit={submit}>
        <label>
          <span>成员角色</span>
          <select value={memberFilters.role} onChange={(event) => setMemberFilter("role", event.target.value)}>
            <option value="">全部</option>
            <option value="owner">owner</option>
            <option value="admin">admin</option>
            <option value="member">member</option>
          </select>
        </label>
        <label>
          <span>成员用户 ID</span>
          <input
            value={memberFilters.user_id}
            onChange={(event) => setMemberFilter("user_id", event.target.value)}
            placeholder="user id"
          />
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          查询成员
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>用户</th>
              <th>用户 ID</th>
              <th>角色</th>
              <th>群昵称</th>
              <th>备注</th>
              <th>入群时间</th>
              <th>会话成员</th>
              <th>已读序号</th>
              <th>最后已读消息</th>
            </tr>
          </thead>
          <tbody>
            {memberItems.map((member) => (
              <tr key={`${String(member.group_id ?? group.id)}-${String(member.user_id ?? "")}`}>
                <td>{groupUserName(member.user, member.user_id)}</td>
                <td>{String(member.user_id ?? member.user?.id ?? "")}</td>
                <td>{String(member.role ?? "")}</td>
                <td>{String(member.group_nickname ?? "")}</td>
                <td>{String(member.note ?? "")}</td>
                <td>{String(member.joined_at ?? "")}</td>
                <td>{boolLabel(member.session_member?.exists)}</td>
                <td>{displayValue(member.session_member?.last_read_seq)}</td>
                <td>{String(member.session_member?.last_read_message_id ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {members ? <p className="empty-text">{`匹配 ${members.total ?? memberItems.length} 个成员`}</p> : null}
    </article>
  );
}

function MomentsPage({
  payload,
  filters,
  setFilter,
  search,
  selectedMoment,
  comments,
  likes,
  commentFilters,
  likeFilters,
  setCommentFilter,
  setLikeFilter,
  detailLoading,
  openMoment,
  searchComments,
  searchLikes
}: {
  payload: MomentListPayload | null;
  filters: MomentFilters;
  setFilter: (key: keyof MomentFilters, value: string) => void;
  search: () => void;
  selectedMoment: MomentItem | null;
  comments: MomentCommentListPayload | null;
  likes: MomentLikeListPayload | null;
  commentFilters: MomentUserFilters;
  likeFilters: MomentUserFilters;
  setCommentFilter: (key: keyof MomentUserFilters, value: string) => void;
  setLikeFilter: (key: keyof MomentUserFilters, value: string) => void;
  detailLoading: boolean;
  openMoment: (momentId: string) => void;
  searchComments: () => void;
  searchLikes: () => void;
}) {
  const items = payload?.items ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    search();
  }

  return (
    <section className="page-section">
      <PageTitle title="朋友圈" subtitle={`共 ${payload?.total ?? 0} 条动态`} />
      <form className="filter-panel" onSubmit={submit}>
        <label>
          <span>动态关键词</span>
          <input
            value={filters.keyword}
            onChange={(event) => setFilter("keyword", event.target.value)}
            placeholder="内容、动态 ID 或发布人 ID"
          />
        </label>
        <label>
          <span>发布人 ID</span>
          <input
            value={filters.user_id}
            onChange={(event) => setFilter("user_id", event.target.value)}
            placeholder="user id"
          />
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          筛选动态
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>动态 ID</th>
              <th>发布人</th>
              <th>发布人 ID</th>
              <th>内容</th>
              <th>评论</th>
              <th>点赞</th>
              <th>创建时间</th>
              <th>更新时间</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {items.map((moment) => (
              <tr key={moment.id}>
                <td>{moment.id}</td>
                <td>{momentUserName(moment.author, moment.user_id)}</td>
                <td>{String(moment.user_id ?? moment.author?.id ?? "")}</td>
                <td className="message-cell">{String(moment.content ?? "")}</td>
                <td>{displayValue(moment.comment_count)}</td>
                <td>{displayValue(moment.like_count)}</td>
                <td>{String(moment.created_at ?? "")}</td>
                <td>{String(moment.updated_at ?? "")}</td>
                <td>
                  <button
                    className="table-action-button"
                    type="button"
                    onClick={() => openMoment(moment.id)}
                    aria-label="查看动态详情"
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detailLoading ? <p className="empty-text">正在读取动态详情...</p> : null}
      {selectedMoment ? (
        <MomentDetailPanel
          moment={selectedMoment}
          comments={comments}
          likes={likes}
          commentFilters={commentFilters}
          likeFilters={likeFilters}
          setCommentFilter={setCommentFilter}
          setLikeFilter={setLikeFilter}
          searchComments={searchComments}
          searchLikes={searchLikes}
        />
      ) : null}
    </section>
  );
}

function MomentDetailPanel({
  moment,
  comments,
  likes,
  commentFilters,
  likeFilters,
  setCommentFilter,
  setLikeFilter,
  searchComments,
  searchLikes
}: {
  moment: MomentItem;
  comments: MomentCommentListPayload | null;
  likes: MomentLikeListPayload | null;
  commentFilters: MomentUserFilters;
  likeFilters: MomentUserFilters;
  setCommentFilter: (key: keyof MomentUserFilters, value: string) => void;
  setLikeFilter: (key: keyof MomentUserFilters, value: string) => void;
  searchComments: () => void;
  searchLikes: () => void;
}) {
  const commentItems = comments?.items ?? [];
  const likeItems = likes?.items ?? [];

  function submitComments(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchComments();
  }

  function submitLikes(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    searchLikes();
  }

  return (
    <>
      <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{moment.id}</h2>
          <p>{String(moment.created_at ?? "")}</p>
        </div>
        <span className="status-badge ok">moment</span>
      </div>
      <div className="info-grid">
        <InfoBlock title="动态" rows={[
          ["动态 ID", moment.id],
          ["发布人", momentUserName(moment.author, moment.user_id)],
          ["发布人 ID", moment.user_id],
          ["内容", moment.content],
          ["评论数", moment.comment_count],
          ["点赞数", moment.like_count],
          ["创建时间", moment.created_at],
          ["更新时间", moment.updated_at]
        ]} />
        <InfoBlock title="作者" rows={[
          ["用户名", moment.author?.username],
          ["昵称", moment.author?.nickname],
          ["用户存在", boolLabel(moment.author?.exists)],
          ["账号禁用", boolLabel(moment.author?.is_disabled)]
        ]} />
      </div>
      </article>
      <article className="detail-panel">
        <div className="detail-header">
          <div>
            <h2>评论列表</h2>
            <p>{`共 ${comments?.total ?? 0} 条评论`}</p>
          </div>
        </div>
        <form className="filter-panel" onSubmit={submitComments}>
          <label>
            <span>评论用户 ID</span>
            <input
              value={commentFilters.user_id}
              onChange={(event) => setCommentFilter("user_id", event.target.value)}
              placeholder="user id"
            />
          </label>
          <button className="secondary-button" type="submit">
            <Search size={17} />
            查询评论
          </button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>评论 ID</th>
                <th>用户</th>
                <th>用户 ID</th>
                <th>内容</th>
                <th>创建时间</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {commentItems.map((comment) => (
                <tr key={comment.id}>
                  <td>{comment.id}</td>
                  <td>{momentUserName(comment.user, comment.user_id)}</td>
                  <td>{String(comment.user_id ?? comment.user?.id ?? "")}</td>
                  <td className="message-cell">{String(comment.content ?? "")}</td>
                  <td>{String(comment.created_at ?? "")}</td>
                  <td>{String(comment.updated_at ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
      <article className="detail-panel">
        <div className="detail-header">
          <div>
            <h2>点赞列表</h2>
            <p>{`共 ${likes?.total ?? 0} 个点赞`}</p>
          </div>
        </div>
        <form className="filter-panel" onSubmit={submitLikes}>
          <label>
            <span>点赞用户 ID</span>
            <input
              value={likeFilters.user_id}
              onChange={(event) => setLikeFilter("user_id", event.target.value)}
              placeholder="user id"
            />
          </label>
          <button className="secondary-button" type="submit">
            <Search size={17} />
            查询点赞
          </button>
        </form>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>用户</th>
                <th>用户 ID</th>
                <th>创建时间</th>
                <th>更新时间</th>
              </tr>
            </thead>
            <tbody>
              {likeItems.map((like) => (
                <tr key={`${String(like.moment_id ?? moment.id)}-${String(like.user_id ?? "")}`}>
                  <td>{momentUserName(like.user, like.user_id)}</td>
                  <td>{String(like.user_id ?? like.user?.id ?? "")}</td>
                  <td>{String(like.created_at ?? "")}</td>
                  <td>{String(like.updated_at ?? "")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </article>
    </>
  );
}

function UsersPage({
  payload,
  keyword,
  setKeyword,
  search,
  selectedUser,
  disableReason,
  setDisableReason,
  operationLoading,
  openUserDetail,
  runUserOperation
}: {
  payload: UserListPayload | null;
  keyword: string;
  setKeyword: (value: string) => void;
  search: () => void;
  selectedUser: UserDetailPayload | null;
  disableReason: string;
  setDisableReason: (value: string) => void;
  operationLoading: boolean;
  openUserDetail: (userId: string) => void;
  runUserOperation: (operation: "role" | "disable" | "enable" | "forceLogout", role?: string) => void;
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
              <th>详情</th>
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
                <td>
                  <button
                    className="table-action-button"
                    type="button"
                    onClick={() => openUserDetail(String(user.id ?? ""))}
                    aria-label={`查看 ${String(user.username ?? user.display_name ?? user.id)} 详情`}
                  >
                    查看
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selectedUser ? (
        <UserDetailPanel
          user={selectedUser}
          disableReason={disableReason}
          setDisableReason={setDisableReason}
          operationLoading={operationLoading}
          runUserOperation={runUserOperation}
        />
      ) : null}
    </section>
  );
}

function UserDetailPanel({
  user,
  disableReason,
  setDisableReason,
  operationLoading,
  runUserOperation
}: {
  user: UserDetailPayload;
  disableReason: string;
  setDisableReason: (value: string) => void;
  operationLoading: boolean;
  runUserOperation: (operation: "role" | "disable" | "enable" | "forceLogout", role?: string) => void;
}) {
  const isDisabled = Boolean(user.is_disabled);
  const role = String(user.role ?? "user");
  const nextRole = role === "admin" ? "user" : "admin";
  const devices = Array.isArray(user.devices) ? user.devices : [];
  return (
    <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{String(user.username ?? user.display_name ?? user.id)}</h2>
          <p>{String(user.display_name ?? user.nickname ?? "")}</p>
        </div>
        <span className={`status-badge ${isDisabled ? "error" : "ok"}`}>{isDisabled ? "已禁用" : "正常"}</span>
      </div>
      <div className="info-grid">
        <InfoBlock title="基础信息" rows={[
          ["用户名", user.username],
          ["昵称", user.nickname],
          ["邮箱", user.email],
          ["手机号", user.phone],
          ["角色", user.role],
          ["状态", user.status]
        ]} />
        <InfoBlock title="业务计数" rows={Object.entries(user.counts ?? {})} />
      </div>
      <div className="account-actions">
        <button
          className="secondary-button"
          type="button"
          disabled={operationLoading}
          onClick={() => runUserOperation("role", nextRole)}
        >
          {nextRole === "admin" ? "设为管理员" : "设为普通用户"}
        </button>
        <label className="inline-field">
          <span>禁用原因</span>
          <input
            value={disableReason}
            onChange={(event) => setDisableReason(event.target.value)}
            placeholder="可选"
          />
        </label>
        <button
          className="danger-button"
          type="button"
          disabled={operationLoading || isDisabled}
          onClick={() => runUserOperation("disable")}
        >
          禁用用户
        </button>
        <button
          className="secondary-button"
          type="button"
          disabled={operationLoading || !isDisabled}
          onClick={() => runUserOperation("enable")}
        >
          启用用户
        </button>
        <button
          className="danger-button"
          type="button"
          disabled={operationLoading}
          onClick={() => runUserOperation("forceLogout")}
        >
          强制下线
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>设备 ID</th>
              <th>设备名</th>
              <th>状态</th>
              <th>最后在线</th>
            </tr>
          </thead>
          <tbody>
            {devices.map((device) => (
              <tr key={String(device.device_id)}>
                <td>{String(device.device_id ?? "")}</td>
                <td>{String(device.device_name ?? "")}</td>
                <td>{device.is_active ? "活跃" : "停用"}</td>
                <td>{String(device.last_seen_at ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
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

function FilesPage({
  status,
  issues,
  issueType,
  setIssueType
}: {
  status: FileStorageStatusPayload | null;
  issues: FileStorageIssuesPayload | null;
  issueType: string;
  setIssueType: (value: string) => void;
}) {
  const [page, setPage] = useState(1);
  const items = issues?.items ?? [];
  const issueTypes = Array.from(new Set(items.map((item) => String(item.issue_type ?? "")).filter(Boolean))).sort();
  const filteredItems = issueType ? items.filter((item) => String(item.issue_type ?? "") === issueType) : items;
  const pageSize = 20;
  const totalPages = Math.max(1, Math.ceil(filteredItems.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const pageItems = filteredItems.slice((safePage - 1) * pageSize, safePage * pageSize);
  const issueCount = numberValue(status?.issues?.total ?? issues?.total);
  const errorCount = numberValue(status?.issues?.errors);
  const warningCount = numberValue(status?.issues?.warnings);

  function updateIssueType(value: string) {
    setIssueType(value);
    setPage(1);
  }

  return (
    <section className="page-section">
      <PageTitle title="文件" subtitle="本地上传文件记录与磁盘一致性巡检" />
      <div className="metric-grid compact-grid">
        <MetricCard label="状态" value={status?.status} tone={status?.status === "ok" ? "ok" : "warn"} />
        <MetricCard label="本地记录" value={status?.database?.local_records} />
        <MetricCard label="磁盘托管文件" value={status?.disk?.managed_files} />
        <MetricCard label="问题总数" value={issueCount} tone={issueCount > 0 ? "warn" : "ok"} />
        <MetricCard label="错误" value={errorCount} tone={errorCount > 0 ? "warn" : "ok"} />
        <MetricCard label="警告" value={warningCount} tone={warningCount > 0 ? "warn" : "ok"} />
      </div>
      <div className="info-grid">
        <InfoBlock title="上传目录" rows={[
          ["存储后端", status?.storage_provider],
          ["目录存在", boolLabel(status?.upload_dir?.exists)],
          ["是目录", boolLabel(status?.upload_dir?.is_dir)],
          ["可读", boolLabel(status?.upload_dir?.readable)],
          ["可写", boolLabel(status?.upload_dir?.writable)]
        ]} />
        <InfoBlock title="容量与记录" rows={[
          ["全部记录", status?.database?.total_records],
          ["非本地记录", status?.database?.non_local_records],
          ["本地记录大小", formatBytes(status?.database?.local_size_bytes)],
          ["磁盘文件数", status?.disk?.total_files],
          ["磁盘总大小", formatBytes(status?.disk?.total_size_bytes)],
          ["忽略系统生成文件", status?.disk?.ignored_server_generated_files]
        ]} />
      </div>
      <form className="filter-panel" onSubmit={(event) => event.preventDefault()}>
        <label>
          <span>问题类型</span>
          <select value={issueType} onChange={(event) => updateIssueType(event.target.value)}>
            <option value="">全部</option>
            {issueTypes.map((type) => (
              <option value={type} key={type}>
                {type}
              </option>
            ))}
          </select>
        </label>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>类型</th>
              <th>级别</th>
              <th>文件</th>
              <th>Storage Key</th>
              <th>预期大小</th>
              <th>实际大小</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            {pageItems.map((issue, index) => (
              <tr key={`${String(issue.issue_type ?? "issue")}-${String(issue.storage_key ?? issue.file_id ?? index)}`}>
                <td>{String(issue.issue_type ?? "")}</td>
                <td>{String(issue.severity ?? "")}</td>
                <td>{String(issue.file_name ?? issue.file_id ?? "")}</td>
                <td>{String(issue.storage_key ?? "")}</td>
                <td>{formatBytes(issue.expected_size_bytes)}</td>
                <td>{formatBytes(issue.actual_size_bytes)}</td>
                <td>{issueSummary(issue)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="pager-row">
        <span>{`显示 ${pageItems.length} / ${filteredItems.length} 个问题，第 ${safePage} / ${totalPages} 页`}</span>
        <div className="table-actions">
          <button
            className="table-action-button"
            type="button"
            disabled={safePage <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            上一页
          </button>
          <button
            className="table-action-button"
            type="button"
            disabled={safePage >= totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
          >
            下一页
          </button>
        </div>
      </div>
    </section>
  );
}

function BackupsPage({
  payload,
  selectedBackup,
  pruneForm,
  setPruneForm,
  pruneResult,
  downloadUrl,
  operationLoading,
  createBackup,
  openBackupDetail,
  verifyBackup,
  deleteBackup,
  pruneBackups,
  showDownloadUrl
}: {
  payload: DatabaseBackupListPayload | null;
  selectedBackup: DatabaseBackupItem | null;
  pruneForm: BackupPruneForm;
  setPruneForm: (patch: Partial<BackupPruneForm>) => void;
  pruneResult: DatabaseBackupPruneResult | null;
  downloadUrl: string;
  operationLoading: boolean;
  createBackup: () => void;
  openBackupDetail: (backupId: string) => void;
  verifyBackup: (backupId: string) => void;
  deleteBackup: (backupId: string) => void;
  pruneBackups: (dryRun: boolean) => void;
  showDownloadUrl: (backupId: string) => void;
}) {
  const backups = payload?.items ?? [];
  return (
    <section className="page-section">
      <PageTitle title="备份" subtitle={`共 ${payload?.total ?? 0} 个备份记录`} />
      <div className="toolbar">
        <button className="primary-button compact-action" type="button" disabled={operationLoading} onClick={createBackup}>
          <Archive size={17} />
          创建备份
        </button>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>备份 ID</th>
              <th>状态</th>
              <th>文件名</th>
              <th>大小</th>
              <th>创建人</th>
              <th>创建时间</th>
              <th>验证</th>
              <th>错误</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {backups.map((backup) => (
              <tr key={backup.id}>
                <td>{backup.id}</td>
                <td>{String(backup.status ?? "")}</td>
                <td>{String(backup.file_name ?? "")}</td>
                <td>{formatBytes(backup.size_bytes)}</td>
                <td>{String(backup.created_by_username ?? "")}</td>
                <td>{String(backup.created_at ?? "")}</td>
                <td>{String(backup.verification_status ?? "")}</td>
                <td>{String(backup.error_message ?? "")}</td>
                <td>
                  <div className="table-actions">
                    <button
                      className="table-action-button"
                      type="button"
                      onClick={() => openBackupDetail(backup.id)}
                      aria-label="查看备份详情"
                    >
                      查看
                    </button>
                    <button
                      className="table-action-button"
                      type="button"
                      disabled={operationLoading || backup.status !== "completed"}
                      onClick={() => verifyBackup(backup.id)}
                      aria-label="验证备份"
                    >
                      验证
                    </button>
                    <button
                      className="table-action-button danger-link"
                      type="button"
                      disabled={operationLoading}
                      onClick={() => deleteBackup(backup.id)}
                      aria-label="删除备份"
                    >
                      删除
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <form className="filter-panel" onSubmit={(event) => event.preventDefault()}>
        <label>
          <span>保留最近</span>
          <input
            inputMode="numeric"
            value={pruneForm.keep_last}
            onChange={(event) => setPruneForm({ keep_last: event.target.value })}
            placeholder="例如 3"
          />
        </label>
        <label>
          <span>早于天数</span>
          <input
            inputMode="numeric"
            value={pruneForm.older_than_days}
            onChange={(event) => setPruneForm({ older_than_days: event.target.value })}
            placeholder="例如 30"
          />
        </label>
        <label className="checkbox-field">
          <input
            checked={pruneForm.include_failed}
            onChange={(event) => setPruneForm({ include_failed: event.target.checked })}
            type="checkbox"
          />
          <span>包含失败备份</span>
        </label>
        <label className="checkbox-field">
          <input
            checked={pruneForm.include_deleted}
            onChange={(event) => setPruneForm({ include_deleted: event.target.checked })}
            type="checkbox"
          />
          <span>包含已删除记录</span>
        </label>
        <button className="secondary-button" type="button" disabled={operationLoading} onClick={() => pruneBackups(true)}>
          预览清理
        </button>
        <button className="danger-button" type="button" disabled={operationLoading} onClick={() => pruneBackups(false)}>
          执行清理
        </button>
      </form>
      {pruneResult ? <BackupPruneResultPanel result={pruneResult} /> : null}
      {selectedBackup ? (
        <BackupDetailPanel
          backup={selectedBackup}
          downloadUrl={downloadUrl}
          showDownloadUrl={() => showDownloadUrl(selectedBackup.id)}
        />
      ) : null}
    </section>
  );
}

function BackupPruneResultPanel({ result }: { result: DatabaseBackupPruneResult }) {
  const items = result.items ?? [];
  return (
    <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{result.dry_run ? "清理预览" : "清理结果"}</h2>
          <p>{`候选 ${result.candidate_count ?? 0} · 已处理 ${result.processed_count ?? 0}`}</p>
        </div>
        <span className="status-badge warning">{result.dry_run ? "预览" : "已执行"}</span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>备份 ID</th>
              <th>动作</th>
              <th>原状态</th>
              <th>新状态</th>
              <th>文件名</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={String(item.id)}>
                <td>{String(item.id ?? "")}</td>
                <td>{String(item.action ?? "")}</td>
                <td>{String(item.status_before ?? "")}</td>
                <td>{String(item.status_after ?? "")}</td>
                <td>{String(item.file_name ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </article>
  );
}

function BackupDetailPanel({
  backup,
  downloadUrl,
  showDownloadUrl
}: {
  backup: DatabaseBackupItem;
  downloadUrl: string;
  showDownloadUrl: () => void;
}) {
  return (
    <article className="detail-panel">
      <div className="detail-header">
        <div>
          <h2>{String(backup.file_name ?? backup.id)}</h2>
          <p>{String(backup.created_at ?? "")}</p>
        </div>
        <span className={`status-badge ${backup.status === "completed" ? "ok" : "warning"}`}>
          {String(backup.status ?? "")}
        </span>
      </div>
      <div className="info-grid">
        <InfoBlock title="备份" rows={[
          ["备份 ID", backup.id],
          ["数据库", backup.database_dialect],
          ["格式", backup.backup_format],
          ["大小", formatBytes(backup.size_bytes)],
          ["创建人", backup.created_by_username],
          ["耗时", backup.duration_ms]
        ]} />
        <InfoBlock title="验证" rows={[
          ["验证状态", backup.verification_status],
          ["验证信息", backup.verification_message],
          ["错误信息", backup.error_message],
          ["存储键", backup.storage_key],
          ["checksum_sha256", backup.checksum_sha256]
        ]} />
      </div>
      <button className="secondary-button compact-action" type="button" onClick={showDownloadUrl}>
        生成下载地址
      </button>
      {downloadUrl ? (
        <div className="json-block">
          <span>download_url</span>
          <pre>{downloadUrl}</pre>
        </div>
      ) : null}
    </article>
  );
}

function LogsPage({
  payload,
  entries,
  filters,
  setFilter,
  search,
  downloadStatus,
  downloadLogFile
}: {
  payload: LogFilesPayload | null;
  entries: LogQueryPayload | null;
  filters: LogFilters;
  setFilter: (key: keyof LogFilters, value: string) => void;
  search: () => void;
  downloadStatus: string;
  downloadLogFile: (fileName: string) => void;
}) {
  const files = payload?.files ?? payload?.items ?? [];
  const logItems = entries?.items ?? [];

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    search();
  }

  return (
    <section className="page-section">
      <PageTitle title="日志" subtitle={`共 ${payload?.total ?? files.length} 个文件`} />
      <form className="filter-panel log-filter-panel" onSubmit={submit}>
        <label>
          <span>日志文件</span>
          <select value={filters.file_name} onChange={(event) => setFilter("file_name", event.target.value)}>
            <option value="">全部</option>
            {files.map((file) => {
              const fileName = String(file.file_name ?? file.name ?? "");
              return (
                <option value={fileName} key={fileName}>
                  {fileName}
                </option>
              );
            })}
          </select>
        </label>
        <label>
          <span>日志级别</span>
          <select value={filters.level} onChange={(event) => setFilter("level", event.target.value)}>
            <option value="">全部</option>
            <option value="DEBUG">DEBUG</option>
            <option value="INFO">INFO</option>
            <option value="WARNING">WARNING</option>
            <option value="ERROR">ERROR</option>
            <option value="CRITICAL">CRITICAL</option>
          </select>
        </label>
        <label>
          <span>关键词</span>
          <input
            value={filters.keyword}
            onChange={(event) => setFilter("keyword", event.target.value)}
            placeholder="message 关键词"
          />
        </label>
        <label>
          <span>开始时间</span>
          <input
            value={filters.created_from}
            onChange={(event) => setFilter("created_from", event.target.value)}
            placeholder="2026-05-03T00:00:00+00:00"
          />
        </label>
        <label>
          <span>结束时间</span>
          <input
            value={filters.created_to}
            onChange={(event) => setFilter("created_to", event.target.value)}
            placeholder="2026-05-03T23:59:59+00:00"
          />
        </label>
        <label>
          <span>返回条数</span>
          <input
            inputMode="numeric"
            value={filters.limit}
            onChange={(event) => setFilter("limit", event.target.value)}
            placeholder="100"
          />
        </label>
        <button className="secondary-button" type="submit">
          <Search size={17} />
          查询日志
        </button>
      </form>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>文件名</th>
              <th>大小</th>
              <th>更新时间</th>
              <th>下载</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => (
              <tr key={String(file.file_name ?? file.name)}>
                <td>{String(file.file_name ?? file.name ?? "")}</td>
                <td>{formatBytes(file.size_bytes)}</td>
                <td>{String(file.modified_at ?? "")}</td>
                <td>
                  <button
                    className="table-action-button"
                    type="button"
                    onClick={() => downloadLogFile(String(file.file_name ?? file.name ?? ""))}
                    aria-label={`下载 ${String(file.file_name ?? file.name ?? "")}`}
                  >
                    下载
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {downloadStatus ? <p className="empty-text" role="status">{downloadStatus}</p> : null}
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>级别</th>
              <th>Logger</th>
              <th>文件</th>
              <th>消息</th>
            </tr>
          </thead>
          <tbody>
            {logItems.map((entry, index) => (
              <tr key={`${String(entry.file_name ?? "log")}-${String(entry.timestamp ?? index)}-${index}`}>
                <td>{String(entry.timestamp ?? "")}</td>
                <td>{String(entry.level ?? "")}</td>
                <td>{String(entry.logger ?? "")}</td>
                <td>{String(entry.file_name ?? "")}</td>
                <td className="message-cell">{String(entry.message ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {entries ? <p className="empty-text">{`匹配 ${entries.total ?? logItems.length} 条，限制 ${entries.limit ?? "-"}`}</p> : null}
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

function loadUsers(client: AdminApiClient, keyword: string): Promise<UserListPayload> {
  const params: ListUsersParams = { page: 1, size: 20 };
  if (keyword.trim()) {
    params.keyword = keyword.trim();
  }
  return client.listUsers<UserListPayload>(params);
}

function loadChatSessions(client: AdminApiClient, filters: ChatFilters): Promise<ChatSessionListPayload> {
  const params: ListChatSessionsParams = { page: 1, size: 20 };
  for (const key of ["type", "keyword", "user_id"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  return client.listChatSessions<ChatSessionListPayload>(params);
}

function loadChatMessages(
  client: AdminApiClient,
  sessionId: string,
  filters: ChatMessageFilters
): Promise<ChatMessageListPayload> {
  const params: ListChatMessagesParams = { page: 1, size: 50 };
  if (filters.type.trim()) {
    params.type = filters.type.trim();
  }
  return client.listChatMessages<ChatMessageListPayload>(sessionId, params);
}

async function loadContactData(
  client: AdminApiClient,
  requestFilters: ContactRequestFilters,
  friendshipFilters: ContactFriendshipFilters
): Promise<{ requests: ContactFriendRequestListPayload; friendships: ContactFriendshipListPayload }> {
  const [requests, friendships] = await Promise.all([
    loadContactFriendRequests(client, requestFilters),
    loadContactFriendships(client, friendshipFilters)
  ]);
  return { requests, friendships };
}

function loadContactFriendRequests(
  client: AdminApiClient,
  filters: ContactRequestFilters
): Promise<ContactFriendRequestListPayload> {
  const params: ListContactFriendRequestsParams = { page: 1, size: 20 };
  for (const key of ["status", "sender_id", "receiver_id"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  return client.listContactFriendRequests<ContactFriendRequestListPayload>(params);
}

function loadContactFriendships(
  client: AdminApiClient,
  filters: ContactFriendshipFilters
): Promise<ContactFriendshipListPayload> {
  const params: ListContactFriendshipsParams = { page: 1, size: 20 };
  for (const key of ["user_id", "friend_id"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  return client.listContactFriendships<ContactFriendshipListPayload>(params);
}

function loadGroups(client: AdminApiClient, filters: GroupFilters): Promise<GroupListPayload> {
  const params: ListGroupsParams = { page: 1, size: 20 };
  for (const key of ["keyword", "owner_id"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  return client.listGroups<GroupListPayload>(params);
}

function loadGroupMembers(
  client: AdminApiClient,
  groupId: string,
  filters: GroupMemberFilters
): Promise<GroupMemberListPayload> {
  const params: ListGroupMembersParams = { page: 1, size: 20 };
  for (const key of ["role", "user_id"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  return client.listGroupMembers<GroupMemberListPayload>(groupId, params);
}

function loadMoments(client: AdminApiClient, filters: MomentFilters): Promise<MomentListPayload> {
  const params: ListMomentsParams = { page: 1, size: 20 };
  for (const key of ["keyword", "user_id"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  return client.listMoments<MomentListPayload>(params);
}

function loadMomentComments(
  client: AdminApiClient,
  momentId: string,
  filters: MomentUserFilters
): Promise<MomentCommentListPayload> {
  const params: ListMomentCommentsParams = { page: 1, size: 20 };
  if (filters.user_id.trim()) {
    params.user_id = filters.user_id.trim();
  }
  return client.listMomentComments<MomentCommentListPayload>(momentId, params);
}

function loadMomentLikes(
  client: AdminApiClient,
  momentId: string,
  filters: MomentUserFilters
): Promise<MomentLikeListPayload> {
  const params: ListMomentLikesParams = { page: 1, size: 20 };
  if (filters.user_id.trim()) {
    params.user_id = filters.user_id.trim();
  }
  return client.listMomentLikes<MomentLikeListPayload>(momentId, params);
}

async function loadFileStorageInspection(client: AdminApiClient): Promise<{
  status: FileStorageStatusPayload;
  issues: FileStorageIssuesPayload;
}> {
  const [status, issues] = await Promise.all([
    client.getFileStorageStatus<FileStorageStatusPayload>(),
    client.listFileStorageIssues<FileStorageIssuesPayload>()
  ]);
  return { status, issues };
}

function loadLogEntries(client: AdminApiClient, filters: LogFilters): Promise<LogQueryPayload> {
  return client.queryLogs<LogQueryPayload>(logQueryParams(filters));
}

function logQueryParams(filters: LogFilters): QueryLogsParams {
  const params: QueryLogsParams = {};
  for (const key of ["file_name", "level", "keyword", "created_from", "created_to"] as const) {
    if (filters[key].trim()) {
      params[key] = filters[key].trim();
    }
  }
  const limit = parseOptionalPositiveInt(filters.limit);
  if (limit !== undefined) {
    params.limit = limit;
  }
  return params;
}

function loadDatabaseBackups(client: AdminApiClient): Promise<DatabaseBackupListPayload> {
  return client.listDatabaseBackups<DatabaseBackupListPayload>({ page: 1, size: 20 });
}

function backupPruneParams(form: BackupPruneForm, dryRun: boolean): PruneDatabaseBackupsParams {
  return {
    dry_run: dryRun,
    include_deleted: form.include_deleted,
    include_failed: form.include_failed,
    keep_last: parseOptionalPositiveInt(form.keep_last),
    older_than_days: parseOptionalPositiveInt(form.older_than_days)
  };
}

function parseOptionalPositiveInt(value: string): number | undefined {
  const normalized = String(value || "").trim();
  if (!normalized) {
    return undefined;
  }
  const parsed = Number(normalized);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return undefined;
  }
  return Math.floor(parsed);
}

function mergeUserDetail(current: UserDetailPayload, next: UserDetailPayload): UserDetailPayload {
  return {
    ...current,
    ...next,
    counts: next.counts ?? current.counts,
    devices: next.devices ?? current.devices
  };
}

function userOperationConfirmMessage(
  operation: "role" | "disable" | "enable" | "forceLogout",
  username: string,
  role?: string
): string {
  if (operation === "role") {
    return `确认将 ${username} 的角色修改为 ${role === "admin" ? "管理员" : "普通用户"}？`;
  }
  if (operation === "disable") {
    return `确认禁用 ${username}？禁用后该用户将无法登录，现有登录状态也会失效。`;
  }
  if (operation === "forceLogout") {
    return `确认强制 ${username} 下线？该操作会断开实时连接并让旧 token 失效。`;
  }
  return `确认启用 ${username}？`;
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

function contactUserName(user?: ContactUserSummary, fallbackId?: string): string {
  return String(user?.username || user?.nickname || user?.id || fallbackId || "");
}

function groupUserName(user?: GroupUserSummary, fallbackId?: string): string {
  return String(user?.username || user?.nickname || user?.id || fallbackId || "");
}

function momentUserName(user?: MomentUserSummary, fallbackId?: string): string {
  return String(user?.username || user?.nickname || user?.id || fallbackId || "");
}

function contactStatusTone(status: unknown): HealthStatus {
  const normalized = String(status ?? "").toLowerCase();
  if (normalized === "accepted") {
    return "ok";
  }
  if (normalized === "rejected" || normalized === "cancelled") {
    return "error";
  }
  if (normalized === "pending") {
    return "warning";
  }
  return "unknown";
}

function boolLabel(value: unknown): string {
  if (value === true) {
    return "是";
  }
  if (value === false) {
    return "否";
  }
  return "-";
}

function triggerTextDownload(fileName: string, content: string): void {
  if (typeof document === "undefined" || typeof URL === "undefined" || typeof URL.createObjectURL !== "function") {
    return;
  }
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = fileName;
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
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
