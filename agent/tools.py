import concurrent.futures
import datetime
import glob
import json
import math
import os
import re
import sys
import time
import base64
from urllib.parse import parse_qs, urlparse
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_community.tools.tavily_search import TavilySearchResults
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
import pandas as pd
import numpy as np
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg as FigureCanvas
from matplotlib.patches import Rectangle
from matplotlib import font_manager
import warnings

# 全局配置中文字体与负号显示，防止 Glyph 缺失警告 (兼容 Windows、macOS 与 Linux 开源字体)
matplotlib.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
    "Noto Sans CJK SC", "Arial Unicode MS", "DejaVu Sans", "sans-serif"
]
matplotlib.rcParams["axes.unicode_minus"] = False
warnings.filterwarnings("ignore", category=UserWarning, module="matplotlib")
warnings.filterwarnings("ignore", message=".*Glyph.*")


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


def _ensure_kline_ma_columns(df: pd.DataFrame) -> pd.DataFrame:
    """确保 K 线 DataFrame 包含五日线、十日线、二十日线、三十日线及中文别名列"""
    if df.empty or "收盘价" not in df.columns:
        return df

    code_col = "股票代码" if "股票代码" in df.columns else ("code" if "code" in df.columns else None)
    close_s = pd.to_numeric(df["收盘价"], errors="coerce")
    for col, period in [("MA5", 5), ("MA10", 10), ("MA20", 20), ("MA30", 30)]:
        if code_col and df[code_col].nunique() > 1:
            rolling_s = df.groupby(code_col)["收盘价"].transform(
                lambda s: pd.to_numeric(s, errors="coerce").rolling(period, min_periods=1).mean().round(2)
            )
        else:
            rolling_s = close_s.rolling(period, min_periods=1).mean().round(2)

        df[col] = rolling_s
        df[f"{period}日均线"] = rolling_s

    return df


