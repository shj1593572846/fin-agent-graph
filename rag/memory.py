"""
rag/memory.py
RAG 智能体滑动窗口记忆模块 (Sliding Window Memory)

实现基于会话 (session_id) 隔离的定长滑动窗口对话记忆机制：
1. 窗口限制：默认保留最近 K 轮（默认 5 轮）问答交互，超出窗口阈值时最早的交互自动滑出淘汰（FIFO）；
2. 实体与上下文继承：支持从窗口记忆中反向提取最近讨论的标的代码与分类，辅助指代消歧与多轮连续追问；
3. LangChain 消息无缝对接：支持快速转换为 HumanMessage 与 AIMessage 序列注入大模型上下文；
4. 线程安全与持久化：支持线程锁保障并发安全，支持持久化至本地 JSON 文件防止服务重启记忆丢失。
"""

import os
import json
import time
import uuid
import threading
from typing import List, Dict, Any, Optional
from collections import deque
from pydantic import BaseModel, Field

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
_DEFAULT_MEMORY_FILE = os.path.join(_CURRENT_DIR, "data", "rag_memory.json")


class MemoryTurn(BaseModel):
    """单轮对话结构"""
    turn_id: str = Field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:6]}")
    timestamp: str = Field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    query: str
    answer: str
    stock_code: Optional[str] = None
    stock_name: Optional[str] = None
    category: Optional[str] = None


