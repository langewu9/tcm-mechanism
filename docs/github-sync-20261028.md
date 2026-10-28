# 2026-10-28 协作版本同步

本次将本地近期开发与已经合入 main 的协作修改汇合。保留管理员边界、访问审计、上传配额、归档与历史任务恢复，补齐数据库主表、参考医案、首页和 R 可视化功能。

## 本次功能

- 首页保留纸面底图和卷轴，加入标题逐字出现、统计累加、卷轴收放和响应式布局；统一界面字体、分栏高度和四角卡片。
- 检索接入多来源实体主表、别名、结构标识和可核验的人类靶点映射；保留来源版本、原始记录号及无法统一的候选状态。
- 参考医案使用独立的 case_rag 数据库。导入器支持原有 2500 例和新增综合分类 2000 例，含分类检索、分页、详情、版本和引用快照。仓库不包含原始医案或数据库文件。
- R 0.4.2 提供圆形交互网络、名称定位、图例筛选、关联高亮和四种导出。演示图库为 16 类较大合成数据及 7 类公开 STRING 示例，采用六卡片分页和独立图窗。
- 启动脚本继续支持原 SQLite Docker、Django、Celery、R 和前端。模型配置与权重保持原状。

## 升级与数据准备

1. 备份当前业务数据库、参考医案 SQLite 和私有上传存储。不要在运行中的旧目录直接覆盖代码或切换空 PostgreSQL 数据卷。
2. 在独立检出目录安装 `python_app/requirements.txt`，前端使用仓库指定的 pnpm 9.15.9 执行 `pnpm install --frozen-lockfile`。
3. 配置本机 `.env` 和私有数据挂载。执行以下命令，或由生产 Compose 的 setup 服务执行迁移：

```sh
cd python_app
python manage.py migrate --noinput
python manage.py migrate case_rag --database=case_rag --noinput
```

`core/0028_merge_platform_updates` 同时依赖主表/靶点分支的 0026 和审计/配额分支的 0027。两侧已经应用的迁移文件名均保留，不能删除迁移历史或使用 `--fake` 跳过检查。

仅在空的参考医案库首次部署时，由有内部使用权限的成员提供私有工作簿并导入：

```sh
python manage.py import_case_rag /private/original-cases.xlsx --expected-total 2500 --dry-run
python manage.py import_case_rag /private/original-cases.xlsx --expected-total 2500
python manage.py extend_case_rag /private/linglan-cases.xlsx --expected-source-count 2000 --expected-total 4500 --dry-run
python manage.py extend_case_rag /private/linglan-cases.xlsx --expected-source-count 2000 --expected-total 4500
```

已配置的医案库应使用备份与恢复流程，不要重复初始化。医案数量以实际成功导入后的 summary 接口为准。未知物种、缺少可核验编号的记录保留待核验状态。

## 演示图表与构建

生成图表前启动与本版本匹配的 R 服务，在本机环境设置 `R_VIZ_BASE_URL` 和 `R_VIZ_API_TOKEN`：

```sh
python r_viz/test_demo_fixtures.py
python r_viz/prepare_demo_gallery.py
python r_viz/prepare_public_gallery.py
cd web
pnpm build:delivery
```

公开示例默认读取仓库中的 STRING 12.5 快照；合成数据与公开示例都不写入业务数据库。`public/r-demo`、`public/r-public-demo` 为可再生成的忽略目录，完整交付构建会校验 23 类图表及 92 个 SVG/PDF/PNG/HTML 文件的哈希。生产 Nginx 镜像构建前必须完成此步骤。

## 本地验证

- 隔离 Linux Docker、内存 SQLite：588 项后端测试完成，1 项环境相关测试跳过，其余通过。
- `makemigrations --check --dry-run`、OpenAPI schema 验证及 4 项 R 演示数据契约测试通过。
- 前端 API、查询、网络、来源管理、任务恢复、演示图库、R 交互及字体检查通过；`build:delivery` 通过。
- 已用本版本 R 源码重新生成全部 23 类图表并验证输入与产物哈希。
- 4 项备份脚本测试通过；Shell 文件固定 LF，避免 Windows 检出导致 Linux 执行失败。

这些检查使用隔离环境及合成测试数据。真实 SMTP、S3、生产域名、模型推理和线上容量不在本次代码同步验证范围内。GitHub Actions 继续分别验证 SQLite、PostgreSQL 和前端。
