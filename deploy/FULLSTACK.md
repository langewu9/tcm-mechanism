# 全栈构建清单

## 已实现

- Next.js App Router 网站
- TypeScript 严格模式
- Tailwind CSS 设计系统
- Prisma ORM 与 SQLite 默认库
- 迁移 SQL：`prisma/migrations/000001_init/migration.sql`
- seed 脚本：`prisma/seed.ts`
- 登录、注册、退出、角色字段
- 数据上传、检索 API、删除 API
- 医案新增、列表、删除
- 证候到通路的分析任务与保存
- CSV/PDF 导出
- Recharts 可视化
- 管理后台
- 全站浮动本地模型助手
- FastAPI/Qwen/BianCang 服务保留并可代理调用
- API 接入控制台：`/api-integration`
- Next API 代理：`/api/integrations/status`、`/api/integrations/test`

## 启动顺序

1. 启动模型服务：`start_biancang_server.bat`
2. 启动 FastAPI：`D:\mini\envs\py310\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8010`
3. 启动 Next：`npm run dev`
4. 登录后访问 API 接入控制台：`http://127.0.0.1:3000/api-integration`

## 验收命令

```bat
npm run build
npm run prisma:seed
```

接口链路验收：

```text
登录 admin@qihuang.local 后，在 /api-integration 点击“刷新状态”和“一键测试全部”。
至少应看到 FastAPI 健康状态、数据源、疾病检索、靶点交集、成分比对等接口返回成功。
```

## 默认账号

```text
admin@qihuang.local / Admin123!
user@qihuang.local / User123!
```
