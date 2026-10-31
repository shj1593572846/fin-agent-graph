-- ==============================================================================
-- 数据库: stock
-- 表名: stock_recommendation (股票荐股与收益评估记录表)
-- ==============================================================================

-- 1. 创建数据库（若不存在）
CREATE DATABASE IF NOT EXISTS `stock` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE `stock`;

-- 2. 创建荐股记录表
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
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COLLATE = utf8mb4_unicode_ci COMMENT = '股票荐股与收益评估记录表';

-- 3. 创建纯中文列名视图（便于直接在可视化工具中查询与展示）
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

-- 4. 示例插入与查询
-- INSERT INTO `stock_recommendation`
--   (`stock_code`, `stock_name`, `buy_price`, `close_price`, `buy_date`, `next_day_break_price`, `is_recommend_success`)
-- VALUES
--   ('000001', '平安银行', 11.20, 11.58, '2026-10-17', 11.05, 1);

-- SELECT * FROM `v_stock_recommendation`;