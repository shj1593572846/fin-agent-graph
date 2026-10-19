"""
A股次日量化监控与跌破分时均线卖出执行脚本 (agent/monitor_break_price.py)

核心量化业务规则：
1. 【监控范围】：
   - 必须是 MySQL `stock_recommendation` 表中 `is_monitored = 1` 的标的；
   - 当天日期必须为【A股开市日】且【当天日期 > 买入日期】(严格遵循 A 股 T+1 交易交割规则)。
2. 【量化卖出判定】：
   - 实时监控开市日个股**当天分时**走势与分时均线 (VWAP)；
   - 严格核验行情数据日期为【当天】，防止非开市日或盘前旧数据误判；
   - 当当天分时现价跌破分时均线 (现价 < 分时均价) 时，视为需要执行卖出。
3. 【数据回写更新】：
   - 记录当天跌破均线的价格至 `next_day_break_price`；
   - 判定是否荐股成功 `is_recommend_success` (跌破价格 >= 买入价格 为 1，否则为 0)；
   - 移出量化监控：`is_monitored = 0`；
   - 更新时间：`updated_at = NOW()`。
"""

import os
import sys
import time
import json
import argparse
import datetime
import requests
from typing import Any, Dict, List, Optional, Tuple

# 适配 Windows 终端编码
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

try:
    from db import get_candidates_for_break_monitor, record_break_sell, get_connection
except ImportError:
    from agent.db import get_candidates_for_break_monitor, record_break_sell, get_connection


# 中国 A 股常见法定节假日公历日期（每年更新/动态适配）
_KNOWN_HOLIDAYS = {
    # 2026年法定休市日示例
    "2026-01-01", "2026-01-02", "2026-01-03", # 元旦
    "2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19", "2026-02-20", "2026-02-21", # 春节
    "2026-04-04", "2026-04-05", "2026-04-06", # 清明
    "2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05", # 劳动节
    "2026-06-19", "2026-06-20", "2026-06-21", # 端午
    "2026-09-25", "2026-09-26", "2026-09-27", # 中秋
    "2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04", "2026-10-05", "2026-10-06", "2026-10-07", # 国庆
}


def is_ashare_trading_day(now: Optional[datetime.datetime] = None) -> Tuple[bool, str]:
    """
    判断目标日期是否为 A 股开市交易日。
    规则：
    1. 周六、周日为法定周末休市日；
    2. 法定节假日休市；
    3. 周一至周五非节假日为 A 股开市日。
    """
    if now is None:
        now = datetime.datetime.now()

    date_str = now.strftime("%Y-%m-%d")
    weekday = now.weekday()  # 0=周一, 6=周日

    if weekday == 5:
        return False, f"周六休市 (日期: {date_str})"
    if weekday == 6:
        return False, f"周日休市 (日期: {date_str})"
    if date_str in _KNOWN_HOLIDAYS:
        return False, f"法定节假日休市 (日期: {date_str})"

    return True, f"A股开市交易日 (周{weekday+1}, 日期: {date_str})"


def is_ashare_trading_hours(now: Optional[datetime.datetime] = None) -> Tuple[bool, str]:
    """
    判断当前时刻是否处于 A 股开市日的盘中连续竞价交易时段 (09:30-11:30, 13:00-15:00)。
    """
    if now is None:
        now = datetime.datetime.now()

    is_trade_day, day_desc = is_ashare_trading_day(now)
    if not is_trade_day:
        return False, day_desc

    t_str = now.strftime("%H:%M:%S")
    if t_str < "09:30:00":
        return False, f"开市盘前 ({t_str})，尚未进入 09:30 连续竞价阶段"
    if "11:30:00" < t_str < "13:00:00":
        return False, f"午间休市时段 ({t_str})，等待 13:00 午后开盘"
    if t_str > "15:00:00":
        return False, f"今日收盘已结 ({t_str})，连续竞价时段已结束"

    return True, f"开盘交易进行中 ({t_str})"


