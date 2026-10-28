# 原数据库 Docker 启动说明

本地恢复日期：2026-10-25。

## 一键打开（2026-10-26）

双击桌面 **远志平台一键启动**，或项目根目录的 `start-all-services.cmd`。

入口会按顺序启动 Docker Desktop、Redis、原数据库 Django、R 渲染服务、普通分析队列及 R 图表队列，
检查后端、R 与队列状态，再启动前端并在默认浏览器打开 http://127.0.0.1:5173/。
已有服务会被复用；其他程序占用前端端口时会报告错误，不会结束该程序。
首次打开 Docker Desktop 后，等待引擎就绪可能需要几分钟。

启动日志：`var/launcher/startup-*.log`；前端日志：`var/launcher/frontend.stdout.log` 和 `frontend.stderr.log`。
启动失败会弹出提示并给出日志位置。此入口不重新构建镜像、安装依赖、迁移或重建数据库。
当前已安装的 Docker、Node.js、前端依赖及镜像必须保留。

更换项目目录后，可重新运行 `deploy/install-start-shortcut.ps1` 创建指向新目录的桌面入口；
同名快捷方式存在时，安装脚本会拒绝覆盖，应先自行重命名旧入口。

## 当前数据来源

- 原库：`python_app/var/qa.sqlite3`，约 3.10 GB。
- Docker 内路径：`/app/var/qa.sqlite3`。
- 整个 `python_app/var` 绑定挂载，保留同目录的 WAL/SHM 以及原 `media` 文件。
- 已核对 109,945 条知识实体及启用的原管理员账号；未修改密码。
- 已创建一致性备份：`D:/MMDD/backups/original_database_20261025_01/qa.sqlite3`，`quick_check=ok`，实体数量一致。
- 原 PostgreSQL 容器和数据卷保留，但本配置的 API/worker 不再连接它。

## 以后使用这份配置启动

在项目根目录运行：

```powershell
docker compose -p deploy -f deploy/compose.original-sqlite.yml up -d --build redis r-viz api worker r-worker
```

不要使用旧 `compose.python.yml` 的 API 启动命令；它连接另一套 PostgreSQL 数据库。
不要运行 `down -v`、重建数据库、重新导入或清空用户表。

本配置启动时先验证原库挂载并执行 `migrate --check`，仅检查，不应用迁移。
库文件缺失、空库或迁移不匹配时会拒绝启动，不会创建空库替代。
Redis、API、普通分析 worker、R 服务及 R worker 设置为 `unless-stopped`；仍需 Docker Desktop 引擎处于运行状态。
首次启动需要构建 R 镜像、下载运行环境并按 `r_viz/renv.lock` 安装依赖。
普通分析仅消费 `celery` 队列；R 图表由独立 `r-worker` 消费 `r_visualization` 队列，
且必须等 `r-viz` 健康后启动。R 端口不发布到宿主机，API/R worker 通过内部网络访问。

## 前端

前端继续使用本机 Vite，入口 http://127.0.0.1:5173/，API 代理到 127.0.0.1:8020。
如前端未运行，在 `web` 目录运行：

```powershell
npm run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

使用原账号密码登录。切换数据库后，旧空库的登录会话不能直接沿用。

## 核验

```powershell
docker compose -p deploy -f deploy/compose.original-sqlite.yml ps
Invoke-RestMethod http://127.0.0.1:8020/api/v1/health/
Invoke-RestMethod http://127.0.0.1:5173/api/v1/home-stats/
```

本次核验：首页中药 8,967、成分 33,045、靶点 63,923、通路 2,883。
这些是核验时点的数据，不应硬编码进网页。

## 范围与限制

这是本地原库恢复配置，不是生产部署或 SQLite 向 PostgreSQL 的迁移方案。
任务进程使用单进程并发，减少本地 SQLite 写锁竞争；正式多人部署应另行规划数据迁移。
本次仅恢复数据库、API 和任务进程；不启动模型、定时同步或重新生成演示数据。
R 渲染服务已纳入同一 Compose 配置；API/登录正常不等于 R 服务健康，
可通过 `docker compose ... ps` 查看 R 容器状态。图表重试新建任务，不覆盖历史失败记录。

## R 服务修复验收（2026-10-25）

- R 镜像补齐 Linux 编译依赖和中文字体，修复 renv 下载地址、安装权限及运行时包目录。
- 已验证 Docker 内网中的 7 类网络/富集图各生成 SVG、PDF、PNG、HTML，未授权请求及非法节点输入被拒绝。
- 原合成分析任务 #33 的火山图通过 Docker R 四格式渲染；网页提交的分析概览图任务 #37 由正式 `r-worker` 成功完成。
- 临时本机 R 与临时图表消费者已停止，当前由 Compose 中的 `r-viz` 和 `r-worker` 提供服务。原数据库、用户密码和模型保持不变。

## 后续备份

停止新的写入/任务提交后，可使用一致性备份工具；目标必须是不存在的新文件：

```powershell
python deploy/backup_original_sqlite.py python_app/var/qa.sqlite3 D:/MMDD/backups/new_backup/qa.sqlite3
```

工具以只读模式连接原库，使用 SQLite backup API，并校验备份实体数及完整性。
