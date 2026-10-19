import sys
import pymysql

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 数据库连接配置
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "charset": "utf8mb4",
}

# 1. 确保 stock 数据库存在
CREATE_DB_SQL = "CREATE DATABASE IF NOT EXISTS `stock` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2. 建表语句 (标准英文列名 + 中文注释与索引)
CREATE_TABLE_SQL = """
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='股票荐股与收益评估记录表';
"""

# 3. 创建中文视图 (方便直接使用中文列名看盘/导出)
CREATE_VIEW_SQL = """
CREATE OR REPLACE VIEW `v_stock_recommendation` AS
SELECT 
    `id` AS `主键`,
    `stock_code` AS `股票代码`,
    `stock_name` AS `股票名称`,
    `buy_price` AS `买入价格`,
    `close_price` AS `当日收盘价格`,
    `buy_date` AS `买入日期`,
    `next_day_break_price` AS `第二天跌破均线的价格`,
    `is_recommend_success` AS `是否荐股成功`,
    `is_monitored` AS `是否监控`,
    `created_at` AS `创建时间`,
    `updated_at` AS `更新时间`
FROM `stock_recommendation`;
"""

def main():
    print("🔌 正在连接本地 MySQL 数据库 (127.0.0.1:3306)...")
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            # 1. 确保库存在
            cursor.execute(CREATE_DB_SQL)
            cursor.execute("USE `stock`;")
            print("📁 已选定 stock 数据库")

            # 2. 创建核心表
            cursor.execute(CREATE_TABLE_SQL)
            print("✅ 数据表 `stock_recommendation` 创建成功！")

            # 兼容已有旧表：检查并动态添加 is_monitored 字段
            cursor.execute("SHOW COLUMNS FROM `stock_recommendation` LIKE 'is_monitored';")
            if not cursor.fetchone():
                cursor.execute("""
                    ALTER TABLE `stock_recommendation` 
                    ADD COLUMN `is_monitored` TINYINT(1) DEFAULT 1 COMMENT '是否监控 (1:监控中, 0:未监控/已停止监控)' 
                    AFTER `is_recommend_success`;
                """)
                try:
                    cursor.execute("ALTER TABLE `stock_recommendation` ADD INDEX `idx_is_monitored` (`is_monitored`);")
                except Exception:
                    pass
                print("✨ 已成功向现有数据表追加 `is_monitored` (是否监控) 字段！")

            # 3. 创建中文视图
            cursor.execute(CREATE_VIEW_SQL)
            print("✅ 中文别名视图 `v_stock_recommendation` 创建成功！")

            conn.commit()

            # 4. 验证表结构
            cursor.execute("DESCRIBE `stock_recommendation`;")
            columns = cursor.fetchall()
            print("\n📋 `stock_recommendation` 表字段结构：")
            print("-" * 65)
            print(f"{'Field':<25} {'Type':<18} {'Null':<6} {'Key':<6} {'Default':<10}")
            print("-" * 65)
            for col in columns:
                field, col_type, nullable, key, default, extra = col
                print(f"{field:<25} {col_type:<18} {nullable:<6} {key:<6} {str(default):<10}")
            print("-" * 65)

    finally:
        conn.close()
        print("\n🔒 数据库连接已安全关闭。")

if __name__ == "__main__":
    main()
