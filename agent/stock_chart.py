import sys
import json
import time
import re
import os
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor
import requests

# 保证 Windows 控制台输出正常
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# 1. 默认监控标的 (最多支持 16 只 A股 标的，支持网页端随时修改)
# ==============================================================================
DEFAULT_STOCKS = [
    "600519",  # 贵州茅台
    "002475",  # 立讯精密
    "600036",  # 招商银行
    "000858",  # 五粮液
    "000001",  # 平安银行
    "300750",  # 宁德时代
    "601899",  # 紫金矿业
    "601318",  # 中国平安
    "002594",  # 比亚迪
    "600900",  # 长江电力
    "601111",  # 中国国航
    "600276",  # 恒瑞医药
    "002230",  # 科大讯飞
    "601012",  # 隆基绿能
    "300059",  # 东方财富
    "000333",  # 美的集团
]

WEB_PORT = 8888
HTTP_HOST = "127.0.0.1"


# ==============================================================================
# 2. 高可用行情数据中心 (基于新浪全天分时K线与逐笔挂牌，零封禁、全天秒级刷新)
# ==============================================================================
class StockDataHub:
    def __init__(self, symbols=None):
        self.symbols = list(symbols or DEFAULT_STOCKS)
        self.lock = threading.Lock()
        self.stock_cache = {}  # {code: {info & minute_bars}}
        self.is_running = True
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://finance.sina.com.cn"
        })

    def set_symbols(self, new_symbols):
        """动态更新监控股票 (支持多窗口，每页16只)"""
        clean_symbols = []
        for s in new_symbols:
            s_clean = s.strip().split(".")[0]
            if s_clean and len(s_clean) == 6 and s_clean.isdigit():
                if s_clean not in clean_symbols:
                    clean_symbols.append(s_clean)
        if clean_symbols:
            with self.lock:
                self.symbols = clean_symbols
                pages = max(1, (len(self.symbols) + 15) // 16)
                print(f"[配置更新] 监控股票已更新为 {len(self.symbols)} 只 (对应 {pages} 个16宫格窗口): {self.symbols}")
            self.refresh_all_once()

    def fetch_single_stock(self, code):
        """抓取并解析单只 A 股的实时全天分时数据与分时量"""
        prefix = "sh" if code.startswith(("6", "9")) else "sz"
        full_sym = f"{prefix}{code}"

        try:
            # 1. 获取最新盘口基础行情 (名称、现价、昨收、开高低、总成交)
            q_url = f"https://hq.sinajs.cn/list={full_sym}"
            q_res = self.session.get(q_url, timeout=3.5)
            q_text = q_res.content.decode("gbk", errors="ignore")

            if '"' not in q_text:
                return None
            fields = q_text.split('"')[1].split(",")
            if len(fields) < 10:
                return None

            name = fields[0]
            open_p = float(fields[1])
            pre_close = float(fields[2])
            latest_p = float(fields[3]) if float(fields[3]) > 0 else pre_close
            high_p = float(fields[4]) if float(fields[4]) > 0 else latest_p
            low_p = float(fields[5]) if float(fields[5]) > 0 else latest_p
            total_vol_shares = float(fields[8])
            total_vol_hands = total_vol_shares / 100.0  # 手
            total_turnover = float(fields[9])
            today_date = fields[30] if len(fields) > 30 and fields[30] else time.strftime("%Y-%m-%d")

            # 2. 获取当天 1分钟 K线序列 (每分钟独立真实分时量与分时成交额)
            k_url = f"https://quotes.sina.cn/cn/api/jsonp_v2.php/var_{full_sym}_1_=/CN_MarketDataService.getKLineData?symbol={full_sym}&scale=1&ma=no&datalen=242"
            k_res = self.session.get(k_url, timeout=3.5).text
            raw_json = k_res[k_res.find("(") + 1 : k_res.rfind(")")]
            bars_data = json.loads(raw_json)

            bars = []
            cum_v_hands = 0.0
            cum_t = 0.0

            for item in bars_data:
                day_str = item.get("day", "")
                # 仅保留属于当天的分钟线
                if not day_str.startswith(today_date):
                    continue
                t_str = day_str.split()[1][:5]
                p = float(item.get("close", 0))
                v_shares = float(item.get("volume", 0))
                v_hands = v_shares / 100.0  # 分时量 (手)
                t_amt = float(item.get("amount", p * v_shares))

                cum_v_hands += v_hands
                cum_t += t_amt
                # 当日累计均价 (VWAP)
                avg_p = (cum_t / (cum_v_hands * 100.0)) if cum_v_hands > 0 else p

                bars.append({
                    "time": t_str,
                    "price": p,
                    "volume": v_hands,
                    "avg_price": avg_p
                })

            diff = latest_p - pre_close if pre_close > 0 else 0.0
            pct = (diff / pre_close * 100.0) if pre_close > 0 else 0.0

            return {
                "code": code,
                "full_code": full_sym.upper(),
                "name": name,
                "latest_price": latest_p,
                "pre_close": pre_close,
                "open_price": open_p,
                "high_price": high_p,
                "low_price": low_p,
                "diff": diff,
                "pct": pct,
                "total_volume": total_vol_hands if total_vol_hands > 0 else cum_v_hands,
                "total_turnover": total_turnover if total_turnover > 0 else cum_t,
                "bars": bars,
                "update_time": time.strftime("%H:%M:%S")
            }
        except Exception as e:
            return None

    def refresh_all_once(self):
        """并发抓取所有已配置股票的数据"""
        with self.lock:
            current_symbols = list(self.symbols)

        with ThreadPoolExecutor(max_workers=min(24, len(current_symbols) or 1)) as executor:
            results = list(executor.map(self.fetch_single_stock, current_symbols))

        with self.lock:
            for item in results:
                if item and "code" in item:
                    self.stock_cache[item["code"]] = item

    def polling_loop(self):
        """后台高频轮询任务 (每 2 秒一次)"""
        while self.is_running:
            self.refresh_all_once()
            time.sleep(2)

    def get_all_data(self):
        with self.lock:
            ordered_data = []
            for s in self.symbols:
                if s in self.stock_cache:
                    ordered_data.append(self.stock_cache[s])
            return ordered_data

    def get_page_data(self, page=1, page_size=16):
        """获取指定窗口页码的 16 只股票数据"""
        with self.lock:
            total = len(self.symbols)
            total_pages = max(1, (total + page_size - 1) // page_size)
            page = max(1, min(page, total_pages))
            start_idx = (page - 1) * page_size
            end_idx = start_idx + page_size
            page_symbols = self.symbols[start_idx:end_idx]
            ordered_data = []
            for s in page_symbols:
                if s in self.stock_cache:
                    ordered_data.append(self.stock_cache[s])
            return ordered_data

    def get_pages_meta(self, page_size=16):
        """获取多窗口页面元数据"""
        with self.lock:
            total = len(self.symbols)
            total_pages = max(1, (total + page_size - 1) // page_size)
            pages = []
            for p in range(1, total_pages + 1):
                p_syms = self.symbols[(p - 1) * page_size : p * page_size]
                pages.append({
                    "page": p,
                    "count": len(p_syms),
                    "symbols": p_syms,
                    "url": f"http://{HTTP_HOST}:{WEB_PORT}/?page={p}"
                })
            return {
                "total_stocks": total,
                "total_pages": total_pages,
                "page_size": page_size,
                "pages": pages
            }


# 初始化全局数据中心
data_hub = StockDataHub(DEFAULT_STOCKS)


# ==============================================================================
# 3. 前端现代九宫格分时全景看板单页 (HTML + CSS + Canvas)
# ==============================================================================
FRONTEND_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>A股实时分时16宫格全景终端</title>
  <style>
    :root {
      --bg-main: #0a0e17;
      --bg-card: #111827;
      --bg-card-header: #162032;
      --border-color: #1f293d;
      --text-main: #f3f4f6;
      --text-dim: #9ca3af;
      --color-up: #ff4d4f;
      --color-down: #00d084;
      --color-flat: #8c8c8c;
      --color-price: #00e5ff;
      --color-vwap: #ffd166;
      --color-ref: #4b5563;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background-color: var(--bg-main);
      color: var(--text-main);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif;
      overflow: hidden;
      height: 100vh;
      display: flex;
      flex-direction: column;
      user-select: none;
    }

    /* 顶部导航与控制栏 */
    header {
      height: 48px;
      background: #0d1320;
      border-bottom: 1px solid var(--border-color);
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0 16px;
      flex-shrink: 0;
      z-index: 100;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 15px;
      font-weight: 700;
      letter-spacing: 0.5px;
      color: #38bdf8;
    }

    .page-badges {
      display: flex;
      gap: 6px;
      margin-left: 10px;
    }

    .page-btn {
      font-size: 11px;
      padding: 3px 8px;
      border-radius: 4px;
      background: #1e293b;
      color: #94a3b8;
      text-decoration: none;
      border: 1px solid #334155;
      cursor: pointer;
      font-weight: 500;
      transition: all 0.2s;
      white-space: nowrap;
    }

    .page-btn:hover {
      background: #38bdf8;
      color: #0f172a;
    }

    .page-btn.active {
      background: #0284c7;
      color: #ffffff;
      font-weight: 700;
      border-color: #38bdf8;
    }

    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 8px #10b981;
      animation: pulse 1.5s infinite;
    }

    @keyframes pulse {
      0% { transform: scale(0.95); opacity: 0.7; }
      50% { transform: scale(1.3); opacity: 1; }
      100% { transform: scale(0.95); opacity: 0.7; }
    }

    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .stock-input {
      background: #1f293d;
      border: 1px solid #374151;
      color: #fff;
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 13px;
      width: 420px;
      outline: none;
      transition: border-color 0.2s;
    }
    .stock-input:focus {
      border-color: #38bdf8;
    }

    .btn {
      background: #0284c7;
      color: #fff;
      border: none;
      padding: 5px 14px;
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 600;
      transition: background 0.2s;
    }
    .btn:hover {
      background: #0369a1;
    }

    .clock {
      font-family: "JetBrains Mono", Consolas, monospace;
      font-size: 13px;
      color: #cbd5e1;
      background: #1e293b;
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid #334155;
    }

    /* 16宫格布局容器 */
    main {
      flex: 1;
      padding: 6px;
      display: grid;
      grid-gap: 6px;
      height: calc(100vh - 48px);
      box-sizing: border-box;
      position: relative;
    }

    /* 动态行列自适应 (支持最多16个4x4) */
    .grid-16 {
      grid-template-columns: repeat(4, 1fr);
      grid-template-rows: repeat(4, 1fr);
    }
    .grid-12 {
      grid-template-columns: repeat(4, 1fr);
      grid-template-rows: repeat(3, 1fr);
    }
    .grid-9 {
      grid-template-columns: repeat(3, 1fr);
      grid-template-rows: repeat(3, 1fr);
    }
    .grid-6 {
      grid-template-columns: repeat(3, 1fr);
      grid-template-rows: repeat(2, 1fr);
    }
    .grid-4 {
      grid-template-columns: repeat(2, 1fr);
      grid-template-rows: repeat(2, 1fr);
    }
    .grid-1 {
      grid-template-columns: 1fr;
      grid-template-rows: 1fr;
    }

    /* 单个分时卡片窗口 */
    .stock-card {
      background: var(--bg-card);
      border: 1px solid var(--border-color);
      border-radius: 6px;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      min-height: 0;
      min-width: 0;
      box-shadow: 0 3px 8px rgba(0,0,0,0.3);
      position: relative;
    }

    /* 卡片头部行情栏 */
    .card-header {
      background: var(--bg-card-header);
      padding: 3px 8px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #1a2438;
      flex-shrink: 0;
    }

    .stock-title {
      display: flex;
      align-items: center;
      gap: 5px;
    }

    .stock-name {
      font-size: 13px;
      font-weight: 700;
      color: #ffffff;
    }

    .stock-code {
      font-size: 11px;
      color: #94a3b8;
      background: #0f172a;
      padding: 2px 5px;
      border-radius: 4px;
      border: 1px solid #1e293b;
      font-family: monospace;
    }

    .stock-price-box {
      display: flex;
      align-items: baseline;
      gap: 8px;
    }

    .stock-price {
      font-size: 17px;
      font-weight: 700;
      font-family: "JetBrains Mono", Consolas, monospace;
    }

    .stock-pct {
      font-size: 12px;
      font-weight: 600;
      padding: 2px 6px;
      border-radius: 4px;
    }

    .card-stats {
      font-size: 11px;
      color: #94a3b8;
      display: flex;
      gap: 8px;
    }

    /* Canvas 绘图区域 */
    .canvas-container {
      flex: 1;
      position: relative;
      width: 100%;
      height: 100%;
      min-height: 0;
    }

    canvas {
      position: absolute;
      left: 0;
      top: 0;
      width: 100%;
      height: 100%;
      display: block;
    }

    /* 悬浮十字光标 HUD Tooltip */
    .hud-tooltip {
      position: absolute;
      pointer-events: none;
      background: rgba(15, 23, 42, 0.94);
      border: 1px solid #38bdf8;
      border-radius: 5px;
      padding: 5px 9px;
      font-size: 11px;
      color: #f8fafc;
      font-family: monospace;
      display: none;
      z-index: 10;
      box-shadow: 0 4px 12px rgba(0,0,0,0.5);
      white-space: nowrap;
    }

    /* 空状态与加载状态 */
    .loading-overlay {
      position: absolute;
      inset: 0;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      gap: 12px;
      color: #94a3b8;
      font-size: 14px;
      background: var(--bg-main);
      z-index: 50;
    }

    .spinner {
      width: 32px;
      height: 32px;
      border: 3px solid #1e293b;
      border-top-color: #38bdf8;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
    }

    @keyframes spin {
      to { transform: rotate(360deg); }
    }

    /* 涨跌颜色辅助类 */
    .up { color: var(--color-up); }
    .down { color: var(--color-down); }
    .flat { color: var(--color-flat); }
    .badge-up { background: rgba(239, 68, 68, 0.2); color: #f87171; }
    .badge-down { background: rgba(16, 185, 129, 0.2); color: #34d399; }
    .badge-flat { background: rgba(148, 163, 184, 0.2); color: #cbd5e1; }
  </style>
</head>
<body>

  <header>
    <div class="brand">
      <div class="pulse-dot"></div>
      <span id="pageTitle">A股实时分时16宫格全景终端</span>
      <div id="pageBadges" class="page-badges"></div>
    </div>

    <div class="controls">
      <input type="text" id="stockInput" class="stock-input" placeholder="输入股票代码，逗号分隔，支持多窗口" />
      <button class="btn" onclick="applyCustomStocks()">更新自选</button>
      <div class="clock" id="liveClock">--:--:--</div>
    </div>
  </header>

  <main id="gridContainer" class="grid-16">
    <div class="loading-overlay" id="loadingOverlay">
      <div class="spinner"></div>
      <span>正在同步全天分时行情数据，请稍候...</span>
    </div>
  </main>

  <script>
    // 当前窗口页码（通过 URL 参数 ?page=1, ?page=2 传递）
    const urlParams = new URLSearchParams(window.location.search);
    const currentPage = parseInt(urlParams.get('page') || '1', 10);

    // 渲染槽位与时间轴 (全天 240 分钟映射)
    const TOTAL_SLOTS = 240;

    function timeToSlot(tStr) {
      if (!tStr) return null;
      const parts = tStr.split(':');
      const h = parseInt(parts[0], 10);
      const m = parseInt(parts[1], 10);

      if (h === 9) {
        if (m >= 30) return m - 30; // 09:30 -> 0, 09:59 -> 29
      } else if (h === 10) {
        return 30 + m;             // 10:00 -> 30, 10:59 -> 89
      } else if (h === 11) {
        return Math.min(120, 90 + m); // 11:00 -> 90, 11:30 -> 120
      } else if (h === 13) {
        if (m === 0) return 120;
        return 120 + m;            // 13:01 -> 121, 13:59 -> 179
      } else if (h === 14) {
        return 180 + m;            // 14:00 -> 180, 14:59 -> 239
      } else if (h === 15) {
        return 240;                // 15:00 -> 240
      }
      return null;
    }

    // 内存数据缓存
    let stocksData = [];
    let mouseState = {}; // { cardId: { x, y, active } }
    let hasLoadedFirst = false;

    async function fetchStocksData() {
      try {
        const resp = await fetch(`/api/stocks?page=${currentPage}`);
        if (resp.ok) {
          const data = await resp.json();
          if (Array.isArray(data) && data.length > 0) {
            stocksData = data;
            const overlay = document.getElementById('loadingOverlay');
            if (overlay) overlay.style.display = 'none';

            renderGridCards();
            // 在下一帧统一渲染 Canvas
            requestAnimationFrame(() => {
              drawAllCanvases();
            });
            hasLoadedFirst = true;
          }
        }
      } catch (e) {
        console.error("Fetch stocks error:", e);
      }
    }

    function renderGridCards() {
      const container = document.getElementById('gridContainer');
      const count = stocksData.length;

      // 自适应十六宫格网格类
      container.className = count <= 1 ? 'grid-1' : (count <= 4 ? 'grid-4' : (count <= 6 ? 'grid-6' : (count <= 9 ? 'grid-9' : (count <= 12 ? 'grid-12' : 'grid-16'))));

      // 仅在卡片数量或代码改变时重构 DOM
      const currentCards = Array.from(container.querySelectorAll('.stock-card'));
      const currentIds = currentCards.map(c => c.getAttribute('data-code')).join(',');
      const newIds = stocksData.map(s => s.code).join(',');

      if (currentIds !== newIds) {
        // 保留可能存在的 loading 节点除外的内容
        const oldCards = container.querySelectorAll('.stock-card');
        oldCards.forEach(c => c.remove());

        stocksData.forEach((st) => {
          const card = document.createElement('div');
          card.className = 'stock-card';
          card.setAttribute('data-code', st.code);
          card.id = `card_${st.code}`;

          card.innerHTML = `
            <div class="card-header">
              <div class="stock-title">
                <span class="stock-name" id="name_${st.code}">${st.name}</span>
                <span class="stock-code">${st.full_code}</span>
              </div>
              <div class="stock-price-box">
                <span class="stock-price" id="price_${st.code}">--</span>
                <span class="stock-pct" id="pct_${st.code}">--</span>
              </div>
              <div class="card-stats">
                <span>昨收: <b id="pre_${st.code}">--</b></span>
                <span>总量: <b id="vol_${st.code}">--</b></span>
              </div>
            </div>
            <div class="canvas-container" id="wrap_${st.code}">
              <canvas id="cvs_${st.code}"></canvas>
              <div class="hud-tooltip" id="hud_${st.code}"></div>
            </div>
          `;

          container.appendChild(card);
          bindCanvasEvents(st.code);
        });

        // 仅在首次或未聚焦时填充顶栏输入框
        const inputEl = document.getElementById('stockInput');
        if (inputEl && document.activeElement !== inputEl) {
          inputEl.value = stocksData.map(s => s.code).join(', ');
        }
      }

      // 更新卡片数值
      stocksData.forEach(st => {
        const diff = st.diff || 0;
        const colorClass = diff > 0 ? 'up' : (diff < 0 ? 'down' : 'flat');
        const badgeClass = diff > 0 ? 'badge-up' : (diff < 0 ? 'badge-down' : 'badge-flat');

        const elPrice = document.getElementById(`price_${st.code}`);
        const elPct = document.getElementById(`pct_${st.code}`);
        const elPre = document.getElementById(`pre_${st.code}`);
        const elVol = document.getElementById(`vol_${st.code}`);

        if (elPrice) {
          elPrice.className = `stock-price ${colorClass}`;
          elPrice.innerText = st.latest_price.toFixed(2);
        }
        if (elPct) {
          elPct.className = `stock-pct ${badgeClass}`;
          elPct.innerText = `${st.pct >= 0 ? '+' : ''}${st.pct.toFixed(2)}%`;
        }
        if (elPre) elPre.innerText = st.pre_close.toFixed(2);
        if (elVol) elVol.innerText = (st.total_volume >= 10000) ? (st.total_volume / 10000).toFixed(1) + '万手' : Math.round(st.total_volume) + '手';
      });
    }

    function bindCanvasEvents(code) {
      const cvs = document.getElementById(`cvs_${code}`);
      const hud = document.getElementById(`hud_${code}`);
      if (!cvs) return;

      cvs.addEventListener('mousemove', (e) => {
        const rect = cvs.getBoundingClientRect();
        mouseState[code] = {
          x: e.clientX - rect.left,
          y: e.clientY - rect.top,
          active: true
        };
        drawCanvas(code);
      });

      cvs.addEventListener('mouseleave', () => {
        mouseState[code] = { active: false };
        if (hud) hud.style.display = 'none';
        drawCanvas(code);
      });
    }

    // 绘制所有 Canvas
    function drawAllCanvases() {
      stocksData.forEach(st => {
        drawCanvas(st.code);
      });
    }

    // 核心绘制函数: 绘制单只个股全天分时图与分时量
    function drawCanvas(code) {
      const st = stocksData.find(s => s.code === code);
      const cvs = document.getElementById(`cvs_${code}`);
      const hud = document.getElementById(`hud_${code}`);
      if (!st || !cvs) return;

      const rect = cvs.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const w = Math.floor(rect.width);
      const h = Math.floor(rect.height);

      if (w <= 20 || h <= 20) return; // 尺寸未就绪跳过

      if (cvs.width !== Math.floor(w * dpr) || cvs.height !== Math.floor(h * dpr)) {
        cvs.width = Math.floor(w * dpr);
        cvs.height = Math.floor(h * dpr);
      }

      const ctx = cvs.getContext('2d');
      ctx.resetTransform();
      ctx.scale(dpr, dpr);
      ctx.clearRect(0, 0, w, h);

      // 分区划分: 上 68% 为价格分时线，下 32% 为分时量柱
      const padding = { top: 10, bottom: 18, left: 42, right: 42 };
      const totalPlotH = h - padding.top - padding.bottom;
      const priceH = Math.floor(totalPlotH * 0.68);
      const volH = totalPlotH - priceH - 8;
      const volTop = padding.top + priceH + 8;
      const plotW = w - padding.left - padding.right;

      if (plotW <= 0 || priceH <= 0) return;

      const preClose = st.pre_close || (st.bars[0] ? st.bars[0].price : 100);
      const bars = st.bars || [];

      // 1. 将有效分钟映射到 0~240 槽位
      let mappedPoints = [];
      let maxVol = 10;
      let maxDev = preClose * 0.005; // 至少 0.5% 视距

      bars.forEach((b) => {
        const slot = timeToSlot(b.time);
        if (slot !== null) {
          mappedPoints.push({
            slot: slot,
            price: b.price,
            avg: b.avg_price,
            vol: b.volume,
            time: b.time
          });
          const dev = Math.abs(b.price - preClose);
          if (dev > maxDev) maxDev = dev;
          if (b.volume > maxVol) maxVol = b.volume;
        }
      });

      const yPriceMin = preClose - maxDev * 1.05;
      const yPriceMax = preClose + maxDev * 1.05;
      const maxPct = (maxDev / preClose * 100) * 1.05;

      const getX = (slot) => padding.left + (slot / TOTAL_SLOTS) * plotW;
      const getYPrice = (p) => padding.top + priceH * (1 - (p - yPriceMin) / (yPriceMax - yPriceMin));
      const getYVol = (v) => volTop + volH * (1 - (v / maxVol));

      // 2. 绘制网格与时间分界线
      ctx.lineWidth = 1;

      // 昨收基准线 (中轴)
      const yPreClose = getYPrice(preClose);
      ctx.setLineDash([3, 3]);
      ctx.strokeStyle = '#475569';
      ctx.beginPath();
      ctx.moveTo(padding.left, yPreClose);
      ctx.lineTo(padding.left + plotW, yPreClose);
      ctx.stroke();

      // 上下边界线
      ctx.setLineDash([2, 4]);
      ctx.strokeStyle = '#243048';
      ctx.beginPath();
      ctx.moveTo(padding.left, padding.top);
      ctx.lineTo(padding.left + plotW, padding.top);
      ctx.moveTo(padding.left, padding.top + priceH);
      ctx.lineTo(padding.left + plotW, padding.top + priceH);
      // 分时量上下边界
      ctx.moveTo(padding.left, volTop);
      ctx.lineTo(padding.left + plotW, volTop);
      ctx.moveTo(padding.left, volTop + volH);
      ctx.lineTo(padding.left + plotW, volTop + volH);
      ctx.stroke();

      // 垂直分割线: 10:30 (slot 60), 11:30/13:00 (slot 120), 14:00 (slot 180)
      [60, 120, 180].forEach(s => {
        const x = getX(s);
        ctx.beginPath();
        ctx.moveTo(x, padding.top);
        ctx.lineTo(x, volTop + volH);
        ctx.strokeStyle = (s === 120) ? '#64748b' : '#1e293b';
        ctx.stroke();
      });
      ctx.setLineDash([]); // 恢复实线

      // 3. 绘制 X 轴时间刻度
      ctx.fillStyle = '#64748b';
      ctx.font = '10px -apple-system, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('09:30', getX(0) + 12, h - 4);
      ctx.fillText('10:30', getX(60), h - 4);
      ctx.fillText('11:30/13:00', getX(120), h - 4);
      ctx.fillText('14:00', getX(180), h - 4);
      ctx.fillText('15:00', getX(240) - 12, h - 4);

      // 4. 绘制 Y 轴数值 (左价格，右涨跌幅)
      ctx.textAlign = 'right';
      ctx.fillStyle = '#ff4d4f';
      ctx.fillText(yPriceMax.toFixed(2), padding.left - 4, padding.top + 10);
      ctx.fillStyle = '#00d084';
      ctx.fillText(yPriceMin.toFixed(2), padding.left - 4, padding.top + priceH);
      ctx.fillStyle = '#94a3b8';
      ctx.fillText(preClose.toFixed(2), padding.left - 4, yPreClose + 3);

      ctx.textAlign = 'left';
      ctx.fillStyle = '#ff4d4f';
      ctx.fillText(`+${maxPct.toFixed(2)}%`, padding.left + plotW + 4, padding.top + 10);
      ctx.fillStyle = '#00d084';
      ctx.fillText(`-${maxPct.toFixed(2)}%`, padding.left + plotW + 4, padding.top + priceH);
      ctx.fillStyle = '#94a3b8';
      ctx.fillText('0.00%', padding.left + plotW + 4, yPreClose + 3);

      // 分时量最大刻度
      ctx.textAlign = 'right';
      ctx.fillStyle = '#64748b';
      const volLabel = maxVol >= 10000 ? (maxVol / 10000).toFixed(1) + '万' : Math.round(maxVol);
      ctx.fillText(volLabel, padding.left - 4, volTop + 10);

      if (mappedPoints.length === 0) return;

      // 5. 绘制分时价格折线与渐变填充
      ctx.beginPath();
      mappedPoints.forEach((pt, i) => {
        const x = getX(pt.slot);
        const y = getYPrice(pt.price);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });

      // 价格折线描边 (霓虹青色)
      ctx.strokeStyle = '#00e5ff';
      ctx.lineWidth = 1.4;
      ctx.stroke();

      // 渐变填充至昨收线
      const lastPt = mappedPoints[mappedPoints.length - 1];
      ctx.lineTo(getX(lastPt.slot), yPreClose);
      ctx.lineTo(getX(mappedPoints[0].slot), yPreClose);
      ctx.closePath();
      const grad = ctx.createLinearGradient(0, padding.top, 0, yPreClose);
      grad.addColorStop(0, 'rgba(0, 229, 255, 0.18)');
      grad.addColorStop(1, 'rgba(0, 229, 255, 0.00)');
      ctx.fillStyle = grad;
      ctx.fill();

      // 6. 绘制分时均价线 (金黄色虚线)
      ctx.beginPath();
      ctx.setLineDash([3, 2]);
      mappedPoints.forEach((pt, i) => {
        const x = getX(pt.slot);
        const y = getYPrice(pt.avg);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      });
      ctx.strokeStyle = '#ffd166';
      ctx.lineWidth = 1.2;
      ctx.stroke();
      ctx.setLineDash([]);

      // 7. 绘制分时量柱状图 (红涨绿跌)
      const barW = Math.max(1.2, (plotW / TOTAL_SLOTS) * 0.75);
      mappedPoints.forEach((pt, i) => {
        const x = getX(pt.slot) - barW / 2;
        const yBar = getYVol(pt.vol);
        const hBar = Math.max(1, volTop + volH - yBar);
        const refP = (i === 0) ? preClose : mappedPoints[i - 1].price;

        ctx.fillStyle = (pt.price >= refP) ? '#ff4d4f' : '#00d084';
        ctx.fillRect(x, yBar, barW, hBar);
      });

      // 8. 交互十字光标与 HUD 提示
      const m = mouseState[code];
      if (m && m.active && m.x >= padding.left && m.x <= padding.left + plotW) {
        const hoveredSlot = Math.round(((m.x - padding.left) / plotW) * TOTAL_SLOTS);
        const crossX = getX(hoveredSlot);

        // 垂直十字线
        ctx.setLineDash([2, 2]);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.6)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(crossX, padding.top);
        ctx.lineTo(crossX, volTop + volH);
        ctx.stroke();
        ctx.setLineDash([]);

        // 查找最接近的数据点
        const nearestPt = mappedPoints.find(p => p.slot === hoveredSlot) ||
                          mappedPoints.reduce((prev, curr) => Math.abs(curr.slot - hoveredSlot) < Math.abs(prev.slot - hoveredSlot) ? curr : prev, mappedPoints[0]);

        if (nearestPt && hud) {
          const crossY = getYPrice(nearestPt.price);
          // 交叉圆点
          ctx.beginPath();
          ctx.arc(crossX, crossY, 3, 0, Math.PI * 2);
          ctx.fillStyle = '#ffffff';
          ctx.fill();

          const ptDiff = nearestPt.price - preClose;
          const ptPct = (ptDiff / preClose * 100);
          const ptColor = ptDiff >= 0 ? '#ff4d4f' : '#00d084';

          hud.style.display = 'block';
          hud.innerHTML = `
            <div><b>${nearestPt.time}</b></div>
            <div>价: <span style="color:${ptColor};font-weight:bold">${nearestPt.price.toFixed(2)}</span> (${ptPct >= 0 ? '+' : ''}${ptPct.toFixed(2)}%)</div>
            <div>均: <span style="color:#ffd166">${nearestPt.avg.toFixed(2)}</span></div>
            <div>量: <span>${Math.round(nearestPt.vol)}手</span></div>
          `;

          // HUD 位置动态防溢出
          let hudLeft = crossX + 10;
          let hudTop = crossY - 20;
          if (hudLeft + 130 > w) hudLeft = crossX - 130;
          if (hudTop < padding.top) hudTop = padding.top;
          hud.style.left = `${hudLeft}px`;
          hud.style.top = `${hudTop}px`;
        }
      }
    }

    // 动态应用用户输入的自定义股票列表
    function applyCustomStocks() {
      const input = document.getElementById('stockInput').value;
      const codes = input.split(/[,，\\s]+/).map(s => s.trim()).filter(s => s.length > 0);
      if (codes.length === 0) {
        alert("请输入至少一个 6 位股票代码！");
        return;
      }
      fetch('/api/set_stocks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stocks: codes })
      }).then(() => {
        fetchStocksData();
        updatePagesMeta();
      });
    }

    // 更新多窗口页面元数据与导航标签
    async function updatePagesMeta() {
      try {
        const resp = await fetch('/api/pages');
        if (resp.ok) {
          const meta = await resp.json();
          const titleEl = document.getElementById('pageTitle');
          if (titleEl) {
            if (meta.total_pages > 1) {
              titleEl.innerText = `A股分时16宫格终端 [窗口 ${currentPage}/${meta.total_pages}]`;
            } else {
              titleEl.innerText = `A股实时分时16宫格全景终端`;
            }
          }
          const badgeContainer = document.getElementById('pageBadges');
          if (badgeContainer) {
            badgeContainer.innerHTML = '';
            if (meta.total_pages > 1) {
              for (let p = 1; p <= meta.total_pages; p++) {
                const a = document.createElement('a');
                a.className = `page-btn ${p === currentPage ? 'active' : ''}`;
                a.href = `/?page=${p}`;
                const count = meta.pages && meta.pages[p-1] ? meta.pages[p-1].count : 0;
                a.innerText = `窗口 ${p} (${count}只)`;
                badgeContainer.appendChild(a);
              }
            }
          }
        }
      } catch (e) {}
    }

    // 实时系统时钟
    function updateClock() {
      const now = new Date();
      document.getElementById('liveClock').innerText = now.toTimeString().split(' ')[0];
    }
    setInterval(updateClock, 1000);
    updateClock();

    // 窗口重置自适应重绘
    window.addEventListener('resize', () => {
      drawAllCanvases();
    });

    // 轮询后端 API (分时数据 2 秒一次，页面元数据 4 秒一次)
    setInterval(fetchStocksData, 2000);
    fetchStocksData();

    setInterval(updatePagesMeta, 4000);
    updatePagesMeta();
  </script>
</body>
</html>
"""


# ==============================================================================
# 4. HTTP Web 服务端
# ==============================================================================
class WebDashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        qs = parse_qs(parsed_url.query)

        if path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(FRONTEND_HTML.encode("utf-8"))

        elif path == "/api/stocks":
            page_str = qs.get("page", [None])[0]
            if page_str is not None and page_str != "all":
                try:
                    page_num = int(page_str)
                except ValueError:
                    page_num = 1
                data = data_hub.get_page_data(page=page_num, page_size=16)
            else:
                data = data_hub.get_all_data()

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

        elif path == "/api/pages":
            meta = data_hub.get_pages_meta()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(meta, ensure_ascii=False).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path

        if path == "/api/set_stocks":
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length)
            try:
                req_data = json.loads(post_body.decode("utf-8"))
                new_stocks = req_data.get("stocks", [])
                data_hub.set_symbols(new_stocks)
                meta = data_hub.get_pages_meta()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "status": "ok",
                    "count": len(data_hub.symbols),
                    "total_pages": meta["total_pages"],
                    "pages": meta["pages"]
                }, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # 屏蔽高频轮询日志，保持终端清爽
        fmt_str = format % args
        if "/api/stocks" not in fmt_str and "/api/pages" not in fmt_str:
            super().log_message(format, *args)


def start_server():
    print("\n" + "=" * 70)
    print(f"⏳ 正在初始化抓取 {len(DEFAULT_STOCKS)} 只股票的最新全天分时数据...")
    data_hub.refresh_all_once()
    loaded_count = len(data_hub.get_all_data())
    print(f"✅ 数据预载完成! 已成功载入 {loaded_count} 只股票的实时分时走势。")
    print("=" * 70)

    server_address = (HTTP_HOST, WEB_PORT)
    try:
        httpd = HTTPServer(server_address, WebDashboardHandler)
        meta = data_hub.get_pages_meta()
        print(f"🚀 A股实时分时16宫格网页终端已启动!")
        print(f"📊 当前共监控 {meta['total_stocks']} 只股票，分布在 {meta['total_pages']} 个16宫格窗口：")
        for p in meta["pages"]:
            print(f"  👉 窗口 {p['page']}: {p['url']} (包含 {p['count']} 只标的: {p['symbols']})")
        print(f"💡 提示: 超过16只股票将自动生成新窗口展示，各Agent节点将自动轮询抓取所有窗口。")
        print("=" * 70 + "\n")

        # 启动后台自动拉取线程
        polling_thread = threading.Thread(target=data_hub.polling_loop, daemon=True)
        polling_thread.start()

        # 自动调用系统默认浏览器打开所有窗口
        for p in meta["pages"]:
            threading.Timer(0.8 * p["page"], lambda u=p["url"]: webbrowser.open(u)).start()

        httpd.serve_forever()
    except OSError as e:
        if e.errno == 98 or "address already in use" in str(e).lower() or "10048" in str(e):
            alt_port = WEB_PORT + 1
            print(f"[提示] 端口 {WEB_PORT} 被占用，切换至端口 {alt_port}...")
            httpd = HTTPServer((HTTP_HOST, alt_port), WebDashboardHandler)
            threading.Timer(0.8, lambda: webbrowser.open(f"http://{HTTP_HOST}:{alt_port}")).start()
            httpd.serve_forever()
        else:
            raise e


# ==============================================================================
# 5. 主程序启动入口
# ==============================================================================
if __name__ == "__main__":
    try:
        start_server()
    except KeyboardInterrupt:
        print("\n服务已手动停止。")
