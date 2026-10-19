"""
机构与投行研报财报自动抓取与入库模块
实时拉取东方财富/券商研究所发布的最新个股研报、行业研报、季报/年报点评，
自动解析文本、结构化元数据并持久化导入 RAG 向量知识库
"""

import os
import re
import datetime
import requests
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup

from rag.config import CATEGORY_RESEARCH, CATEGORY_FINANCIAL
from rag.rag_service import rag_service

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def _infer_category(title: str, user_category: str = "自动") -> str:
    """根据标题特征自动推断分类（研报分析 / 财报解读）"""
    if user_category in [CATEGORY_RESEARCH, CATEGORY_FINANCIAL]:
        return user_category

    # 包含中报、季报、年报、业绩、财报、业绩预告等关键词归类为财报解读
    financial_keywords = ["季报", "中报", "年报", "业绩", "财报", "点评", "快报", "利润", "营收", "财务"]
    for kw in financial_keywords:
        if kw in title:
            return CATEGORY_FINANCIAL

    return CATEGORY_RESEARCH


def fetch_report_detail_content(info_code: str) -> str:
    """抓取单篇机构研报在东方财富上的详细正文与投资要点"""
    url = f"https://data.eastmoney.com/report/info/{info_code}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.encoding = "utf-8"
        if r.status_code != 200:
            return ""

        soup = BeautifulSoup(r.text, "html.parser")
        ctx = soup.find("div", class_="ctx-content")
        if ctx:
            # 清理无用脚本和广告
            for s in ctx.find_all(["script", "style"]):
                s.decompose()
            return ctx.get_text().strip()

        # 备选结构
        ctx2 = soup.find("div", class_="newsContent") or soup.find("div", class_="detail-body")
        if ctx2:
            return ctx2.get_text().strip()

    except Exception as e:
        print(f"⚠️ [ReportFetcher] 抓取研报详情失败 (infoCode={info_code}): {e}")

    return ""


def get_recent_reports_list(
    symbol: str = "",
    count: int = 15,
    rating: str = "*",
    keyword: str = "",
) -> List[Dict[str, Any]]:
    """
    拉取各大券商/投行近期最新发布的研报列表（元数据预览）
    """
    url = "https://reportapi.eastmoney.com/report/list"
    now_year = datetime.datetime.now().year
    params = {
        "industryCode": "*",
        "pageSize": str(min(count * 2, 50)),  # 多拉取一些以便按关键词过滤
        "industry": "*",
        "rating": rating or "*",
        "ratingChange": "*",
        "beginTime": f"{now_year - 1}-01-01",
        "endTime": f"{now_year + 1}-01-01",
        "pageNo": "1",
        "qType": "0",
    }
    if symbol and symbol.strip():
        params["code"] = symbol.strip()

    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return []
        data_json = r.json()
        raw_items = data_json.get("data", [])
        if not raw_items:
            return []

        results = []
        for item in raw_items:
            title = str(item.get("title", "")).strip()
            stock_code = str(item.get("stockCode", "")).strip()
            stock_name = str(item.get("stockName", "")).strip()
            org_sname = str(item.get("orgSName", "") or item.get("orgName", "")).strip()
            pub_date = str(item.get("publishDate", "")).split()[0]
            em_rating = str(item.get("emRatingName", "")).strip() or "未评级"
            info_code = str(item.get("infoCode", "")).strip()

            if keyword and keyword.strip():
                kw = keyword.strip().lower()
                if kw not in title.lower() and kw not in stock_name.lower() and kw not in org_sname.lower():
                    continue

            pdf_url = f"https://pdf.dfcfw.com/pdf/H3_{info_code}_1.pdf"
            inferred_cat = _infer_category(title)

            results.append({
                "infoCode": info_code,
                "title": title,
                "stockCode": stock_code,
                "stockName": stock_name,
                "orgSName": org_sname,
                "publishDate": pub_date,
                "emRatingName": em_rating,
                "industryName": str(item.get("indvInduName", "") or item.get("industryName", "")).strip(),
                "author": str(item.get("author", "")).strip(),
                "predictThisYearPe": str(item.get("predictThisYearPe", "") or "-"),
                "predictNextYearPe": str(item.get("predictNextYearPe", "") or "-"),
                "predictThisYearEps": str(item.get("predictThisYearEps", "") or "-"),
                "predictNextYearEps": str(item.get("predictNextYearEps", "") or "-"),
                "pdfUrl": pdf_url,
                "category": inferred_cat,
            })

            if len(results) >= count:
                break

        return results

    except Exception as e:
        print(f"❌ [ReportFetcher] 请求研报列表接口异常: {e}")
        return []


