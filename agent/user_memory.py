"""
agent/user_memory.py
用户记忆持久化模块 (User Memory Persistence)

实现对用户操盘人设 (user_role)、交易风格 (trading_style)、战法笔记 (memory_notes)
以及个性化量化参数 (custom_preferences) 的 JSON 文件持久化管理。
使得 Node 4 (16宫格分时量化分析 Agent) 及后续 Agent 能够动态加载并执行用户的专属记忆设定。
"""

import os
import sys
import json
import datetime
from typing import Dict, Any, List, Optional


def get_project_root() -> str:
    """获取项目根目录（兼容在 agent 子目录或根目录下运行）"""
    curr = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(curr)
    for candidate in [parent, curr]:
        if os.path.exists(os.path.join(candidate, "stock_data")):
            return candidate
    return parent


def get_user_memory_path() -> str:
    """获取用户记忆 JSON 存储文件路径 (stock_data/user_memory.json)"""
    root = get_project_root()
    data_dir = os.path.join(root, "stock_data")
    os.makedirs(data_dir, exist_ok=True)
    return os.path.join(data_dir, "user_memory.json")


# 默认用户记忆模板配置
DEFAULT_USER_MEMORY: Dict[str, Any] = {
    "user_role": "你是一名顶级 A股 日内量化与超短线盘口操盘手",
    "persona_title": "顶级 A股 日内量化与超短线盘口操盘手",
    "trading_style": "超短线日内盘口量化，严格执行均线承接战法与分时回踩纪律",
    "memory_notes": [
        "重点监控早盘 09:30-09:35 回踩不跌破分时均线、快速收回且有资金主动放量承接的标的",
        "均线收复速度在1、2分钟内，或全程处于均线上方无需收回的均符合战法要求",
        "对回调缩量衰竭与分时反弹放量保持敏锐捕捉",
        "破位后无法在2分钟内收回的标的坚决剔除淘汰",
    ],
    "custom_preferences": {
        "focus_window": "09:30 - 09:35",
        "max_recovery_minutes": 2,
        "strategy_tag": "回踩均线资金承接战法",
    },
    "updated_at": "2026-10-19 15:24:36",
}


def load_user_memory() -> Dict[str, Any]:
    """
    从 JSON 文件加载持久化的用户记忆；若文件不存在则自动初始化默认记忆并持久化
    """
    path = get_user_memory_path()
    if not os.path.exists(path):
        save_user_memory(DEFAULT_USER_MEMORY)
        return dict(DEFAULT_USER_MEMORY)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSON 根结构必须为字典对象")
            # 补齐默认字段，防止缺失键
            merged = dict(DEFAULT_USER_MEMORY)
            merged.update(data)
            return merged
    except Exception as e:
        print(f"⚠️ [UserMemory] 读取用户记忆文件异常: {e}，回退使用默认配置")
        return dict(DEFAULT_USER_MEMORY)


def save_user_memory(data: Dict[str, Any]) -> bool:
    """
    持久化保存用户记忆至 stock_data/user_memory.json
    """
    path = get_user_memory_path()
    try:
        data_to_save = dict(data)
        data_to_save["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ [UserMemory] 保存用户记忆文件失败: {e}")
        return False


def get_user_role(default: str = "你是一名顶级 A股 日内量化与超短线盘口操盘手") -> str:
    """
    获取持久化的用户人设/角色设定 (user_role)
    """
    mem = load_user_memory()
    role = str(mem.get("user_role") or "").strip()
    return role if role else default


def update_user_role(new_role: str) -> bool:
    """
    更新持久化的用户角色人设
    """
    mem = load_user_memory()
    mem["user_role"] = new_role.strip()
    return save_user_memory(mem)


def get_user_memory_prompt_addition() -> str:
    """
    生成注入 Agent 提示词的用户个性化记忆与操盘纪律文本
    """
    mem = load_user_memory()
    lines = []
    trading_style = mem.get("trading_style")
    if trading_style:
        lines.append(f"【用户持久化交易风格】：{trading_style}")

    notes = mem.get("memory_notes")
    if notes and isinstance(notes, list):
        valid_notes = [str(n).strip() for n in notes if str(n).strip()]
        if valid_notes:
            lines.append("【用户核心实操纪律备忘】：")
            for idx, note in enumerate(valid_notes, 1):
                lines.append(f"  {idx}. {note}")

    if lines:
        return "\n".join(lines) + "\n"
    return ""
