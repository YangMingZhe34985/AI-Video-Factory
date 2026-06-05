# AI Video Factory — 云端部署方案

> **版本**: official v1.0  
> **最后更新**: 2026-06-04  
> **文档说明**: 本文件已写入 `.gitignore`，仅存在于本地，不提交到代码库。

---

## 目录

1. [架构概览](#1-架构概览)
2. [前置要求](#2-前置要求)
3. [部署文件说明](#3-部署文件说明)
4. [步骤一：服务器环境准备](#4-步骤一服务器环境准备)
5. [步骤二：上传项目代码](#5-步骤二上传项目代码)
6. [步骤三：配置环境变量](#6-步骤三配置环境变量)
7. [步骤四：构建并启动服务](#7-步骤四构建并启动服务)
8. [步骤五：验证部署](#8-步骤五验证部署)
9. [日常运维](#9-日常运维)
10. [常见问题排查](#10-常见问题排查)

---

## 1. 架构概览

```
                         互联网用户
                              │
                         Port 80 (HTTP)
                              │
                    ┌─────────▼─────────┐
                    │      Nginx        │
                    │  (video_factory_  │
                    │   frontend)       │
                    │                   │
                    │  ① / → Vue SPA   │
                    │  ② /api/ → ③    │
                    └─────────┬─────────┘
                              │ /api/*  (Docker 内网)
                    ┌─────────▼─────────┐
                    │  Flask (Gunicorn) │
                    │  (video_factory_  │
                    │   backend :5000)  │
                    └─────────┬─────────┘
                              │ SQLAlchemy (Docker 内网)
                    ┌─────────▼─────────┐
                    │    MySQL 8.0      │
                    │  (video_factory_  │
                    │   db :3306)       │
                    └───────────────────┘
```

**服务组成：**

| 容器名                   | 镜像          | 对外端口 | 说明                        |
|--------------------------|---------------|----------|-----------------------------|
| `video_factory_db`       | mysql:8.0     | 无       | 数据库（仅内网访问）        |
| `video_factory_backend`  | 自构建        | 无       | Flask API (Gunicorn)        |
| `video_factory_frontend` | 自构建        | **80**   | Nginx + Vue 3 静态文件      |

**持久化卷：**

| 卷名               | 挂载点              | 说明                         |
|--------------------|---------------------|------------------------------|
| `mysql_data`       | MySQL 内部          | 数据库数据持久化             |
| `backend_storage`  | `/app/storage`      | 用户上传 & 生成产物持久化    |

---

## 2. 前置要求

### 服务器最低配置

| 项目   | 要求                             |
|--------|----------------------------------|
| 操作系统 | Ubuntu 22.04 LTS（推荐）        |
| CPU    | 4 核及以上                       |
| 内存   | 8 GB 及以上                      |
| 存储   | 50 GB SSD（视生成产物量可扩充）  |

### 软件依赖

```bash
# Docker 24.0+
docker --version

# Docker Compose 2.20+ (Compose V2，作为 docker compose 子命令)
docker compose version
```

### 防火墙/安全组

| 端口 | 协议 | 用途         | 来源        |
|------|------|--------------|-------------|
| 22   | TCP  | SSH 登录     | 运维 IP     |
| 80   | TCP  | HTTP 访问    | 所有用户    |
| 443  | TCP  | HTTPS（可选）| 所有用户    |

> MySQL 端口 3306 和后端端口 5000 **不暴露**到公网，仅 Docker 内网通信。

### API 密钥

部署前请准备好：
- **DashScope API Key** (`DASHSCOPE_API_KEY`) — 阿里云百炼平台
- **DeepSeek API Key** (`DEEPSEEK_API_KEY`) — DeepSeek 开放平台

---

## 3. 部署文件说明

```
项目根目录/
├── docker-compose.yml              # Docker Compose 编排文件
├── .dockerignore                   # Docker 构建上下文排除规则
├── DEPLOYMENT.md                   # 本文件（已加入 .gitignore）
│
└── deploy/                         # 所有 Docker 相关配置
    ├── Dockerfile.backend          # Flask 后端镜像
    ├── Dockerfile.frontend         # Vue + Nginx 镜像（多阶段）
    ├── nginx.conf                  # Nginx 站点配置
    ├── entrypoint.sh               # 后端启动脚本（迁移 + Gunicorn）
    └── .env.production.example     # 生产环境变量模板
```

---

## 4. 步骤一：服务器环境准备

### 4.1 安装 Docker（Ubuntu 22.04）

```bash
# 更新系统包
sudo apt-get update && sudo apt-get upgrade -y

# 安装必要工具
sudo apt-get install -y ca-certificates curl gnupg

# 添加 Docker 官方 GPG 密钥
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# 添加 Docker 软件源
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# 安装 Docker Engine + Compose Plugin
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# 验证安装
docker --version
docker compose version

# 允许当前用户无需 sudo 运行 Docker
sudo usermod -aG docker $USER
newgrp docker
```

### 4.2 验证 Docker 正常运行

```bash
docker run --rm hello-world
# 应输出 "Hello from Docker!"
```

---

## 5. 步骤二：上传项目代码

### 方式 A：Git 克隆（推荐）

```bash
# 在服务器上克隆代码（替换为实际仓库地址）
cd /opt
git clone <YOUR_REPO_URL> video-factory
cd video-factory
```

### 方式 B：SCP 上传

```bash
# 在本地执行（将整个项目目录上传到服务器）
scp -r /path/to/Task7 ubuntu@<服务器IP>:/opt/video-factory
```

> **注意**：确保 `.env.production`、`backend/.env` 等含密钥的文件**不在**代码库中，
> 这些文件需要在服务器上单独创建（见下一步）。

---

## 6. 步骤三：配置环境变量

这是部署中**最关键**的一步。

### 6.1 创建生产环境配置文件

```bash
# 进入项目根目录
cd /opt/video-factory

# 从模板复制环境配置
cp deploy/.env.production.example .env.production

# 用编辑器填写真实配置
nano .env.production
```

### 6.2 必填项说明

打开 `.env.production`，**必须修改**以下字段：

| 变量名                | 说明                                  | 示例值                              |
|-----------------------|---------------------------------------|-------------------------------------|
| `SECRET_KEY`          | Flask session 密钥（随机强字符串）    | 见下方生成命令                      |
| `JWT_SECRET_KEY`      | JWT 签名密钥（另一个随机字符串）      | 见下方生成命令                      |
| `MYSQL_ROOT_PASSWORD` | MySQL root 密码                       | `Str0ng!Pass#2024`                  |
| `DASHSCOPE_API_KEY`   | 阿里云百炼 API Key                    | `replace-with-dashscope-api-key`    |
| `DEEPSEEK_API_KEY`    | DeepSeek API Key                      | `replace-with-deepseek-api-key`     |

**生成随机密钥命令：**

```bash
# 在服务器上执行，分别生成 SECRET_KEY 和 JWT_SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 6.3 可选配置

```bash
# 如需修改前端访问端口（默认 80）
HOST_PORT=8080

# 根据服务器 CPU 核心数调整 worker 数
GUNICORN_WORKERS=4      # 建议 = CPU核心数 × 2

# 按需开启工作流功能
T2V_ENABLED=true
R2V_FLASH_ENABLED=true
```

### 6.4 配置文件权限保护

```bash
# 限制只有当前用户可读
chmod 600 .env.production
```

---

## 7. 步骤四：构建并启动服务

### 7.1 首次部署

```bash
cd /opt/video-factory

# 构建所有镜像（首次约 3-8 分钟，取决于网速）
docker compose --env-file .env.production build

# 启动所有服务（后台运行）
docker compose --env-file .env.production up -d
```

> `entrypoint.sh` 会在 backend 容器启动时自动执行：
> 1. `flask db upgrade` — 运行数据库迁移
> 2. `flask seed-defaults` — 写入默认数据（Series、Models、Workflow Nodes）
> 3. 启动 Gunicorn

### 7.2 查看启动日志

```bash
# 实时查看所有服务日志
docker compose logs -f

# 只看后端日志（迁移过程）
docker compose logs -f backend

# 只看数据库日志
docker compose logs -f db
```

### 7.3 期望看到的输出

后端日志成功示例：

```
video_factory_backend | === AI Video Factory — Backend Startup ===
video_factory_backend | [1/3] Running database migrations...
video_factory_backend |       Migrations OK.
video_factory_backend | [2/3] Seeding default data (idempotent)...
video_factory_backend |       Seed OK.
video_factory_backend | [3/3] Starting Gunicorn...
video_factory_backend | [INFO] Starting gunicorn 22.0.0
video_factory_backend | [INFO] Listening at: http://0.0.0.0:5000
video_factory_backend | [INFO] Booting worker with pid: ...
```

---

## 8. 步骤五：验证部署

### 8.1 检查容器状态

```bash
docker compose ps
```

期望输出：所有容器 `Status` 均为 `running`，`health` 为 `healthy`。

```
NAME                       STATUS          PORTS
video_factory_db           running (healthy)
video_factory_backend      running (healthy)
video_factory_frontend     running (healthy)   0.0.0.0:80->80/tcp
```

### 8.2 API 健康检查

```bash
curl http://localhost/api/health
# 期望响应:
# {"status": "healthy", ...}
```

### 8.3 浏览器访问

打开浏览器访问：

```
http://<服务器公网IP>
```

应看到 AI Video Factory 登录页面。

### 8.4 首次登录 — 注册账户

系统**不创建默认账户**，需要通过注册 API 手动创建第一个账号：

```bash
curl -X POST http://localhost/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "root123456", "email": "admin@test.com"}'
```

成功响应示例：

```json
{
  "data": {
    "user": {"username": "admin", "user_id": "..."},
    "access_token": "...",
    "refresh_token": "..."
  }
}
```

注册成功后打开浏览器，用刚才设置的用户名和密码登录即可。

> **注意**：`/api/auth/register` 接口无需认证，任何人均可调用。
> 如需防止陌生人注册，可在初次注册完成后通过防火墙或 Nginx 限制该端点的外部访问，
> 或将 `API_AUTH_REQUIRED` 与自定义鉴权中间件结合使用。

---

## 9. 日常运维

### 9.1 更新部署（新版本上线）

```bash
cd /opt/video-factory

# 1. 拉取最新代码
git pull

# 2. 重新构建镜像（只重建有变化的层）
docker compose --env-file .env.production build

# 3. 滚动重启（数据库不重启，minimizes downtime）
docker compose --env-file .env.production up -d --no-deps backend
docker compose --env-file .env.production up -d --no-deps frontend

# 如需全量重启
docker compose --env-file .env.production up -d
```

### 9.2 查看运行日志

```bash
# 实时日志（所有服务）
docker compose logs -f

# 最近 100 行日志（指定服务）
docker compose logs --tail=100 backend

# 带时间戳
docker compose logs -t backend
```

### 9.3 备份数据库

```bash
# 导出数据库（替换密码）
docker exec video_factory_db \
    mysqldump -u root -p"${MYSQL_ROOT_PASSWORD}" video_factory \
    > backup_$(date +%Y%m%d_%H%M%S).sql

# 建议定时备份（加入 crontab）
# 每天凌晨 3 点备份
# 0 3 * * * /opt/video-factory/scripts/backup.sh
```

### 9.4 备份用户上传文件

```bash
# 用户上传和生成产物存在 Docker 卷中
# 查看卷位置
docker volume inspect video-factory_backend_storage

# 备份方式：直接 tar 打包
docker run --rm \
    -v video-factory_backend_storage:/data \
    -v $(pwd):/backup \
    alpine tar czf /backup/storage_$(date +%Y%m%d).tar.gz -C /data .
```

### 9.5 停止 / 启动 / 重启服务

```bash
# 停止所有服务（数据不丢失）
docker compose stop

# 启动已停止的服务
docker compose --env-file .env.production start

# 重启某个服务
docker compose restart backend

# 彻底删除容器（数据卷保留）
docker compose down

# 彻底删除包括数据卷（危险！）
docker compose down -v
```

### 9.6 进入容器调试

```bash
# 进入后端容器
docker exec -it video_factory_backend bash

# 在后端容器内运行 Flask CLI
docker exec -it video_factory_backend flask --app run.py --help

# 直接访问 MySQL
docker exec -it video_factory_db \
    mysql -u root -p video_factory
```

### 9.7 资源监控

```bash
# 查看容器资源使用
docker stats

# 查看磁盘使用
docker system df
```

---

## 10. 常见问题排查

### 问题 1：后端启动失败 — 数据库连接超时

**症状：** `backend` 容器不断重启，日志显示 `Can't connect to MySQL server`

**原因：** MySQL 未完全就绪时后端尝试连接

**解决：**
```bash
# 手动等待 MySQL 健康
docker compose logs db | tail -20
# 等待出现 "ready for connections" 后再启动后端
docker compose restart backend
```

---

### 问题 2：镜像构建失败 — npm install 超时

**症状：** 前端 Docker build 卡在 `npm ci` 阶段

**解决：** 使用国内镜像源

```bash
# 在服务器上配置 npm 镜像（可选）
# 修改 deploy/Dockerfile.frontend，在 npm ci 前添加：
# RUN npm config set registry https://registry.npmmirror.com
```

---

### 问题 3：前端访问 502 Bad Gateway

**症状：** 浏览器打开显示 502

**原因：** Nginx 启动但后端尚未就绪

**解决：**
```bash
# 检查后端状态
docker compose ps backend
docker compose logs backend --tail=50

# 等待后端 healthy 后 Nginx 自动恢复
```

---

### 问题 4：上传大文件失败（413 Request Entity Too Large）

**症状：** 上传视频时出现 413 错误

**解决：** 检查 nginx.conf 的 `client_max_body_size` 和 `.env.production` 的 `MAX_CONTENT_LENGTH_MB` 是否一致。默认均为 500MB。

---

### 问题 5：数据库迁移失败

```bash
# 手动在容器内运行迁移
docker exec -it video_factory_backend flask --app run.py db upgrade

# 查看迁移历史
docker exec -it video_factory_backend flask --app run.py db history

# 如需重置（危险！会丢失数据）
docker exec -it video_factory_backend flask --app run.py db downgrade base
docker exec -it video_factory_backend flask --app run.py db upgrade
```

---

### 问题 6：SSE (实时进度) 不工作

**症状：** 任务运行时页面无实时更新

**原因：** Nginx 缓冲配置问题

**解决：** 确认 `deploy/nginx.conf` 中 SSE location 块存在且 `proxy_buffering off` 已设置。

---

### 查看所有容器日志（出现异常时全量排查）

```bash
docker compose logs --tail=200 2>&1 | tee /tmp/debug_$(date +%Y%m%d%H%M%S).log
```

---

## 附录：完整命令速查

```bash
# 首次部署
docker compose build
docker compose --env-file .env.production up -d

# 查看状态
docker compose ps
docker compose logs -f

# 更新上线
git pull
docker compose build
docker compose --env-file .env.production up -d

# 健康检查
curl http://localhost/api/health

# 备份数据库
docker exec video_factory_db \
    mysqldump -u root -p"<密码>" video_factory > backup.sql

# 停止服务
docker compose stop

# 重启服务
docker compose --env-file .env.production restart
```

---

## 附录：已有部署增量更新（模板包 + 视频压缩）

如果服务器已经部署过旧版本，不需要从头初始化数据库或删除 Docker volume。按以下方式增量更新：

```bash
cd /opt/video-factory
git pull
```

不要用新版示例文件覆盖服务器现有 `.env.production`。只检查并追加以下新增/推荐变量：

```env
DEFAULT_VIDEO_UNDERSTANDING_MODEL=qwen3.7-plus

VIDEO_COMPRESSION_ENABLED=true
VIDEO_COMPRESSION_CRF=28
VIDEO_COMPRESSION_PRESET=medium
VIDEO_COMPRESSION_AUDIO_BITRATE=128k
FFMPEG_BINARY=

FAILURE_AGENT_ON_ERROR=true
FAILURE_AGENT_ENABLED=true
FAILURE_AGENT_MAX_RETRIES=1
```

重建并滚动更新后端和前端：

```bash
docker compose --env-file .env.production build backend frontend
docker compose --env-file .env.production up -d --no-deps backend frontend
```

确认新版后端镜像已包含 `ffmpeg`：

```bash
docker exec video_factory_backend ffmpeg -version
```

模板级打包接口：

```http
POST /api/templates/{template_id}/package
GET  /api/templates/{template_id}/package/download
```

模板包现在只包含生产需要的最小内容：`prompts/i2i.md`、`prompts/i2v.md`，或在没有可用主路径/I2I 提示词时包含 `prompts/r2v.md`，再加一个最佳生成视频和 `package_manifest.json`。

视频压缩故障排查：

- 如果 Job 仍成功但事件里出现 `VIDEO_COMPRESSION_SKIPPED`，说明压缩失败后系统已自动回退原视频。
- 如果错误是 `ffmpeg executable was not found`，确认 backend 镜像已重建，并在容器内执行 `ffmpeg -version`。
- 如果压缩后文件大于原文件，系统会保留原视频作为 Artifact，这是预期保护逻辑。
