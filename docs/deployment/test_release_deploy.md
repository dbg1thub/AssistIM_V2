# AssistIM 测试发版与云服务器部署方案

本文档面向期中演示后的同组测试版本，目标是先把服务端部署到云服务器，把客户端用 Nuitka 打成 Windows 测试包。热更新程序暂不实现，但本次产物结构会提前保留 `version.json`、`manifest.json` 和 `latest.json`，后续可以在这个基础上继续做自动上传与客户端更新。

如果服务器已经安装 Docker，优先使用本文档中的 Docker Compose 方案；宿主机 `venv + systemd` 方案保留为兜底路径。

## 一、当前发版边界

本轮发版包含：

- 云服务器部署 FastAPI 后端
- PostgreSQL 作为服务端数据库
- Nginx 反向代理 HTTP 与 WebSocket
- Windows 客户端 Nuitka standalone 打包
- 客户端包内写入服务器地址
- 客户端包生成文件级 manifest
- 生成未来热更新可消费的 `latest.json`

本轮暂不包含：

- 客户端自动更新程序
- 本地 AI 模型随客户端包分发
- 模型文件自动下载
- 远程模型服务
- 自动化 CI/CD 发布流水线

## 二、云服务器推荐结构

推荐第一版使用 Docker Compose 托管 `api + postgres`，宿主机 Nginx 负责 `80/443` 反向代理：

```text
Internet
  |
  v
Nginx :80/:443
  |
  |-- /api/v1/*  -> 127.0.0.1:8000
  |-- /ws        -> 127.0.0.1:8000
  |-- /uploads/* -> FastAPI 鉴权文件接口
  v
Docker Compose
  |
  |-- api
  |-- postgres
```

建议目录：

```text
/opt/assistim/app           # 项目代码
/opt/assistim/app/deploy/docker/server.env  # Docker Compose 环境变量
/var/lib/assistim/uploads   # 上传文件
/var/log/assistim           # 日志目录
```

## 三、Docker 环境变量

复制仓库中的 `deploy/docker/server.env.example` 到服务器：

```bash
cd /opt/assistim/app
cp deploy/docker/server.env.example deploy/docker/server.env
nano deploy/docker/server.env
```

必须修改：

```text
SECRET_KEY=换成足够长的随机字符串
POSTGRES_PASSWORD=你的数据库密码
DEBUG=false
CORS_ORIGINS=*
```

这里不需要手写 `DATABASE_URL`。`docker-compose.yml` 会用 `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_DB` 自动拼出后端连接串，所以数据库密码直接改 `POSTGRES_PASSWORD` 这一处即可。

`CORS_ORIGINS=*` 对桌面客户端测试比较省事。后续如果接 Web 管理端，再改成明确域名。

## 四、Ubuntu 22.04 Docker 部署步骤

安装基础组件：

```bash
sudo apt update
sudo apt install -y nginx git docker.io docker-compose-plugin
```

部署代码：

```bash
sudo mkdir -p /opt/assistim
sudo chown -R $USER:$USER /opt/assistim
git clone <你的仓库地址> /opt/assistim/app
cd /opt/assistim/app
```

创建运行目录：

```bash
sudo mkdir -p /var/lib/assistim/uploads /var/log/assistim
sudo chown -R $USER:$USER /var/lib/assistim /var/log/assistim
```

准备 Docker 环境变量：

```bash
cd /opt/assistim/app
cp deploy/docker/server.env.example deploy/docker/server.env
nano deploy/docker/server.env
```

启动服务：

```bash
cd /opt/assistim/app
docker compose --env-file deploy/docker/server.env -f deploy/docker/docker-compose.yml up -d --build
```

查看容器状态：

```bash
docker compose --env-file deploy/docker/server.env -f deploy/docker/docker-compose.yml ps
docker compose --env-file deploy/docker/server.env -f deploy/docker/docker-compose.yml logs -f api
```

本方案中：

- PostgreSQL 会自动初始化
- API 容器启动前会先执行 `alembic upgrade head`
- 后端只暴露到 `127.0.0.1:8000`

另开终端验证：

```bash
curl http://127.0.0.1:8000/
```

## 五、Nginx 反向代理

创建 `/etc/nginx/sites-available/assistim`：

