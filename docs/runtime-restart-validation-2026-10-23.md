# 本机重启与运行验收（2026-10-23）

按用户“重启然后进行测试”的要求，正常重启现有本地 API 和 worker，加载 `bdb7a2c` 的业务修补。没有重启 PostgreSQL、Redis、R 或 Vite，也没有在工作 worker 上强杀进程。网页地址仍为 `http://127.0.0.1:5174/`。

## 重启范围

- 重启前数据库没有排队/运行的分析或同步记录，Celery active/reserved/scheduled 均为空；保存了原 42 个任务及相关研究记录、目录的只读指纹。
- 先停止 API，复核 worker 空闲，再以 SIGTERM 正常停止 worker；没有使用 SIGKILL。API PID 从 603781 变为 648099，worker 从 603782 变为 648100。
- 原本本地启动器采用 solo，不能执行 prefork 父进程的子进程丢失/硬超时钩子。本次将该本机启动器固定为 **prefork、并发 1**；没有修改生产的超时参数或业务算法。Celery 实际 stats 返回 `celery.concurrency.prefork:TaskPool`，子进程为 648176，七个业务任务已注册。

## 重启后实际检查

| 检查 | 结果 |
| --- | --- |
| 直连 API 和前端同源代理的健康接口 | 均为 HTTP 200 |
| 首页、研究页、蛋白组学页 | 三个 HTML 页面入口均为 HTTP 200；不计作完整浏览器交互或视觉验收 |
| 新测试任务 #43 | 通过真实同源 HTTP、登录/CSRF、Redis、常驻 prefork worker 和 PostgreSQL，约 0.048 秒执行成功 |
| 结果持久化与导出 | 12 个报告章节，完整 JSONL 的表记录数/校验值及 CSV 章节数一致；重新读取结果不变 |
| 权限 | 另一研究者读取详情、快照分页、导出均为 404；管理员读取仍保留原所有者 |
| 同一任务重复投递 | 实际 worker 返回 skipped，结果不变，没有新建另一业务任务 |
| 原有记录 | 原 42 个任务、原快照、数据集/行结果、医案/候选、工件、来源、实体和标识按重启前上界核对内容哈希一致；约 498 万条关系仅核对总数和最大编号，没有逐条重新哈希 |
| 恢复专项回归 | 独立临时 PostgreSQL 测试库执行 31 项全部通过，0 跳过，0.560 秒；测试库已销毁，无残留 |

任务 #43 的输入明确标注 `SYNTHETIC_RESTART_ACCEPTANCE_20261023`，疾病/中药使用不存在的合成查询词，来源命中为空。这证明重启后的任务基础链路能完成，不是实际实验、真实科研结果正向验收或医学结论验证。模型、外部科学服务及上传实验均未调用。新增业务写入仅此一个命名测试任务及其冻结章节；登录会话、最近登录和敏感访问审计属于预期附带写入，没有重算或修改旧研究任务。

私有证据保存在 Git 忽略的 `python_app/var/restart-validation-2026-10-23/`：`before.json`、`processes.json`、`runtime.json`、`verified.json`、`http-state.json`、`smoke-task.jsonl`、`smoke-task-report.csv`、`recovery-postgres.log` 及 API/worker 日志。账号凭据没有进入 Git，也没有在报告中显示。

本次只验证正常重启及运行链路。子进程/整个 worker 强制退出和硬超时的破坏性演练仍以此前隔离证据为准，参见 [中断与保守恢复](task-interruption-recovery-2026-10-23.md)。整个父进程消失、数据库不可用、发布锁占用等情况下仍可能需要维护命令，正常重启不会取消这些既有边界。