def fetch_today_intraday_data(stock_code: str, expected_date_str: str = "") -> Optional[Dict[str, Any]]:
    """
    抓取个股分时数据及分时均价 (VWAP)，并严格核对数据产生的日期。
    """
    code = str(stock_code).strip().zfill(6)
    expected_compact = expected_date_str.replace("-", "") if expected_date_str else ""

    # 1. 优先同花顺分时 CDN
    try:
        url_ths = f"http://d.10jqka.com.cn/v6/time/hs_{code}/last.js"
        headers_ths = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://stockpage.10jqka.com.cn/",
        }
        resp = requests.get(url_ths, headers=headers_ths, timeout=3.5)
        if resp.status_code == 200 and "{" in resp.text:
            text = resp.text
            raw_json = text[text.find("{") : text.rfind("}") + 1]
            data_dict = json.loads(raw_json)
            info = list(data_dict.values())[0] if data_dict else {}
            stock_name = info.get("name", "")
            data_date_compact = str(info.get("date", "")).strip()
            raw_pts = [p.split(",") for p in info.get("data", "").split(";") if p]

            if raw_pts:
                bars = []
                breaks = []
                for p in raw_pts:
                    if len(p) >= 4:
                        t = p[0]
                        time_fmt = f"{t[:2]}:{t[2:]}" if len(t) == 4 else t
                        pr = float(p[1])
                        vw = float(p[3])
                        bars.append({"time": time_fmt, "price": pr, "vwap": vw})
                        if pr < vw:
                            breaks.append({"time": time_fmt, "price": pr, "vwap": vw})

                last_bar = bars[-1]
                data_date_fmt = (
                    f"{data_date_compact[:4]}-{data_date_compact[4:6]}-{data_date_compact[6:]}"
                    if len(data_date_compact) == 8
                    else data_date_compact
                )
                return {
                    "code": code,
                    "name": stock_name,
                    "data_date": data_date_fmt,
                    "data_date_compact": data_date_compact,
                    "latest_price": last_bar["price"],
                    "latest_vwap": last_bar["vwap"],
                    "bars_count": len(bars),
                    "has_broken": len(breaks) > 0,
                    "first_break": breaks[0] if breaks else None,
                    "latest_break": breaks[-1] if breaks else None,
                    "source": "ths",
                }
    except Exception:
        pass

    # 2. 备用源：东方财富 trends2
    try:
        secid = f"1.{code}" if code.startswith(("6", "9")) else f"0.{code}"
        url_em = (
            f"https://push2.eastmoney.com/api/qt/stock/trends2/get?"
            f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
        )
        headers_em = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://quote.eastmoney.com/",
        }
        resp_em = requests.get(url_em, headers=headers_em, timeout=3.5)
        if resp_em.status_code == 200:
            data = resp_em.json().get("data", {})
            stock_name = data.get("name", "")
            trends = data.get("trends", [])
            if trends:
                bars = []
                breaks = []
                data_date_fmt = ""
                for tr in trends:
                    parts = tr.split(",")
                    if len(parts) >= 8:
                        dt_part = parts[0].split(" ")
                        data_date_fmt = dt_part[0]
                        time_fmt = dt_part[-1][:5]
                        pr = float(parts[2])
                        vw = float(parts[7])
                        bars.append({"time": time_fmt, "price": pr, "vwap": vw})
                        if pr < vw:
                            breaks.append({"time": time_fmt, "price": pr, "vwap": vw})

                last_bar = bars[-1]
                data_date_compact = data_date_fmt.replace("-", "")
                return {
                    "code": code,
                    "name": stock_name,
                    "data_date": data_date_fmt,
                    "data_date_compact": data_date_compact,
                    "latest_price": last_bar["price"],
                    "latest_vwap": last_bar["vwap"],
                    "bars_count": len(bars),
                    "has_broken": len(breaks) > 0,
                    "first_break": breaks[0] if breaks else None,
                    "latest_break": breaks[-1] if breaks else None,
                    "source": "eastmoney",
                }
    except Exception:
        pass

    return None