```bash
sudo cp /opt/assistim/app/deploy/server/nginx-assistim.conf.example /etc/nginx/sites-available/assistim
sudo nano /etc/nginx/sites-available/assistim
```

把 `server_name _;` 改成你的域名或服务器公网 IP。

启用配置：

```bash
sudo ln -s /etc/nginx/sites-available/assistim /etc/nginx/sites-enabled/assistim
sudo nginx -t
sudo systemctl reload nginx
```

如果暂时没有域名，客户端打包时 `ServerHost` 直接填服务器公网 IP，`UseSsl` 不传即可。

如果使用 HTTPS，先配置证书，再把客户端打包命令中的 `-UseSsl` 打开。

## 六、客户端测试包打包

本地 Windows 执行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\build_client_nuitka.ps1 `
  -Version 0.1.0 `
  -Channel test `
  -ServerHost "你的服务器IP或域名" `
  -ServerPort 80
```

打包脚本默认使用 `deploy/client/config.test.json` 作为客户端测试包配置模板，然后把 `ServerHost`、`ServerPort`、`UseSsl` 写入包内 `data/config.json`。不要直接依赖本机 `data/config.json`，避免把个人测试配置打进发给同组的包。

HTTPS 场景：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\build_client_nuitka.ps1 `
  -Version 0.1.0 `
  -Channel test `
  -ServerHost "你的域名" `
  -ServerPort 443 `
  -UseSsl
```

输出目录：

```text
dist/client/package/AssistIM
dist/client/release/AssistIM-0.1.0-win64.zip
dist/client/release/latest.json
```

打包后执行一次产物检查：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File tools\verify_client_release.ps1 `
  -ExpectedVersion 0.1.0 `
  -ExpectedServerHost "你的服务器IP或域名"
```

发给同组测试时，优先发 `release/AssistIM-0.1.0-win64.zip`。

## 七、模型分发策略

客户端包默认不包含 `.gguf`、`.bin`、`.safetensors` 模型文件。原因：

- 模型体积大，会显著拖慢打包、上传和分发
- 同组测试的通信功能不应该被模型文件体积阻塞
- 后续热更新不应把程序更新和模型资源更新绑死

如果测试 AI 能力，需要单独提供模型文件，并放到解压后的：

```text
AssistIM/client/resources/models/
```

当前模型配置依赖 `client/resources/models/manifest.json` 和 `data/config.json` 中的 `AI.ModelId`。

## 八、热更新预留结构

当前打包脚本已经生成：

```text
AssistIM/version.json
AssistIM/manifest.json
release/latest.json
```

后续热更新可以按这个流程扩展：

```text
本地构建 zip
  |
  v
上传 release zip + latest.json 到服务器静态目录
  |
  v
客户端启动或手动检查 latest.json
  |
  v
比较本地 version.json
  |
  v
下载 zip
  |
  v
独立 updater 替换程序文件
```

建议后续 updater 规则：

- updater 独立进程，主程序退出后再替换文件
- 不覆盖 `data/assistim.db`
- 不覆盖用户本地 AI 模型
- 不覆盖用户本地日志
- 更新前校验 zip 的 SHA256
- manifest 只管理程序文件和内置资源文件
- 模型走独立资源包或手动安装

## 九、宿主机部署兜底方案

如果 Docker 不方便使用，仍可使用：

- [server/.env.production.example](/D:/AssistIM_V2/server/.env.production.example)
- [assistim-api.service.example](/D:/AssistIM_V2/deploy/server/assistim-api.service.example)
- [nginx-assistim.conf.example](/D:/AssistIM_V2/deploy/server/nginx-assistim.conf.example)

宿主机 `venv + systemd` 路线与前一版文档一致。

## 十、测试检查清单

服务端：

- `curl http://服务器IP/` 能返回应用信息
- `POST /api/v1/auth/register` 能注册
- 两个客户端能分别登录
- WebSocket 能连上 `/ws`
- 消息能实时到达
- 上传文件后可被接收方查看

客户端：

- 解压后可启动
- `data/config.json` 中的 `Server` 指向云服务器
- 登录和注册走云服务器
- 两个不同电脑的客户端能互发消息
- 未放置模型文件时，通信功能不受影响
- 放置模型文件后，AI 助手可正常加载本地模型
