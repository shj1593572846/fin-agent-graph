"""
A股收盘价同步独立执行脚本 (agent/sync_close_price.py)
由定时任务调度器 (cron 10 15 * * 1-5) 或手动调用：
1. 查询 MySQL stock_recommendation 表中指定日期（默认当天）的所有推荐股票；
2. 调用实时行情接口（腾讯/新浪）获取当日最终收盘价；
3. 更新回写 stock_recommendation 表的 close_price 及 is_recommend_success 字段。
"""

import os
import sys
import argparse
import datetime
import requests

# 适配 Windows 控制台 UTF-8 编码
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

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from db import get_connection, ensure_table_and_unique_key


def fetch_realtime_close_price(stock_code: str):
    """获取单只股票的当日收盘价/现价（优先腾讯行情，回退新浪行情）"""
    code_clean = str(stock_code).strip().zfill(6)
    prefix = "sh" if code_clean.startswith(("6", "9")) else ("bj" if code_clean.startswith(("4", "8", "920")) else "sz")
    full_sym = f"{prefix}{code_clean}"

    # 1. 优先腾讯行情接口
    try:
        url_tx = f"http://qt.gtimg.cn/q={full_sym}"
        resp = requests.get(url_tx, timeout=3.5)
        if resp.status_code == 200 and "~" in resp.text:
            parts = resp.text.split("~")
            if len(parts) > 4:
                price = float(parts[3])
                if price > 0:
                    return round(price, 2)
    except Exception:
        pass

    # 2. 回退新浪行情接口
    try:
        url_sina = f"https://hq.sinajs.cn/list={full_sym}"
        headers = {"Referer": "https://finance.sina.com.cn"}
        resp = requests.get(url_sina, headers=headers, timeout=3.5)
        if resp.status_code == 200 and '"' in resp.text:
            fields = resp.text.split('"')[1].split(",")
            if len(fields) > 3:
                price = float(fields[3])
                if price > 0:
                    return round(price, 2)
    except Exception:
        pass

    return None


def run_sync(target_date: str = "") -> bool:
    """执行当日收盘价同步并回写数据库"""
    if not target_date:
        target_date = datetime.date.today().strftime("%Y-%m-%d")

    print("\n" + "=" * 70)
    print(f"📊 [A股收盘价同步脚本] 开始执行 | 目标买入日期: {target_date}")
    print("=" * 70)

    conn = None
    try:
        conn = get_connection()
        ensure_table_and_unique_key(conn)

        with conn.cursor() as cur:
            query_sql = """
            SELECT `id`, `stock_code`, `stock_name`, `buy_price`, `close_price`, `buy_date`, `is_monitored`
            FROM `stock_recommendation`
            WHERE `buy_date` = %s;
            """
            cur.execute(query_sql, (target_date,))
            rows = cur.fetchall()

            if not rows:
                print(f"ℹ️ [提示] 买入日期 {target_date} 在 stock_recommendation 表中未找到任何推荐记录，跳过更新。")
                print("=" * 70 + "\n")
                return True

            print(f"🔍 检索到 {len(rows)} 只待更新标的，正在调用官方行情接口拉取最终收盘价...")

            updated_count = 0
            for row in rows:
                rec_id = row[0]
                code = str(row[1]).strip().zfill(6)
                name = str(row[2]).strip()
                buy_p = float(row[3]) if row[3] is not None else 0.0
                is_mon = row[6] if len(row) > 6 and row[6] is not None else 1

                if is_mon == 0:
                    print(f"⏸️ 标的【{name}】({code}) 当前【已停止监控】(is_monitored=0)，跳过收盘价同步。")
                    continue

                close_p = fetch_realtime_close_price(code)
                if close_p is None or close_p <= 0:
                    print(f"⚠️ 标的【{name}】({code}) 拉取收盘价失败，跳过。")
                    continue

                is_success = 1 if (buy_p > 0 and close_p >= buy_p) else 0

                update_sql = """
                UPDATE `stock_recommendation`
                SET `close_price` = %s, `is_recommend_success` = %s, `updated_at` = NOW()
                WHERE `id` = %s;
                """
                cur.execute(update_sql, (close_p, is_success, rec_id))

                diff_p = close_p - buy_p if buy_p > 0 else 0.0
                diff_pct = (diff_p / buy_p * 100.0) if buy_p > 0 else 0.0
                eval_str = "盈利/保本" if is_success == 1 else "浮亏"

                print(
                    f"✅ 标的【{name}】({code}) 收盘价已回写更新为: ¥{close_p:.2f} "
                    f"(买入价: ¥{buy_p:.2f}, 盈亏: {diff_p:+.2f} / {diff_pct:+.2f}%, 评估: {eval_str})"
                )
                updated_count += 1

            print(f"\n🎉 [成功] 日期 {target_date} 共成功更新 {updated_count} 只个股收盘价！")
            print("=" * 70 + "\n")
            return True

    except Exception as e:
        print(f"❌ [异常] 同步收盘价数据库操作失败: {str(e)}")
        print("=" * 70 + "\n")
        return False
    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="A股收盘价定时同步脚本")
    parser.add_argument("--date", type=str, default="", help="指定同步的买入日期 (YYYY-MM-DD)，留空默认为今天")
    args = parser.parse_args()

    success = run_sync(args.date)
    sys.exit(0 if success else 1)
