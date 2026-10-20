# 合作分支优先修复与验证

本轮以 `codex/django-foundation-hardening` 的 `3ae71c6` 为基线，在独立分支实现；不替换原始数据库，不下载或修改模型，不直接合并 main。

## 1. 登录保护

会话 API 的 POST 同时按 IP（默认 30 次/分钟）和规范化账号（默认 10 次/分钟）限流，返回现有 `RATE_LIMITED` 错误结构及 `Retry-After`。GET 会话状态和 DELETE 退出不计入限额。账号缓存键仅保存哈希，不保存密码。生产 API 使用 Redis 共享限流状态；开发默认内存缓存仅用于单进程。

生产 Nginx 对 API 登录、旧登录页面及管理后台登录增加 POST 限流，不限制普通后台表单提交。API 的 DRF 限流是非原子应用级保护，Nginx 提供入口级保护；它们不代替强密码、HTTPS 和监控。`NUM_PROXIES=1` 要求生产 API 只能经可信 Nginx 访问，不能另行开放 API 端口。

环境变量 `DJANGO_LOGIN_IP_RATE`、`DJANGO_LOGIN_ACCOUNT_RATE` 可调整应用级限制。Nginx 的入口限制需调整 `deploy/nginx/rate-limits.conf`。

## 2. 邮箱身份约束

迁移 `0021_unique_user_email` 为现有用户表创建 `LOWER(TRIM(email))` 非空邮箱唯一索引，支持项目的 PostgreSQL 和 SQLite。无需切换用户模型，允许系统账号不填邮箱。注册和管理员表单采用相同查询表达式；并发注册命中数据库约束时返回邮箱字段错误。

部署前先备份数据库，再执行 `python manage.py migrate --noinput`。如果历史账号存在重复邮箱，迁移停止并报告首个用户 ID 和重复数量，需管理员审核身份后处理；本迁移不会删除、合并用户或研究数据。该索引由数据库迁移管理，而非默认 Django User 模型的字段定义；直接导入/写入数据库同样受约束。SQLite 对非 ASCII 字符的 LOWER 规则与 PostgreSQL 不完全一致，国际化邮箱需另行制定一致规范。

## 3. 定时数据源预览

保持现有连接器：Reactome、UniProt、PubChem、STRING，以及经过审核配置的本地 SQLite 文件。调度只调用现有预览任务，不调用 apply，不自动认可证据或重建静态数据库。

管理员在数据源设置 `enabled=true` 和 `refresh_interval_hours>=1`。空值或 0 不定时执行。设置 `SOURCE_SCHEDULED_PREVIEWS_ENABLED=true`，重新创建 worker，再启动唯一的 beat 实例：

```sh
# 开发：先启动并确认 API 迁移完成，再启动调度器
docker compose -f deploy/compose.python.yml up -d api worker
docker compose -f deploy/compose.python.yml --profile scheduler up -d beat

# 生产：将开关写入 .env.production，服务构建/健康检查通过后启动
docker compose --env-file .env.production -f deploy/compose.production.yml --profile scheduler up -d --build
```

beat 每分钟扫描一次；每个数据源依据最近尝试/成功时间和刷新间隔决定是否到期。PostgreSQL 行锁和持久时间戳防止重复调度；存在 pending/running 任务时跳过。Redis 投递失败会记录 failed 并按刷新间隔退避。停用开关后重新创建 worker/beat；停用单个数据源会同时阻止其同步任务执行。

管理员仍需审核预览差异、版本和校验和后使用原有 apply 接口入库，之后原有统一标识/关系证据链继续生效。任务若因进程崩溃长期停留 pending/running，应核对队列和运行日志后人工处理，不能盲目重置或重复入库。SQLite 本地开发不提供 PostgreSQL 同等级的并发锁保证；生产调度应使用 PostgreSQL。

## 4. 协作自动验证

`.github/workflows/platform-checks.yml` 对 PR 和 main/codex 分支推送运行：SQLite/PostgreSQL 两种数据库迁移、模型漂移检查、Django 测试、OpenAPI 校验；前端锁定依赖安装、API/研究请求/网络图回归、TypeScript 检查和生产构建。只使用 CI 测试数据库及测试密码，不连接生产数据或模型服务。

这些检查不等同于真实供应商 API、R 容器、TLS、SMTP、S3 的上线验收。建议仓库管理员将检查设为合并必需状态；本轮不修改分支保护规则。

## 5. Windows 回归一致性

中文 JSON 测试基准显式按 UTF-8 读取；源码基准哈希统一 CRLF/LF 后比较，仍保留原 SHA-256 校验；SQLite 合成测试使用显式关闭连接的上下文，避免 Windows 文件占用导致清理失败。这里仅调整测试资源管理，不改旧数据库、旧数据服务或科学统计结果。