def run_monitor_scan(
    today_str: Optional[str] = None,
    ignore_date_check: bool = False,
    force_run: bool = False,
) -> Dict[str, Any]:
    """
    执行一轮次日量化跌破均线监控扫描：
    【严格准入条件】：
    1. 当天必须为 A 股开市交易日（若非开市日且未开启强制模式，安全跳过，防止历史数据误触）；
    2. 标的范围：stock_recommendation 中 is_monitored=1 且 当天日期 > 买入日期；
    3. 行情数据日期校验：必须为当天生成的分时走势；
    4. 当天分时跌破分时均线 (VWAP)：判定卖出，回写第二天跌破均线价格、评估荐股成功、移出监控。
    """
    now = datetime.datetime.now()
    if not today_str:
        today_str = now.strftime("%Y-%m-%d")

    is_trade_day, day_status = is_ashare_trading_day(now)
    in_trade_hours, hour_status = is_ashare_trading_hours(now)

    print("\n" + "=" * 78)
    print(f"📊 [A股次日量化监控] 开始执行分时均线研判 | 当前时间: {today_str} {now.strftime('%H:%M:%S')}")
    print(f"📅 【开市日判定】: {day_status} | 【交易时段】: {hour_status}")
    print("=" * 78)

    # 非开市日检查保护：非开市日不执行次日分时卖出监控，保护持仓
    if not is_trade_day and not force_run:
        msg = f"🚫 [非A股开市日] {day_status}。按照规则，次日分时卖出监控仅在 A 股开市日开盘期间执行，本次安全跳过。"
        print(msg)
        print("💡 [提示] 如需在非开市日进行模拟演练或测试，可添加 `--force` 参数强制运行。")
        print("=" * 78 + "\n")
        return {
            "success": True,
            "message": msg,
            "is_trading_day": False,
            "candidates_count": 0,
            "triggered_count": 0,
            "kept_count": 0,
            "details": [],
        }

    # 检索符合条件的监控候选标的：is_monitored=1 且 buy_date < today
    candidates = get_candidates_for_break_monitor(
        today_str=today_str,
        ignore_date_check=ignore_date_check,
    )

    if not candidates:
        msg = f"ℹ️  [提示] 当前无需要次日监控的标的 (筛选条件: is_monitored=1 且 买入日期 < {today_str})。"
        print(msg)
        print("=" * 78 + "\n")
        return {
            "success": True,
            "message": msg,
            "is_trading_day": is_trade_day,
            "candidates_count": 0,
            "triggered_count": 0,
            "kept_count": 0,
            "details": [],
        }

    print(f"🔍 检索到 {len(candidates)} 只符合次日量化监控条件的推荐标的，正在逐一核验当天分时数据...")

    triggered_count = 0
    kept_count = 0
    details = []

    for item in candidates:
        rec_id = item["id"]
        code = item["stock_code"]
        name = item["stock_name"]
        buy_p = item["buy_price"] or 0.0
        buy_date = item["buy_date"]

        intraday = fetch_today_intraday_data(code, expected_date_str=today_str)
        if not intraday or not intraday.get("bars_count"):
            print(f"⚠️ 标的【{name}】({code}) 暂未获取到有效分时数据，稍后重试。")
            details.append({"id": rec_id, "code": code, "name": name, "status": "no_data"})
            continue

        stock_display_name = intraday.get("name") or name
        data_date = intraday.get("data_date", "")

        # 严格分时日期核验：必须是【当天】产生的分时
        if not force_run and data_date != today_str:
            print(
                f"⏸️ 标的【{stock_display_name}】({code}) 行情数据日期为 {data_date}，非当天({today_str})分时数据。"
                f"（可能尚未开盘或今日无成交），跳过本次研判。"
            )
            details.append({
                "id": rec_id,
                "code": code,
                "name": stock_display_name,
                "status": "date_mismatch",
                "data_date": data_date,
                "expected_date": today_str,
            })
            continue

        # 核心判定：当天的分时跌破均线时视为需要卖出
        if intraday["has_broken"]:
            break_info = intraday["first_break"]
            break_p = break_info["price"]
            break_time = break_info["time"]
            vwap_at_break = break_info["vwap"]

            success, log_msg = record_break_sell(
                rec_id=rec_id,
                break_price=break_p,
                buy_price=buy_p,
                break_time=break_time,
            )

            is_profit = break_p >= buy_p
            diff = break_p - buy_p
            pct = (diff / buy_p * 100.0) if buy_p > 0 else 0.0

            print(
                f"🚨 【分时跌破均线·触发卖出】标的【{stock_display_name}】({code}) "
                f"在当天 {break_time} 跌破分时均线！\n"
                f"   - 跌破分时均线价格 (next_day_break_price): ¥{break_p:.2f} (当时均线: ¥{vwap_at_break:.2f})\n"
                f"   - 推荐买入价格 (buy_price): ¥{buy_p:.2f} (买入日期: {buy_date})\n"
                f"   - 盈亏价差: {diff:+.2f} ({pct:+.2f}%)\n"
                f"   - 荐股判定 (is_recommend_success): {'✅ 成功 (跌破价 >= 买入价)' if is_profit else '❌ 失败 (止损离场)'}\n"
                f"   - 监控状态: 终止监控 (is_monitored=0)"
            )
            triggered_count += 1
            details.append({
                "id": rec_id,
                "code": code,
                "name": stock_display_name,
                "status": "triggered_sell",
                "break_price": break_p,
                "break_time": break_time,
                "buy_price": buy_p,
                "is_profit": is_profit,
                "diff_pct": round(pct, 2),
            })
        else:
            # 价格始终在分时均线上方，未跌破均线，安全持股继续监控
            lat_p = intraday["latest_price"]
            lat_vw = intraday["latest_vwap"]
            margin = lat_p - lat_vw
            margin_pct = (margin / lat_vw * 100.0) if lat_vw > 0 else 0.0

            print(
                f"🛡️  【均线上方运行·安全持股】标的【{stock_display_name}】({code}) "
                f"当天分时始终位于均线上方，未跌破均线！\n"
                f"   - 当天最新现价: ¥{lat_p:.2f} | 当天分时均线: ¥{lat_vw:.2f} (安全垫: {margin:+.2f} / {margin_pct:+.2f}%)\n"
                f"   - 初始买入价格: ¥{buy_p:.2f} (买入日期: {buy_date})\n"
                f"   - 监控状态维持: 继续保持次日量化监控 (is_monitored=1)"
            )
            kept_count += 1
            details.append({
                "id": rec_id,
                "code": code,
                "name": stock_display_name,
                "status": "kept_monitoring",
                "latest_price": lat_p,
                "latest_vwap": lat_vw,
                "buy_price": buy_p,
            })

    summary_msg = (
        f"🎉 本轮 A 股次日量化监控完成：共检测 {len(candidates)} 只开市日标的，"
        f"触发跌破卖出 {triggered_count} 只，持续安全监控 {kept_count} 只。"
    )
    print("\n" + summary_msg)
    print("=" * 78 + "\n")

    return {
        "success": True,
        "message": summary_msg,
        "is_trading_day": is_trade_day,
        "candidates_count": len(candidates),
        "triggered_count": triggered_count,
        "kept_count": kept_count,
        "details": details,
    }


