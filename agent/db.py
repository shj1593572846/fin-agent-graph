"""
MySQL 数据库操作模块：负责将选股策略研判出的龙头标的持久化至 stock_recommendation 表
"""

import datetime
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple
import pymysql
from dotenv import load_dotenv

# 适配 Windows 控制台编码，防止 Emoji 及中文字符输出异常
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 加载环境变量
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
for _d in [_CURRENT_DIR, _PROJECT_ROOT]:
    _env_prod = os.path.join(_d, ".env.prod")
    if os.path.exists(_env_prod):
        load_dotenv(_env_prod)
    _env_path = os.path.join(_d, ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
load_dotenv(".env.prod")
load_dotenv(".env")


def get_mysql_config() -> dict:
    """获取本地 MySQL 连接配置（支持 .env 覆盖，默认 root/123456@127.0.0.1:3306/stock）"""
    return {
        "host": os.getenv("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.getenv("MYSQL_PORT", 3306)),
        "user": os.getenv("MYSQL_USER", "root"),
        "password": os.getenv("MYSQL_PASSWORD", "123456"),
        "database": os.getenv("MYSQL_DATABASE", "stock"),
        "charset": "utf8mb4",
        "autocommit": True,
    }


def get_connection():
    """获取 MySQL 数据库连接（若 stock 数据库不存在则自动创建）"""
    cfg = get_mysql_config()
    db_name = cfg.pop("database", "stock")
    try:
        conn = pymysql.connect(database=db_name, **cfg)
        return conn
    except pymysql.err.OperationalError as e:
        if e.args and e.args[0] == 1049:  # 1049: Unknown database
            admin_conn = pymysql.connect(**cfg)
            with admin_conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            admin_conn.close()
            return pymysql.connect(database=db_name, **cfg)
        raise


def ensure_table_and_unique_key(conn) -> None:
    """确保 stock_recommendation 表及 (stock_code, buy_date) 唯一索引存在"""
    create_table_sql = """
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
    with conn.cursor() as cur:
        cur.execute(create_table_sql)
        # 兼容旧表可能缺少 is_monitored 字段的情况
        try:
            cur.execute("SHOW COLUMNS FROM `stock_recommendation` LIKE 'is_monitored';")
            if not cur.fetchone():
                cur.execute("""
                    ALTER TABLE `stock_recommendation` 
                    ADD COLUMN `is_monitored` TINYINT(1) DEFAULT 1 COMMENT '是否监控 (1:监控中, 0:未监控/已停止监控)' 
                    AFTER `is_recommend_success`;
                """)
                cur.execute("ALTER TABLE `stock_recommendation` ADD INDEX `idx_is_monitored` (`is_monitored`);")
        except Exception:
            pass
        # 兼容旧表可能缺少唯一键的情况
        try:
            cur.execute("ALTER TABLE `stock_recommendation` ADD UNIQUE KEY `uk_stock_code_buy_date` (`stock_code`, `buy_date`);")
        except Exception:
            pass


def extract_buy_order_high_price(
    decision_text: str,
    stock_code: str = "",
    stock_name: str = "",
    default_price: float = 0.0,
) -> Tuple[float, str]:
    """
    从终审研报中精准提取目标股票的【建议低吸买点区间】（或买入挂单区间）最高值。
    优先检索全文（包括第一板块决策矩阵表、第三板块实战操盘表及个股分析明细）：
    1. 策略 A：解析所有 Markdown 表格，查找【建议低吸买点区间】/【买入挂单区间】列对应目标股票行；
    2. 策略 B：查找个股专属段落或清单中的【建议低吸买点区间】；
    3. 策略 C：全局正则穿透匹配区间；
    4. 兜底策略：若未在文本中解析到区间，则以基准价（最新价/现价）的建议低吸买点区间最高值 (基准价 * 1.002) 自动推导计算。

    返回: (buy_price_high: float, raw_interval_str: str)
    """
    text = str(decision_text or "").strip()
    code = str(stock_code or "").strip().zfill(6) if stock_code else ""
    name = str(stock_name or "").strip()
    try:
        default_price = float(default_price)
    except (ValueError, TypeError):
        default_price = 0.0

    raw_interval = ""

    if text:
        # 1. 策略 A：扫描全文所有 Markdown 表格，查找包含【建议低吸买点区间】或【买入挂单区间】等列的表格
        tbl_blocks = []
        cur_tbl = []
        for line in text.split("\n"):
            s_line = line.strip()
            if s_line.startswith("|"):
                cur_tbl.append(s_line)
            else:
                if cur_tbl:
                    tbl_blocks.append(cur_tbl)
                    cur_tbl = []
        if cur_tbl:
            tbl_blocks.append(cur_tbl)

        interval_column_keys = [
            "建议低吸买点区间", "买入挂单区间", "建议低吸买点", "低吸买点区间",
            "建议买点区间", "买点区间", "挂单区间", "低吸区间", "买入区间", "建议买点",
        ]

        for tbl in tbl_blocks:
            header_idx = -1
            interval_col_idx = -1
            for idx, line in enumerate(tbl):
                cells = [c.strip() for c in line.split("|")[1:-1]]
                for c_i, c in enumerate(cells):
                    if any(k in c for k in interval_column_keys):
                        header_idx = idx
                        interval_col_idx = c_i
                        break
                if interval_col_idx != -1:
                    break

            if interval_col_idx != -1:
                matched_row_interval = ""
                first_data_interval = ""
                for line in tbl[header_idx + 1:]:
                    # 跳过对齐分割行 |:---|:---|
                    if set(line.replace("|", "").replace(":", "").replace("-", "").strip()) == set():
                        continue
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    if interval_col_idx < len(cells):
                        val = cells[interval_col_idx].strip()
                        if not first_data_interval and any(ch.isdigit() for ch in val):
                            first_data_interval = val
                        row_text = " ".join(cells)
                        if (code and code in row_text) or (name and name in row_text):
                            matched_row_interval = val
                            break
                if matched_row_interval:
                    raw_interval = matched_row_interval
                    break
                elif first_data_interval and not raw_interval:
                    raw_interval = first_data_interval

        # 2. 策略 B：查找个股专属段落或清单中的【建议低吸买点区间】
        if not raw_interval:
            pats = [
                r"\|\s*(?:\*\*)?(?:建议低吸买点|买入挂单|低吸买点|买点).*?区间(?:\*\*)?\s*\|\s*([^\|\n]*\d[^\|\n]*?)\s*\|",
                r"(?:\*\*)?(?:建议低吸买点|买入挂单|低吸买点|买点).*?区间(?:\*\*)?[：:\s]+([^\n]*\d[^\n]*)",
            ]
            for pat in pats:
                m = re.search(pat, text)
                if m:
                    raw_interval = m.group(1).strip()
                    break

        # 3. 策略 C：全局正则穿透匹配
        if not raw_interval:
            m_general = re.search(
                r"(?:建议低吸买点|买入挂单|低吸|挂单).*?区间[^¥￥\d\n]*([¥￥]?\s*\d+(?:\.\d+)?\s*(?:[—\-\~到至~～]+|\.{2,})\s*[¥￥]?\s*\d+(?:\.\d+)?)",
                text,
            )
            if m_general:
                raw_interval = m_general.group(1).strip()

    # 4. 从区间字符串中提取【最高值】
    if raw_interval:
        # 清除百分比 (如 +3.5%) 防止被当作价格
        cleaned = re.sub(r"[+-]?\s*\d+(?:\.\d+)?\s*%", "", raw_interval)
        # 清除 markdown 加粗及货币符号
        cleaned = cleaned.replace("**", "").replace("¥", "").replace("￥", "").strip()
        # 提取所有浮点数
        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", cleaned)]
        if nums:
            if default_price > 0:
                valid_prices = [p for p in nums if 0.3 * default_price <= p <= 3.0 * default_price]
                if valid_prices:
                    nums = valid_prices
            if len(nums) >= 2:
                # 明确取建议低吸买点区间的【最高值】
                high_price = round(max(nums), 2)
                return (high_price, raw_interval)
            elif len(nums) == 1:
                val = nums[0]
                if default_price > 0 and abs(val - default_price) < 0.05:
                    high_price = round(val * 1.002, 2)
                else:
                    high_price = round(val, 2)
                return (high_price, raw_interval)

    # 5. 若未在文本中解析到区间，则以基准价（最新价/现价）的建议低吸买点区间最高值 (基准价 * 1.002) 兜底
    if default_price > 0:
        high_price = round(default_price * 1.002, 2)
        low_price = round(default_price * 0.996, 2)
        calc_interval = f"¥{low_price:.2f} ~ ¥{high_price:.2f} (算法推导最高值)"
        return (high_price, calc_interval)

    return (0.0, "")


def extract_top_stock_from_state(state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    从工作流最终状态或本地持久化文件中，提取排名第一的股票
    优先级：
    1. final_decision 中决策矩阵中大模型评定排名第一 (Top 1) 的股票
    2. state 中的 top_stock
    3. state["qualified_stocks"][0]（Node4 按 score/above_ratio/shrink_ratio 综合排名第一）
    4. 本地 stock_data/qualified_stocks_morning.json 首只标的
    5. state["filtered_stocks"][0]（Node2 按近10日涨停与涨跌幅排名第一）
    6. 本地 stock_data/filtered_stocks.csv 首只标的
    """
    decision_text = str(state.get("final_decision") or state.get("analysis_result") or "")
    qualified = state.get("qualified_stocks") or []
    filtered = state.get("filtered_stocks") or []

    # 1. 如果存在终审文本，优先尝试从表格或文本中解析排名第一 (Top 1) 的股票标的
    if decision_text:
        # 匹配 markdown 表格中排名第1名的标的行: | 1 | 601519 | 大智慧 | ... | ¥9.48 |
        table_match = re.search(
            r"\|\s*(?:\*\*)?(?:第\s*1\s*名|1|Top\s*1)[^\|]*\|\s*(\d{6})\s*\|\s*([^\|]+?)\s*\|.*?\|\s*[¥￥]?\s*([\d.]+)",
            decision_text,
            re.IGNORECASE,
        )
        if table_match:
            code = table_match.group(1).strip()
            name = table_match.group(2).strip()
            price_str = table_match.group(3).strip()
            try:
                price = float(price_str)
            except ValueError:
                price = 0.0

            matched_item = None
            for s in qualified:
                if str(s.get("code", "")).zfill(6) == code:
                    matched_item = dict(s)
                    break
            if not matched_item:
                for s in filtered:
                    s_code = str(s.get("code") or s.get("股票代码") or "").zfill(6)
                    if s_code == code:
                        matched_item = dict(s)
                        break

            if not matched_item:
                matched_item = {
                    "code": code,
                    "name": name,
                    "latest_price": price,
                }
            else:
                matched_item["code"] = code
                matched_item["name"] = name
                if price > 0:
                    matched_item["latest_price"] = price

            # 从第三板块精准提取【买入挂单区间】最高价位
            buy_price_high, raw_interval = extract_buy_order_high_price(
                decision_text=decision_text,
                stock_code=code,
                stock_name=name,
                default_price=price,
            )
            matched_item["buy_price"] = buy_price_high if buy_price_high > 0 else price
            matched_item["buy_price_range"] = raw_interval
            return matched_item

        # 文本正则匹配: "第 1 名"、"第一名"、"Top 1" 附近的6位股票代码
        patterns = [
            r"(?:第\s*1\s*名|第一名|Top\s*1|排名第一).*?(\d{6})",
            r"(\d{6}).*?(?:强烈推荐|稳健底仓)",
        ]
        for pat in patterns:
            m = re.search(pat, decision_text, re.IGNORECASE)
            if m:
                matched_code = m.group(1)
                for s in qualified:
                    if str(s.get("code", "")).zfill(6) == matched_code:
                        res = dict(s)
                        lp = float(res.get("latest_price", 0.0) or 0.0)
                        buy_price_high, raw_interval = extract_buy_order_high_price(
                            decision_text=decision_text,
                            stock_code=matched_code,
                            stock_name=res.get("name", ""),
                            default_price=lp,
                        )
                        res["buy_price"] = buy_price_high if buy_price_high > 0 else (round(lp * 1.002, 2) if lp > 0 else 0.0)
                        res["buy_price_range"] = raw_interval
                        return res
                for s in filtered:
                    s_code = str(s.get("code") or s.get("股票代码") or "").zfill(6)
                    if s_code == matched_code:
                        res = dict(s)
                        lp = float(res.get("latest_price", 0.0) or 0.0)
                        buy_price_high, raw_interval = extract_buy_order_high_price(
                            decision_text=decision_text,
                            stock_code=matched_code,
                            stock_name=res.get("name") or res.get("股票简称", ""),
                            default_price=lp,
                        )
                        res["buy_price"] = buy_price_high if buy_price_high > 0 else (round(lp * 1.002, 2) if lp > 0 else 0.0)
                        res["buy_price_range"] = raw_interval
                        return res

    # 2. 显式指定的 top_stock
    top = state.get("top_stock")
    if top and isinstance(top, dict) and (top.get("code") or top.get("股票代码")):
        res = dict(top)
        c = res.get("code") or res.get("股票代码") or ""
        n = res.get("name") or res.get("股票简称") or ""
        lp = float(res.get("latest_price") or res.get("price") or 0.0)
        buy_price_high, raw_interval = extract_buy_order_high_price(
            decision_text=decision_text,
            stock_code=c,
            stock_name=n,
            default_price=lp,
        )
        res["buy_price"] = buy_price_high if buy_price_high > 0 else (round(lp * 1.002, 2) if lp > 0 else 0.0)
        res["buy_price_range"] = raw_interval
        return res
    if top and isinstance(top, dict) and (top.get("code") or top.get("股票代码")):
        return top

    # 3. 取 Node4 量化得分排名第一的标的
    if qualified and len(qualified) > 0 and isinstance(qualified[0], dict):
        return qualified[0]

    # 4. 回退读取本地 stock_data/qualified_stocks_morning.json
    root_dir = _PROJECT_ROOT
    json_path = os.path.join(root_dir, "stock_data", "qualified_stocks_morning.json")
    if os.path.exists(json_path):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], dict):
                    return data[0]
        except Exception:
            pass

    # 5. 回退取 Node2 过滤出的最高动能标的
    if filtered and len(filtered) > 0 and isinstance(filtered[0], dict):
        return filtered[0]

    # 6. 回退读取本地 stock_data/filtered_stocks.csv
    csv_path = os.path.join(root_dir, "stock_data", "filtered_stocks.csv")
    if os.path.exists(csv_path):
        try:
            import pandas as pd
            df = pd.read_csv(csv_path, dtype={"股票代码": str})
            if not df.empty:
                return df.iloc[0].to_dict()
        except Exception:
            pass

    return None


