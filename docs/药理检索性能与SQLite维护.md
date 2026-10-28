# 药理检索性能与SQLite维护

适用：原Docker SQLite环境的目录中药检索、成分反查及关联查询。

`core.0024_catalog_lookup_indexes`增加主体/客体与关系类型的联合索引，以及实体精确名称、来源观察别名的表达式索引。`0025_catalog_covering_indexes`增加包含活跃状态、关系另一端与来源版本主键的覆盖索引，配合先筛选有界主键、再加载详情的查询，减少读取大表。精确名称仍在数据库端转换大小写，不使用子串匹配，不按名称合并主键。原始证据、来源可见性及每类关系返回限额不变。

部署到已有数据库前先创建一致性备份并检查迁移计划。正常应用0024、0025后，运行一次优化器统计维护；大批导入改变分布后也可再次运行：

```powershell
docker compose -f deploy/compose.original-sqlite.yml -p deploy run --rm --no-deps api python manage.py optimize_catalog_lookup
```

该命令仅更新SQLite的sqlite_stat1规划统计，不修改业务数据，不联网、不重建数据表、不导入或删除记录。默认读取完整索引，执行完恢复连接原来的analysis_limit；缺少0024索引时明确报错，PostgreSQL环境跳过。不要在每个Web请求中运行维护。可用--sample-limit显式限制抽样量，但原库关系类型分布高度不均，少量抽样可能低估高频关系类型，不建议代替部署后的完整统计。

仅增加索引而不更新原库缺失的统计信息，可能使SQLite从全体蛋白节点反向遍历几百万条关系。更新后，使用EXPLAIN QUERY PLAN核验中药→成分→靶点查询是否按已选主体集合使用evidence_subject_type_idx，成分→中药反查是否利用客体索引。

实体来源通过有界批量预取读取；靶点证据不执行不适用的结构去重聚合。没有增加检索结果缓存，库内变更按原可见性规则实时读取。

SQLite每连接页面缓存默认64MiB，可通过SQLITE_CACHE_SIZE_KIB设置512–262144KiB。它缓存数据库页并遵循SQLite的一致性规则，不缓存业务结果；连接寿命、原库路径、WAL设置均保留原配置。

回归：`python manage.py test apps.core.tests.test_catalog_lookup_performance apps.core.tests.test_network_pharmacology apps.core.tests.test_catalog_visualization apps.core.tests.test_disease_evidence apps.sources.tests.test_workbook_import apps.sources.tests.test_master_identity`。测试使用隔离数据库。
