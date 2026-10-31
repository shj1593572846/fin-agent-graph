# 🗄️ fin-agent-graph 数据库架构与 SQL 脚本中心 (Database & SQL Center)

本目录归档系统 MySQL 数据库建库、建表、视图以及数据初始化脚本。

---

## 📁 文件清单

| 文件名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `schema_stock_recommendation.sql` | SQL 脚本 | **标准 DDL 建表脚本**：包含 `stock` 数据库创建、`stock_recommendation` 荐股记录表定义（含联合唯一索引、普通索引）以及中文列名视图 `v_stock_recommendation`。同时挂载于 `docker-compose.yml` 用于 MySQL 容器启动初始化。 |
| `create_stock_table.py` | Python 脚本 | **Python 版自动化建表工具**：使用 `pymysql` 连接本地/远程 MySQL 实例，幂等执行建库、建表与视图创建。 |

---

## 📊 表结构说明：`stock_recommendation`

```sql
CREATE TABLE IF NOT EXISTS `stock_recommendation` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
    `stock_code` VARCHAR(16) NOT NULL DEFAULT '' COMMENT '股票代码',
    `stock_name` VARCHAR(64) NOT NULL COMMENT '股票名称',
    `buy_price` DECIMAL(10, 2) DEFAULT NULL COMMENT '买入价格',
    `close_price` DECIMAL(10, 2) DEFAULT NULL COMMENT '当日收盘价格',
    `buy_date` DATE DEFAULT NULL COMMENT '买入日期',
    `next_day_break_price` DECIMAL(10, 2) DEFAULT NULL COMMENT '第二天跌破均线的价格',
    `is_recommend_success` TINYINT(1) DEFAULT 0 COMMENT '是否荐股成功 (1:成功, 0:失败)',
    `is_monitored` TINYINT(1) DEFAULT 1 COMMENT '是否监控 (1:监控中, 0:未监控/已停止监控)',
    `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX `idx_stock_code` (`stock_code`),
    INDEX `idx_buy_date` (`buy_date`),
    INDEX `idx_is_success` (`is_recommend_success`),
    INDEX `idx_is_monitored` (`is_monitored`),
    UNIQUE KEY `uk_stock_code_buy_date` (`stock_code`, `buy_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

---

## 🚀 执行方式

### 方式一：MySQL 命令行直接导入
```bash
mysql -h 127.0.0.1 -u root -p < sql/schema_stock_recommendation.sql
```

### 方式二：Python 脚本一键执行
```bash
python sql/create_stock_table.py
```

### 方式三：Docker 自动挂载
`docker-compose.yml` 已配置自动将 `./sql/schema_stock_recommendation.sql` 挂载至容器内部 `/docker-entrypoint-initdb.d/01_schema.sql`，首次启动容器时自动执行。