def insert_top_recommendation(
    stock_code: str,
    stock_name: str,
    buy_price: float,
    buy_date: Optional[str] = None,
    is_monitored: int = 1,
) -> Tuple[bool, str]:
    """
    往 stock_recommendation 表插入数据（当股票代码 + 买入日期不重复时插入）。
    插入字段：stock_code (股票代码), stock_name (股票名称), buy_price (买入价格), buy_date (买入日期), is_monitored (是否监控), created_at (创建时间)
    返回: (是否成功执行插入, 结果信息)
    """
    stock_code = str(stock_code).strip().zfill(6)
    stock_name = str(stock_name).strip()

    if isinstance(buy_price, str):
        buy_price = re.sub(r"[^\d.]", "", buy_price)
    try:
        buy_price = round(float(buy_price), 2)
    except (ValueError, TypeError):
        buy_price = 0.0

    if not buy_date:
        buy_date = datetime.date.today().strftime("%Y-%m-%d")
    else:
        buy_date = str(buy_date).strip().replace("/", "-")
        if " " in buy_date:
            buy_date = buy_date.split(" ")[0]
        if len(buy_date) == 8 and buy_date.isdigit():
            buy_date = f"{buy_date[:4]}-{buy_date[4:6]}-{buy_date[6:]}"

    created_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = None
    try:
        conn = get_connection()
        ensure_table_and_unique_key(conn)

        with conn.cursor() as cur:
            # 1. 严格排重检测：当股票代码 + 买入日期已存在时不重复插入
            check_sql = """
            SELECT `id`, `stock_code`, `stock_name`, `buy_price`, `buy_date`, `is_monitored`, `created_at` 
            FROM `stock_recommendation` 
            WHERE `stock_code` = %s AND `buy_date` = %s 
            LIMIT 1;
            """
            cur.execute(check_sql, (stock_code, buy_date))
            existing_row = cur.fetchone()

            if existing_row:
                msg = (
                    f"⏭️  [数据库排重] 标的【{stock_name}】({stock_code}) 在买入日期 {buy_date} 已存在推荐记录 (ID: {existing_row[0]})，跳过插入。"
                )
                return False, msg

            # 2. 不重复则插入指定字段：股票代码、股票名称、买入价格、买入日期、是否监控、创建时间
            insert_sql = """
            INSERT INTO `stock_recommendation` 
                (`stock_code`, `stock_name`, `buy_price`, `buy_date`, `is_monitored`, `created_at`) 
            VALUES 
                (%s, %s, %s, %s, %s, %s);
            """
            cur.execute(insert_sql, (stock_code, stock_name, buy_price, buy_date, 1 if is_monitored else 0, created_at))
            inserted_id = cur.lastrowid
            msg = (
                f"🎉 ✅ [数据库入库成功] 排名第一股票【{stock_name}】({stock_code}) 已插入 stock_recommendation 表！\n"
                f"    - 主键 ID: {inserted_id}\n"
                f"    - 股票代码: {stock_code}\n"
                f"    - 股票名称: {stock_name}\n"
                f"    - 买入价格: ¥{buy_price:.2f}\n"
                f"    - 买入日期: {buy_date}\n"
                f"    - 是否监控: {'是 (监控中)' if is_monitored else '否 (已停止)'}\n"
                f"    - 创建时间: {created_at}"
            )
            return True, msg

    except pymysql.err.IntegrityError:
        msg = f"⏭️  [数据库排重] 标的【{stock_name}】({stock_code}) 在买入日期 {buy_date} 已存在推荐记录，跳过插入。"
        return False, msg
    except Exception as e:
        err_msg = f"❌ [数据库操作异常] 写入 stock_recommendation 表失败: {str(e)}"
        return False, err_msg
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def save_top_stock_from_state(state: Dict[str, Any]) -> Tuple[bool, str]:
    """一键启动选股策略执行完毕后调用的主入口函数"""
    top_stock = extract_top_stock_from_state(state)
    if not top_stock:
        msg = "⚠️ [数据库提示] 本轮策略执行中未发现任何达标候选股票，未向数据库插入记录。"
        print(f"\n{'='*70}\n{msg}\n{'='*70}\n")
        sys.stdout.flush()
        return False, msg

    # 提取字段
    code = top_stock.get("code") or top_stock.get("股票代码") or ""
    name = top_stock.get("name") or top_stock.get("股票简称") or ""

    decision_text = str(state.get("final_decision") or state.get("analysis_result") or "")
    default_p = (
        top_stock.get("latest_price")
        or top_stock.get("最新收盘价")
        or top_stock.get("price")
        or top_stock.get("现价")
        or top_stock.get("收盘价")
        or 0.0
    )
    try:
        default_p = float(default_p)
    except (ValueError, TypeError):
        default_p = 0.0

    # 核心：入库的买入价格字段取【建议低吸买点区间】的最高值
    buy_price_high, raw_interval = extract_buy_order_high_price(
        decision_text=decision_text,
        stock_code=code,
        stock_name=name,
        default_price=default_p,
    )
    if buy_price_high <= 0:
        if top_stock.get("buy_price"):
            try:
                buy_price_high = float(top_stock["buy_price"])
            except (ValueError, TypeError):
                buy_price_high = round(default_p * 1.002, 2) if default_p > 0 else 0.0
        elif default_p > 0:
            buy_price_high = round(default_p * 1.002, 2)
    if not raw_interval and top_stock.get("buy_price_range"):
        raw_interval = top_stock.get("buy_price_range")

    price = round(buy_price_high, 2)

    buy_date = (
        top_stock.get("buy_date")
        or top_stock.get("date")
        or top_stock.get("日期")
        or state.get("buy_date")
        or state.get("date")
        or datetime.date.today().strftime("%Y-%m-%d")
    )

    print("\n" + "=" * 70)
    print("💾 正在将策略选出的排名第一股票同步至 MySQL stock_recommendation 表...")
    print(f"🎯 [买入价格解析] 标的【{name}】({code}):")
    if raw_interval:
        print(f"    - 识别建议低吸买点区间: {raw_interval}")
        print(f"    - 建议低吸买点区间最高值 (入库 buy_price): ¥{price:.2f}")
    else:
        print(f"    - 建议低吸买点区间最高值 (入库 buy_price): ¥{price:.2f}")
    print("=" * 70)
    sys.stdout.flush()

    success, msg = insert_top_recommendation(
        stock_code=code,
        stock_name=name,
        buy_price=price,
        buy_date=buy_date,
    )
    print(msg)
    print("=" * 70 + "\n")
    sys.stdout.flush()
    return success, msg


