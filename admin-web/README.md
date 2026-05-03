# AssistIM 管理看板前端

这是后端管理员接口的第一版 Web 看板骨架。它只连接现有管理员接口，不直接保存账号密码或 token。

## 功能范围

- 登录页：输入服务端地址和管理员访问令牌。
- 概览页：读取 `/api/v1/admin/dashboard`。
- 用户页：读取 `/api/v1/admin/users`。
- 数据库页：读取 `/api/v1/admin/database/status`。
- 日志页：读取 `/api/v1/admin/logs/files`。

## 本地运行

```powershell
cd D:\AssistIM_V2\admin-web
npm.cmd install --cache D:\AssistIM_V2\tmp\npm-cache
npm.cmd run dev
```

默认地址是 `http://127.0.0.1:5174`。后端默认 CORS 允许 `5173`，如果使用 `5174`，需要启动后端前设置：

```powershell
$env:CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:5174"
```

## 验证

```powershell
npm.cmd run build
npm.cmd test
node_modules\.bin\tsc.cmd --noEmit
```

当前开发机存在一个 Node 子进程限制：Vite/Vitest 调用 esbuild 时使用 pipe，会触发 `spawn EPERM`。因此在该机器上已验证 `tsc --noEmit`，但 `build/test` 会被本机进程策略阻断。换到允许 Node 子进程 pipe 的环境后，应继续执行完整 `build/test`。
