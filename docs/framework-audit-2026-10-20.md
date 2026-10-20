# 基础框架检查与修补（2026-10-20）

后续数据库性能审核已为当前前端接入轻量列表，并增加三项有执行计划对照的索引；旧完整列表仍兼容保留。最新状态及本文“大结果列表”后续处理进展见 [数据库性能审核](database-performance-audit-2026-10-20.md)。下文保留本轮基础框架审核时的范围和测量记录。

## 任务管理后台只读补充

2026-10-20 后续安全核查确认：`AnalysisTaskAdmin` 原先只有时间字段只读，有任务修改权限的后台账号可手工改写所有者、创建者、输入、结果和来源版本。新增回归在修补前复现了超级管理员伪造修改请求被接受并重定向（302）。

现在任务后台的全部字段（包括 `source_releases` 多对多来源版本）只读，同时明确禁止新增、修改、单条删除和批量删除。超级管理员和拥有任务模型权限的 staff 账号同样不能通过直接 POST 重新开启写入。仍可按原查看权限检索和查看任务；本次没有调整其他后台模型的查看权限。

限制只作用于 Django 管理后台，研究服务和分析 worker 仍负责正常创建任务、更新状态并保存结果。没有修改数据库表或研究者页面，也没有增加重算/版本管理接口。该措施防止管理界面误改历史记录，不是对直接数据库访问的防篡改保证。

验证：新增 6 项后台保护回归通过；SQLite 全量 427 项通过（45.697 秒）；隔离 PostgreSQL 的后台保护、蛋白组学 API/业务、科研助手及目录任务共 50 项通过（7.123 秒）。测试使用合成数据和临时测试库，模型及外部生物接口未调用。日志保存在 Git 忽略的 `python_app/var/framework-audit/task-admin-*.log`。

## 本轮结论

在现有 React/Vite + Django 架构上完成一轮基础修补，覆盖错误边界、隐私缓存、输入限额、共享限流、列表查询和部署启动顺序。没有新增业务模块，没有改页面组件、布局、CSS 或研究算法；没有调用模型或外部生物数据库。SQLite 和 PostgreSQL 各 413 项后端测试、前端回归及交付构建通过。真实本机 Nginx → Gunicorn → Django → 隔离 PostgreSQL 链路通过了 TLS、会话、权限、缓存、限流和小规模并发验证。

这是一轮代码及本地验证，不是完整公网安全认证或生产容量验收。修改保存在本地 Git，本轮没有推送远程。

## 已确认并修补的问题

| 方面 | 实际问题 | 修补及影响 |
|---|---|---|
| 错误边界 | Django 会把视图异常先转换为响应，原先外层 try/except 捕捉不到；开发模式能返回包含异常文本的 HTML 500 | 增加 `process_exception` 和响应兜底。API 500 统一安全 JSON，不返回内部异常内容；保留 404/403 语义、请求编号及必要的重试响应头 |
| 数据隐私 | 会话、任务和数据集响应没有统一的禁止缓存策略 | 所有 API 响应，包括错误和私有文件流，设置 `private, no-store`、`Vary: Cookie`；继续由服务端会话和所有者权限控制访问 |
| 输入限制 | 普通 API JSON 缺少独立的有界读取及嵌套限制；密码长度没有上限 | 普通请求默认 1 MiB，JSON 有界读取并限制 64 层，密码最多 1024 字符；保留独立的 100 MiB 文件上传额度和单文件约束，验证合法大于 1 MiB 的 CSV 仍可上传 |
| 资源消耗 | 普通用户接口和多种研究提交缺少统一预算 | 增加按用户的 600/min 普通预算和 120/hour 研究提交预算；生产 Redis 在 API 进程之间共享计数，保留已有登录和外部服务限流 |
| 列表性能 | 任务逐条查询来源版本、数据集逐条查询所有者 | 任务预取来源，数据集/医案关联预加载用户；分页和响应字段保持兼容 |
| 管理统计 | 用户资产计数同时关联多张一对多表，容易产生中间结果乘积 | 改为各资产的独立关联计数子查询，保留原有管理员接口结构 |
| 生产启动 | 各 API 启动过程都执行迁移，worker 未明确等待迁移完成 | 独立一次性 `setup` 执行生产检查、迁移和静态收集；API/worker 等待成功退出，Gunicorn 独立管理进程数、超时和请求回收 |
| 入口防护 | 默认虚拟主机可接收未知 Host；转发链可能保留用户伪造内容；网关错误不统一 | 拒绝未知 Host/SNI，单入口覆盖转发 IP/协议；413、429、上游故障返回带请求编号的 JSON。Django/Gunicorn 必须继续放在私有网络 |
| 静态缓存 | SPA HTML 缺少明确更新策略 | HTML `no-cache`，带哈希静态资源一年缓存并压缩；私有代理响应不压缩，私有媒体路径不走静态公开目录 |
| 日志关联 | URL 查询参数可能进入访问日志，代理编号与后端编号不一致 | Nginx/Gunicorn 不记录 query string，代理 API 日志使用后端响应编号；实际合成标记验证未进入日志，同一请求编号能在两份日志中找到 |
| 构建上下文 | `.env.production` 等变体、证书或数据库备份可能进入 Docker 构建上下文 | 补充忽略 `.env.*`、TLS 证书、备份及 dump；保留安全的环境配置示例 |
| 备份与恢复 | 默认权限下新 dump 可能对其他本机用户可读；恢复缺少单事务要求，未停止可选调度器 | 备份使用 `umask 077`；恢复保留校验和及人工 `RESTORE` 确认，停止 api/worker/beat/setup 等写入服务，使用 `--single-transaction` |