class SlidingWindowMemory:
    """
    定长滑动窗口对话记忆管理器 (Sliding Window Memory)
    """

    def __init__(
        self,
        window_size: int = 5,
        storage_file: Optional[str] = None,
        auto_persist: bool = True
    ):
        """
        初始化滑动窗口记忆
        :param window_size: 滑动窗口最大保留轮数（默认 5 轮）
        :param storage_file: 持久化存储文件路径
        :param auto_persist: 是否在新增/清空时自动持久化到本地文件
        """
        self.window_size = max(1, window_size)
        self.storage_file = storage_file or _DEFAULT_MEMORY_FILE
        self.auto_persist = auto_persist
        self._lock = threading.Lock()
        # session_id -> deque[MemoryTurn]
        self._sessions: Dict[str, deque] = {}

        # 尝试加载历史持久化记忆
        self._load_from_file()

    def set_window_size(self, new_size: int):
        """动态更新滑动窗口大小，并对超容窗口执行裁剪"""
        with self._lock:
            self.window_size = max(1, int(new_size))
            for s_id, q in self._sessions.items():
                while len(q) > self.window_size:
                    q.popleft()
            if self.auto_persist:
                self._save_to_file()

    def add_turn(
        self,
        session_id: str,
        query: str,
        answer: str,
        stock_code: Optional[str] = None,
        stock_name: Optional[str] = None,
        category: Optional[str] = None,
    ) -> MemoryTurn:
        """
        将本轮用户提问与回答追加至对应会话的滑动窗口中
        若超出窗口容量，最老的一轮自动滑出 (FIFO)
        """
        s_id = (session_id or "default").strip()
        turn = MemoryTurn(
            query=query.strip(),
            answer=answer.strip(),
            stock_code=(stock_code or "").strip() or None,
            stock_name=(stock_name or "").strip() or None,
            category=(category or "").strip() or None,
        )

        with self._lock:
            if s_id not in self._sessions:
                self._sessions[s_id] = deque(maxlen=self.window_size)
            elif self._sessions[s_id].maxlen != self.window_size:
                # 重新构建带 maxlen 的 deque
                existing = list(self._sessions[s_id])
                self._sessions[s_id] = deque(existing, maxlen=self.window_size)

            q = self._sessions[s_id]
            q.append(turn)

            if self.auto_persist:
                self._save_to_file()

        return turn

    def get_turns(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """获取指定会话在滑动窗口中的全部对话轮次（按时间升序）"""
        s_id = (session_id or "default").strip()
        with self._lock:
            if s_id not in self._sessions:
                return []
            return [t.dict() for t in self._sessions[s_id]]

    def get_history_messages(self, session_id: str = "default") -> List[Any]:
        """
        将滑动窗口内的轮次转换为 LangChain 消息对象列表
        [HumanMessage(query_1), AIMessage(answer_1), HumanMessage(query_2)...]
        """
        try:
            from langchain_core.messages import HumanMessage, AIMessage
        except ImportError:
            return []

        turns = self.get_turns(session_id)
        messages = []
        for t in turns:
            messages.append(HumanMessage(content=t["query"]))
            # 缩略截取历史回答以防长篇大论撑爆 Prompt，保留核心逻辑
            ans = t["answer"]
            if len(ans) > 800:
                ans = ans[:750] + "\n...(历史回答已截略)..."
            messages.append(AIMessage(content=ans))
        return messages

    def get_history_text(self, session_id: str = "default", max_chars_per_answer: int = 400) -> str:
        """
        将滑动窗口格式化为引述文本块，便于直接拼接于 Prompt 模板
        """
        turns = self.get_turns(session_id)
        if not turns:
            return ""

        blocks = []
        for idx, t in enumerate(turns, 1):
            ans = t["answer"]
            if len(ans) > max_chars_per_answer:
                ans = ans[:max_chars_per_answer] + "..."
            block = (
                f"【前序交互第 {idx} 轮】\n"
                f"👤 用户：{t['query']}\n"
                f"🤖 分析师回答：{ans}"
            )
            blocks.append(block)

        return "\n\n".join(blocks)

    def get_last_stock_code(self, session_id: str = "default") -> Optional[str]:
        """
        从滑动窗口记忆中倒序查找最近讨论的股票代码（用于多轮上下文指代消歧）
        """
        turns = self.get_turns(session_id)
        for t in reversed(turns):
            if t.get("stock_code"):
                return t["stock_code"]
        return None

    def clear(self, session_id: Optional[str] = None) -> bool:
        """
        清空指定会话的滑动窗口记忆；若 session_id 为 None 则清空所有会话
        """
        with self._lock:
            if session_id:
                s_id = session_id.strip()
                if s_id in self._sessions:
                    self._sessions[s_id].clear()
            else:
                self._sessions.clear()

            if self.auto_persist:
                self._save_to_file()
            return True

    def get_stats(self) -> Dict[str, Any]:
        """获取记忆管理器统计数据"""
        with self._lock:
            active_sessions = len(self._sessions)
            session_counts = {k: len(v) for k, v in self._sessions.items()}
            total_turns = sum(session_counts.values())
            return {
                "window_size": self.window_size,
                "active_sessions_count": active_sessions,
                "total_stored_turns": total_turns,
                "session_turns": session_counts,
                "storage_file": self.storage_file,
            }

    def _save_to_file(self):
        """持久化保存至 JSON 文件"""
        try:
            os.makedirs(os.path.dirname(self.storage_file), exist_ok=True)
            data = {}
            for s_id, turns in self._sessions.items():
                data[s_id] = [t.dict() for t in turns]
            with open(self.storage_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ [Memory] 持久化记忆文件失败: {e}")

    def _load_from_file(self):
        """从 JSON 文件加载持久化记忆"""
        if not os.path.exists(self.storage_file):
            return
        try:
            with open(self.storage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for s_id, turns in data.items():
                    turn_objs = []
                    for item in turns:
                        try:
                            turn_objs.append(MemoryTurn(**item))
                        except Exception:
                            pass
                    # 保留最新的 window_size 轮
                    self._sessions[s_id] = deque(turn_objs[-self.window_size:], maxlen=self.window_size)
        except Exception as e:
            print(f"⚠️ [Memory] 读取持久化记忆文件异常: {e}")


# 全局单例滑动窗口记忆实例（默认窗口 5 轮）
sliding_window_memory = SlidingWindowMemory(window_size=5)