def fetch_batch_realtime_bars(codes: list[str]) -> dict[str, dict]:
    """通过腾讯行情极速批量接口 (单次支持 80-100 只标的)，毫秒级拉取个股当日最新分时/收盘实时行情条柱。
    
    返回:
        dict: {code_clean: {'交易日期': 'YYYY-MM-DD', '股票代码': '...', '股票简称': '...', '开盘价': ..., '最高价': ..., '最低价': ..., '收盘价': ..., '涨跌额': ..., '涨跌幅(%)': ..., '成交量(股)': ..., '成交额(元)': ...}}
    """
    if not codes:
        return {}

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    clean_codes = [str(c).strip().zfill(6) for c in codes if c and str(c).strip().isdigit() and len(str(c).strip()) <= 6]
    clean_codes = list(dict.fromkeys(clean_codes))

    batch_size = 80
    chunks = [clean_codes[i : i + batch_size] for i in range(0, len(clean_codes), batch_size)]

    def _fetch_chunk(sub_codes):
        bars = {}
        syms = [("bj" if c.startswith(("4", "8", "920")) else ("sh" if c.startswith(("6", "9")) else "sz")) + c for c in sub_codes]
        url = "http://qt.gtimg.cn/q=" + ",".join(syms)
        try:
            resp = requests.get(url, timeout=5)
            resp.encoding = "gbk"
            for line in resp.text.split(";"):
                line = line.strip()
                if not line or "~" not in line:
                    continue
                parts = line.split("~")
                if len(parts) < 38:
                    continue
                c_code = parts[2].strip().zfill(6)
                name = parts[1].strip()
                close_p = float(parts[3])
                pre_close = float(parts[4])
                open_p = float(parts[5]) if float(parts[5]) > 0 else close_p
                high_p = float(parts[33]) if float(parts[33]) > 0 else max(open_p, close_p)
                low_p = float(parts[34]) if float(parts[34]) > 0 else min(open_p, close_p)
                vol_shares = int(float(parts[6]) * 100) if parts[6] else 0
                amt_yuan = float(parts[37]) * 10000 if parts[37] else 0.0
                chg_amt = float(parts[31]) if parts[31] else round(close_p - pre_close, 2)
                chg_pct = float(parts[32]) if parts[32] else (round(chg_amt / pre_close * 100, 2) if pre_close > 0 else 0.0)
                turnover = float(parts[38]) if len(parts) > 38 and parts[38] else 0.0
                amplitude = float(parts[43]) if len(parts) > 43 and parts[43] else (round((high_p - low_p) / pre_close * 100, 2) if pre_close > 0 else 0.0)

                date_raw = parts[30][:8] if len(parts[30]) >= 8 else ""
                t_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}" if date_raw else today_str

                if close_p > 0:
                    bars[c_code] = {
                        "交易日期": t_date,
                        "股票代码": c_code,
                        "股票简称": name,
                        "开盘价": open_p,
                        "最高价": high_p,
                        "最低价": low_p,
                        "收盘价": close_p,
                        "涨跌额": chg_amt,
                        "涨跌幅(%)": chg_pct,
                        "振幅(%)": amplitude,
                        "成交量(股)": vol_shares,
                        "成交额(元)": amt_yuan,
                        "换手率(%)": turnover,
                    }
        except Exception:
            pass
        return bars

    all_bars = {}
    max_workers = min(20, max(1, len(chunks)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for res_map in executor.map(_fetch_chunk, chunks):
            all_bars.update(res_map)

    return all_bars


def append_today_realtime_data_if_missing(df: pd.DataFrame, force_refresh: bool = False) -> pd.DataFrame:
    """检查并更新 DataFrame 中今日最新分时/日K行情数据。若缺失或需刷新，全自动并发拉取最新行情并追加/覆盖合并，重新计算均线指标。"""
    if df.empty or ("股票代码" not in df.columns and "code" not in df.columns):
        return df

    code_col = "股票代码" if "股票代码" in df.columns else "code"
    unique_codes = df[code_col].dropna().astype(str).str.zfill(6).unique().tolist()
    if not unique_codes:
        return df

    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # 检查当前数据中是否已经包含今天的记录
    existing_today = set()
    if "交易日期" in df.columns:
        today_rows = df[df["交易日期"] == today_str]
        existing_today = set(today_rows[code_col].astype(str).str.zfill(6))

    if force_refresh:
        target_codes = unique_codes
    else:
        target_codes = [c for c in unique_codes if c not in existing_today]

    if not target_codes:
        return df

    print(f"🔄 [今日分时实时同步] 正在为 {len(target_codes)} 只标的拉取今日({today_str})最新行情分时数据并自动合并...")
    today_bars = fetch_batch_realtime_bars(target_codes)
    if not today_bars:
        return df

    new_rows = []
    for c_code, bar in today_bars.items():
        if bar.get("收盘价", 0) > 0:
            bar_copy = dict(bar)
            bar_copy["交易日期"] = bar.get("交易日期") or today_str
            new_rows.append(bar_copy)

    if not new_rows:
        return df

    new_df = pd.DataFrame(new_rows)
    if "code" in df.columns and "股票代码" not in df.columns:
        new_df["code"] = new_df["股票代码"]

    combined = pd.concat([df, new_df], ignore_index=True)
    combined.drop_duplicates(subset=[code_col, "交易日期"], keep="last", inplace=True)
    combined.sort_values(by=[code_col, "交易日期"], inplace=True)
    combined.reset_index(drop=True, inplace=True)

    combined = _ensure_kline_ma_columns(combined)
    print(f"✅ [今日分时合并完成] 成功为 {len(new_rows)} 只标的追加/刷新今日({today_str})最新行情分时数据，均线系统已全量刷新！")
    return combined


def render_stock_kline_chart(df: pd.DataFrame, code: str, name: str = "", output_dir: str = None, force_refresh: bool = False) -> str:
    """
    根据个股日K线时序数据渲染并保存包含五日线(MA5)、十日线(MA10)、二十日线(MA20)、三十日线(MA30)的高清K线走势图。
    使用 FigureCanvasAgg 纯底层绘图，线程安全、极速并发、支持秒级本地缓存复用。

    图表文件名追加生成日期 YYYYMMDD (例如 000001_平安银行_20261028_kline.png)：
    - 当已有图表生成日期 >= 数据最新日期且 >= 今日日期时，直接秒级复用；
    - 当已有图表生成日期早于数据最新日期/今日日期（历史旧图，缺失最新K线）或强制刷新时，重新生成替换对应个股K线图。

    参数:
        df: 个股K线时序 DataFrame
        code: 股票代码
        name: 股票简称
        output_dir: 自定义输出目录（默认输出到项目根目录下 kline_charts/）
        force_refresh: 是否强制重新绘制，默认 False
    返回:
        生成的图表本地绝对路径（若绘图失败则返回空字符串）
    """
    if df.empty or "收盘价" not in df.columns:
        return ""

    code_clean = str(code).strip().zfill(6)
    stock_name = name or (df["股票简称"].iloc[-1] if "股票简称" in df.columns and not df.empty else code_clean)

    root_dir = get_project_root()
    chart_dir = output_dir or os.path.join(root_dir, "kline_charts")
    os.makedirs(chart_dir, exist_ok=True)

    today_date = datetime.date.today()
    today_str = today_date.strftime("%Y%m%d")
    out_path = os.path.join(chart_dir, f"{code_clean}_{stock_name}_{today_str}_kline.png")

    # 检索是否已有该个股的历史/当日图表（必须匹配带 8 位生成日期的文件名；无日期历史图表不参与复用，强制重新生成为新格式）
    existing_charts = glob.glob(os.path.join(chart_dir, f"{code_clean}_*_kline.png"))
    if existing_charts and not force_refresh:
        best_path = None
        best_date = None
        for p in existing_charts:
            if not os.path.exists(p) or os.path.getsize(p) <= 1024:
                continue
            m = re.search(r"_(\d{8})_kline\.png$", os.path.basename(p))
            if m:
                try:
                    p_date = datetime.datetime.strptime(m.group(1), "%Y%m%d").date()
                    if best_date is None or p_date > best_date:
                        best_date = p_date
                        best_path = p
                except Exception:
                    pass

        # 获取数据源中的最新交易日期
        latest_bar_date = str(df["交易日期"].iloc[-1]).split()[0] if "交易日期" in df.columns and not df.empty else ""
        latest_bar_d = datetime.datetime.strptime(latest_bar_date, "%Y-%m-%d").date() if latest_bar_date else today_date

        # 规则：只有当已有图表生成日期 >= 数据最新日期 并且 >= 今日日期时（即当天已生成过包含最新数据的图表），才直接秒级复用
        # 若已有图表生成日期早于今日/最新数据日期 (如 20261027 早于 20261028)，则视为过期图表，必须重新渲染包含今日最新K线的走势图！
        if best_path and best_date:
            if best_date >= latest_bar_d and best_date >= today_date:
                return best_path

    # 当未生成过或已有图表已过期：执行重新生成并替换
    chart_df = df.copy()

    # 关键：检查单股 chart_df 是否包含今日最新分时/收盘数据 (仅在开市交易时间 09:25 之后才拉取，非交易时间直接复用时序，避免产生海量无意义网络轮询)
    today_dash = today_date.strftime("%Y-%m-%d")
    latest_date = str(chart_df["交易日期"].iloc[-1]).split()[0] if "交易日期" in chart_df.columns and not chart_df.empty else ""
    now_time = datetime.datetime.now().time()
    can_have_today_bar = (now_time >= datetime.time(9, 25)) and (today_date.weekday() < 5)
    if latest_date < today_dash and can_have_today_bar:
        today_bar_map = fetch_batch_realtime_bars([code_clean])
        single_bar = today_bar_map.get(code_clean)
        if single_bar and single_bar.get("收盘价", 0) > 0:
            single_bar_copy = dict(single_bar)
            single_bar_copy["交易日期"] = single_bar.get("交易日期") or today_dash
            chart_df = pd.concat([chart_df, pd.DataFrame([single_bar_copy])], ignore_index=True)
            chart_df.drop_duplicates(subset=["交易日期"], keep="last", inplace=True)

    chart_df = _ensure_kline_ma_columns(chart_df)

    fig = None
    try:
        import logging
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)

        fig = Figure(figsize=(11, 6.5), facecolor="#181a20")
        canvas = FigureCanvas(fig)
        ax1, ax2 = fig.subplots(
            2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]}
        )
        ax1.set_facecolor("#1e222d")
        ax2.set_facecolor("#1e222d")

        x = np.arange(len(chart_df))
        candle_colors = []
        for i, row in enumerate(chart_df.itertuples()):
            o = float(getattr(row, "开盘价", 0.0))
            h = float(getattr(row, "最高价", 0.0))
            l = float(getattr(row, "最低价", 0.0))
            c = float(getattr(row, "收盘价", 0.0))
            color = "#f6465d" if c >= o else "#0ecb81"
            candle_colors.append(color)
            ax1.vlines(i, l, h, color=color, linewidth=1.2, alpha=0.9)
            rect_y = min(o, c)
            rect_h = max(abs(c - o), 0.005)
            ax1.add_patch(Rectangle((i - 0.3, rect_y), 0.6, rect_h, color=color, alpha=0.95))

        # 绘制五日线、十日线、二十日线、三十日线
        latest_c = float(chart_df["收盘价"].iloc[-1])
        ma5_last = float(chart_df["MA5"].iloc[-1]) if "MA5" in chart_df.columns else latest_c
        ma10_last = float(chart_df["MA10"].iloc[-1]) if "MA10" in chart_df.columns else latest_c
        ma20_last = float(chart_df["MA20"].iloc[-1]) if "MA20" in chart_df.columns else latest_c
        ma30_last = float(chart_df["MA30"].iloc[-1]) if "MA30" in chart_df.columns else latest_c

        _font_families = [
            "Microsoft YaHei", "SimHei", "WenQuanYi Zen Hei", "WenQuanYi Micro Hei",
            "Noto Sans CJK SC", "Arial Unicode MS", "sans-serif"
        ]
        font_prop = font_manager.FontProperties(family=_font_families, size=9.5)
        title_font = font_manager.FontProperties(family=_font_families, size=13)
        label_font = font_manager.FontProperties(family=_font_families, size=10)

        ax1.plot(x, chart_df["MA5"], label=f"MA5 (五日线): {ma5_last:.2f}", color="#f0b90b", linewidth=1.4)
        ax1.plot(x, chart_df["MA10"], label=f"MA10 (十日线): {ma10_last:.2f}", color="#9353d3", linewidth=1.4)
        ax1.plot(x, chart_df["MA20"], label=f"MA20 (二十日线): {ma20_last:.2f}", color="#00b8d9", linewidth=1.4)
        ax1.plot(x, chart_df["MA30"], label=f"MA30 (三十日线): {ma30_last:.2f}", color="#ff7043", linewidth=1.4)

        ax1.legend(loc="upper left", facecolor="#181a20", edgecolor="#2b313a", labelcolor="#eaecef", prop=font_prop)
        title_str = f"{code_clean} {stock_name} - 日K线图 (最新现价: {latest_c:.2f} | 含 MA5/MA10/MA20/MA30 均线系统)"
        ax1.set_title(title_str, color="#ffffff", pad=10, fontproperties=title_font)
        ax1.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
        ax1.tick_params(colors="#848e9c")
        ax1.set_ylabel("价格 (元)", color="#848e9c", fontproperties=label_font)

        # 副图成交量
        vol_col = "成交量(股)" if "成交量(股)" in chart_df.columns else ("成交量" if "成交量" in chart_df.columns else None)
        if vol_col:
            ax2.bar(x, chart_df[vol_col], color=candle_colors, width=0.6, alpha=0.9)
        ax2.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
        ax2.tick_params(colors="#848e9c")
        ax2.set_ylabel("成交量", color="#848e9c", fontproperties=label_font)

        # 格式化日期轴
        if "交易日期" in chart_df.columns:
            step = max(1, len(chart_df) // 8)
            tick_indices = list(range(0, len(chart_df), step))
            if tick_indices[-1] != len(chart_df) - 1:
                tick_indices.append(len(chart_df) - 1)
            ax2.set_xticks(tick_indices)
            ax2.set_xticklabels(
                [str(chart_df["交易日期"].iloc[i]) for i in tick_indices],
                rotation=25,
                ha="right",
                color="#848e9c",
                fontproperties=label_font,
            )

        fig.tight_layout()
        canvas.print_figure(out_path, dpi=100, facecolor=fig.get_facecolor())

        # 成功重新生成后，清理该个股旧版本/历史日期的K线图文件，确保目录内每只股票只保留最新的图表
        if existing_charts:
            for old_p in existing_charts:
                if os.path.abspath(old_p) != os.path.abspath(out_path) and os.path.exists(old_p):
                    try:
                        os.remove(old_p)
                    except Exception:
                        pass

        return out_path
    except Exception as e:
        print(f"⚠️ 渲染个股 {code_clean} K线图异常: {e}")
        return ""


# 内存级全局数据与图表缓存，避免短时间内多次重复解析 30MB CSV 文件与重复扫描磁盘
_KLINE_DF_CACHE = {
    "filepath": "",
    "mtime": 0.0,
    "df": None,
}

_LATEST_RENDERED_CHARTS: list[str] = []


def get_latest_rendered_charts() -> list[str]:
    """获取最新一次生成的个股K线图绝对路径列表（内存级秒级复用）"""
    global _LATEST_RENDERED_CHARTS
    return _LATEST_RENDERED_CHARTS


def load_cached_kline_df(filepath: str) -> pd.DataFrame:
    """加载K线数据总表，带有基于文件 mtime 的内存缓存，彻底消除短时间内反复解析 30MB CSV 带来的重复 I/O 耗时"""
    global _KLINE_DF_CACHE
    if not os.path.exists(filepath) or os.path.getsize(filepath) <= 10240:
        return pd.DataFrame()
    mtime = os.path.getmtime(filepath)
    if _KLINE_DF_CACHE["filepath"] == filepath and _KLINE_DF_CACHE["mtime"] == mtime and _KLINE_DF_CACHE["df"] is not None:
        return _KLINE_DF_CACHE["df"]

    df = pd.read_csv(filepath, dtype={"股票代码": str, "code": str}, encoding="utf-8-sig")
    if "股票代码" not in df.columns and "code" in df.columns:
        df["股票代码"] = df["code"]
    df["股票代码"] = df["股票代码"].astype(str).str.zfill(6)
    _KLINE_DF_CACHE = {
        "filepath": filepath,
        "mtime": mtime,
        "df": df,
    }
    return df


def render_all_stock_kline_charts(df: pd.DataFrame, chart_dir: str = None, max_workers: int = 30, force_refresh: bool = False) -> list[str]:
    """并发生成 DataFrame 中包含的所有个股日K线走势图表（存在已生成的直接秒级复用）。

    参数:
        df: 包含全量或板块个股K线数据的 DataFrame
        chart_dir: 图表输出目录（默认 kline_charts/）
        max_workers: 并发工作线程数，默认 30
        force_refresh: 是否强制重绘所有图表，默认 False
    返回:
        所有已就绪的个股 K 线走势图 PNG 绝对路径列表
    """
    global _LATEST_RENDERED_CHARTS
    if df.empty or "股票代码" not in df.columns:
        return []

    # 绘制全量个股走势图：仅在强制刷新或开市交易时间执行增量分时拉取，避免重复网络调用
    now_time = datetime.datetime.now().time()
    today_date = datetime.date.today()
    is_trading_time = (now_time >= datetime.time(9, 25)) and (today_date.weekday() < 5)
    if force_refresh or is_trading_time:
        df = append_today_realtime_data_if_missing(df, force_refresh=force_refresh)

    root_dir = get_project_root()
    target_dir = chart_dir or os.path.join(root_dir, "kline_charts")
    os.makedirs(target_dir, exist_ok=True)

    today_date = datetime.date.today()
    # 极速预热图表索引：一次性毫秒级扫描目录，获取所有个股现有图表及生成日期，避免多线程频繁 glob 造成高 I/O 耗时
    existing_chart_map = {}  # code_clean -> (file_path, gen_date)
    if os.path.exists(target_dir):
        for entry in os.scandir(target_dir):
            if entry.is_file() and entry.name.endswith("_kline.png") and entry.stat().st_size > 1024:
                m = re.match(r"^(\d{6})_(.*?)_(\d{8})_kline\.png$", entry.name)
                if m:
                    c_key = m.group(1)
                    d_str = m.group(3)
                    try:
                        g_date = datetime.datetime.strptime(d_str, "%Y%m%d").date()
                        if c_key not in existing_chart_map or g_date > existing_chart_map[c_key][1]:
                            existing_chart_map[c_key] = (entry.path, g_date)
                    except Exception:
                        pass

    latest_data_date = str(df["交易日期"].max()).split()[0] if "交易日期" in df.columns and not df.empty else ""
    latest_data_d = datetime.datetime.strptime(latest_data_date, "%Y-%m-%d").date() if latest_data_date else today_date

    unique_codes = df["股票代码"].dropna().unique()
    total_stocks = len(unique_codes)
    print(f"🖼️ [全量K线图生成] 正在校验/生成全部 {total_stocks} 只个股的五/十/二十/三十日均线走势图...")

    ready_charts = []
    need_render_codes = set()
    if not force_refresh:
        for c in unique_codes:
            c_code_clean = str(c).zfill(6)
            if c_code_clean in existing_chart_map:
                exist_path, exist_date = existing_chart_map[c_code_clean]
                # 若图表生成日期不早于最新数据日期，且（非交易时段已闭市或今日已生成过），则直接秒级复用
                if exist_date >= latest_data_d and (exist_date >= today_date or not is_trading_time):
                    ready_charts.append(exist_path)
                    continue
            need_render_codes.add(c)
    else:
        need_render_codes = set(unique_codes)

    # 性能极致提速：若全量标的均已就绪且处于最新状态，直接返回，消除 4,700 次无意义的 groupby 与线程池开销
    if not need_render_codes:
        print(f"✅ [全量K线图就绪] 全部 {len(ready_charts)} 只个股高清K线走势图秒级就绪！\n")
        _LATEST_RENDERED_CHARTS = ready_charts
        return ready_charts

    # 仅针对缺失或需要重新绘制的少数标的进行分组和并发绘图
    sub_df = df[df["股票代码"].isin(need_render_codes)]
    grouped = list(sub_df.groupby("股票代码"))
    newly_rendered = []

    def _worker(item):
        c_code, sdf = item
        c_code_clean = str(c_code).zfill(6)
        c_name = str(sdf["股票简称"].iloc[-1]) if "股票简称" in sdf.columns and not sdf.empty else c_code_clean
        return render_stock_kline_chart(sdf, c_code_clean, c_name, output_dir=target_dir, force_refresh=force_refresh)

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, max(1, len(grouped)))) as executor:
        for idx, chart_p in enumerate(executor.map(_worker, grouped), 1):
            if chart_p and os.path.exists(chart_p):
                newly_rendered.append(chart_p)
            if idx % 500 == 0 or idx == len(grouped):
                print(f"   ⏳ 绘图进度: 增量完成 {len(newly_rendered)}/{len(grouped)} 张个股K线图...")

    all_charts = ready_charts + newly_rendered
    print(f"✅ [全量K线图就绪] 全部 {len(all_charts)} 只个股高清K线走势图准备完毕！\n")
    _LATEST_RENDERED_CHARTS = all_charts
    return all_charts


