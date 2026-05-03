# AssistIM 管理看板前端

这是后端管理员接口的第一版 Web 看板骨架。它只连接现有管理员接口，不直接保存账号密码或 token。

## 功能范围

- 登录页：输入服务端地址和管理员访问令牌。
- 概览页：读取 `/api/v1/admin/dashboard`。
- 巡检页：读取认证、数据库、聊天、联系人、群组、朋友圈、实时连接、通话、HTTP、限流、E2EE、文件存储等只读健康检查接口。
- 用户页：读取 `/api/v1/admin/users`。
- 数据库页：读取 `/api/v1/admin/database/status`。
- 日志页：读取 `/api/v1/admin/logs/files`。

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
