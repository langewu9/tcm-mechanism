# 远志平台 Windows 启动手册

更新日期：2026-11-03

适用目录：当前仓库根目录
适用配置：原 SQLite 数据库 + Docker Django/Redis/R/分析队列 + 本机 Vite 前端

## 本次问题与处理结果

| 现象 | 原因/判断 | 处理方式 |
| --- | --- | --- |
| 点 Docker Desktop 后网站仍打不开 | Docker Desktop 图形界面打开，不代表 Linux 引擎、项目容器和网页服务都已就绪 | 使用“远志平台一键启动”启动器；它会等待引擎就绪，再按顺序启动并检查各服务 |
| 网页仍停在 `/research`，看起来像没打开 | 浏览器保留了之前的路由；成功启动后需要进入首页根路径 | 启动器验证并打开 `http://127.0.0.1:5173/` |
| 5173 端口被占用 | 曾手动运行 Vite，遗留的前端进程占用了端口 | 本次确认进程命令行属于项目 Vite 后才停止；启动器今后会复用本项目 Vite，遇到其他程序占用时会报错并保留该进程 |
| 点错快捷方式 | `Docker Desktop.lnk` 只启动 Docker Desktop，不启动项目服务 | 桌面另设“远志平台一键启动.lnk”，指向本项目启动脚本；Docker 快捷方式保持原用途 |
| `CreateProcessSecurityEnvironment failed (0x80070020)` | Windows 创建进程失败；重启后仍需由启动脚本逐层确认 Docker、容器和前端。现有记录不足以确定该系统错误的单一根因 | 用启动日志和服务健康检查定位具体阶段；不要仅凭 Docker 窗口已打开判断项目已启动 |
| 遗留日志提到其他前端或数据库命令 | 当前仓库已清理退役的旧运行栈；网站使用 `web/` 的 Vite 前端和 Django API | 只使用本手册列出的入口 |

本次正确启动最终通过了原库文件检查、Docker Compose 容器等待、Django 健康检查、R renderer 健康检查、两个 Celery 队列注册、Vite 首页、API 代理及首页统计接口检查。确认的首页数据库统计为中药 8,967、成分 39,998、靶点 62,920、通路 2,883；数据库更新后数字可能变化。

## 日常一键启动

1. 双击桌面的 **远志平台一键启动**。也可以在项目目录双击 `start-all-services.cmd`。
2. 等待启动窗口显示“所有服务已就绪”或成功提示。首次启动 Docker 引擎可能需要几分钟。
3. 浏览器应打开首页：<http://127.0.0.1:5173/>。如果浏览器未自动弹出，手动访问该地址。

启动器会启动/复用原 SQLite 配置的 Redis、Django API、R renderer、普通分析 worker、R 分析 worker，并启动/复用本机 Vite。它会检查 `python_app\var\qa.sqlite3` 存在且大小正常；不会创建空数据库、迁移数据库或重建镜像。

## 不要混用的入口

- `Docker Desktop.lnk`：仅打开 Docker Desktop。
- `start-all-services.cmd`：项目一键入口，推荐桌面快捷方式调用的同一套流程。
- `deploy\start-original-stack.ps1`：一键入口实际执行的启动和健康检查脚本。
- `deploy\compose.original-sqlite.yml`：当前原数据库 Docker Compose 配置。
- `deploy\compose.python.yml`：另一套 PostgreSQL 配置，不用于本地原 SQLite 数据库启动。
- 不要同时启动另一套项目或占用相同端口的开发服务。

## 故障排查

### 启动失败

先查看 `var\launcher\startup-*.log` 最新文件。前端输出在 `var\launcher\frontend.stdout.log` 和 `var\launcher\frontend.stderr.log`。启动器报错会带出日志路径。

### Docker Desktop 已开但引擎未就绪

打开 Docker Desktop，确认状态为 Engine running，然后重新双击项目快捷方式。启动脚本会等待 Docker 引擎，最长等待 5 分钟。

### 提示 5173 被其他进程占用

不要结束陌生进程。脚本会显示占用 PID。检查该进程命令行，只有确认它是本项目的 Vite 后才关闭；随后重新启动快捷方式。若进程属于其他项目，先关闭那个项目或在其终端正常停止服务。

### 页面能打开但 API 不可用

依次核对：

```powershell
docker compose -p deploy -f deploy/compose.original-sqlite.yml ps
Invoke-RestMethod http://127.0.0.1:8020/api/v1/health/
Invoke-RestMethod http://127.0.0.1:5173/api/v1/health/
Invoke-RestMethod http://127.0.0.1:5173/api/v1/home-stats/
```

### 网站打开在旧页面

访问首页根地址 `http://127.0.0.1:5173/`，不要用浏览器保留的 `/research` 地址判断启动失败。

## 更新项目目录后的快捷方式

在新的项目根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-start-shortcut.ps1
```

脚本会更新桌面“远志平台一键启动”快捷方式，目标为当前目录下的 `deploy\start-original-stack.ps1`。Docker Desktop 自身的快捷方式不会被改写。