def get_latest_recommendations(limit: int = 20) -> List[Dict[str, Any]]:
    """查询 stock_recommendation 表中最新的推荐记录列表"""
    conn = None
    try:
        conn = get_connection()
        ensure_table_and_unique_key(conn)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            sql = """
            SELECT 
                `id`, 
                `stock_code`, 
                `stock_name`, 
                `buy_price`, 
                `close_price`, 
                `buy_date`, 
                `next_day_break_price`, 
                `is_recommend_success`, 
                `is_monitored`,
                `created_at`, 
                `updated_at`
            FROM `stock_recommendation`
            ORDER BY `id` DESC
            LIMIT %s;
            """
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
            # 格式化日期与 Decimal 类型
            results = []
            for r in rows:
                item = dict(r)
                if item.get("buy_date"):
                    item["buy_date"] = str(item["buy_date"])
                if item.get("buy_price") is not None:
                    item["buy_price"] = float(item["buy_price"])
                if item.get("close_price") is not None:
                    item["close_price"] = float(item["close_price"])
                if item.get("next_day_break_price") is not None:
                    item["next_day_break_price"] = float(item["next_day_break_price"])
                if item.get("is_monitored") is not None:
                    item["is_monitored"] = int(item["is_monitored"])
                if item.get("created_at"):
                    item["created_at"] = str(item["created_at"])
                if item.get("updated_at"):
                    item["updated_at"] = str(item["updated_at"])
                results.append(item)
            return results
    except Exception as e:
        print(f"⚠️ 查询 stock_recommendation 失败: {str(e)}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def update_recommendation_monitor_status(rec_id: int, is_monitored: int) -> Tuple[bool, str]:
    """更新某条荐股记录的【是否监控】状态 (1: 监控中, 0: 未监控/已停止)"""
    conn = None
    try:
        conn = get_connection()
        ensure_table_and_unique_key(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE `stock_recommendation` SET `is_monitored` = %s, `updated_at` = NOW() WHERE `id` = %s;",
                (1 if is_monitored else 0, rec_id),
            )
            if cur.rowcount > 0:
                state_text = "监控中" if is_monitored else "已停止监控"
                return True, f"✅ 记录 ID #{rec_id} 监控状态已更新为: {state_text}"
            return False, f"⚠️ 未找到 ID 为 {rec_id} 的荐股记录"
    except Exception as e:
        return False, f"❌ 更新监控状态失败: {str(e)}"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def get_candidates_for_break_monitor(
    today_str: Optional[str] = None,
    ignore_date_check: bool = False,
) -> List[Dict[str, Any]]:
    """
    查询需要进行次日量化跌破均线卖出监控的标的列表：
    条件：
    1. is_monitored = 1 (处于开启监控状态)
    2. 当天日期大于买入日期 (buy_date < today_str，满足 A 股 T+1 交易交割规则)
       (当 ignore_date_check=True 时，可豁免日期限制用于测试模拟)
    """
    if not today_str:
        today_str = datetime.date.today().strftime("%Y-%m-%d")
    conn = None
    try:
        conn = get_connection()
        ensure_table_and_unique_key(conn)
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            if ignore_date_check:
                sql = """
                SELECT 
                    `id`, 
                    `stock_code`, 
                    `stock_name`, 
                    `buy_price`, 
                    `close_price`, 
                    `buy_date`, 
                    `next_day_break_price`, 
                    `is_recommend_success`, 
                    `is_monitored`, 
                    `created_at`
                FROM `stock_recommendation`
                WHERE `is_monitored` = 1
                ORDER BY `buy_date` ASC, `id` ASC;
                """
                cur.execute(sql)
            else:
                sql = """
                SELECT 
                    `id`, 
                    `stock_code`, 
                    `stock_name`, 
                    `buy_price`, 
                    `close_price`, 
                    `buy_date`, 
                    `next_day_break_price`, 
                    `is_recommend_success`, 
                    `is_monitored`, 
                    `created_at`
                FROM `stock_recommendation`
                WHERE `is_monitored` = 1 AND `buy_date` < %s
                ORDER BY `buy_date` ASC, `id` ASC;
                """
                cur.execute(sql, (today_str,))

            rows = cur.fetchall()
            results = []
            for r in rows:
                item = dict(r)
                if item.get("buy_date"):
                    item["buy_date"] = str(item["buy_date"])
                if item.get("buy_price") is not None:
                    item["buy_price"] = float(item["buy_price"])
                if item.get("close_price") is not None:
                    item["close_price"] = float(item["close_price"])
                if item.get("next_day_break_price") is not None:
                    item["next_day_break_price"] = float(item["next_day_break_price"])
                if item.get("is_monitored") is not None:
                    item["is_monitored"] = int(item["is_monitored"])
                if item.get("is_recommend_success") is not None:
                    item["is_recommend_success"] = int(item["is_recommend_success"])
                if item.get("created_at"):
                    item["created_at"] = str(item["created_at"])
                results.append(item)
            return results
    except Exception as e:
        print(f"⚠️ 查询次日量化监控标的失败: {str(e)}")
        return []
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


def record_break_sell(
    rec_id: int,
    break_price: float,
    buy_price: float,
    break_time: str = "",
) -> Tuple[bool, str]:
    """
    当个股分时跌破分时均线时，执行卖出信号记录：
    1. 记录第二天跌破均线的价格 (next_day_break_price)
    2. 评估是否荐股成功 (is_recommend_success: 跌破价格 >= 买入价格 为 1，否则为 0)
    3. 移出量化监控 (is_monitored = 0)
    4. 更新时间 updated_at = NOW()
    """
    conn = None
    try:
        break_p = round(float(break_price), 2)
        buy_p = round(float(buy_price), 2)
        is_success = 1 if break_p >= buy_p else 0
        diff_p = round(break_p - buy_p, 2)
        diff_pct = round((diff_p / buy_p * 100.0), 2) if buy_p > 0 else 0.0

        conn = get_connection()
        ensure_table_and_unique_key(conn)
        with conn.cursor() as cur:
            update_sql = """
            UPDATE `stock_recommendation`
            SET 
                `next_day_break_price` = %s,
                `is_recommend_success` = %s,
                `is_monitored` = 0,
                `updated_at` = NOW()
            WHERE `id` = %s;
            """
            cur.execute(update_sql, (break_p, is_success, rec_id))
            if cur.rowcount > 0:
                eval_str = "盈利/保本离场 (荐股成功 ✅)" if is_success == 1 else "触发止损离场 (荐股失败 ❌)"
                time_info = f" [{break_time}]" if break_time else ""
                msg = (
                    f"🎯 [卖出信号触发]{time_info} 标的 ID #{rec_id} 分时跌破均线！\n"
                    f"    - 跌破均线价格: ¥{break_p:.2f}\n"
                    f"    - 初始买入价格: ¥{buy_p:.2f}\n"
                    f"    - 收益价差幅度: {diff_p:+.2f} ({diff_pct:+.2f}%)\n"
                    f"    - 最终荐股成效: {eval_str} (is_recommend_success={is_success})\n"
                    f"    - 监控状态更新: 已终止监控 (is_monitored=0)"
                )
                return True, msg
            return False, f"⚠️ 未找到对应 ID #{rec_id} 的推荐记录"
    except Exception as e:
        return False, f"❌ 记录跌破均线卖出异常: {str(e)}"
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