扩展边界维持原有分层：`web/` 管页面，`python_app/apps/*/views` 管 HTTP，业务服务及连接器保留在原模块，`config/` 管统一基础能力，`deploy/` 管入口和进程配置。没有为本次修补再引入一个框架或认证系统。

## 实测证据

### 后端和前端

- 升级后：SQLite 413 项通过（52.574 秒），PostgreSQL 413 项通过（76.622 秒）。新增 18 项基础框架回归，包含错误脱敏、流读取限额、深层 JSON、非文本编码、文件上传、查询数、越权和限流。
- `check`、`makemigrations --check --dry-run`、OpenAPI 校验通过，无模型变更或新增迁移；`pip check` 无依赖冲突。
- 生产参数下 `check --deploy --fail-level WARNING` 通过。只明确豁免可选的 HSTS 全子域及 preload 两项提示（W005/W021），避免在未取得域名整体控制时自动要求这些政策；其他生产告警仍保留。
- `web` 的 API、研究、网络、来源、R 目录、演示测试，以及 `build:delivery` 通过。14 类图表、56 个合成 R 工件的交付校验通过，本轮未重新调用 R 或模型。
- 依赖更新前后生成的 CSS 文件与语义树均完全相同，SHA-256 为 `e3fadffc6b745f1c962600d8bcd938af0d9544654734aba270d79cf62664b13e`。这能确认本次样式产物没变，不替代全站视觉验收。
- 使用合成配置通过 `docker compose ... config --quiet`；实际 Nginx 配置 `nginx -t` 和 Gunicorn `--check-config` 通过。没有在本轮构建或启动完整生产 Compose。
- 备份脚本 4 项测试通过：新目录/文件权限、失败清理、取消恢复不触碰服务、停止写入方及事务参数。Docker 被测试替身替代，这些测试没有执行真实生产恢复。

### 查询与小规模并发

相同隔离数据库、相同研究者、相同输入；只读取已有本地验收记录。查询计数用强制认证的 APIClient 和数据库只读事务，避免把登录流程混入查询对比。

| 接口 | 修补前查询数 | 修补后查询数 | 实测数据量 |
|---|---:|---:|---|
| 任务列表 | 15 | 3 | 13 个任务，644,862 字节 |
| 数据集列表 | 5 | 2 | 3 个数据集，1,719 字节 |

另有 20 条记录的自动回归验证查询数仍为任务 3 次、数据集 2 次，避免逐条增长。

真实 HTTPS 代理测试采用 Nginx 1.28.3、Gunicorn 26.2.0 两个同步 worker、Django 5.2.18、DRF 3.18.3 和 PostgreSQL 17.11。5 个并发客户端共读取 50 次任务/数据集列表，失败 0 次，耗时 0.814 秒，单次延迟 p50 78.00 ms、p95 102.46 ms、最大 124.00 ms。结果会受机器负载影响，不能推算公网人数或正式数据容量。

同一链路验证了 HTTPS 跳转、未知 Host/SNI 拒绝、安全会话 Cookie、CSRF、研究者之间的数据隔离、静态 gzip/缓存、SPA 缓存，以及 JSON 400/401/403/404/413/429。变换伪造的 `X-Forwarded-For` 无法绕开入口 IP 限流。停止本轮测试上游后，代理返回安全 JSON 503，带缓存保护、安全头和一致请求编号。

临时 TLS 证书只用于本机测试域名，未修改系统信任库，也不是正式站点证书。测试账号及数据位于隔离的 `tcm_acceptance` 库；原 SQLite 预览数据没有覆盖。

## 依赖公告核对

按用户选择，没有将 Python 环境包名和版本清单发送给 OSV，也没有换用其他服务提交同一清单。Python 部分只完成本地依赖冲突检查及重点框架的官方公告核对，不能声称全量依赖无漏洞。