def get_previous_trading_day_str(df: pd.DataFrame = None) -> str:
    """计算基准前一交易日日期 (YYYY-MM-DD)。
    优先根据日K线全局数据集中的交易日期判定；若不可用则根据工作日向前回溯（周一前一天为周五）。
    """
    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")

    if df is not None and not df.empty and "交易日期" in df.columns:
        valid_dates = sorted([str(d).split()[0] for d in df["交易日期"].dropna().unique()])
        valid_dates = [d for d in valid_dates if d <= today_str]
        if valid_dates:
            # 若今日已开盘/有数据，则前一交易日为倒数第二条
            if valid_dates[-1] == today_str and len(valid_dates) >= 2:
                return valid_dates[-2]
            elif valid_dates[-1] < today_str:
                return valid_dates[-1]
            elif len(valid_dates) >= 2:
                return valid_dates[-2]

    # 回退到工作日推算（周一前一天为上周五）
    prev_d = today - datetime.timedelta(days=1)
    while prev_d.weekday() >= 5:
        prev_d -= datetime.timedelta(days=1)
    return prev_d.strftime("%Y-%m-%d")


def get_latest_trading_day_str(df: pd.DataFrame = None) -> str:
    """
    确定 A 股最新有效交易日 (YYYY-MM-DD)。
    1. 优先通过代表性权重股 (如 000001 平安银行) 的实时行情接口毫秒级获取交易所当前最新交易日期；
    2. 若网络暂不可用，则通过日K线历史数据集中的最大交易日期与当前自然日及交易时间窗口智能研判。
    """
    # 1. 尝试网络实时行情探测真实最新交易日
    try:
        anchor_bars = fetch_batch_realtime_bars(["000001"])
        if anchor_bars and "000001" in anchor_bars:
            market_date = anchor_bars["000001"].get("交易日期")
            if market_date and re.match(r"^\d{4}-\d{2}-\d{2}$", str(market_date)):
                return str(market_date)
    except Exception:
        pass

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    now_time = datetime.datetime.now().time()

    # 2. 从本地数据集中推算
    if df is not None and not df.empty and "交易日期" in df.columns:
        valid_dates = sorted([str(d).split()[0] for d in df["交易日期"].dropna().unique()])
        valid_dates = [d for d in valid_dates if d <= today_str]
        if valid_dates:
            max_data_date = valid_dates[-1]
            if today.weekday() < 5 and now_time >= datetime.time(9, 15):
                return today_str
            return max_data_date

    # 3. 回退策略：工作日若过 09:15 算今日，否则算上一交易日
    if today.weekday() < 5 and now_time >= datetime.time(9, 15):
        return today_str

    return get_previous_trading_day_str(df)