def run_loop_monitor(interval_seconds: int = 15, ignore_date_check: bool = False, force_run: bool = False):
    """
    持续实时量化监控守护进程：
    在 A 股开市日的盘中时段持续轮询检测，非交易时段自动待机。
    """
    print("\n" + "=" * 78)
    print(f"🚀 [A股开市日·次日量化卖出实时守护进程已启动] 轮询心跳: {interval_seconds} 秒")
    print("📌 监控准则：stock_recommendation 中 is_monitored=1 且 当天日期 > 买入日期的个股")
    print("🎯 卖出策略：开市日当天分时跌破均线 (VWAP) 立即触发卖出、判定成功、移出监控")
    print("⏹️  随时按 Ctrl+C 可安全停止监控")
    print("=" * 78 + "\n")

    try:
        while True:
            now = datetime.datetime.now()
            is_trade_day, day_desc = is_ashare_trading_day(now)
            in_trade_hours, hour_desc = is_ashare_trading_hours(now)

            if (is_trade_day and in_trade_hours) or force_run:
                run_monitor_scan(ignore_date_check=ignore_date_check, force_run=force_run)
            else:
                t_str = now.strftime("%H:%M:%S")
                if not is_trade_day:
                    status_tip = f"🚫 [非开市日] {day_desc}"
                else:
                    status_tip = f"⏳ [开市休盘] {hour_desc}"
                print(f"\r{status_tip}，守护进程待机中... ({t_str})", end="")
                sys.stdout.flush()

            time.sleep(interval_seconds)
    except KeyboardInterrupt:
        print("\n\n🛑 [守护进程已安全停止] 用户手动中断退出。")


def main():
    parser = argparse.ArgumentParser(description="A股开市日次日量化跌破均线卖出监控脚本")
    parser.add_argument("--once", action="store_true", help="单次扫描并退出 (默认)")
    parser.add_argument("--loop", action="store_true", help="开市日实时守护进程持续轮询监控")
    parser.add_argument("--interval", type=int, default=15, help="守护进程轮询间隔秒数 (默认 15 秒)")
    parser.add_argument("--ignore-date", action="store_true", help="忽略买入日期检查")
    parser.add_argument("--force", action="store_true", help="强制忽略开市日/时段/当天日期限制进行模拟演练")
    args = parser.parse_args()

    if args.loop:
        run_loop_monitor(
            interval_seconds=max(3, args.interval),
            ignore_date_check=args.ignore_date,
            force_run=args.force,
        )
    else:
        run_monitor_scan(
            ignore_date_check=args.ignore_date,
            force_run=args.force,
        )


if __name__ == "__main__":
    main()