| 组件 | 本轮处理 | 依据与边界 |
|---|---|---|
| Django | 5.2.17 → 5.2.18；提高 requirements 下限 | [官方 5.2.18 安全发布说明](https://docs.djangoproject.com/en/5.2/releases/5.2.18/)；保留 5.2 分支 |
| DRF | 3.18.1 → 3.18.3；下限提高到 3.18.3 | [官方发布说明](https://www.django-rest-framework.org/community/release-notes/)：3.18.2 的请求处理等安全修复及 3.18.3 的兼容修正；没有对线上服务做拒绝服务攻击测试 |
| Gunicorn | 本轮测试先使用旧声明的 23.0.0，官方核对后改为 PyPI 可取得的 26.2.0，下限 26.2 | [维护政策](https://github.com/benoitc/gunicorn/security)不再维护 23.0.0；验证了同步 WSGI 配置，未启用 ASGI/HTTP2 上游或运行控制套接字 |
| PostCSS / selector parser | 固定为 8.5.23 / 7.1.6，更新 pnpm 锁文件 | [PostCSS 公告](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp)、[selector parser 公告](https://github.com/advisories/GHSA-rj75-hqrm-r3gf)；前端全依赖审计由 6 项降为 1 项，生产依赖审计报告为 0 项 |
| braces 3.0.3 | 仍保留并明确记录 | [上游公告 GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)未提供补丁版本；位于 Tailwind 构建依赖链，当前只处理仓库可信构建配置，不在最终 Nginx 静态运行镜像中。不得向构建器开放用户自定义 glob/CSS 输入。没有屏蔽这条公告，也不能称全部依赖已经清零 |

Celery/redis-py 官方维护者公告页面也做了人工查看，不能据“没有列出公告”断言不存在漏洞。容器基础镜像、系统包和正式服务器补丁状态需要部署环境继续核对。

## 仍需后续处理的基础问题

1. **大结果列表仍偏重。** 当前任务列表为了兼容现有 UI，仍带完整结果 JSON；13 条已约 630 KiB。查询数已下降，响应体没有缩小。数据增长后应另行协调前后端的轻量摘要列表与详情读取；管理员用户总览也仍需分页。
2. **限流不能替代容量与抗攻击措施。** DRF 共享缓存限流有并发竞态；还缺正式数据规模、长时间并发、上传解析、后台任务堆积及多副本故障测试。worker 硬退出后遗留 running 任务的恢复/告警也需专项验证。
3. **生产服务尚未联合验收。** 全部容器构建/启动、真实 DNS/TLS 续期、邮件收件、私有 S3 读写和备份对象恢复、正式防火墙与日志轮转仍待目标环境验证。本地 health 只说明 API/数据库可用，不代表模型、队列、外部数据或全部依赖健康。
4. **恢复前必须隔离旧队列。** PostgreSQL 与 Redis 并非同一事务快照；恢复数据库后不能直接消费旧任务。脚本不自动删除任何队列，以免误删待执行工作，需维护窗口人工处置。
5. **依赖检查有明确范围。** 全量 Python 在线漏洞核对未执行，前端仍有上述构建依赖公告；不能将编译或测试通过解释为不存在安全问题。
6. 既有的物种/规范编号确认、真实业务黄金样例、模型与外部生物接口，继续按此前安排暂缓，不混入本轮框架验收结论。

## 重跑入口

普通本地逻辑验证可不连接 Redis：

```sh
DJANGO_DEBUG=true DATABASE_URL=sqlite:///:memory: CACHE_URL='' \
  python_app/.venv/bin/python python_app/manage.py test apps.core apps.proteomics apps.sources --noinput
python_app/.venv/bin/python tools/test_backup_scripts.py
```

隔离 PostgreSQL 环境已准备好的机器可使用：

```sh
python_app/.venv/bin/python tools/postgres_acceptance.py manage test apps.core apps.proteomics apps.sources --noinput
python_app/.venv/bin/python tools/framework_acceptance.py prepare
python_app/.venv/bin/python tools/framework_acceptance.py api --check-config
# 各开一个终端运行 api 和 proxy；只监听本机 8022、8084、8444。
python_app/.venv/bin/python tools/framework_acceptance.py api
python_app/.venv/bin/python tools/framework_acceptance.py proxy
python_app/.venv/bin/python tools/smoke_framework_acceptance.py
# 确认停止的只是本轮 8022 测试上游后，可验证网关故障。
python_app/.venv/bin/python tools/smoke_framework_acceptance.py --unavailable
```

这些辅助入口依赖未提交的本机隔离账号配置和 Nginx 运行时，不是其他机器开箱即用的部署脚本。日志、版本审计、CSS 对照与测量 JSON 保存在 Git 忽略的 `python_app/var/framework-audit/`；不包含在远程提交中。

本轮临时 Nginx/Gunicorn 已在验收后停止。隔离 PostgreSQL 预览 `http://127.0.0.1:5174/` 的 API/worker 已重启以加载本次代码，首页、健康接口和会话读取返回 200，新缓存头生效。原 `5173/8020` SQLite 预览及其数据没有覆盖。