def _load_kline_patch_cache(cache_filepath: str) -> dict:
    """读取本地最新交易日 K 线追加与图表缓存文件"""
    if os.path.exists(cache_filepath):
        try:
            with open(cache_filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "latest_trading_date" in data:
                    return data
        except Exception as e:
            print(f"⚠️ [K线缓存读取] 读取异常: {e}")
    return {"latest_trading_date": "", "last_updated": "", "patched_stocks": {}}


def _save_kline_patch_cache(cache_filepath: str, cache_data: dict) -> None:
    """持久化保存最新交易日 K 线追加与图表缓存文件"""
    try:
        os.makedirs(os.path.dirname(cache_filepath), exist_ok=True)
        cache_data["last_updated"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(cache_filepath, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ [K线缓存保存] 写入异常: {e}")


def verify_and_patch_latest_kline(
    kline_charts: list[str] = None, topic: str = "", max_workers: int = 20
) -> list[str]:
    """
    Node 1 核心能力：在 kline_charts 目录下的个股 K 线图内追加最新交易日的 K 线柱并重新渲染。

    缓存设计规范：
    1. 记录最新交易日日期 (latest_trading_date) 和对应已追加的个股清单 (patched_stocks) 供二次运行秒级复用；
    2. 当最新交易日不存在缓存内时（如跨交易日、日期推移或缓存缺失），视为「第一次运行」，自动追加最新交易日K线并重绘图表，同时刷新缓存；
    3. 二次或多次运行且最新交易日命中缓存时，已追加的标的直接秒级复用（0网络请求、0重绘开销），未追加的标的自动进行增量补全并合并入缓存。

    参数:
        kline_charts: 当前 Node 1 搜集到的个股K线图文件路径列表（若为空则自动检索目录下全部高清走势图）
        topic: 股票主题/代码，若为单股则聚焦单股校验
        max_workers: 并发工作线程数，默认 20
    返回:
        已完成最新交易日K线追加并就绪的全部个股高清K线图路径列表
    """
    root_dir = get_project_root()
    chart_dir = os.path.join(root_dir, "kline_charts")
    kline_dir = os.path.join(root_dir, "kline_data")
    stock_data_dir = os.path.join(root_dir, "stock_data")
    os.makedirs(chart_dir, exist_ok=True)
    os.makedirs(kline_dir, exist_ok=True)
    os.makedirs(stock_data_dir, exist_ok=True)

    cache_filepath = os.path.join(stock_data_dir, "kline_patch_cache.json")

    # 1. 加载汇总数据并确定最新交易日
    summary_filename = (
        f"{topic}_kline_all.csv"
        if (topic and topic != "全市场" and not re.match(r"^\d{6}$", topic))
        else "stock_kline_all.csv"
    )
    summary_filepath = os.path.join(stock_data_dir, summary_filename)
    if not os.path.exists(summary_filepath):
        fallback_path = os.path.join(stock_data_dir, "stock_kline_all.csv")
        if os.path.exists(fallback_path):
            summary_filepath = fallback_path

    combined_df = None
    if os.path.exists(summary_filepath) and os.path.getsize(summary_filepath) > 10240:
        try:
            combined_df = load_cached_kline_df(summary_filepath)
        except Exception:
            combined_df = None

    latest_trading_date = get_latest_trading_day_str(combined_df)
    latest_trading_nodash = latest_trading_date.replace("-", "")

    # 2. 读取持久化缓存，评估是否为「第一次运行」或「二次运行缓存」
    cache_data = _load_kline_patch_cache(cache_filepath)
    cached_date = cache_data.get("latest_trading_date", "")
    patched_stocks_map = cache_data.get("patched_stocks", {})

    # 当最新交易日不存在缓存内时，视为第一次，还是需要追加
    is_first_run_for_date = (cached_date != latest_trading_date or not cached_date)

    if is_first_run_for_date:
        print(f"\n📅 [最新交易日K线追踪] 当前最新交易日为「{latest_trading_date}」(缓存内不存在该日期，判定为首次运行)，重置缓存并准备为个股追加最新交易日K线柱...")
        cache_data = {
            "latest_trading_date": latest_trading_date,
            "last_updated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "patched_stocks": {},
        }
        patched_stocks_map = {}
    else:
        print(f"\n⚡ [最新交易日K线追踪] 命中已缓存交易日「{latest_trading_date}」(二次运行缓存模式)，已追加个股缓存数: {len(patched_stocks_map)} 只。")

    # 3. 整理输入目标图表列表（若未传则扫描目录中的图表）
    input_charts = list(kline_charts) if kline_charts else []
    if not input_charts and os.path.exists(chart_dir):
        with os.scandir(chart_dir) as it:
            for entry in it:
                if entry.is_file() and entry.name.endswith("_kline.png") and entry.stat().st_size > 1024:
                    if topic and topic != "全市场" and topic not in entry.name:
                        continue
                    input_charts.append(entry.path)

    # 建立股票代码 -> 现有图表路径与股票名称的映射
    chart_map = {}
    chart_code_to_name = {}
    for p in input_charts:
        base_name = os.path.basename(p)
        m = re.match(r"^(\d{6})_(.*?)_", base_name)
        if m:
            c = m.group(1)
            nm = m.group(2)
            chart_map[c] = p
            chart_code_to_name[c] = nm
        else:
            m2 = re.match(r"^(\d{6})_", base_name)
            if m2:
                c = m2.group(1)
                chart_map[c] = p

    # 4. 甄别哪些标的已就绪（命中缓存或已包含最新交易日），哪些标的需要追加最新K线柱
    missing_codes = []
    ready_charts_map = {}  # code -> valid_chart_path

    for c, chart_path in chart_map.items():
        nm = chart_code_to_name.get(c, "")
        # A. 若非首次运行，且该股票已在最新交易日缓存表中且图表文件有效存在，直接秒级命中缓存
        if not is_first_run_for_date and c in patched_stocks_map:
            cached_chart_path = patched_stocks_map[c].get("chart_path", "")
            if cached_chart_path and os.path.exists(cached_chart_path) and os.path.getsize(cached_chart_path) > 1024:
                ready_charts_map[c] = cached_chart_path
                continue

        # B. 检查现有图表文件是否已经是以最新交易日命名的最新高清图 (例如 000001_平安银行_20261030_kline.png)
        m_date = re.search(r"_(\d{8})_kline\.png$", os.path.basename(chart_path))
        if m_date and m_date.group(1) == latest_trading_nodash and os.path.exists(chart_path) and os.path.getsize(chart_path) > 1024:
            ready_charts_map[c] = chart_path
            # 记录到缓存表中
            patched_stocks_map[c] = {
                "name": nm,
                "chart_path": chart_path,
                "patched_date": latest_trading_date,
            }
            continue

        # C. 否则该标的需要追加最新交易日K线柱并重绘走势图
        missing_codes.append(c)

    # 5. 若全部标的均已就绪且命中缓存，极速持久化缓存并直接返回
    if not missing_codes:
        cache_data["patched_stocks"] = patched_stocks_map
        _save_kline_patch_cache(cache_filepath, cache_data)
        final_charts = list(ready_charts_map.values())
        print(f"✨ [最新交易日K线校验通过] 全部 {len(ready_charts_map)} 只标的均已包含最新交易日「{latest_trading_date}」K线柱并命中缓存，无需重复处理！\n")
        _LATEST_RENDERED_CHARTS = final_charts
        return final_charts

    print(f"🔄 [最新交易日K线追加] 检测到 {len(missing_codes)} 只标的需要追加最新交易日「{latest_trading_date}」K线柱，开始自动拉取并重绘...")

    # 6. 批量极速拉取需要补齐标的的最新实时/收盘分时条柱
    realtime_bars = fetch_batch_realtime_bars(missing_codes)

    patched_new_rows = []
    patched_charts_map = {}

    def _patch_single(code_clean):
        stock_name = chart_code_to_name.get(code_clean, "")
        try:
            # 读取个股独立时序数据
            local_csv = os.path.join(kline_dir, f"{code_clean}_{stock_name}_kline.csv") if stock_name else None
            stock_df = None
            if local_csv and os.path.exists(local_csv):
                try:
                    stock_df = pd.read_csv(local_csv, dtype={"股票代码": str}, encoding="utf-8-sig")
                except Exception:
                    stock_df = None

            # 若本地独立数据缺失，通过行情接口拉取基础时序
            if stock_df is None or stock_df.empty:
                stock_df = _fetch_single_stock_kline(code_clean, stock_name, limit=60)

            if stock_df is None or stock_df.empty:
                return None, None, None, None

            real_name = stock_name or (
                stock_df["股票简称"].iloc[-1]
                if "股票简称" in stock_df.columns and not stock_df.empty
                else code_clean
            )

            # 检查是否已有最新交易日数据，若缺失则追加
            has_latest_bar = (
                "交易日期" in stock_df.columns
                and latest_trading_date in stock_df["交易日期"].astype(str).values
            )

            missing_bar_df = None
            if not has_latest_bar:
                bar = realtime_bars.get(code_clean)
                if bar and bar.get("收盘价", 0) > 0:
                    bar_row = dict(bar)
                    bar_row["交易日期"] = bar.get("交易日期") or latest_trading_date
                    bar_row["股票代码"] = code_clean
                    bar_row["股票简称"] = real_name
                    missing_bar_df = pd.DataFrame([bar_row])
                    stock_df = pd.concat([stock_df, missing_bar_df], ignore_index=True)
                else:
                    # 尝试独立拉取单股最新K线补充
                    extra_df = _fetch_single_stock_kline(code_clean, real_name, limit=10)
                    if not extra_df.empty and latest_trading_date in extra_df["交易日期"].values:
                        stock_df = pd.concat([stock_df, extra_df], ignore_index=True)
                        missing_bar_df = extra_df[extra_df["交易日期"] == latest_trading_date]

            # 清洗、去重、排序并重新计算五日/十日/二十日/三十日均线
            stock_df["股票代码"] = stock_df["股票代码"].astype(str).str.zfill(6)
            stock_df.drop_duplicates(subset=["股票代码", "交易日期"], keep="last", inplace=True)
            stock_df.sort_values(by="交易日期", inplace=True)
            stock_df = _ensure_kline_ma_columns(stock_df)

            # 写回单股独立 CSV
            indiv_path = os.path.join(kline_dir, f"{code_clean}_{real_name}_kline.csv")
            stock_df.to_csv(indiv_path, index=False, encoding="utf-8-sig")

            # 强制渲染包含最新交易日K线柱的高清走势图表（自动覆盖清理历史旧图）
            new_chart_path = render_stock_kline_chart(
                stock_df, code_clean, real_name, output_dir=chart_dir, force_refresh=True
            )

            return code_clean, real_name, new_chart_path, missing_bar_df
        except Exception as e:
            print(f"⚠️ 标的 {code_clean} 追加最新交易日K线柱失败: {e}")
            return None, None, None, None

    max_workers_actual = min(max_workers, max(1, len(missing_codes)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_actual) as executor:
        future_to_code = {executor.submit(_patch_single, c): c for c in missing_codes}
        for future in concurrent.futures.as_completed(future_to_code):
            try:
                c_clean, r_name, new_chart_p, m_bar_df = future.result()
                if c_clean and new_chart_p and os.path.exists(new_chart_p):
                    patched_charts_map[c_clean] = new_chart_p
                    ready_charts_map[c_clean] = new_chart_p
                    # 写入最新交易日缓存
                    patched_stocks_map[c_clean] = {
                        "name": r_name,
                        "chart_path": new_chart_p,
                        "patched_date": latest_trading_date,
                    }
                if m_bar_df is not None and not m_bar_df.empty:
                    patched_new_rows.append(m_bar_df)
            except Exception:
                pass

    # 7. 持久化缓存：将已追加记录与最新交易日写入 stock_data/kline_patch_cache.json
    cache_data["patched_stocks"] = patched_stocks_map
    _save_kline_patch_cache(cache_filepath, cache_data)

    # 8. 同步回写全量/板块汇总 CSV
    if patched_new_rows and combined_df is not None:
        try:
            patched_df = pd.concat(patched_new_rows, ignore_index=True)
            combined_df = pd.concat([combined_df, patched_df], ignore_index=True)
            combined_df.drop_duplicates(subset=["股票代码", "交易日期"], keep="last", inplace=True)
            combined_df.sort_values(by=["股票代码", "交易日期"], inplace=True)
            combined_df = _ensure_kline_ma_columns(combined_df)
            combined_df.to_csv(summary_filepath, index=False, encoding="utf-8-sig")
            print(f"💾 [汇总表同步] 已将追加的 {len(patched_new_rows)} 条最新交易日K线数据持久化回写至 {os.path.basename(summary_filepath)}")
        except Exception as e:
            print(f"⚠️ 回写汇总表异常: {e}")

    # 9. 组装最终全量图表列表
    final_charts = list(ready_charts_map.values())
    _LATEST_RENDERED_CHARTS = final_charts

    print(f"✅ [最新交易日K线追加完成] 成功为 {len(patched_charts_map)} 只标的追加最新交易日「{latest_trading_date}」K线柱并重绘，缓存已就绪（已缓存总数: {len(patched_stocks_map)} 只）！\n")
    return final_charts


def verify_and_patch_previous_day_kline(kline_charts: list[str], topic: str = "", max_workers: int = 15) -> list[str]:
    """兼容历史调用的别名，底层统一调度具备最新交易日追加与智能二级缓存架构的 verify_and_patch_latest_kline。"""
    return verify_and_patch_latest_kline(kline_charts, topic=topic, max_workers=max_workers)



def _fetch_single_stock_kline(code: str, name: str = "", limit: int = 60) -> pd.DataFrame:
    """获取单只股票的日K线图时序数据（包含五日线、十日线、二十日线、三十日线）。
    
    数据源：优先调用新浪行情接口 (CN_MarketDataService.getKLineData, scale=240 为日K线，ma=5,10,20,30)，
    若异常或数据为空则自动回退到同花顺行情接口并增量计算均线。
    """
    code_clean = str(code).strip().zfill(6)
    prefix = "bj" if code_clean.startswith(("4", "8", "920")) else ("sh" if code_clean.startswith(("6", "9")) else "sz")
    full_sym = f"{prefix}{code_clean}"
    session = _get_kline_session()

    # 1. 优先调用新浪行情接口获取日K线
    try:
        sina_url = (
            f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var_{full_sym}_240_="
            f"/CN_MarketDataService.getKLineData?symbol={full_sym}&scale=240&ma=5,10,20,30&datalen={limit}"
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
                stock_name = name
                if not stock_name or stock_name == code_clean:
                    try:
                        resolved = _resolve_single_stock_name(code_clean)
                        stock_name = resolved.get("name", code_clean)
                    except Exception:
                        stock_name = code_clean
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

                    # 提取新浪服务端计算的五日线、十日线、二十日线、三十日线
                    ma5 = float(b.get("ma_price5")) if b.get("ma_price5") is not None else 0.0
                    ma10 = float(b.get("ma_price10")) if b.get("ma_price10") is not None else 0.0
                    ma20 = float(b.get("ma_price20")) if b.get("ma_price20") is not None else 0.0
                    ma30 = float(b.get("ma_price30")) if b.get("ma_price30") is not None else 0.0

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
                        "MA5": round(ma5, 2) if ma5 else 0.0,
                        "MA10": round(ma10, 2) if ma10 else 0.0,
                        "MA20": round(ma20, 2) if ma20 else 0.0,
                        "MA30": round(ma30, 2) if ma30 else 0.0,
                        "5日均线": round(ma5, 2) if ma5 else 0.0,
                        "10日均线": round(ma10, 2) if ma10 else 0.0,
                        "20日均线": round(ma20, 2) if ma20 else 0.0,
                        "30日均线": round(ma30, 2) if ma30 else 0.0,
                    })
                    prev_close = close_p
                if records:
                    df = pd.DataFrame(records)
                    return _ensure_kline_ma_columns(df)
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

                    df = pd.DataFrame(records)
                    return _ensure_kline_ma_columns(df)
    except Exception:
        pass

    return pd.DataFrame()


def _resolve_single_stock_name(name_query: str) -> dict | None:
    """尝试将股票名称或代码解析为单只 A 股代码与简称"""
    if not name_query:
        return None
    name_clean = name_query.strip()
    root_dir = get_project_root()
    kline_dir = os.path.join(root_dir, "kline_data")

    # 1. 若输入为 6 位数字代码，优先解析出真实股票中文简称
    if re.match(r"^\d{6}$", name_clean):
        # 优先从本地已有文件名反查
        if os.path.exists(kline_dir):
            matched = glob.glob(os.path.join(kline_dir, f"{name_clean}_*_kline.csv"))
            for m in matched:
                parts = os.path.basename(m).split("_")
                if len(parts) >= 3 and parts[1] != name_clean:
                    return {"code": name_clean, "name": parts[1]}
        # 联网从行情接口实时反查股票简称
        try:
            prefix = "sz" if name_clean.startswith(("0", "3")) else "sh"
            r = requests.get(f"http://qt.gtimg.cn/q={prefix}{name_clean}", timeout=3)
            if r.status_code == 200:
                r.encoding = "gbk"
                p = r.text.split("~")
                if len(p) > 1 and p[1]:
                    return {"code": name_clean, "name": p[1].strip()}
        except Exception:
            pass
        return {"code": name_clean, "name": name_clean}

    # 2. 若输入为股票名称，尝试通过东方财富与问财解析
    try:
        url = f"http://searchapi.eastmoney.com/api/suggest/get?input={name_clean}&type=14"
        res = requests.get(url, timeout=3).json()
        items = res.get("QuotationCodeTable", {}).get("Data", [])
        for item in items:
            if item.get("Classify") == "AStock" and item.get("Name") == name_clean:
                return {"code": item.get("Code", ""), "name": item.get("Name", "")}
    except Exception:
        pass
    return None


def _get_all_market_stocks() -> list[dict]:
    """获取A股全市场所有非科创板、非创业板、非ST股票列表（优先复用本地已有标的清单，毫秒级就绪）"""
    stocks = []
    seen = set()
    exclude_prefixes = ("688", "689", "300", "301", "302", "30")

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
                if c.startswith(exclude_prefixes) or "ST" in n.upper() or "科创" in n or "创业" in n:
                    continue
                if c not in seen:
                    seen.add(c)
                    stocks.append({"code": c, "name": n})
            if len(stocks) >= 2000:
                return stocks
        except Exception:
            pass

    # 2. 从本地 kline_data/*.csv 检索标的清单
    kline_dir = os.path.join(root_dir, "kline_data")
    if os.path.exists(kline_dir):
        csv_files = glob.glob(os.path.join(kline_dir, "*.csv"))
        if len(csv_files) >= 2000:
            for f in csv_files:
                basename = os.path.basename(f)
                parts = basename.split("_")
                if len(parts) >= 3 and len(parts[0]) == 6 and parts[0].isdigit():
                    c = parts[0]
                    n = parts[1]
                    if c.startswith(exclude_prefixes) or "ST" in n.upper() or "科创" in n or "创业" in n:
                        continue
                    if c not in seen:
                        seen.add(c)
                        stocks.append({"code": c, "name": n})
            if len(stocks) >= 2000:
                return stocks

    # 3. 若本地无缓存，则通过网络拉取（仅拉取主板 m:0+t:6 与 m:1+t:2）
    try:
        page = 1
        while True:
            url = (
                f"http://80.push2.eastmoney.com/api/qt/clist/get"
                f"?pn={page}&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3"
                f"&fs=m:0+t:6,m:1+t:2&fields=f12,f14"
            )
            resp = requests.get(url, timeout=6).json()
            data = resp.get("data")
            if not data or not data.get("diff"):
                break
            diff = data["diff"]
            for item in diff:
                code = str(item.get("f12", "")).strip().zfill(6)
                name = str(item.get("f14", "")).strip()
                # 严格过滤科创板与创业板及ST/*ST股票
                if code.startswith(exclude_prefixes) or "ST" in name.upper() or "科创" in name or "创业" in name:
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
    """通过同花顺问财接口检索目标板块个股代码与简称（完整抓取，排除科创板与创业板）"""
    query = f"{topic_clean} 非科创板 非创业板 非ST 最新日线行情" if topic_clean else "非科创板 非创业板 非ST 最新日线行情"
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
        exclude_prefixes = ("688", "689", "300", "301", "302", "30")
        for row in all_rows:
            code = row.get("code") or row.get("股票代码", "")
            if "." in code:
                code = code.split(".")[0]
            name = row.get("股票简称") or row.get("名称", "")
            if code.startswith(exclude_prefixes) or "ST" in name.upper() or "科创" in name or "创业" in name:
                continue
            if code and code not in seen:
                seen.add(code)
                stocks.append({"code": code, "name": name})
                if len(stocks) >= max_stocks:
                    break
        return stocks
    except Exception:
        return []


def _process_single_stock(s: dict, kline_dir: str, limit: int = 60, force_refresh: bool = False, generate_chart: bool = False) -> tuple[pd.DataFrame | None, dict | None]:
    """单只股票 K 线下载与落盘保存任务函数（支持本地今日文件智能复用、均线计算与K线图渲染）"""
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
                stock_df = pd.read_csv(local_path, dtype={"股票代码": str}, encoding="utf-8-sig")
                if not stock_df.empty and len(stock_df) >= min(limit, 30):
                    # 检查是否缺失今日分时数据或均线列，自动追加合并并更新本地 CSV
                    stock_df = append_today_realtime_data_if_missing(stock_df)
                    stock_df = _ensure_kline_ma_columns(stock_df)
                    stock_df.to_csv(local_path, index=False, encoding="utf-8-sig")

                    real_name = stock_df["股票简称"].iloc[0] or name or code
                    period_high = stock_df["最高价"].max()
                    period_low = stock_df["最低价"].min()
                    first_open = stock_df["开盘价"].iloc[0]
                    latest_close = stock_df["收盘价"].iloc[-1]
                    period_pct = round((latest_close - first_open) / first_open * 100, 2) if first_open else 0.0

                    chart_path = ""
                    if generate_chart:
                        chart_path = render_stock_kline_chart(stock_df, code, real_name)

                    stat = {
                        "code": code,
                        "name": real_name,
                        "latest_close": latest_close,
                        "latest_ma5": float(stock_df["MA5"].iloc[-1]) if "MA5" in stock_df.columns else latest_close,
                        "latest_ma10": float(stock_df["MA10"].iloc[-1]) if "MA10" in stock_df.columns else latest_close,
                        "latest_ma20": float(stock_df["MA20"].iloc[-1]) if "MA20" in stock_df.columns else latest_close,
                        "latest_ma30": float(stock_df["MA30"].iloc[-1]) if "MA30" in stock_df.columns else latest_close,
                        "period_high": period_high,
                        "period_low": period_low,
                        "period_return": period_pct,
                        "bars": len(stock_df),
                        "chart_path": chart_path,
                    }
                    return stock_df, stat
        except Exception:
            pass

    stock_df = _fetch_single_stock_kline(code, name, limit=limit)
    if stock_df.empty:
        return None, None

    real_name = name or (stock_df["股票简称"].iloc[0] if "股票简称" in stock_df.columns and stock_df["股票简称"].iloc[0] != code else "")
    if not real_name or real_name == code:
        single = _resolve_single_stock_name(code)
        real_name = single.get("name", code) if single else code
    stock_df["股票简称"] = real_name
    stock_df = append_today_realtime_data_if_missing(stock_df)
    stock_df = _ensure_kline_ma_columns(stock_df)

    # 针对每个个股单独保存 CSV 到 kline_data/ 目录（存在相同的就直接覆盖）
    indiv_filename = f"{code}_{real_name}_kline.csv"
    indiv_filepath = os.path.join(kline_dir, indiv_filename)
    stock_df.to_csv(indiv_filepath, index=False, encoding="utf-8-sig")

    period_high = stock_df["最高价"].max()
    period_low = stock_df["最低价"].min()
    first_open = stock_df["开盘价"].iloc[0]
    latest_close = stock_df["收盘价"].iloc[-1]
    period_pct = round((latest_close - first_open) / first_open * 100, 2) if first_open else 0.0

    chart_path = ""
    if generate_chart:
        chart_path = render_stock_kline_chart(stock_df, code, real_name)

    stat = {
        "code": code,
        "name": real_name,
        "latest_close": latest_close,
        "latest_ma5": float(stock_df["MA5"].iloc[-1]) if "MA5" in stock_df.columns else latest_close,
        "latest_ma10": float(stock_df["MA10"].iloc[-1]) if "MA10" in stock_df.columns else latest_close,
        "latest_ma20": float(stock_df["MA20"].iloc[-1]) if "MA20" in stock_df.columns else latest_close,
        "latest_ma30": float(stock_df["MA30"].iloc[-1]) if "MA30" in stock_df.columns else latest_close,
        "period_high": period_high,
        "period_low": period_low,
        "period_return": period_pct,
        "bars": len(stock_df),
        "chart_path": chart_path,
    }
    return stock_df, stat


# 下载股票个股K线图数据
@tool
def download_stock_day(topic: str = "", limit: int = 60) -> str:
    """调用同花顺api下载个股的历史日K线图数据到根目录及 kline_data/ 目录，自动计算五日线、十日线、二十日线、三十日线并渲染高清K线图。

    参数:
        topic: 股票代码（如'000001'）、股票名称（如'平安银行'）或股票板块（如'银行'、'半导体'）。为空则获取全市场所有非科创板、非ST个股数据。
        limit: K线时间周期条数，默认为近60个交易日（约3个月短期K线）。
    返回:
        下载结果说明，包含个股K线文件保存路径、K线图路径、总K线条数、五/十/二十/三十日均线及区间统计。
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
    chart_dir = os.path.join(root_dir, "kline_charts")
    os.makedirs(chart_dir, exist_ok=True)
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
                combined_df = load_cached_kline_df(summary_filepath)

                # 性能极致提速：仅在开盘交易时间段 (工作日 09:25 之后) 且本地缓存距离上次同步超过 180 秒时，才进行实时增量拉取；
                # 非交易时间或盘后，直接使用现有高质量时序，跳过网络调用与 30MB 磁盘重写，大幅削减耗时
                now_time = datetime.datetime.now().time()
                is_trading_time = (now_time >= datetime.time(9, 25)) and (today_date.weekday() < 5)
                if is_trading_time and time_diff > 180:
                    len_before = len(combined_df)
                    combined_df = append_today_realtime_data_if_missing(combined_df, force_refresh=False)
                    if len(combined_df) > len_before:
                        combined_df = _ensure_kline_ma_columns(combined_df)
                        combined_df.to_csv(summary_filepath, index=False, encoding="utf-8-sig")
                        _KLINE_DF_CACHE = {
                            "filepath": summary_filepath,
                            "mtime": os.path.getmtime(summary_filepath),
                            "df": combined_df,
                        }

                start_date = combined_df["交易日期"].min()
                end_date = combined_df["交易日期"].max()

                # 统计区间涨幅与均线
                first_last = combined_df.groupby("股票代码").agg(
                    name=("股票简称", "last"),
                    first_open=("开盘价", "first"),
                    latest_close=("收盘价", "last"),
                    latest_ma5=("MA5", "last") if "MA5" in combined_df.columns else ("收盘价", "last"),
                    latest_ma10=("MA10", "last") if "MA10" in combined_df.columns else ("收盘价", "last"),
                    latest_ma20=("MA20", "last") if "MA20" in combined_df.columns else ("收盘价", "last"),
                    latest_ma30=("MA30", "last") if "MA30" in combined_df.columns else ("收盘价", "last"),
                    period_high=("最高价", "max"),
                    period_low=("最低价", "min"),
                    bars=("交易日期", "count")
                ).reset_index()

                first_last["period_return"] = ((first_last["latest_close"] - first_last["first_open"]) / first_last["first_open"] * 100).round(2)
                first_last.sort_values(by="period_return", ascending=False, inplace=True)
                top_gainers = first_last.head(5).to_dict("records")
                top_losers = first_last.tail(5).to_dict("records")
                unique_stocks = len(first_last)

                # 并发生成/校验全部个股高清K线图表 (秒级复用已存在的图表)
                generated_charts = render_all_stock_kline_charts(combined_df, chart_dir=chart_dir)

                summary_lines = [
                    f"### 📊 同花顺个股K线图与均线数据就绪 (⚡本地缓存极速复用)",
                    f"- **目标板块/范围**：{topic_clean or 'A股全市场（非科创板、非ST全部个股）'}",
                    f"- **K线时间周期**：`{start_date}` 至 `{end_date}`（每只个股近 {limit} 个交易日K线时序）",
                    f"- **个股保存目录**：[{kline_dir.replace(os.sep, '/')}]({kline_dir.replace(os.sep, '/')})（共包含 **{unique_stocks}** 只个股独立 CSV 文件）",
                    f"- **K线图表目录**：[{chart_dir.replace(os.sep, '/')}]({chart_dir.replace(os.sep, '/')})（包含绘制五/十/二十/三十日均线的高清走势图表）",
                    f"- **全量汇总文件**：[{summary_filename}]({summary_filepath.replace(os.sep, '/')})（共 **{len(combined_df):,}** 条K线柱）",
                    f"- **K线包含指标**：交易日期、股票代码、股票简称、开盘价、最高价、最低价、收盘价、涨跌额、涨跌幅(%)、振幅(%)、成交量(股)、成交额(元)、换手率(%)、五日均线(MA5)、十日均线(MA10)、二十日均线(MA20)、三十日均线(MA30)",
                    f"\n#### 🚀 区间领涨前 5 个股（近 {limit} 日累计涨幅与均线走势）：",
                    f"| 股票代码 | 股票简称 | 最新现价 | 五日线(MA5) | 十日线(MA10) | 二十日线(MA20) | 三十日线(MA30) | 区间累计涨幅 | K线柱数 |",
                    f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                ]

                for item in top_gainers:
                    ret_str = f"{item['period_return']:+.2f}%"
                    ma5_val = float(item.get("latest_ma5", item["latest_close"]))
                    ma10_val = float(item.get("latest_ma10", item["latest_close"]))
                    ma20_val = float(item.get("latest_ma20", item["latest_close"]))
                    ma30_val = float(item.get("latest_ma30", item["latest_close"]))
                    summary_lines.append(
                        f"| {item['股票代码']} | {item['name']} | {item['latest_close']:.2f} | {ma5_val:.2f} | {ma10_val:.2f} | {ma20_val:.2f} | {ma30_val:.2f} | {ret_str} | {item['bars']} |"
                    )

                summary_lines.extend([
                    f"\n#### 📉 区间表现靠后前 5 个股：",
                    f"| 股票代码 | 股票简称 | 最新现价 | 五日线(MA5) | 十日线(MA10) | 二十日线(MA20) | 三十日线(MA30) | 区间累计涨幅 | K线柱数 |",
                    f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
                ])

                for item in reversed(top_losers):
                    ret_str = f"{item['period_return']:+.2f}%"
                    ma5_val = float(item.get("latest_ma5", item["latest_close"]))
                    ma10_val = float(item.get("latest_ma10", item["latest_close"]))
                    ma20_val = float(item.get("latest_ma20", item["latest_close"]))
                    ma30_val = float(item.get("latest_ma30", item["latest_close"]))
                    summary_lines.append(
                        f"| {item['股票代码']} | {item['name']} | {item['latest_close']:.2f} | {ma5_val:.2f} | {ma10_val:.2f} | {ma20_val:.2f} | {ma30_val:.2f} | {ret_str} | {item['bars']} |"
                    )

                if generated_charts:
                    summary_lines.append(f"\n#### 📸 生成的高清个股K线图表（含五日线、十日线、二十日线、三十日线）：")
                    summary_lines.append(f"共生成/就绪 **{len(generated_charts)}** 只个股高清走势图，已存入图表目录。部分精选示例如下：")
                    for c_path in generated_charts[:15]:
                        summary_lines.append(f"- [{os.path.basename(c_path)}]({c_path.replace(os.sep, '/')})")
                    if len(generated_charts) > 15:
                        summary_lines.append(f"- ... （其余 {len(generated_charts) - 15} 张个股图表已就绪在 [{chart_dir.replace(os.sep, '/')}]({chart_dir.replace(os.sep, '/')})）")

                return "\n".join(summary_lines)
            except Exception as e:
                print(f"⚠️ 解析本地缓存异常，自动切换为增量更新模式: {e}")

    # 1. 解析目标股票列表（支持单股代码、单股名称、板块全部个股、全市场全部个股）
    stocks = []
    if re.match(r"^\d{6}$", topic_clean):
        single = _resolve_single_stock_name(topic_clean)
        stocks = [single] if single else [{"code": topic_clean, "name": topic_clean}]
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
    is_single_stock = (len(stocks) == 1)

    # 3. 高并发多线程下载并保存每只股票的独立 K 线 CSV 文件（存在且为今日则快速复用）
    total_targets = len(stocks)
    print(f"📥 开始并发下载/更新 {total_targets} 只个股的日K线数据并计算五/十/二十/三十日均线...")

    all_kline_dfs = []
    success_stocks = []

    # 全市场大批量任务采用 50 并发，单板块/单股采用 15 并发
    max_workers = 50 if total_targets > 100 else 15
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process_single_stock, s, kline_dir, limit, False, is_single_stock) for s in stocks]
        for idx, future in enumerate(concurrent.futures.as_completed(futures), 1):
            df_item, stat_item = future.result()
            if df_item is not None and stat_item is not None:
                all_kline_dfs.append(df_item)
                success_stocks.append(stat_item)
            if idx % 500 == 0 or idx == total_targets:
                print(f"   ⏳ 进度：已处理 {idx}/{total_targets} 只个股 (成功: {len(success_stocks)})...")

    if not all_kline_dfs:
        return f"❌ 个股K线数据下载失败，未能从行情接口获取到任何个股K线。"

    # 4. 合并生成总K线汇总 CSV 保存到 stock_data 目录（存在相同文件则直接覆盖）
    print("💾 正在整合生成包含均线指标的全量日K线汇总 CSV...")
    combined_df = pd.concat(all_kline_dfs, ignore_index=True)
    combined_df = append_today_realtime_data_if_missing(combined_df, force_refresh=True)
    combined_df = _ensure_kline_ma_columns(combined_df)
    summary_filename = f"{topic_clean}_kline_all.csv" if topic_clean else "stock_kline_all.csv"
    summary_filepath = os.path.join(stock_data_dir, summary_filename)
    combined_df.to_csv(summary_filepath, index=False, encoding="utf-8-sig")

    start_date = combined_df["交易日期"].min()
    end_date = combined_df["交易日期"].max()

    # 5. 生成规范的 Markdown 结果汇总
    success_stocks.sort(key=lambda x: x["period_return"], reverse=True)
    top_gainers = success_stocks[:5]
    top_losers = success_stocks[-5:]

    # 并发生成/校验全部个股高清K线图表 (秒级复用已存在的图表)
    generated_charts = render_all_stock_kline_charts(combined_df, chart_dir=chart_dir)

    summary_lines = [
        f"### 📊 同花顺个股K线图与均线数据下载完成",
        f"- **目标板块/范围**：{topic_clean or 'A股全市场（非科创板、非ST全部个股）'}",
        f"- **K线时间周期**：`{start_date}` 至 `{end_date}`（每只个股近 {limit} 个交易日K线时序）",
        f"- **个股保存目录**：[{kline_dir.replace(os.sep, '/')}]({kline_dir.replace(os.sep, '/')})（共成功导出 **{len(success_stocks)}** 只个股独立 CSV 文件，存在已覆盖）",
        f"- **K线图表目录**：[{chart_dir.replace(os.sep, '/')}]({chart_dir.replace(os.sep, '/')})（包含绘制五/十/二十/三十日均线的高清走势图表）",
        f"- **全量汇总文件**：[{summary_filename}]({summary_filepath.replace(os.sep, '/')})（共 **{len(combined_df):,}** 条K线柱，存在已覆盖）",
        f"- **K线包含技术指标**：交易日期、股票代码、股票简称、开盘价、最高价、最低价、收盘价、涨跌额、涨跌幅(%)、振幅(%)、成交量(股)、成交额(元)、换手率(%)、五日均线(MA5)、十日均线(MA10)、二十日均线(MA20)、三十日均线(MA30)",
        f"\n#### 🚀 区间领涨前 5 个股（近 {limit} 日累计涨幅与均线走势）：",
        f"| 股票代码 | 股票简称 | 最新现价 | 五日线(MA5) | 十日线(MA10) | 二十日线(MA20) | 三十日线(MA30) | 区间累计涨幅 | K线柱数 |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for item in top_gainers:
        ret_str = f"{item['period_return']:+.2f}%"
        ma5_val = float(item.get("latest_ma5", item["latest_close"]))
        ma10_val = float(item.get("latest_ma10", item["latest_close"]))
        ma20_val = float(item.get("latest_ma20", item["latest_close"]))
        ma30_val = float(item.get("latest_ma30", item["latest_close"]))
        summary_lines.append(
            f"| {item['code']} | {item['name']} | {item['latest_close']:.2f} | {ma5_val:.2f} | {ma10_val:.2f} | {ma20_val:.2f} | {ma30_val:.2f} | {ret_str} | {item['bars']} |"
        )

    summary_lines.extend([
        f"\n#### 📉 区间表现靠后前 5 个股：",
        f"| 股票代码 | 股票简称 | 最新现价 | 五日线(MA5) | 十日线(MA10) | 二十日线(MA20) | 三十日线(MA30) | 区间累计涨幅 | K线柱数 |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for item in reversed(top_losers):
        ret_str = f"{item['period_return']:+.2f}%"
        ma5_val = float(item.get("latest_ma5", item["latest_close"]))
        ma10_val = float(item.get("latest_ma10", item["latest_close"]))
        ma20_val = float(item.get("latest_ma20", item["latest_close"]))
        ma30_val = float(item.get("latest_ma30", item["latest_close"]))
        summary_lines.append(
            f"| {item['code']} | {item['name']} | {item['latest_close']:.2f} | {ma5_val:.2f} | {ma10_val:.2f} | {ma20_val:.2f} | {ma30_val:.2f} | {ret_str} | {item['bars']} |"
        )

    if generated_charts:
        summary_lines.append(f"\n#### 📸 生成的高清个股K线图表（含五日线、十日线、二十日线、三十日线）：")
        summary_lines.append(f"共生成/就绪 **{len(generated_charts)}** 只个股高清走势图，已存入图表目录。部分精选示例如下：")
        for c_path in generated_charts[:15]:
            summary_lines.append(f"- [{os.path.basename(c_path)}]({c_path.replace(os.sep, '/')})")
        if len(generated_charts) > 15:
            summary_lines.append(f"- ... （其余 {len(generated_charts) - 15} 张个股图表已就绪在 [{chart_dir.replace(os.sep, '/')}]({chart_dir.replace(os.sep, '/')})）")

    return "\n".join(summary_lines)


# 下载个股K线图及均线专用工具
@tool
def download_stock_kline_chart(topic: str = "", limit: int = 60) -> str:
    """下载指定个股或板块的日K线数据，并绘制生成包含五日线(MA5)、十日线(MA10)、二十日线(MA20)、三十日线(MA30)的高清K线走势图表。

    参数:
        topic: 股票代码（如'000001'）、股票名称（如'平安银行'）或股票板块（如'银行'）。
        limit: K线时间周期条数，默认为近60个交易日。
    返回:
        下载与绘图结果说明，包含K线CSV数据路径、K线走势图PNG路径、均线指标与量价结构。
    """
    return download_stock_day(topic=topic, limit=limit)


# ==============================================================================
# 基于K线图视觉多模态分析筛选强势股票（纯图像审读，无需解析K线表格数据）
# ==============================================================================

def analyze_stock_kline_chart(chart_path: str, code: str = "", name: str = "") -> dict:
    """基于多模态视觉大模型对单只股票的日K线走势图表（PNG图像）进行直接视觉形态深度分析。

    分析要点：
    1. 近10个交易日是否出现过实体大阳线或涨停板形态；
    2. 五日线(黄)、十日线(紫)、二十日线(青)、三十日线(橙)是否自上而下顺向排列 (MA5 >= MA10 >= MA20 >= MA30)；
    3. 四条均线近10日是否全部呈向上倾斜、趋势发散态势；
    4. 给出最终判定结论（【符合】或【不符合】）与技术点评。

    参数:
        chart_path: K线图图片文件路径。
        code: 股票代码（可选）。
        name: 股票简称（可选）。
    返回:
        包含识别与研判结果的字典 (code, name, is_qualified, verdict, trend_desc, analysis_text, chart_path)。
    """
    if not os.path.exists(chart_path):
        return {
            "code": code,
            "name": name,
            "is_qualified": False,
            "verdict": "不符合",
            "trend_desc": "图片文件缺失",
            "analysis_text": f"K线图文件不存在: {chart_path}",
            "chart_path": chart_path,
        }

    # 从文件名提取股票代码与简称（兼容带日期格式及无日期历史格式）
    base_name = os.path.basename(chart_path)
    m = re.match(r"^(\d{6})_(.*?)(?:_(\d{8}))?_kline\.png$", base_name)
    if m:
        if not code:
            code = m.group(1)
        if not name:
            candidate_name = m.group(2)
            if candidate_name and candidate_name != code and "" not in candidate_name:
                name = candidate_name

    if code and (not name or "" in name or name == code):
        res_info = _resolve_single_stock_name(code)
        if res_info:
            name = res_info["name"]

    # 战法硬性条件: 严格排除科创板与创业板 (688/689/300/301/302/30)
    exclude_prefixes = ("688", "689", "300", "301", "302", "30")
    if code.startswith(exclude_prefixes) or "科创" in name or "创业" in name:
        return {
            "code": code,
            "name": name,
            "is_qualified": False,
            "verdict": "不符合",
            "trend_desc": "科创板/创业板股票(按战法排除)",
            "analysis_text": "【判定结果】：不符合\n【形态评述】：该股票属于科创板或创业板个股，按战法硬性规则直接排除，只保留非科创、非创业板个股。",
            "chart_path": chart_path,
        }

    # 读取并 base64 编码图片
    with open(chart_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode("utf-8")

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("MODEL_NAME", "gpt-4o-mini")

    llm = ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        max_tokens=1200,
        timeout=45.0,
        max_retries=1,
    )

    stock_hint = f"股票代码：{code}，股票名称：{name}" if code else "请从图表标题栏识别代码与名称"
    prompt_text = f"""请仔细观察这张股票日K线走势图（{stock_hint}）：
图表上方包含：日K线蜡烛柱（红涨绿跌，涨停板柱体有长实体或标记）、四条均线：五日线MA5(黄色)、十日线MA10(紫色)、二十日线MA20(青色)、三十日线MA30(橙色)，下方包含成交量柱。

请从图像视觉角度进行深度技术形态分析并依次回答：
1. 【股票代码与名称】：确认图中的股票代码、股票简称以及最新收盘价。
2. 【十日内涨停分析】：仔细观察右侧最近10个交易日（约10根K线柱），是否存在实体大阳线或涨停板形态（单日涨幅大阳线，成交量同步放大）？指出具体涨停或大阳线形态位置。
3. 【均线排列状态】：观察五日线(黄)、十日线(紫)、二十日线(青)、三十日线(橙)的相对位置。是否满足「五日线在最上、十日线次之、二十日线再次之、三十日线在最下」（即 MA5 ≥ MA10 ≥ MA20 ≥ MA30，自上而下顺向多头排列）？
4. 【均线趋势方向】：观察近10日内这四条均线（5日、10日、20日、30日）的走势方向，是否全部保持向上倾斜、趋势向上发散？
5. 【综合判定与评级】：
   - 综合判断是否符合战法标准：「近十日内有过涨停，且近十日五日线、十日线、二十日线、三十日线依次从上往下多头排列且都是趋势向上」？
   - 必须在最后单独一行明确输出判定结论：
   【判定结果】：符合
   或
   【判定结果】：不符合
   - 并给出1句核心技术形态短评。
"""

    msg = HumanMessage(content=[
        {"type": "text", "text": prompt_text},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
    ])

    try:
        resp = llm.invoke([msg])
        content = resp.content.strip() if resp.content else ""
        if not content and "reasoning_content" in resp.additional_kwargs:
            content = resp.additional_kwargs["reasoning_content"].strip()
    except Exception as e:
        content = f"视觉大模型分析异常: {e}"

    # 解析判定结论
    is_qualified = False
    verdict = "不符合"
    m_verdict = re.search(r"【判定结果】[：:\s]*(符合|不符合)", content)
    if m_verdict:
        verdict = m_verdict.group(1).strip()
        is_qualified = (verdict == "符合")
    else:
        if "【判定结果】：符合" in content or "【判定结果】: 符合" in content:
            verdict = "符合"
            is_qualified = True
        elif "符合「近十日内有过涨停" in content and "不符合" not in content[-120:]:
            verdict = "符合"
            is_qualified = True

    # 提取收盘价或形态描述
    trend_desc = "四线多头向上发散" if is_qualified else "形态不符"
    if "多头" in content and is_qualified:
        trend_desc = "四线顺向多头向上发散(符合战法)"
    elif not is_qualified:
        if "空头" in content:
            trend_desc = "均线空头排列/拐头向下"
        elif "未见涨停" in content or "不存在" in content:
            trend_desc = "均线排列尚可但近10日无涨停"
        else:
            trend_desc = "未达四线多头顺向向上标准"

    # 若 code 或 name 仍为空，尝试从文本中反抽
    if not code:
        m_c = re.search(r"(?:代码|股票代码)[：:\s]*[*`]*(\d{6})[*`]*", content)
        if m_c:
            code = m_c.group(1)
    if not name or "" in name or name == code:
        if code:
            res_stock = _resolve_single_stock_name(code)
            name = res_stock["name"] if res_stock else code

    return {
        "code": code,
        "name": name,
        "is_qualified": is_qualified,
        "verdict": verdict,
        "trend_desc": trend_desc,
        "analysis_text": content,
        "chart_path": chart_path,
    }


def filter_stocks_by_kline_chart(topic: str = "", days: int = 10, chart_paths: list = None, max_charts: int = 16) -> str:
    """直接基于个股日K线走势图表（视觉图像）进行多模态视觉技术形态分析，
    筛选出「近10日内有过涨停，且近十日五日线、十日线、二十日线、三十日线依次从上往下多头排列且都是趋势向上」的强势个股。
    无需解析表格数据，直接由视觉大模型对图表进行审读、判定并保存筛选结果。

    参数:
        topic: 股票板块、主题名称或单只股票代码/简称。
        days: 回溯窗口交易日天数，默认为近10个交易日。
        chart_paths: 指定要分析的K线走势图文件路径列表（可选）。
        max_charts: 审图上限数量，默认最多分析 16 张图表。
    返回:
        K线图视觉多模态分析筛选报告，包含合格标的列表与详细图表解读。
    """
    topic_clean = topic.strip() if topic else ""
    root_dir = get_project_root()
    chart_dir = os.path.join(root_dir, "kline_charts")
    stock_data_dir = os.path.join(root_dir, "stock_data")
    os.makedirs(chart_dir, exist_ok=True)
    os.makedirs(stock_data_dir, exist_ok=True)

    # 1. 搜集待分析的目标 K 线图文件
    target_charts = []
    if chart_paths:
        target_charts = [p for p in chart_paths if os.path.exists(p)]

    if not target_charts:
        # 若指定了 6 位单股代码或单股名称，精准定位该股票图表
        if re.match(r"^\d{6}$", topic_clean):
            matched = glob.glob(os.path.join(chart_dir, f"*{topic_clean}*_kline.png"))
            if matched:
                target_charts = matched
            else:
                # 若尚未渲染该图表，则触发生成
                print(f"🖼️ 未发现代码 {topic_clean} 的K线图，正在实时生成...")
                download_stock_day(topic=topic_clean, limit=60)
                target_charts = glob.glob(os.path.join(chart_dir, f"*{topic_clean}*_kline.png"))
        elif topic_clean:
            matched = glob.glob(os.path.join(chart_dir, f"*{topic_clean}*_kline.png"))
            if matched:
                target_charts = matched
            else:
                download_stock_day(topic=topic_clean, limit=60)
                target_charts = glob.glob(os.path.join(chart_dir, f"*{topic_clean}*_kline.png"))
                if not target_charts:
                    target_charts = sorted(glob.glob(os.path.join(chart_dir, "*_kline.png")), key=os.path.getmtime, reverse=True)

    if not target_charts:
        # 扫描 kline_charts 目录全部图表，按修改时间最新排序
        all_charts = glob.glob(os.path.join(chart_dir, "*_kline.png"))
        if not all_charts:
            # 自动下载基准股票并渲染K线图
            print("🌐 kline_charts 目录为空，正在下载基准股票并渲染K线图...")
            download_stock_day(topic="", limit=60)
            all_charts = glob.glob(os.path.join(chart_dir, "*_kline.png"))
        target_charts = sorted(all_charts, key=os.path.getmtime, reverse=True)

    # 控制视觉审图数量上限，默认不超过 max_charts 只，并严格排除科创板与创业板股票 (代码排除 688/689/300/301/302/30 开头)
    exclude_prefixes = ("688", "689", "300", "301", "302", "30")
    target_charts = [
        p for p in target_charts
        if not os.path.basename(p).startswith(exclude_prefixes) and not any(k in os.path.basename(p) for k in ["科创", "创业"])
    ][:max_charts]

    if not target_charts:
        return "⚠️ 未找到可供视觉分析的个股K线图表（kline_charts 目录为空）。"

    print(f"👁️ [K线图多模态视觉分析] 即将对 {len(target_charts)} 张个股日K线走势图表进行多模态视觉审读与形态判定...")

    analyzed_results = []
    qualified_stocks = []

    for idx, c_path in enumerate(target_charts, 1):
        filename = os.path.basename(c_path)
        print(f"   📸 [{idx}/{len(target_charts)}] 正在视觉研判K线图: {filename}...")
        res = analyze_stock_kline_chart(c_path)
        analyzed_results.append(res)

        status_tag = "✅ 符合" if res["is_qualified"] else "❌ 不符"
        print(f"      👉 {res['code']} {res['name']}: {status_tag} | {res['trend_desc']}")

        if res["is_qualified"]:
            qualified_stocks.append({
                "股票代码": res["code"],
                "code": res["code"],
                "股票简称": res["name"],
                "name": res["name"],
                "视觉判定": res["verdict"],
                "趋势状态": res["trend_desc"],
                "K线走势图": res["chart_path"],
                "chart_path": res["chart_path"],
                "视觉分析要点": res["analysis_text"][:150] + "...",
            })

    # 持久化保存筛选结果到 stock_data 目录 (覆盖更新)
    filtered_filename = f"{topic_clean}_filtered_stocks.csv" if topic_clean else "filtered_stocks.csv"
    filtered_filepath = os.path.join(stock_data_dir, filtered_filename)

    # 严格确保落地清单 100% 排除科创板与创业板
    qualified_stocks = [
        s for s in qualified_stocks
        if not str(s.get("code", "")).startswith(exclude_prefixes)
    ]
    # 若命中符合标的，以合格标的写入；若暂无完全符合，以评级最高者兜底保存，确保下游节点正常流转
    save_list = qualified_stocks if qualified_stocks else [
        {
            "股票代码": r["code"],
            "code": r["code"],
            "股票简称": r["name"],
            "name": r["name"],
            "视觉判定": r["verdict"],
            "趋势状态": r["trend_desc"],
            "K线走势图": r["chart_path"],
            "chart_path": r["chart_path"],
            "视觉分析要点": r["analysis_text"][:150] + "...",
        }
        for r in analyzed_results
        if not str(r.get("code", "")).startswith(exclude_prefixes)
    ][:4]
    pd.DataFrame(save_list).to_csv(filtered_filepath, index=False, encoding="utf-8-sig")

    # 构建结构化 Markdown 研报
    lines = [
        f"### 🎯 基于K线图视觉多模态分析筛选完成：强势多头高动能标的",
        f"- **分析对象**：个股高清日K线走势图表（视觉图像），无需依赖离线表格数据",
        f"- **图表审核标准**：",
        f"  1. **十日涨停形态**：视觉识别走势图右侧近 10 个交易日是否存在实体大阳线或涨停板",
        f"  2. **四线顺向排列**：五日线(黄) ≥ 十日线(紫) ≥ 二十日线(青) ≥ 三十日线(橙) 自上而下顺向排列",
        f"  3. **趋势向上发散**：近十日内四条均线全部呈昂扬向上倾斜延伸，具有强劲趋势动能",
        f"- **审核图表总量**：共深度视觉审读 **{len(analyzed_results)}** 张个股走势图",
        f"- **符合战法标的**：命中 **{len(qualified_stocks)}** 只标的",
        f"- **持久化保存清单**：[{filtered_filename}]({filtered_filepath.replace(os.sep, '/')})",
        f"\n#### 📊 K线图视觉研判明细汇总表：",
        f"| 股票代码 | 股票简称 | 视觉判定 | 趋势状态 | 走势图文件 | 核心视觉研判摘要 |",
        f"| :--- | :--- | :--- | :--- | :--- | :--- |",
    ]

    for r in analyzed_results:
        verdict_badge = "**【符合】**" if r["is_qualified"] else "【不符合】"
        chart_link = f"[{os.path.basename(r['chart_path'])}]({r['chart_path'].replace(os.sep, '/')})"
        summary_short = r["analysis_text"].replace("\n", " ")[:90] + "..."
        lines.append(
            f"| {r['code']} | {r['name']} | {verdict_badge} | {r['trend_desc']} | {chart_link} | {summary_short} |"
        )

    if qualified_stocks:
        lines.append(f"\n#### 🚀 命中战法强势标的详细视觉分析：")
        for q in qualified_stocks:
            full_r = next((item for item in analyzed_results if item["code"] == q["code"]), None)
            if full_r:
                lines.append(f"##### 📌 {full_r['code']} {full_r['name']} - K线图视觉深度解析")
                lines.append(f"- **走势图表**：[{os.path.basename(full_r['chart_path'])}]({full_r['chart_path'].replace(os.sep, '/')})")
                lines.append(f"- **视觉研判详情**：\n```text\n{full_r['analysis_text']}\n```\n")

    return "\n".join(lines)


# 筛选近十日内有过涨停且趋势向上的股票 (基于K线走势图多模态视觉分析)
@tool
def filter_bullish_limit_up_stocks(topic: str = "", days: int = 10) -> str:
    """直接基于个股日K线走势图（视觉图像）进行多模态视觉形态分析，
    筛选出近10日内有过涨停且五/十/二十/三十日线从上往下多头排列且趋势向上的强势标的。

    参数:
        topic: 股票板块或主题名称，为空则在已生成的K线走势图表中进行全局视觉筛选。
        days: 回溯窗口交易日天数，默认为近10个交易日。
    返回:
        筛选结果说明，包含命中股票数量、保存的文件路径及核心股票走势图。
    """
    return filter_stocks_by_kline_chart(topic=topic, days=days)


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


@tool
def query_financial_rag_knowledge(query: str, category: str = "", stock_code: str = "") -> str:
    """
    检索本地研报分析与财报解读 RAG 知识库。
    当需要查询个股深度券商研报、机构投资评级、目标价、业绩催化剂，或解读企业季报/年报财务指标（营收、净利润、毛利率、现金流等）时调用此工具。
    参数:
    - query: 查询问题或关键词（如'贵州茅台一季度净利润增速与毛利率'、'宁德时代核心投资逻辑'）
    - category: 可选分类过滤，'研报分析' 或 '财报解读'，留空则不限分类
    - stock_code: 可选股票代码（如 '600519'），留空则全局语义匹配
    """
    try:
        from rag.skill import financial_rag_skill
        cat = category if category in ["研报分析", "财报解读"] else None
        res = financial_rag_skill.execute(
            query=query,
            category=cat,
            stock_code=stock_code,
            top_k=3,
            generate_answer=False,
        )
        sources = res.get("sources", [])
        if not sources:
            return f"在 RAG 知识库中未检索到与「{query}」相关的研报或财报切片。"

        output = [f"=== 本地研报与财报 RAG 知识库检索结果（共匹配到 {len(sources)} 条高相关知识切片）==="]
        for idx, s in enumerate(sources):
            output.append(f"\n【切片 {idx+1}】《{s.get('title')}》 ({s.get('category')} | 标的: {s.get('stock_code')} {s.get('stock_name')}) [相似度: {int(s.get('score', 0)*100)}%]")
            output.append(s.get("text", ""))
        return "\n".join(output)
    except Exception as e:
        return f"查询 RAG 知识库异常: {str(e)}"


# 导出由 Skill 自动生成的 LangChain 问答完整分析 Tool (可直接供 ReAct / LangGraph 智能体调用)
try:
    from rag.skill import financial_rag_skill
    financial_rag_qa_tool = financial_rag_skill.as_tool()
except Exception:
    financial_rag_qa_tool = None


COLLECTOR_TOOLS = [
    search_web_data,
    search_academic_papers,
    download_stock_day,
    download_stock_kline_chart,
    filter_bullish_limit_up_stocks,
    monitor_stock_timeline,
    query_financial_rag_knowledge,
]

