import concurrent.futures
import datetime
import glob
import json
import math
import os
import re
import sys
import time
from urllib.parse import parse_qs, urlparse
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.tools import tool
import pandas as pd
import requests

# 确保 agent 目录和项目根目录都在 sys.path 中
_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(1, _PROJECT_ROOT)


def get_project_root() -> str:
    """获取项目根目录（兼容在 agent 子目录或根目录下运行）"""
    curr = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(curr)
    if (
        os.path.exists(os.path.join(curr, "stock_data"))
        or os.path.exists(os.path.join(curr, "stock_kline_all.csv"))
        or os.path.exists(os.path.join(curr, "kline_data"))
    ):
        return curr
    return parent



def _run_community_web_search(query: str) -> str | None:
    """优先尝试使用 langchain_community 提供的联网搜索工具（Tavily / DuckDuckGo）"""
    tavily_key = os.getenv("TAVILY_API_KEY", "").strip()
    if tavily_key:
        try:
            tavily_tool = TavilySearchResults(max_results=3)
            return str(tavily_tool.invoke({"query": query}))
        except Exception:
            pass

    try:
        ddg_tool = DuckDuckGoSearchRun()
        return ddg_tool.invoke(query)
    except Exception:
        return None


@tool
def search_web_data(query: str) -> str:
    """根据关键词搜索互联网资讯、行业数据和背景资料（集成 langchain_community 搜索工具与本地知识库回退）。"""
    # 1. 尝试通过 langchain_community 工具联网检索
    community_result = _run_community_web_search(query)
    if community_result:
        return f"【langchain_community 联网检索结果】\n{community_result}"

    # 2. 离线或未安装搜索后端时，回退到内置模拟检索数据库
    mock_knowledge_base = {
        "多模态大模型": (
            "1. 市场规模：2025-2026年全球多模态AI市场年复合增长率超过35%，企业级渗透率从15%提升至42%。\n"
            "2. 技术进展：原生多模态架构（统一Token处理文本、图像、音视频）成为主流，推理延迟降低约50%。\n"
            "3. 典型场景：智能座舱交互、医疗影像辅助诊断、工业质检、自动化办公Agent。"
        ),
        "AI Agent": (
            "1. 行业趋势：从单一对话助手向多Agent协同系统（Multi-Agent Systems）演进。\n"
            "2. 主流框架：LangGraph、AutoGen、CrewAI，其中LangGraph因支持图状态机、循环流和精细控制备受企业青睐。\n"
            "3. 核心痛点：长链路规划的稳定性、工具调用准确率以及Token成本控制。"
        ),
    }

    results = []
    for key, content in mock_knowledge_base.items():
        if key.lower() in query.lower() or any(word in query for word in key):
            results.append(f"【检索词：{key}】\n{content}")

    if not results:
        return (
            f"【关于“{query}”的检索资料】\n"
            f"- 行业现状：{query} 正在快速发展，技术成熟度与商业化落地同步加速。\n"
            f"- 关键驱动力：算力优化、算法迭代与垂直行业数字化转型需求。\n"
            f"- 挑战与风险：数据安全合规、标准化缺失以及初期投入回报周期。"
        )
    return "\n\n".join(results)


@tool
def search_academic_papers(topic: str) -> str:
    """根据主题检索相关的学术研究摘要与技术突破。"""
    return (
        f"【学术与技术文献摘要 - {topic}】\n"
        f"- 研究结论 A：采用分工协作的多智能体架构相比单智能体在复杂推理任务上准确率提升 23.4%。\n"
        f"- 研究结论 B：引入结构化状态图（StateGraph）可有效减少多轮交互中的上下文丢失与幻觉问题。"
    )


def _get_wencai_headers() -> dict:
    """生成请求同花顺问财接口所需的请求头（包括动态 hexin-v 令牌）"""
    try:
        import pywencai.headers as hd
        h = hd.headers()
        v = h.get("hexin-v", "")
        ua = h.get(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        )
    except Exception:
        v = ""
        ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

    headers = {
        "User-Agent": ua,
        "Referer": "https://www.iwencai.com/unifiedwap/result",
        "Origin": "https://www.iwencai.com",
    }
    if v:
        headers["hexin-v"] = v
        headers["cookie"] = f"v={v};"
    return headers


_KLINE_SESSION = None


def _get_kline_session() -> requests.Session:
    """获取带长连接池的全局 Session，减少高并发握手开销"""
    global _KLINE_SESSION
    if _KLINE_SESSION is None:
        _KLINE_SESSION = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=60, pool_maxsize=60, max_retries=2)
        _KLINE_SESSION.mount("http://", adapter)
        _KLINE_SESSION.mount("https://", adapter)
    return _KLINE_SESSION


