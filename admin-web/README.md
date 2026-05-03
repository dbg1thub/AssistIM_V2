# AssistIM 管理看板前端

这是后端管理员接口的第一版 Web 看板骨架。它只连接现有管理员接口，不直接保存账号密码或 token。

## 功能范围

- 登录页：输入服务端地址和管理员访问令牌。
- 概览页：读取 `/api/v1/admin/dashboard`。
- 巡检页：读取认证、数据库、聊天、联系人、群组、朋友圈、实时连接、通话、HTTP、限流、E2EE、文件存储等只读健康检查接口。
- 审计页：读取 `/api/v1/admin/audit-logs` 和 `/api/v1/admin/audit-logs/{log_id}`，用于查看管理员操作记录与脱敏详情。
- 聊天页：读取 `/api/v1/admin/chat/sessions`、`/api/v1/admin/chat/sessions/{session_id}` 和 `/api/v1/admin/chat/sessions/{session_id}/messages`，用于查看会话、成员和消息入库情况。
- 联系人页：读取 `/api/v1/admin/contacts/friend-requests` 和 `/api/v1/admin/contacts/friendships`，用于按用户和状态查看好友请求、好友关系。
- 群组页：读取 `/api/v1/admin/groups`、`/api/v1/admin/groups/{group_id}` 和 `/api/v1/admin/groups/{group_id}/members`，用于查看群资料、群会话、群成员和公告入库情况。
- 朋友圈页：读取 `/api/v1/admin/moments`、`/api/v1/admin/moments/{moment_id}`、`/api/v1/admin/moments/{moment_id}/comments` 和 `/api/v1/admin/moments/{moment_id}/likes`，用于查看动态、评论和点赞入库情况。
- 用户页：读取 `/api/v1/admin/users` 和 `/api/v1/admin/users/{user_id}`，支持改角色、禁用、启用、强制下线等需要确认的账号管理操作。
- 数据库页：读取 `/api/v1/admin/database/status`。
- 文件页：读取 `/api/v1/admin/files/storage/status` 和 `/api/v1/admin/files/storage/issues`，用于查看本地上传文件记录与磁盘文件一致性问题。
- 备份页：读取和管理 `/api/v1/admin/database/backups*`，支持创建、查看、验证、删除、清理预览和执行清理。
- 日志页：读取 `/api/v1/admin/logs/files`、`/api/v1/admin/logs` 和 `/api/v1/admin/logs/files/{file_name}/download`，支持文件列表、日志查询和脱敏日志下载。

## 本地运行

```powershell
cd D:\AssistIM_V2\admin-web
npm.cmd install --cache D:\AssistIM_V2\tmp\npm-cache
npm.cmd run doctor
npm.cmd run dev
```

默认地址是 `http://127.0.0.1:5173`。后端默认 CORS 已允许该地址，正常情况下不需要额外设置 CORS。

`npm.cmd run doctor` 用于提前检查当前环境是否允许 Node 使用子进程 pipe。Vite、Vitest 和 esbuild 都依赖这个能力；如果诊断失败并出现 `spawn EPERM`，后续 `dev/build/test` 也会在同一环境里失败，需要换到允许该能力的普通 PowerShell/终端或调整本机安全策略后再运行。

## 验证

```powershell
npm.cmd run doctor
npm.cmd run build
npm.cmd test
node_modules\.bin\tsc.cmd --noEmit
```

当前开发机存在一个 Node 子进程限制：Vite/Vitest 调用 esbuild 时使用 pipe，会触发 `spawn EPERM`。因此在该机器上已验证 `tsc --noEmit`，但 `doctor/build/test/dev` 会被本机进程策略阻断。换到允许 Node 子进程 pipe 的环境后，应继续执行完整 `doctor/build/test`。
