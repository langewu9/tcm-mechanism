# 当前架构与模块边界

## 运行结构

```text
浏览器
  └─ React + Vite（web/；开发端口 5173）
       └─ /api/* 通过开发代理转发
            └─ Django REST Framework（python_app/；开发端口 8020）
                 └─ PostgreSQL（研究数据与溯源）
```

开发代理已经配置；公网需要 Nginx 或等效反向代理，把 `/` 指向 React 静态构建，把 `/api/`、`/admin/` 和 `/accounts/` 指向 Django。生产代理、部署容器和 TLS 还没有实现。

原 `src/` Next.js 页面、组件和 CSS 尚留在仓库中供迁移参考。`web/` 目前恢复了首页的 React 结构与原 CSS，并把 Next 专用的 `Link`、`Image`、Prisma 统计替换为 React Router、普通图片和 Django 计数 API。旧研究组件并没有自动成为已接通页面；接入时要逐个核对它调用的接口和后端业务。

## 后端模块

Django 当前保留一个 `core` 应用标签和现有迁移历史，内部先按业务边界拆包：

- `apps/core/domain/sources.py`：数据源、版本、同步记录。
- `apps/core/domain/knowledge.py`：中药/成分/疾病等知识实体和带来源的证据关系。
- `apps/core/domain/research.py`：数据集、去标识化医案和分析任务。
- `apps/core/views/auth.py`：CSRF token、会话状态、登录和退出。
- `apps/core/views/catalog.py`：知识目录查询与首页计数。
- `apps/core/views/research.py`：研究者个人工作区 API。
- `config/api_errors.py`：DRF 错误格式、Django API 404/500、CSRF 错误和请求 ID。

API 按模块分组：

| 模块 | 路径前缀 | 主要数据 |
|---|---|---|
| 认证 | `/api/v1/auth/` | 登录会话、CSRF、退出 |
| 研究工作区 | `/api/v1/research/` | 数据集、医案、分析任务 |
| 知识目录 | `/api/v1/catalog/` | 数据源、实体、证据关系 |
| 平台状态 | `/api/v1/health/` | 服务与数据库可用状态 |

模块拆分不改变现有数据库表名和迁移编号。以后模块增长到需要独立发布、权限配置或迁移边界时，再拆成独立 Django apps。

## 错误响应

所有 API 错误使用同一结构：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "提交的数据无效，请检查后重试。",
    "details": { "name": ["This field is required."] },
    "requestId": "每次请求生成的标识"
  }
}
```

`details` 用于字段级校验反馈；内部异常不向客户端暴露堆栈或数据库细节，日志使用同一个 request ID 关联排查。

## 身份和数据可见性

登录使用 Django 服务端 session，不由前端自报用户 ID。后端在创建数据时填入 `request.user` 作为创建者；研究者查询仅返回本人数据，超级管理员可以查看全部。浏览器的状态变更请求须带 CSRF token。后续对公开研究者账户和数据访问授权的细化仍需在注册、角色和审计阶段实现。

## 后续填充顺序

1. 从旧组件确认实际交互和接口参数，先迁移登录和研究工作台的静态 UI。
2. 按 `research`、`catalog`、`analysis`、`admin` 模块补 API 与业务服务；接口错误继续遵循统一格式。
3. 补文件存储、Celery/Redis、数据库同步、本地模型及 R 可视化连接。
4. 配置反向代理、生产 PostgreSQL、对象存储、HTTPS、备份和部署检查。

当前首页和登录可运行；账号自助注册、上传和分析执行仍未实现。首页中的研究流程文案表示目标能力，不代表当前服务已提供。