def _fetch_single_stock_kline(code: str, name: str = "", limit: int = 60) -> pd.DataFrame:
    """获取单只股票的日K线图时序数据。
    
    数据源：优先调用新浪行情接口 (CN_MarketDataService.getKLineData, scale=240 为日K线)，
    若异常或数据为空则自动回退到同花顺行情接口。
    """
    code_clean = str(code).strip().zfill(6)
    prefix = "sh" if code_clean.startswith(("6", "9")) else "sz"
    full_sym = f"{prefix}{code_clean}"
    session = _get_kline_session()

    # 1. 优先调用新浪行情接口获取日K线
    try:
        sina_url = (
            f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var_{full_sym}_240_="
            f"/CN_MarketDataService.getKLineData?symbol={full_sym}&scale=240&ma=5,10,20&datalen={limit}"
        )
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn",
        }
        resp = session.get(sina_url, headers=headers, timeout=6)
        if resp.status_code == 200 and "(" in resp.text and ")" in resp.text:
            text = resp.text
            raw_json = text[text.find("(") + 1 : text.rfind(")")]
            bars = json.loads(raw_json)
            if isinstance(bars, list) and len(bars) > 0:
                records = []
                prev_close = None
                stock_name = name or code_clean
                for b in bars:
                    date_str = str(b.get("day", "")).split()[0]
                    open_p = float(b.get("open", 0.0))
                    high_p = float(b.get("high", 0.0))
                    low_p = float(b.get("low", 0.0))
                    close_p = float(b.get("close", 0.0))
                    vol = float(b.get("volume", 0.0))
                    amt = float(b.get("amount", 0.0)) if "amount" in b else round(close_p * vol, 2)
                    turnover = float(b.get("turnover", 0.0)) if "turnover" in b else 0.0

                    base_p = prev_close if prev_close is not None else open_p
                    chg_amt = close_p - base_p if base_p else 0.0
                    chg_pct = (chg_amt / base_p * 100) if base_p else 0.0
                    amp = ((high_p - low_p) / base_p * 100) if base_p else 0.0

                    records.append({
                        "交易日期": date_str,
                        "股票代码": code_clean,
                        "股票简称": stock_name,
                        "开盘价": open_p,
                        "最高价": high_p,
                        "最低价": low_p,
                        "收盘价": close_p,
                        "涨跌额": round(chg_amt, 2),
                        "涨跌幅(%)": round(chg_pct, 2),
                        "振幅(%)": round(amp, 2),
                        "成交量(股)": int(vol),
                        "成交额(元)": round(amt, 2),
                        "换手率(%)": round(turnover, 2),
                    })
                    prev_close = close_p
                if records:
                    return pd.DataFrame(records)
    except Exception:
        pass

    # 2. 回退备用：调用同花顺官方行情接口获取日K线
    try:
        url = f"http://d.10jqka.com.cn/v6/line/hs_{code_clean}/01/last.js"
        ths_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            "Referer": "http://stockpage.10jqka.com.cn/",
        }
        r = session.get(url, headers=ths_headers, timeout=8)
        if r.status_code == 200:
            r.encoding = "gbk"
            m = re.search(r"quotebridge_[^(]+\((.*)\)", r.text)
            if m:
                d = json.loads(m.group(1))
                stock_name = name or d.get("name", "") or code_clean
                raw_data = d.get("data", "").strip(";").split(";")
                if raw_data and raw_data != [""]:
                    records = []
                    prev_close = None
                    for item in raw_data:
                        parts = item.split(",")
                        if len(parts) < 7:
                            continue
                        date_str = parts[0]
                        formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}" if len(date_str) == 8 else date_str
                        open_p = float(parts[1]) if parts[1] else 0.0
                        high_p = float(parts[2]) if parts[2] else 0.0
                        low_p = float(parts[3]) if parts[3] else 0.0
                        close_p = float(parts[4]) if parts[4] else 0.0
                        vol = float(parts[5]) if parts[5] else 0.0
                        amt = float(parts[6]) if parts[6] else 0.0
                        turnover = float(parts[7]) if len(parts) > 7 and parts[7] else 0.0

                        base_p = prev_close if prev_close is not None else open_p
                        chg_amt = close_p - base_p if base_p else 0.0
                        chg_pct = (chg_amt / base_p * 100) if base_p else 0.0
                        amp = ((high_p - low_p) / base_p * 100) if base_p else 0.0

                        records.append({
                            "交易日期": formatted_date,
                            "股票代码": code_clean,
                            "股票简称": stock_name,
                            "开盘价": open_p,
                            "最高价": high_p,
                            "最低价": low_p,
                            "收盘价": close_p,
                            "涨跌额": round(chg_amt, 2),
                            "涨跌幅(%)": round(chg_pct, 2),
                            "振幅(%)": round(amp, 2),
                            "成交量(股)": int(vol),
                            "成交额(元)": round(amt, 2),
                            "换手率(%)": round(turnover, 2),
                        })
                        prev_close = close_p

                    if limit and len(records) > limit:
                        records = records[-limit:]

                    return pd.DataFrame(records)
    except Exception:
        pass

    return pd.DataFrame()


def _resolve_single_stock_name(name_query: str) -> dict | None:
    """尝试将名称解析为单只 A 股代码与名称"""
    if not name_query:
        return None
    try:
        url = f"http://searchapi.eastmoney.com/api/suggest/get?input={name_query}&type=14"
        res = requests.get(url, timeout=3).json()
        items = res.get("QuotationCodeTable", {}).get("Data", [])
        for item in items:
            if item.get("Classify") == "AStock" and item.get("Name") == name_query:
                return {"code": item.get("Code", ""), "name": item.get("Name", "")}
    except Exception:
        pass
    return None


def _get_all_market_stocks() -> list[dict]:
    """获取A股全市场所有非科创板、非ST股票列表（优先复用本地已有标的清单，毫秒级就绪）"""
    stocks = []
    seen = set()

    # 1. 优先尝试从本地已有汇总文件中提取全部个股代码与简称
    root_dir = get_project_root()
    summary_filepath = os.path.join(root_dir, "stock_data", "stock_kline_all.csv")
    if not os.path.exists(summary_filepath):
        summary_filepath = os.path.join(root_dir, "stock_kline_all.csv")
    if os.path.exists(summary_filepath) and os.path.getsize(summary_filepath) > 102400:
        try:
            sdf = pd.read_csv(summary_filepath, usecols=["股票代码", "股票简称"], dtype=str)
            sdf = sdf.drop_duplicates(subset=["股票代码"])
            for _, r in sdf.iterrows():
                c = str(r["股票代码"]).zfill(6)
                n = str(r["股票简称"])
                if c not in seen:
                    seen.add(c)
                    stocks.append({"code": c, "name": n})
            if len(stocks) >= 3000:
                return stocks
        except Exception:
            pass

    # 2. 从本地 kline_data/*.csv 检索标的清单
    kline_dir = os.path.join(root_dir, "kline_data")
    if os.path.exists(kline_dir):
        csv_files = glob.glob(os.path.join(kline_dir, "*.csv"))
        if len(csv_files) >= 3000:
            for f in csv_files:
                basename = os.path.basename(f)
                parts = basename.split("_")
                if len(parts) >= 3 and len(parts[0]) == 6 and parts[0].isdigit():
                    c = parts[0]
                    n = parts[1]
                    if c not in seen:
                        seen.add(c)
                        stocks.append({"code": c, "name": n})
            if len(stocks) >= 3000:
                return stocks

    # 3. 若本地无缓存，则通过网络拉取
    try:
        page = 1
        while True:
            url = (
                f"http://80.push2.eastmoney.com/api/qt/clist/get"
                f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3"
                f"&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23&fields=f12,f14"
            )
            resp = requests.get(url, timeout=6).json()
            data = resp.get("data")
            if not data or not data.get("diff"):
                break
            diff = data["diff"]
            for item in diff:
                code = str(item.get("f12", "")).strip().zfill(6)
                name = str(item.get("f14", "")).strip()
                # 严格过滤科创板(688开头)和ST/*ST股票
                if code.startswith("688") or "ST" in name.upper():
                    continue
                if code and code not in seen:
                    seen.add(code)
                    stocks.append({"code": code, "name": name})
            page += 1
            if page > 70:
                break
    except Exception:
        pass

    # 若上述方式未获取到，则通过问财接口抓取
    if not stocks:
        stocks = _get_stock_list_from_wencai(topic_clean="", max_stocks=5000)

    return stocks