def download_and_import_reports(
    symbol: str = "",
    count: int = 5,
    category: str = "自动",
    rating: str = "*",
    keyword: str = "",
    selected_info_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    一键抓取并下载机构最新研报/财报解读，结构化分块后导入到 RAG 知识库
    """
    # 1. 获取研报列表
    fetch_count = count if not selected_info_codes else 30
    report_list = get_recent_reports_list(
        symbol=symbol,
        count=fetch_count,
        rating=rating,
        keyword=keyword,
    )

    if not report_list:
        return {
            "success": False,
            "message": "未能从权威机构接口获取到相关的研报列表，请检查网络或更换股票代码/关键词",
            "imported_count": 0,
            "imported_items": [],
        }

    # 检查已入库的文档，避免重复下载
    existing_docs = rag_service.list_documents()
    existing_titles = set(d.get("title", "") for d in existing_docs)
    existing_filenames = set(d.get("original_name", "") for d in existing_docs)

    imported_items = []
    skipped_count = 0

    # 如果指定了勾选的研报 infoCode 列表，优先按勾选入库
    target_reports = report_list
    if selected_info_codes:
        code_set = set(selected_info_codes)
        target_reports = [r for r in report_list if r["infoCode"] in code_set]

    for item in target_reports:
        if len(imported_items) >= count:
            break

        info_code = item["infoCode"]
        title = item["title"]
        stock_code = item["stockCode"]
        stock_name = item["stockName"]
        org = item["orgSName"] or "券商机构"

        full_title = f"{org}：{title}"
        doc_filename = f"{org}_{stock_name}_{info_code}.md"

        # 判重
        if full_title in existing_titles or doc_filename in existing_filenames:
            skipped_count += 1
            continue

        # 2. 抓取正文投资要点
        body_text = fetch_report_detail_content(info_code)
        if not body_text or len(body_text) < 60:
            # 详情正文过短或未能抓取到，构造丰富摘要卡片
            body_text = (
                f"{stock_name}（{stock_code}）最新机构研报由 {org} 发布，"
                f"投资评级为【{item['emRatingName']}】。\n\n"
                f"研报标题：《{title}》\n"
                f"所属行业：{item['industryName']}\n"
                f"分析师：{item['author'] or '行业组'}\n"
                f"盈利预测：预测今年市盈率 PE 为 {item['predictThisYearPe']}，预测每股收益 EPS 为 {item['predictThisYearEps']} 元。\n"
                f"预测下年市盈率 PE 为 {item['predictNextYearPe']}，预测每股收益 EPS 为 {item['predictNextYearEps']} 元。\n"
                f"报告原始发布日期：{item['publishDate']}\n"
            )

        cat = _infer_category(title, category)

        # 3. 构造专业结构化 Markdown 研报文档
        md_content = (
            f"# 【{org}研报】{title}\n\n"
            f"- **标的股票**：{stock_code} {stock_name}\n"
            f"- **研究机构**：{org}\n"
            f"- **研报类型**：{cat}\n"
            f"- **发布日期**：{item['publishDate']}\n"
            f"- **投资评级**：{item['emRatingName']}\n"
            f"- **所属行业**：{item['industryName']}\n"
            f"- **分析师团队**：{item['author'] or '行业首席'}\n"
            f"- **盈利预测指标**：今年 PE {item['predictThisYearPe']} / 下年 PE {item['predictNextYearPe']} | "
            f"今年 EPS {item['predictThisYearEps']} / 下年 EPS {item['predictNextYearEps']}\n"
            f"- **报告原件来源**：{item['pdfUrl']}\n\n"
            f"---\n\n"
            f"## 研报正文与核心投资要点\n\n"
            f"{body_text}\n"
        )

        try:
            file_bytes = md_content.encode("utf-8")
            doc_meta = rag_service.save_and_index_document(
                file_bytes=file_bytes,
                filename=doc_filename,
                category=cat,
                stock_code=stock_code,
                stock_name=stock_name,
                title=full_title,
            )
            imported_items.append(doc_meta)
            existing_titles.add(full_title)
            existing_filenames.add(doc_filename)
        except Exception as err:
            print(f"⚠️ [ReportFetcher] 入库研报《{full_title}》异常: {err}")

    return {
        "success": True,
        "imported_count": len(imported_items),
        "skipped_count": skipped_count,
        "imported_items": imported_items,
        "message": (
            f"🎉 成功下载并入库 {len(imported_items)} 篇机构最新研报/财报解读！"
            f"{f'（跳过 {skipped_count} 篇已入库文档）' if skipped_count else ''}"
        ),
    }