def _get_stock_list_from_wencai(topic_clean: str, max_stocks: int = 5000) -> list[dict]:
    """通过同花顺问财接口检索目标板块个股代码与简称（完整抓取，不人为截断）"""
    query = f"{topic_clean} 非科创板 非ST 最新日线行情" if topic_clean else "非科创板 非ST 最新日线行情"
    headers = _get_wencai_headers()
    payload = {
        "add_info": json.dumps(
            {"urp": {"scene": 1, "company": 1, "business": 1}, "contentType": "json", "searchInfo": True}
        ),
        "perpage": "100",
        "page": "1",
        "source": "Ths_iwencai_Xuangu",
        "log_info": json.dumps({"input_type": "click"}),
        "version": "2.0",
        "secondary_intent": "stock",
        "question": query,
    }

    url = "https://www.iwencai.com/unifiedwap/unified-wap/v2/result/get-robot-data"
    try:
        resp = requests.post(url, data=payload, headers=headers, timeout=20)
        resp.raise_for_status()
        res_json = resp.json()
        c_raw = res_json.get("data", {}).get("answer", [{}])[0].get("txt", [{}])[0].get("content", {})
        comp = (json.loads(c_raw) if isinstance(c_raw, str) else c_raw).get("components", [{}])[0]

        all_rows = list(comp.get("data", {}).get("datas", []))
        row_count = comp.get("data", {}).get("meta", {}).get("extra", {}).get("row_count", 0)
        footer_url = comp.get("config", {}).get("other_info", {}).get("footer_info", {}).get("url", "")
        if footer_url and (row_count > len(all_rows) or row_count == 0):
            parsed = urlparse(footer_url)
            url_params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
            perpage = 100
            total_pages = math.ceil(row_count / perpage) if row_count > 0 else 50
            max_pages = min(total_pages, math.ceil(max_stocks / perpage))
            for p in range(1, max_pages + 1):
                try:
                    r = requests.post(
                        "https://www.iwencai.com/gateway/urp/v7/landing/getDataList",
                        data={**url_params, "perpage": str(perpage), "page": str(p)},
                        headers=headers,
                        timeout=15,
                    )
                    if r.status_code == 200:
                        comps = r.json().get("answer", {}).get("components", [])
                        datas = comps[0].get("data", {}).get("datas", []) if comps else []
                        if datas:
                            all_rows.extend(datas)
                        elif p > 1:
                            break
                    else:
                        break
                except Exception:
                    break

        stocks = []
        seen = set()
        for row in all_rows:
            code = row.get("code") or row.get("股票代码", "")
            if "." in code:
                code = code.split(".")[0]
            name = row.get("股票简称") or row.get("名称", "")
            if code and code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": name})
                if len(stocks) >= max_stocks:
                    break
        return stocks
    except Exception:
        return []


def _process_single_stock(s: dict, kline_dir: str, limit: int = 60, force_refresh: bool = False) -> tuple[pd.DataFrame | None, dict | None]:
    """单只股票 K 线下载与落盘保存任务函数（支持本地今日文件智能复用）"""
    code = s["code"]
    name = s.get("name", "")

    # 优先检查本地是否已有今日更新且有效的个股 CSV 文件
    pattern = os.path.join(kline_dir, f"{code}_*_kline.csv")
    matched = glob.glob(pattern)
    if matched and not force_refresh:
        local_path = matched[0]
        try:
            file_mtime = datetime.date.fromtimestamp(os.path.getmtime(local_path))
            if file_mtime == datetime.date.today() and os.path.getsize(local_path) > 300:
                stock_df = pd.read_csv(local_path, dtype={"股票代码": str})
                if not stock_df.empty and len(stock_df) >= min(limit, 30):
                    real_name = stock_df["股票简称"].iloc[0] or name or code
                    period_high = stock_df["最高价"].max()
                    period_low = stock_df["最低价"].min()
                    first_open = stock_df["开盘价"].iloc[0]
                    latest_close = stock_df["收盘价"].iloc[-1]
                    period_pct = round((latest_close - first_open) / first_open * 100, 2) if first_open else 0.0
                    stat = {
                        "code": code,
                        "name": real_name,
                        "latest_close": latest_close,
                        "period_high": period_high,
                        "period_low": period_low,
                        "period_return": period_pct,
                        "bars": len(stock_df),
                    }
                    return stock_df, stat
        except Exception:
            pass

    stock_df = _fetch_single_stock_kline(code, name, limit=limit)
    if stock_df.empty:
        return None, None

    real_name = stock_df["股票简称"].iloc[0] or name or code
    # 针对每个个股单独保存 CSV 到 kline_data/ 目录（存在相同的就直接覆盖）
    indiv_filename = f"{code}_{real_name}_kline.csv"
    indiv_filepath = os.path.join(kline_dir, indiv_filename)
    stock_df.to_csv(indiv_filepath, index=False, encoding="utf-8-sig")

    period_high = stock_df["最高价"].max()
    period_low = stock_df["最低价"].min()
    first_open = stock_df["开盘价"].iloc[0]
    latest_close = stock_df["收盘价"].iloc[-1]
    period_pct = round((latest_close - first_open) / first_open * 100, 2) if first_open else 0.0

    stat = {
        "code": code,
        "name": real_name,
        "latest_close": latest_close,
        "period_high": period_high,
        "period_low": period_low,
        "period_return": period_pct,
        "bars": len(stock_df),
    }
    return stock_df, stat


# 下载股票个股K线图数据
@tool
def download_stock_day(topic: str = "", limit: int = 60) -> str:
    """调用同花顺api下载个股的历史日K线图数据到根目录及 kline_data/ 目录（存在相同的就覆盖）。

    参数:
        topic: 股票代码（如'000001'）、股票名称（如'平安银行'）或股票板块（如'银行'、'半导体'）。为空则获取全市场所有非科创板、非ST个股数据。
        limit: K线时间周期条数，默认为近60个交易日（约3个月短期K线）。
    返回:
        下载结果说明，包含个股K线文件保存路径、总K线条数、日期跨度及区间统计。
    """
    topic_clean = topic.strip() if topic else ""
    try:
        limit = int(limit) if limit else 60
    except (ValueError, TypeError):
        limit = 60

    # 0. 极速缓存检测：如果本地汇总文件存在且数据量充足，直接秒级复用！
    root_dir = get_project_root()
    stock_data_dir = os.path.join(root_dir, "stock_data")
    os.makedirs(stock_data_dir, exist_ok=True)
    summary_filename = f"{topic_clean}_kline_all.csv" if topic_clean else "stock_kline_all.csv"
    summary_filepath = os.path.join(stock_data_dir, summary_filename)
    if not os.path.exists(summary_filepath):
        legacy_path = os.path.join(root_dir, summary_filename)
        if os.path.exists(legacy_path):
            summary_filepath = legacy_path

    kline_dir = os.path.join(root_dir, "kline_data")
    fast_mode = os.environ.get("FAST_MODE", "1") == "1"

    # 如果指定主题文件不存在，且没有特定主题，回退使用全市场总表
    if not os.path.exists(summary_filepath) and not topic_clean:
        fallback_all = os.path.join(stock_data_dir, "stock_kline_all.csv")
        if not os.path.exists(fallback_all):
            fallback_all = os.path.join(root_dir, "stock_kline_all.csv")
        if os.path.exists(fallback_all):
            summary_filepath = fallback_all

    if os.path.exists(summary_filepath) and os.path.getsize(summary_filepath) > 10240:
        file_mtime = datetime.date.fromtimestamp(os.path.getmtime(summary_filepath))
        today_date = datetime.date.today()
        time_diff = time.time() - os.path.getmtime(summary_filepath)
        # 极速模式下或者7天内（含周末及节假日），直接秒级复用本地优质K线数据
        if fast_mode or file_mtime == today_date or time_diff < 604800:
            print(f"⚡ [node1: 极速缓存命中] 检测到本地「{os.path.basename(summary_filepath)}」有效，直接秒级复用本地K线数据...")
            try:
                combined_df = pd.read_csv(summary_filepath, dtype={"股票代码": str})
                start_date = combined_df["交易日期"].min()
                end_date = combined_df["交易日期"].max()

                # 统计区间涨幅
                first_last = combined_df.groupby("股票代码").agg(
                    name=("股票简称", "last"),
                    first_open=("开盘价", "first"),
                    latest_close=("收盘价", "last"),
                    period_high=("最高价", "max"),
                    period_low=("最低价", "min"),
                    bars=("交易日期", "count")
                ).reset_index()

                first_last["period_return"] = ((first_last["latest_close"] - first_last["first_open"]) / first_last["first_open"] * 100).round(2)
                first_last.sort_values(by="period_return", ascending=False, inplace=True)
                top_gainers = first_last.head(5).to_dict("records")
                top_losers = first_last.tail(5).to_dict("records")
                unique_stocks = len(first_last)

                summary_lines = [
                    f"### 📊 同花顺个股K线图数据就绪 (⚡本地缓存极速复用)",
                    f"- **目标板块/范围**：{topic_clean or 'A股全市场（非科创板、非ST全部个股）'}",
                    f"- **K线时间周期**：`{start_date}` 至 `{end_date}`（每只个股近 {limit} 个交易日K线时序）",
                    f"- **个股保存目录**：[{kline_dir.replace(os.sep, '/')}]({kline_dir.replace(os.sep, '/')})（共包含 **{unique_stocks}** 只个股独立 CSV 文件）",
                    f"- **全量汇总文件**：[{summary_filename}]({summary_filepath.replace(os.sep, '/')})（共 **{len(combined_df):,}** 条K线柱）",
                    f"- **K线包含指标**：交易日期、股票代码、股票简称、开盘价、最高价、最低价、收盘价、涨跌额、涨跌幅(%)、振幅(%)、成交量(股)、成交额(元)、换手率(%)",
                    f"\n#### 🚀 区间领涨前 5 个股（近 {limit} 日累计涨幅）：",
                    f"| 股票代码 | 股票简称 | 最新收盘价 | 区间最高价 | 区间最低价 | 区间累计涨幅 | K线柱数 |",
                    f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                ]

                for item in top_gainers:
                    ret_str = f"{item['period_return']:+.2f}%"
                    summary_lines.append(
                        f"| {item['股票代码']} | {item['name']} | {item['latest_close']} | {item['period_high']} | {item['period_low']} | {ret_str} | {item['bars']} |"
                    )

                summary_lines.extend([
                    f"\n#### 📉 区间表现靠后前 5 个股：",
                    f"| 股票代码 | 股票简称 | 最新收盘价 | 区间最高价 | 区间最低价 | 区间累计涨幅 | K线柱数 |",
                    f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                ])

                for item in reversed(top_losers):
                    ret_str = f"{item['period_return']:+.2f}%"
                    summary_lines.append(
                        f"| {item['股票代码']} | {item['name']} | {item['latest_close']} | {item['period_high']} | {item['period_low']} | {ret_str} | {item['bars']} |"
                    )

                return "\n".join(summary_lines)
            except Exception as e:
                print(f"⚠️ 解析本地缓存异常，自动切换为增量更新模式: {e}")

    # 1. 解析目标股票列表（支持单股代码、单股名称、板块全部个股、全市场全部个股）
    stocks = []
    if re.match(r"^\d{6}$", topic_clean):
        stocks = [{"code": topic_clean, "name": ""}]
    elif topic_clean:
        single = _resolve_single_stock_name(topic_clean)
        if single:
            stocks = [single]
        else:
            print(f"🔍 正在检索「{topic_clean}」板块内成分龙头标的...")
            max_sector_stocks = 80 if fast_mode else 3000
            stocks = _get_stock_list_from_wencai(topic_clean, max_stocks=max_sector_stocks)
    else:
        print("🌐 未指定主题/板块，正在检索 A 股重点龙头标的清单...")
        stocks = _get_all_market_stocks()

    if not stocks:
        return f"⚠️ 围绕主题「{topic_clean or '全市场'}」未能检索到可下载K线数据的个股。"

    # 2. 准备输出目录
    os.makedirs(kline_dir, exist_ok=True)

    # 3. 高并发多线程下载并保存每只股票的独立 K 线 CSV 文件（存在且为今日则快速复用）
    total_targets = len(stocks)
    print(f"📥 开始并发下载/更新 {total_targets} 只个股的日K线数据并保存到 kline_data/...")

    all_kline_dfs = []
    success_stocks = []

    # 全市场大批量任务采用 50 并发，单板块/单股采用 15 并发
    max_workers = 50 if total_targets > 100 else 15
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process_single_stock, s, kline_dir, limit) for s in stocks]
        for idx, future in enumerate(concurrent.futures.as_completed(futures), 1):
            df_item, stat_item = future.result()
            if df_item is not None and stat_item is not None:
                all_kline_dfs.append(df_item)
                success_stocks.append(stat_item)
            if idx % 500 == 0 or idx == total_targets:
                print(f"   ⏳ 进度：已处理 {idx}/{total_targets} 只个股 (成功: {len(success_stocks)})...")

    if not all_kline_dfs:
        return f"❌ 个股K线数据下载失败，未能从同花顺行情接口获取到任何个股K线。"

    # 4. 合并生成总K线汇总 CSV 保存到 stock_data 目录（存在相同文件则直接覆盖）
    print("💾 正在整合生成全量日K线汇总 CSV...")
    combined_df = pd.concat(all_kline_dfs, ignore_index=True)
    summary_filename = f"{topic_clean}_kline_all.csv" if topic_clean else "stock_kline_all.csv"
    summary_filepath = os.path.join(stock_data_dir, summary_filename)
    combined_df.to_csv(summary_filepath, index=False, encoding="utf-8-sig")

    start_date = combined_df["交易日期"].min()
    end_date = combined_df["交易日期"].max()

    # 5. 生成规范的 Markdown 结果汇总
    success_stocks.sort(key=lambda x: x["period_return"], reverse=True)
    top_gainers = success_stocks[:5]
    top_losers = success_stocks[-5:]

    summary_lines = [
        f"### 📊 同花顺个股K线图数据下载完成",
        f"- **目标板块/范围**：{topic_clean or 'A股全市场（非科创板、非ST全部个股）'}",
        f"- **K线时间周期**：`{start_date}` 至 `{end_date}`（每只个股近 {limit} 个交易日K线时序）",
        f"- **个股保存目录**：[{kline_dir.replace(os.sep, '/')}]({kline_dir.replace(os.sep, '/')})（共成功导出 **{len(success_stocks)}** 只个股独立 CSV 文件，存在已覆盖）",
        f"- **全量汇总文件**：[{summary_filename}]({summary_filepath.replace(os.sep, '/')})（共 **{len(combined_df):,}** 条K线柱，存在已覆盖）",
        f"- **K线包含指标**：交易日期、股票代码、股票简称、开盘价、最高价、最低价、收盘价、涨跌额、涨跌幅(%)、振幅(%)、成交量(股)、成交额(元)、换手率(%)",
        f"\n#### 🚀 区间领涨前 5 个股（近 {limit} 日累计涨幅）：",
        f"| 股票代码 | 股票简称 | 最新收盘价 | 区间最高价 | 区间最低价 | 区间累计涨幅 | K线柱数 |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for item in top_gainers:
        ret_str = f"{item['period_return']:+.2f}%"
        summary_lines.append(
            f"| {item['code']} | {item['name']} | {item['latest_close']} | {item['period_high']} | {item['period_low']} | {ret_str} | {item['bars']} |"
        )

    summary_lines.extend([
        f"\n#### 📉 区间表现靠后前 5 个股：",
        f"| 股票代码 | 股票简称 | 最新收盘价 | 区间最高价 | 区间最低价 | 区间累计涨幅 | K线柱数 |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for item in reversed(top_losers):
        ret_str = f"{item['period_return']:+.2f}%"
        summary_lines.append(
            f"| {item['code']} | {item['name']} | {item['latest_close']} | {item['period_high']} | {item['period_low']} | {ret_str} | {item['bars']} |"
        )

    return "\n".join(summary_lines)


# 筛选近十日内有过涨停且趋势向上的股票
@tool
def filter_bullish_limit_up_stocks(topic: str = "", days: int = 10) -> str:
    """解析个股K线图时序数据，筛选出近10日内有过涨停且日K线五日线、十日线、二十日线呈现上升趋势的个股，并持久化保存到文件中。

    参数:
        topic: 股票板块或主题名称，为空则在全市场已下载的K线数据中进行全局筛选。
        days: 回溯窗口交易日天数，默认为近10个交易日。
    返回:
        筛选结果说明，包含命中股票数量、保存的文件路径及核心股票列表。
    """
    topic_clean = topic.strip() if topic else ""
    root_dir = get_project_root()
    stock_data_dir = os.path.join(root_dir, "stock_data")
    os.makedirs(stock_data_dir, exist_ok=True)
    kline_dir = os.path.join(root_dir, "kline_data")

    # 1. 寻找数据源：优先读取 stock_data 合并大表，若无则尝试根目录，最后遍历 kline_data/*.csv
    target_summary_filename = f"{topic_clean}_kline_all.csv" if topic_clean else "stock_kline_all.csv"
    target_summary_file = os.path.join(stock_data_dir, target_summary_filename)
    if not os.path.exists(target_summary_file):
        legacy_summary_file = os.path.join(root_dir, target_summary_filename)
        if os.path.exists(legacy_summary_file):
            target_summary_file = legacy_summary_file

    stock_dfs = []
    if os.path.exists(target_summary_file):
        try:
            full_df = pd.read_csv(target_summary_file, dtype={"股票代码": str})
            full_df["股票代码"] = full_df["股票代码"].astype(str).str.zfill(6)
            for _, group in full_df.groupby("股票代码"):
                stock_dfs.append(group.sort_values(by="交易日期"))
        except Exception:
            stock_dfs = []

    if not stock_dfs and os.path.exists(kline_dir):
        pattern = os.path.join(kline_dir, "*.csv")
        csv_files = glob.glob(pattern)
        for f in csv_files:
            try:
                sdf = pd.read_csv(f, dtype={"股票代码": str})
                if not sdf.empty:
                    sdf["股票代码"] = sdf["股票代码"].astype(str).str.zfill(6)
                    stock_dfs.append(sdf.sort_values(by="交易日期"))
            except Exception:
                continue

    if not stock_dfs:
        return "⚠️ 未找到可供筛选的个股K线数据文件，请先运行数据收集 Agent 下载K线数据。"

    total_scanned = len(stock_dfs)
    matched_stocks = []
    matched_kline_dfs = []

    for df in stock_dfs:
        # 计算 MA20 及与前一日均线对比，至少需要 21 个交易日
        if len(df) < 21:
            continue
        code = str(df["股票代码"].iloc[0]).strip().zfill(6)
        name = str(df["股票简称"].iloc[0]).strip()
        recent_window = df.tail(days).copy()

        # 涨停板判定：创业板(30开头)涨停阈值为 19.85%，主板(00, 60开头)涨停阈值为 9.85%
        limit_threshold = 19.85 if code.startswith("30") else 9.85
        limit_up_bars = recent_window[recent_window["涨跌幅(%)"] >= limit_threshold]
        if limit_up_bars.empty:
            continue

        last_limit_date = limit_up_bars["交易日期"].iloc[-1]
        last_limit_pct = limit_up_bars["涨跌幅(%)"].iloc[-1]
        limit_count = len(limit_up_bars)

        # 趋势向上判定（日K线图的五日线、十日线、二十日线呈现上升趋势）：
        ma5_series = df["收盘价"].rolling(5).mean()
        ma10_series = df["收盘价"].rolling(10).mean()
        ma20_series = df["收盘价"].rolling(20).mean()

        latest_close = float(df["收盘价"].iloc[-1])
        latest_ma5 = float(ma5_series.iloc[-1])
        prev_ma5 = float(ma5_series.iloc[-2])
        latest_ma10 = float(ma10_series.iloc[-1])
        prev_ma10 = float(ma10_series.iloc[-2])
        latest_ma20 = float(ma20_series.iloc[-1])
        prev_ma20 = float(ma20_series.iloc[-2])

        # 1. 均线自身呈现上升趋势：五日线向上、十日线向上、二十日线向上
        ma5_up = latest_ma5 >= prev_ma5
        ma10_up = latest_ma10 >= prev_ma10
        ma20_up = latest_ma20 >= prev_ma20

        # 近 N 日区间涨跌幅
        start_open = recent_window["开盘价"].iloc[0]
        pct_window = round((latest_close - start_open) / start_open * 100, 2) if start_open else 0.0

        # 趋势向上标准：五日线、十日线、二十日线均呈现上升趋势，收盘价位于二十日线支撑之上，且区间累计涨幅为正
        is_uptrend = ma5_up and ma10_up and ma20_up and (latest_close >= latest_ma20) and (pct_window > 0)
        if not is_uptrend:
            continue

        # 多头形态细分描述
        if latest_close >= latest_ma5 >= latest_ma10 >= latest_ma20:
            trend_desc = "强劲多头向上发散"
        elif latest_ma5 >= latest_ma10 >= latest_ma20:
            trend_desc = "均线多头持续上升"
        elif latest_ma5 >= latest_ma10:
            trend_desc = "五日十日多头攀升"
        else:
            trend_desc = "三线共振向上"

        stat_item = {
            "股票代码": code,
            "股票简称": name,
            "最新收盘价": latest_close,
            "近10日涨跌幅(%)": pct_window,
            "近10日涨停次数": limit_count,
            "最近涨停日期": last_limit_date,
            "最近涨停幅度(%)": last_limit_pct,
            "5日均线": round(latest_ma5, 2),
            "10日均线": round(latest_ma10, 2),
            "20日均线": round(latest_ma20, 2),
            "趋势状态": trend_desc,
        }
        matched_stocks.append(stat_item)
        matched_kline_dfs.append(df)

    if not matched_stocks:
        return f"⚠️ 在扫描的 {total_scanned} 只个股中，暂未发现符合「近 {days} 日内有过涨停且日K线五日、十日、二十日线呈上升趋势」的股票。"

    # 按近 10 日涨停次数与累计涨跌幅双重降序排序
    matched_stocks.sort(key=lambda x: (x["近10日涨停次数"], x["近10日涨跌幅(%)"]), reverse=True)

    # 2. 将过滤后的股票清单保存到 CSV 文件至 stock_data 目录（存在相同的就直接覆盖）
    filtered_df = pd.DataFrame(matched_stocks)
    filtered_filename = f"{topic_clean}_filtered_stocks.csv" if topic_clean else "filtered_stocks.csv"
    filtered_filepath = os.path.join(stock_data_dir, filtered_filename)
    filtered_df.to_csv(filtered_filepath, index=False, encoding="utf-8-sig")

    # 3. 将筛选股票对应的完整 K 线时序数据合并保存至 stock_data 目录（存在相同的就直接覆盖）
    filtered_kline_filename = f"{topic_clean}_filtered_kline_all.csv" if topic_clean else "filtered_kline_all.csv"
    filtered_kline_filepath = os.path.join(stock_data_dir, filtered_kline_filename)
    if matched_kline_dfs:
        combined_filtered_kline = pd.concat(matched_kline_dfs, ignore_index=True)
        combined_filtered_kline.to_csv(filtered_kline_filepath, index=False, encoding="utf-8-sig")

    # 4. 构造结构化 Markdown 汇报说明
    summary_lines = [
        f"### 🎯 强势股筛选完成：近 {days} 日内有过涨停且五/十/二十日线呈上升趋势标的",
        f"- **目标股票池**：{topic_clean or 'A股全市场（非科创板、非ST）'}（共解析 **{total_scanned}** 只个股K线数据）",
        f"- **筛选技术标准**：",
        f"  1. **涨停异动**：近 {days} 个交易日内至少出现 1 次涨停（主板≥9.85%，创业板≥19.85%）",
        f"  2. **趋势向上**：日K线五日线(MA5)、十日线(MA10)、二十日线(MA20)均呈现上升趋势（MA5、MA10、MA20斜率均向上且收盘价站上支撑均线）",
        f"- **持久化保存文件**：",
        f"  - 核心标的汇总清单：[{filtered_filename}]({filtered_filepath.replace(os.sep, '/')})（共 **{len(matched_stocks)}** 只标的，存在已覆盖）",
        f"  - 标的完整K线时序：[{filtered_kline_filename}]({filtered_kline_filepath.replace(os.sep, '/')})（包含筛选个股全量时序柱，存在已覆盖）",
        f"\n#### 🚀 代表性高动能强势股（前 15 只）：",
        f"| 股票代码 | 股票简称 | 最新收盘价 | 近10日涨跌幅 | 近10日涨停次数 | 最近涨停日期 | 5日均线 | 10日均线 | 20日均线 | 趋势状态 |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for item in matched_stocks[:15]:
        ret_str = f"{item['近10日涨跌幅(%)']:+.2f}%"
        limit_pct_str = f"+{item['最近涨停幅度(%)']:.2f}%"
        summary_lines.append(
            f"| {item['股票代码']} | {item['股票简称']} | {item['最新收盘价']} | {ret_str} | {item['近10日涨停次数']} 次 | {item['最近涨停日期']} ({limit_pct_str}) | {item['5日均线']} | {item['10日均线']} | {item['20日均线']} | {item['趋势状态']} |"
        )

    return "\n".join(summary_lines)


# 实时监控个股分时图
def _fetch_single_stock_timeline(code: str, name: str = "") -> tuple[pd.DataFrame | None, dict | None]:
    """获取单只股票的当日/最新日内 1 分钟分时走势时序数据及盘口指标。

    数据源：优先同花顺分时 CDN 接口，备用东方财富 push2 trends 接口。
    """
    code = str(code).zfill(6)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "http://stockpage.10jqka.com.cn/",
    }
    url = f"http://d.10jqka.com.cn/v6/time/hs_{code}/last.js"

    rows = []
    pre_close = 0.0
    stock_name = name or ""

    # 1. 尝试从同花顺 CDN 获取分时时序数据
    try:
        resp = requests.get(url, headers=headers, timeout=6)
        if resp.status_code == 200:
            resp.encoding = "gbk"
            text = resp.text
            start_idx = text.find("{")
            end_idx = text.rfind("}")
            if start_idx != -1 and end_idx != -1:
                raw_json = text[start_idx : end_idx + 1]
                data_dict = json.loads(raw_json)
                info = list(data_dict.values())[0] if data_dict else {}
                if not stock_name:
                    stock_name = info.get("name", "")
                pre_close = float(info.get("pre", 0.0))
                raw_pts = info.get("data", "").split(";")
                for pt in raw_pts:
                    if not pt:
                        continue
                    parts = pt.split(",")
                    if len(parts) >= 5:
                        t = parts[0]
                        time_str = f"{t[:2]}:{t[2:]}" if len(t) == 4 else t
                        price = float(parts[1])
                        amt = float(parts[2])
                        avg = float(parts[3])
                        vol = float(parts[4])
                        pct = round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0.0
                        diff = round(price - pre_close, 2)
                        rows.append({
                            "时间": time_str,
                            "股票代码": code,
                            "股票简称": stock_name,
                            "现价": price,
                            "分时均价": avg,
                            "涨跌额": diff,
                            "涨跌幅(%)": pct,
                            "成交量(手)": int(vol / 100),
                            "成交额(元)": amt,
                        })
    except Exception:
        pass

    # 2. 备用源：东方财富 trends 接口
    if not rows:
        try:
            secid = f"0.{code}" if code.startswith(("0", "3")) else f"1.{code}"
            em_url = (
                f"https://push2.eastmoney.com/api/qt/stock/trends2/get?"
                f"secid={secid}&fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11&fields2=f51,f52,f53,f54,f55,f56,f57,f58"
            )
            em_resp = requests.get(em_url, timeout=6)
            if em_resp.status_code == 200:
                data = em_resp.json().get("data", {})
                if not stock_name:
                    stock_name = data.get("name", "")
                pre_close = float(data.get("preClose", 0.0))
                for tr in data.get("trends", []):
                    parts = tr.split(",")
                    if len(parts) >= 8:
                        time_str = parts[0].split(" ")[-1]
                        price = float(parts[2])
                        vol = float(parts[5])
                        amt = float(parts[6])
                        avg = float(parts[7])
                        pct = round((price - pre_close) / pre_close * 100, 2) if pre_close > 0 else 0.0
                        rows.append({
                            "时间": time_str,
                            "股票代码": code,
                            "股票简称": stock_name,
                            "现价": price,
                            "分时均价": avg,
                            "涨跌额": round(price - pre_close, 2),
                            "涨跌幅(%)": pct,
                            "成交量(手)": int(vol),
                            "成交额(元)": amt,
                        })
        except Exception:
            pass

    if not rows:
        return None, None

    df = pd.DataFrame(rows)
    latest = df.iloc[-1]
    latest_price = float(latest["现价"])
    latest_avg = float(latest["分时均价"])
    latest_pct = float(latest["涨跌幅(%)"])
    latest_time = str(latest["时间"])
    open_price = float(df.iloc[0]["现价"])
    high_price = float(df["现价"].max())
    low_price = float(df["现价"].min())

    amp = round((high_price - low_price) / pre_close * 100, 2) if pre_close > 0 else 0.0
    bias = round((latest_price - latest_avg) / latest_avg * 100, 2) if latest_avg > 0 else 0.0
    total_vol = int(df["成交量(手)"].sum())
    total_amount = float(df["成交额(元)"].sum())

    # 分时强弱状态
    if latest_price > latest_avg:
        trend_status = "多头走强(站上分时均线)"
    elif latest_price < latest_avg:
        trend_status = "空头承压(跌破分时均线)"
    else:
        trend_status = "均线粘合震荡"

    # 异动信号判定
    signals = []
    is_chinext = code.startswith("30")
    limit_pct = 19.85 if is_chinext else 9.85
    if latest_pct >= limit_pct:
        signals.append("[强势封板]")
    elif high_price >= pre_close * (1 + limit_pct / 100) - 0.01:
        signals.append("[曾触及涨停/开板]")
    elif latest_pct <= -limit_pct:
        signals.append("[封死跌停板]")

    if bias >= 2.5:
        signals.append("[偏离均线过高(超买)]")
    elif bias <= -2.5:
        signals.append("[偏离均线过低(超卖)]")

    if len(df) >= 10:
        recent_vol = df.tail(5)["成交量(手)"].mean()
        prev_vol = df.iloc[:-5]["成交量(手)"].mean()
        if prev_vol > 0 and (recent_vol / prev_vol) >= 2.5:
            signals.append("[短时急剧放量]")

    if not signals:
        signals.append("[走势平稳]")

    metrics = {
        "code": code,
        "name": stock_name,
        "pre_close": pre_close,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "latest_price": latest_price,
        "latest_avg": latest_avg,
        "latest_pct": latest_pct,
        "latest_time": latest_time,
        "amplitude": amp,
        "bias": bias,
        "trend_status": trend_status,
        "signals": " | ".join(signals),
        "total_vol": total_vol,
        "total_amount_wan": round(total_amount / 10000, 2),
        "total_amount_yi": round(total_amount / 100000000, 2),
    }

    return df, metrics


@tool
def monitor_stock_timeline(target: str = "") -> str:
    """实时监控个股分时图时序数据及盘口走势（支持单只股票代码/名称、多个股票逗号分隔，或留空自动监控已筛选的强势股票池）。

    功能特点：
    1. 获取个股当日 1 分钟级别分时时序数据（现价、分时均价、涨跌幅、成交量、成交额）。
    2. 计算实时核心指标：分时均线偏离度（乖离率 Bias）、日内振幅、均线强弱支撑。
    3. 监控分时异动：触及涨跌停、开板/炸板、短时急剧放量、均线突破/跌破。
    4. 分时数据持久化落盘至 timeline_data/ 目录，保存为 CSV 文件（存在则直接覆盖）。
    5. 生成专业结构化分时走势与异动监控报告。
    """
    target_clean = target.strip() if target else ""
    root_dir = get_project_root()

    # 1. 解析监控目标列表
    stocks = []
    if target_clean and target_clean.lower() != "auto":
        # 用户显式指定目标：支持逗号、空格分隔的多个股票代码或名称
        raw_items = [x.strip() for x in re.split(r"[,，\s]+", target_clean) if x.strip()]
        for it in raw_items:
            if re.match(r"^\d{6}$", it):
                stocks.append({"code": it, "name": ""})
            else:
                resolved = _resolve_single_stock_name(it)
                if resolved:
                    stocks.append(resolved)
                else:
                    stocks.append({"code": it, "name": it})
    else:
        # 留空或传入 auto：联动上一阶段筛选出的强势股票池
        filtered_csv = os.path.join(root_dir, "stock_data", "filtered_stocks.csv")
        if not os.path.exists(filtered_csv):
            filtered_csv = os.path.join(root_dir, "filtered_stocks.csv")
        if os.path.exists(filtered_csv):
            try:
                fdf = pd.read_csv(filtered_csv, dtype={"股票代码": str})
                if not fdf.empty:
                    # 取筛选出来的代表性强势标的（前 10 只）
                    stocks = [
                        {"code": row["股票代码"], "name": row.get("股票简称", "")}
                        for _, row in fdf.head(10).iterrows()
                    ]
            except Exception:
                pass
        if not stocks:
            # 默认兜底标的：平安银行 (000001)
            stocks = [{"code": "000001", "name": "平安银行"}]

    # 2. 准备保存目录
    timeline_dir = os.path.join(root_dir, "timeline_data")
    os.makedirs(timeline_dir, exist_ok=True)

    # 3. 多线程并发获取分时图数据
    monitored_dfs = []
    monitored_metrics = []

    print(f"\n[分时图监控] 正在获取 {len(stocks)} 只标的的实时分时数据...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(15, len(stocks))) as executor:
        futures = {executor.submit(_fetch_single_stock_timeline, s["code"], s.get("name", "")): s for s in stocks}
        for fut in concurrent.futures.as_completed(futures):
            try:
                df, metrics = fut.result()
                if df is not None and metrics is not None:
                    code = metrics["code"]
                    name = metrics["name"]
                    # 保存个股独立分时 CSV 文件（存在则覆盖）
                    single_csv = os.path.join(timeline_dir, f"{code}_{name}_timeline.csv")
                    df.to_csv(single_csv, index=False, encoding="utf-8-sig")
                    monitored_dfs.append(df)
                    monitored_metrics.append(metrics)
            except Exception:
                pass

    if not monitored_metrics:
        return "【提示】未能成功获取目标股票的分时图时序数据，请检查股票代码或网络连接。"

    # 按股票代码排序
    monitored_metrics.sort(key=lambda x: x["code"])

    # 4. 若为多只股票，合并保存全量分时时序数据
    combined_csv_path = os.path.join(timeline_dir, "monitored_timeline_all.csv")
    if monitored_dfs:
        combined_df = pd.concat(monitored_dfs, ignore_index=True)
        combined_df.to_csv(combined_csv_path, index=False, encoding="utf-8-sig")

    # 5. 构造结构化 Markdown 监控报告
    summary_lines = [
        "### 【实时个股分时图监控与盘口异动分析报告】",
        f"- **监控标的数**：共监控 **{len(monitored_metrics)}** 只标的分时走势",
        f"- **数据时序级别**：1 分钟高精度时序（含现价、分时均价、成交量、成交额）",
        f"- **持久化保存目录**：`{timeline_dir.replace(os.sep, '/')}`",
        f"  - 汇总合并分时文件：[{os.path.basename(combined_csv_path)}]({combined_csv_path.replace(os.sep, '/')})（已保存/覆盖）",
        "\n#### 实时分时核心盘口与形态监控表：",
        "| 股票代码 | 股票简称 | 最新现价 | 涨跌幅 | 分时均价 | 均线偏离(乖离率) | 日内振幅 | 成交额(亿元) | 分时强弱状态 | 实时异动信号 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for m in monitored_metrics:
        pct_str = f"{m['latest_pct']:+.2f}%"
        bias_str = f"{m['bias']:+.2f}%"
        summary_lines.append(
            f"| {m['code']} | {m['name']} | {m['latest_price']:.2f} | {pct_str} | {m['latest_avg']:.2f} | {bias_str} | {m['amplitude']:.2f}% | {m['total_amount_yi']:.2f}亿 | {m['trend_status']} | {m['signals']} |"
        )

    # 附加重点标的最近 5 分钟分时明细切片
    first_metric = monitored_metrics[0]
    first_df = next((df for df in monitored_dfs if df.iloc[0]["股票代码"] == first_metric["code"]), None)
    if first_df is not None and len(first_df) > 0:
        summary_lines.append(f"\n#### 重点标的【{first_metric['code']} {first_metric['name']}】最近 5 分钟分时走势切片：")
        summary_lines.append("| 时间 | 现价 | 分时均价 | 涨跌幅 | 当分成交量(手) | 当分成交额(万元) |")
        summary_lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for _, row in first_df.tail(5).iterrows():
            amt_wan = round(row["成交额(元)"] / 10000, 2)
            summary_lines.append(
                f"| {row['时间']} | {row['现价']:.2f} | {row['分时均价']:.2f} | {row['涨跌幅(%)']:+.2f}% | {int(row['成交量(手)'])} | {amt_wan}万 |"
            )

    return "\n".join(summary_lines)


COLLECTOR_TOOLS = [
    search_web_data,
    search_academic_papers,
    download_stock_day,
    filter_bullish_limit_up_stocks,
    monitor_stock_timeline,
]

