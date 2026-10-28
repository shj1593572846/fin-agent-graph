"""
定时任务调度引擎 (Scheduler & Dynamic Task Manager)
核心配置三要素：
1. 任务名称 (name)
2. 运行的python文件 (python_script，例如 agent/sync_close_price.py 或 agent/main.py)
3. cron表达式 (cron_expr，例如 10 15 * * 1-5 或 30 9 * * 1-5)

特性：
- 内存级动态热加载调度：新增、编辑、删除或启用/停用定时任务后立刻生效，无需重启服务
- 持久化至 MySQL sys_cron_task 表 + 本地 JSON 容灾
- 到期自动调用 python 异步子进程执行该脚本并记录执行结果
"""

import os
import sys
import json
import time
import datetime
import threading
import subprocess
from typing import Any, Dict, List, Optional, Tuple

_CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

try:
    from db import get_connection, ensure_table_and_unique_key
except ImportError:
    from agent.db import get_connection, ensure_table_and_unique_key

_PROJECT_ROOT = os.path.dirname(_CURRENT_DIR)
_JSON_FALLBACK_PATH = os.path.join(_PROJECT_ROOT, "stock_data", "cron_tasks.json")


# ==============================================================================
# Cron 表达式与时间计算
# ==============================================================================
def _parse_field(field_str: str, min_val: int, max_val: int) -> List[int]:
    """解析单个 cron 字段（支持 *、?、逗号列表、减号区间、斜杠步长）"""
    field_str = str(field_str or "").strip()
    if not field_str or field_str in ("*", "?"):
        return list(range(min_val, max_val + 1))

    # 逗号列表: 1,3,5
    if "," in field_str:
        res = []
        for item in field_str.split(","):
            res.extend(_parse_field(item, min_val, max_val))
        return sorted(list(set([x for x in res if min_val <= x <= max_val])))

    # 斜杠步长: */5 或 10/15
    if "/" in field_str:
        sub_parts = field_str.split("/")
        start_part = sub_parts[0]
        step = int(sub_parts[1]) if len(sub_parts) > 1 and sub_parts[1].isdigit() else 1
        start = min_val if start_part in ("*", "?", "") else (int(start_part) if start_part.isdigit() else min_val)
        return [x for x in range(start, max_val + 1, max(1, step)) if min_val <= x <= max_val]

    # 范围区间: 1-5 或 9-15
    if "-" in field_str:
        sub_parts = field_str.split("-")
        if len(sub_parts) == 2 and sub_parts[0].isdigit() and sub_parts[1].isdigit():
            s = int(sub_parts[0])
            e = int(sub_parts[1])
            if s <= e:
                return [x for x in range(s, e + 1) if min_val <= x <= max_val]
            else:
                return [x for x in range(min_val, max_val + 1)]

    # 单个整数
    if field_str.isdigit():
        val = int(field_str)
        return [max(min_val, min(max_val, val))]

    return list(range(min_val, max_val + 1))


def parse_cron_expression(cron_expr: str) -> Tuple[List[int], List[int], List[int]]:
    """
    解析 Cron 表达式或 HH:MM 格式。
    全面支持：
    1. 标准 5 段 Linux Cron: '分 时 日 月 周' (例如 '53 22 * * *' 或 '10 15 * * 1-5')
    2. 6 段 / 7 段 Spring / Quartz Cron: '秒 分 时 日 月 周 [年]' (例如 '0 53 22 * * ?' 或 '0 10 15 * * ?')
    3. 简易时间格式: '15:10' 或 '22:53'
    返回: (minutes: List[int], hours: List[int], weekdays: List[int]) (weekday: 0=周一, 6=周日)
    """
    cron_expr = str(cron_expr or "").strip()

    # 1. 简易时间格式 '15:10' 或 '22:53'
    if ":" in cron_expr and " " not in cron_expr:
        parts = cron_expr.split(":")
        h = int(parts[0]) if parts[0].isdigit() else 15
        m = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 10
        h = max(0, min(23, h))
        m = max(0, min(59, m))
        return [m], [h], list(range(7))

    parts = cron_expr.split()

    # 2. 6 段或 7 段 Spring / Quartz Cron: 秒 分 时 日 月 周 [年]
    # 例如: '0 53 22 * * ?' -> 秒=0, 分=53, 时=22, 日=*, 月=*, 周=?
    if len(parts) >= 6:
        m_part = parts[1]
        h_part = parts[2]
        w_part = parts[5]

        minutes = _parse_field(m_part, 0, 59)
        hours = _parse_field(h_part, 0, 23)

        if w_part in ("*", "?"):
            weekdays = list(range(7))
        else:
            raw_w = _parse_field(w_part, 1, 7)
            weekdays = sorted(list(set([((w - 1) % 7) for w in raw_w])))
            if not weekdays:
                weekdays = list(range(7))

        return minutes or [0], hours or [0], weekdays or list(range(7))

    # 3. 标准 5 段 Linux Cron: 分 时 日 月 周
    # 例如: '10 15 * * 1-5' 或 '53 22 * * *'
    if len(parts) == 5:
        m_part = parts[0]
        h_part = parts[1]
        w_part = parts[4]

        minutes = _parse_field(m_part, 0, 59)
        hours = _parse_field(h_part, 0, 23)

        if w_part in ("*", "?"):
            weekdays = list(range(7))
        else:
            raw_w = _parse_field(w_part, 0, 7)
            weekdays = sorted(list(set([(w % 7) if w in (0, 7) else ((w - 1) % 7) for w in raw_w])))
            if not weekdays:
                weekdays = list(range(7))

        return minutes or [10], hours or [15], weekdays or list(range(7))

    # 兜底：每天 15:10
    return [10], [15], list(range(7))


def calculate_next_run(
    cron_expr: str,
    from_time: Optional[datetime.datetime] = None,
) -> datetime.datetime:
    """计算下一次触发时间，安全兜底永不抛出越界异常"""
    if from_time is None:
        from_time = datetime.datetime.now()

    try:
        minutes, hours, weekdays = parse_cron_expression(cron_expr)
    except Exception:
        minutes, hours, weekdays = [10], [15], list(range(7))

    # 从今天开始向后遍历最多 30 天
    for day_offset in range(30):
        test_date = (from_time + datetime.timedelta(days=day_offset)).date()
        if test_date.weekday() not in weekdays:
            continue

        for h in sorted(hours):
            h_clamped = max(0, min(23, int(h)))
            for m in sorted(minutes):
                m_clamped = max(0, min(59, int(m)))
                try:
                    target_dt = datetime.datetime(test_date.year, test_date.month, test_date.day, h_clamped, m_clamped, 0)
                    if target_dt > from_time:
                        return target_dt
                except Exception:
                    continue

    # 兜底：次日同一时间
    return from_time + datetime.timedelta(days=1)


# ==============================================================================
# 定时任务调度器类 (单例、热更新、即刻生效)
# ==============================================================================
class TaskScheduler:
    """动态定时任务调度器：增删改查立即生效，无需重启服务"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(TaskScheduler, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.tasks: Dict[int, Dict[str, Any]] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # 初始化数据库表并加载既有任务
        self._init_db_and_load_tasks()

    def _init_db_and_load_tasks(self):
        """初始化数据表结构并加载既有配置"""
        create_sql = """
        CREATE TABLE IF NOT EXISTS `sys_cron_task` (
            `id` INT AUTO_INCREMENT PRIMARY KEY COMMENT '任务ID',
            `name` VARCHAR(128) NOT NULL COMMENT '任务名称',
            `python_script` VARCHAR(255) NOT NULL COMMENT '运行的python文件',
            `cron_expr` VARCHAR(64) NOT NULL DEFAULT '10 15 * * 1-5' COMMENT 'cron表达式',
            `enabled` TINYINT(1) DEFAULT 1 COMMENT '是否启用(1:启用, 0:停用)',
            `last_run_time` DATETIME DEFAULT NULL COMMENT '上次执行时间',
            `last_status` VARCHAR(32) DEFAULT NULL COMMENT '上次状态: success / error / running',
            `last_result` TEXT DEFAULT NULL COMMENT '上次执行结果摘要',
            `next_run_time` DATETIME DEFAULT NULL COMMENT '下次触发时间',
            `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
            `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统定时任务配置表';
        """
        conn = None
        db_loaded = False
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute(create_sql)
                # 兼容旧表升级：检查是否存在 python_script 列，若无则自动新增
                try:
                    cur.execute("SHOW COLUMNS FROM `sys_cron_task` LIKE 'python_script';")
                    if not cur.fetchone():
                        cur.execute("ALTER TABLE `sys_cron_task` ADD COLUMN `python_script` VARCHAR(255) NOT NULL DEFAULT 'agent/sync_close_price.py' AFTER `name`;")
                except Exception:
                    pass

                # 查询表中既有任务
                cur.execute("SELECT `id`, `name`, `python_script`, `cron_expr`, `enabled`, `last_run_time`, `last_status`, `last_result`, `next_run_time` FROM `sys_cron_task` ORDER BY `id` ASC;")
                rows = cur.fetchall()

                # 若表为空，插入默认预设任务
                if not rows:
                    seed_sql = """
                    INSERT INTO `sys_cron_task` 
                        (`name`, `python_script`, `cron_expr`, `enabled`, `last_result`)
                    VALUES 
                        (%s, %s, %s, %s, %s),
                        (%s, %s, %s, %s, %s),
                        (%s, %s, %s, %s, %s);
                    """
                    cur.execute(seed_sql, (
                        "A股收盘价自动同步", "agent/sync_close_price.py", "10 15 * * 1-5", 1, "开市日每天15:10自动执行 agent/sync_close_price.py 更新当日收盘价",
                        "早盘全市场智能选股", "agent/main.py", "30 9 * * 1-5", 0, "开市日每天09:30自动执行 agent/main.py 选股策略流水线",
                        "A股次日量化跌破均线卖出监控", "agent/monitor_break_price.py", "*/1 9-14 * * 1-5", 1, "开市日盘中每分钟动态监控次日推荐个股分时，跌破均线自动执行卖出研判并回写记录",
                    ))
                    cur.execute("SELECT `id`, `name`, `python_script`, `cron_expr`, `enabled`, `last_run_time`, `last_status`, `last_result`, `next_run_time` FROM `sys_cron_task` ORDER BY `id` ASC;")
                    rows = cur.fetchall()
                else:
                    # 检查既有表中是否缺少次日量化监控任务，若无则平滑增补
                    cur.execute("SELECT COUNT(*) FROM `sys_cron_task` WHERE `python_script` = 'agent/monitor_break_price.py';")
                    if cur.fetchone()[0] == 0:
                        cur.execute("""
                        INSERT INTO `sys_cron_task` 
                            (`name`, `python_script`, `cron_expr`, `enabled`, `last_status`, `last_result`)
                        VALUES 
                            ('A股次日量化跌破均线卖出监控', 'agent/monitor_break_price.py', '*/1 9-14 * * 1-5', 1, 'idle', '开市日盘中每分钟动态监控次日推荐个股分时，跌破均线自动执行卖出研判并回写记录');
                        """)
                        cur.execute("SELECT `id`, `name`, `python_script`, `cron_expr`, `enabled`, `last_run_time`, `last_status`, `last_result`, `next_run_time` FROM `sys_cron_task` ORDER BY `id` ASC;")
                        rows = cur.fetchall()

                    # 检查既有表中是否缺少 Node 1+2 每日初筛定时任务，若无则平滑增补
                    cur.execute("SELECT COUNT(*) FROM `sys_cron_task` WHERE `python_script` = 'agent/run_nodes_1_2.py';")
                    if cur.fetchone()[0] == 0:
                        cur.execute("""
                        INSERT INTO `sys_cron_task` 
                            (`name`, `python_script`, `cron_expr`, `enabled`, `last_status`, `last_result`)
                        VALUES 
                            ('每日日K下载与视觉选股初筛 (Node 1+2)', 'agent/run_nodes_1_2.py', '30 1 * * *', 1, 'idle', '每天凌晨 01:30 自动调用执行 Node 1 (下载日线并生成全量K线图) 和 Node 2 (视觉多模态战法初筛过滤)');
                        """)
                        cur.execute("SELECT `id`, `name`, `python_script`, `cron_expr`, `enabled`, `last_run_time`, `last_status`, `last_result`, `next_run_time` FROM `sys_cron_task` ORDER BY `id` ASC;")
                        rows = cur.fetchall()

                for r in rows:
                    t_id = int(r[0])
                    task = {
                        "id": t_id,
                        "name": str(r[1]),
                        "python_script": str(r[2]),
                        "cron_expr": str(r[3]),
                        "enabled": bool(r[4]),
                        "last_run_time": str(r[5]) if r[5] else None,
                        "last_status": str(r[6]) if r[6] else "idle",
                        "last_result": str(r[7]) if r[7] else "就绪中",
                        "next_run_time": str(r[8]) if r[8] else None,
                    }
                    if task["enabled"]:
                        nxt = calculate_next_run(task["cron_expr"])
                        task["next_run_time"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        task["next_run_time"] = None

                    self.tasks[t_id] = task
                db_loaded = True
        except Exception as e:
            print(f"⚠️ [定时任务] 连接 MySQL 失败，启用本地 JSON 容灾加载: {e}")

        if not db_loaded:
            self._load_from_json()

    def _load_from_json(self):
        """从本地 JSON 文件读取任务配置"""
        if os.path.exists(_JSON_FALLBACK_PATH):
            try:
                with open(_JSON_FALLBACK_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for t in data:
                        t_id = int(t["id"])
                        if t.get("enabled"):
                            nxt = calculate_next_run(t.get("cron_expr", "10 15 * * 1-5"))
                            t["next_run_time"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                        else:
                            t["next_run_time"] = None
                        self.tasks[t_id] = t
                    return
            except Exception:
                pass

        # 默认任务
        t1 = {
            "id": 1,
            "name": "A股收盘价自动同步",
            "python_script": "agent/sync_close_price.py",
            "cron_expr": "10 15 * * 1-5",
            "enabled": True,
            "last_run_time": None,
            "last_status": "idle",
            "last_result": "开市日每天15:10自动执行 agent/sync_close_price.py 更新当日收盘价",
            "next_run_time": calculate_next_run("10 15 * * 1-5").strftime("%Y-%m-%d %H:%M:%S"),
        }
        t2 = {
            "id": 2,
            "name": "早盘全市场智能选股",
            "python_script": "agent/main.py",
            "cron_expr": "30 9 * * 1-5",
            "enabled": False,
            "last_run_time": None,
            "last_status": "idle",
            "last_result": "开市日每天09:30自动执行 agent/main.py 选股策略流水线",
            "next_run_time": calculate_next_run("30 9 * * 1-5").strftime("%Y-%m-%d %H:%M:%S"),
        }
        t3 = {
            "id": 3,
            "name": "A股次日量化跌破均线卖出监控",
            "python_script": "agent/monitor_break_price.py",
            "cron_expr": "*/1 9-14 * * 1-5",
            "enabled": True,
            "last_run_time": None,
            "last_status": "idle",
            "last_result": "开市日盘中每分钟动态监控次日推荐个股分时，跌破均线自动执行卖出研判并回写记录",
            "next_run_time": calculate_next_run("*/1 9-14 * * 1-5").strftime("%Y-%m-%d %H:%M:%S"),
        }
        self.tasks[1] = t1
        self.tasks[2] = t2
        self.tasks[3] = t3
        self._save_to_json()

    def _save_to_json(self):
        """将任务保存至本地 JSON 文件"""
        os.makedirs(os.path.dirname(_JSON_FALLBACK_PATH), exist_ok=True)
        try:
            with open(_JSON_FALLBACK_PATH, "w", encoding="utf-8") as f:
                json.dump(list(self.tasks.values()), f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _sync_task_to_db(self, task: Dict[str, Any]):
        """将单个任务更新同步到数据库"""
        conn = None
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                update_sql = """
                INSERT INTO `sys_cron_task` 
                    (`id`, `name`, `python_script`, `cron_expr`, `enabled`, `last_run_time`, `last_status`, `last_result`, `next_run_time`)
                VALUES 
                    (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                    `name` = VALUES(`name`),
                    `python_script` = VALUES(`python_script`),
                    `cron_expr` = VALUES(`cron_expr`),
                    `enabled` = VALUES(`enabled`),
                    `last_run_time` = VALUES(`last_run_time`),
                    `last_status` = VALUES(`last_status`),
                    `last_result` = VALUES(`last_result`),
                    `next_run_time` = VALUES(`next_run_time`);
                """
                cur.execute(update_sql, (
                    task["id"],
                    task["name"],
                    task["python_script"],
                    task["cron_expr"],
                    1 if task.get("enabled", True) else 0,
                    task.get("last_run_time"),
                    task.get("last_status"),
                    task.get("last_result"),
                    task.get("next_run_time"),
                ))
        except Exception:
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        self._save_to_json()

    # ==========================================================================
    # 对外 CRUD 接口 (即刻热生效)
    # ==========================================================================
    def get_all_tasks(self) -> List[Dict[str, Any]]:
        """获取所有定时任务列表"""
        now = datetime.datetime.now()
        for t in self.tasks.values():
            if t.get("enabled"):
                nxt = calculate_next_run(t["cron_expr"], now)
                t["next_run_time"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
            else:
                t["next_run_time"] = None
        return list(self.tasks.values())

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取单条定时任务"""
        return self.tasks.get(task_id)

    def add_task(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """新增定时任务 -> 写入存储并立刻热装载生效"""
        new_id = max(self.tasks.keys(), default=0) + 1
        name = str(data.get("name") or f"定时任务 #{new_id}").strip()
        python_script = str(data.get("python_script") or "agent/sync_close_price.py").strip()
        cron_expr = str(data.get("cron_expr") or "10 15 * * 1-5").strip()
        enabled = bool(data.get("enabled", True))

        nxt = calculate_next_run(cron_expr) if enabled else None

        task = {
            "id": new_id,
            "name": name,
            "python_script": python_script,
            "cron_expr": cron_expr,
            "enabled": enabled,
            "last_run_time": None,
            "last_status": "idle",
            "last_result": f"已装载，将执行 {python_script}",
            "next_run_time": nxt.strftime("%Y-%m-%d %H:%M:%S") if nxt else None,
        }
        self.tasks[new_id] = task
        self._sync_task_to_db(task)
        print(f"⏰ [定时任务热加载] 新增任务【{name}】(ID: {new_id}, 脚本: {python_script}, Cron: {cron_expr}) 已实时生效，下次运行: {task['next_run_time']}")
        return task

    def update_task(self, task_id: int, data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """修改定时任务 -> 更新配置并立刻热重载生效"""
        if task_id not in self.tasks:
            return None
        task = self.tasks[task_id]

        if "name" in data:
            task["name"] = str(data["name"]).strip()
        if "python_script" in data:
            task["python_script"] = str(data["python_script"]).strip()
        if "cron_expr" in data:
            task["cron_expr"] = str(data["cron_expr"]).strip()
        if "enabled" in data:
            task["enabled"] = bool(data["enabled"])

        if task["enabled"]:
            nxt = calculate_next_run(task["cron_expr"])
            task["next_run_time"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            task["next_run_time"] = None

        self._sync_task_to_db(task)
        print(f"⏰ [定时任务热重载] 修改任务【{task['name']}】(ID: {task_id}, 脚本: {task['python_script']}, Cron: {task['cron_expr']}) 已实时生效，下次运行: {task['next_run_time']}")
        return task

    def delete_task(self, task_id: int) -> bool:
        """删除定时任务 -> 从调度池卸载并立刻生效"""
        if task_id not in self.tasks:
            return False
        task = self.tasks.pop(task_id)
        conn = None
        try:
            conn = get_connection()
            with conn.cursor() as cur:
                cur.execute("DELETE FROM `sys_cron_task` WHERE `id` = %s;", (task_id,))
        except Exception:
            pass
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
        self._save_to_json()
        print(f"⏰ [定时任务卸载] 任务【{task['name']}】(ID: {task_id}) 已成功卸载移除。")
        return True

    def toggle_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """切换任务启用/禁用状态 -> 立刻生效"""
        if task_id not in self.tasks:
            return None
        task = self.tasks[task_id]
        task["enabled"] = not task.get("enabled", True)
        if task["enabled"]:
            nxt = calculate_next_run(task["cron_expr"])
            task["next_run_time"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            task["next_run_time"] = None
        self._sync_task_to_db(task)
        print(f"⏰ [定时任务状态切换] 任务【{task['name']}】已切换为: {'✅ 启用' if task['enabled'] else '⏸️ 停用'}")
        return task

    # ==========================================================================
    # 任务执行器：直接运行配置的 Python 文件
    # ==========================================================================
    def execute_task_now(self, task_id: int) -> Dict[str, Any]:
        """手动或定时触发执行配置的 Python 脚本"""
        if task_id not in self.tasks:
            return {"success": False, "error": f"任务 ID {task_id} 不存在"}
        task = self.tasks[task_id]
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        task["last_run_time"] = now_str
        task["last_status"] = "running"
        task["last_result"] = f"正在后台执行脚本: {task['python_script']} ..."
        self._sync_task_to_db(task)

        script_rel = str(task.get("python_script") or "").strip()
        if not script_rel:
            task["last_status"] = "error"
            task["last_result"] = "未配置运行的 python 文件路径"
            self._sync_task_to_db(task)
            return {"success": False, "error": "未配置运行的 python 文件路径"}

        # 解析完整脚本路径
        if os.path.isabs(script_rel):
            script_full = script_rel
        else:
            script_full = os.path.normpath(os.path.join(_PROJECT_ROOT, script_rel))

        if not os.path.exists(script_full):
            err_msg = f"指定的 Python 脚本不存在: {script_full}"
            task["last_status"] = "error"
            task["last_result"] = err_msg
            self._sync_task_to_db(task)
            return {"success": False, "error": err_msg}

        def _run_script_worker():
            try:
                cmd = [sys.executable, "-u", script_full]
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["PYTHONUNBUFFERED"] = "1"
                run_kwargs = {}
                if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                    run_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
                proc = subprocess.run(
                    cmd,
                    cwd=_PROJECT_ROOT,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                    timeout=1800,
                    **run_kwargs,
                )
                stdout_str = (proc.stdout or "").strip()
                stderr_str = (proc.stderr or "").strip()
                output = stdout_str or stderr_str
                # 截取输出摘要
                lines = [l.strip() for l in output.split("\n") if l.strip()]
                summary = " | ".join(lines[-3:]) if lines else "执行完成"
                if len(summary) > 300:
                    summary = summary[:300] + "..."

                if proc.returncode == 0:
                    task["last_status"] = "success"
                    task["last_result"] = f"执行成功: {summary}"
                else:
                    task["last_status"] = "error"
                    task["last_result"] = f"执行异常 (退出码 {proc.returncode}): {summary}"
            except subprocess.TimeoutExpired:
                task["last_status"] = "error"
                task["last_result"] = "执行超时 (超过 600 秒)"
            except Exception as ex:
                task["last_status"] = "error"
                task["last_result"] = f"启动异常: {str(ex)}"
            finally:
                self._sync_task_to_db(task)

        # 异步线程拉起子进程执行，不阻塞主服务
        threading.Thread(target=_run_script_worker, daemon=True).start()
        return {
            "success": True,
            "message": f"任务【{task['name']}】已成功在后台触发运行: python {script_rel}",
            "task": task,
        }

    # ==========================================================================
    # 后台常驻监听线程 (每 5 秒心跳检测是否有到期任务)
    # ==========================================================================
    def start(self):
        """启动后台调度监听线程"""
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        def _loop():
            print("🚀 [定时任务调度器] 后台守护监听引擎已启动，常驻运行中...")
            last_checked_minute = ""
            while not self._stop_event.is_set():
                try:
                    now = datetime.datetime.now()
                    current_minute_str = now.strftime("%Y-%m-%d %H:%M")

                    if current_minute_str != last_checked_minute:
                        last_checked_minute = current_minute_str

                        for t_id, task in list(self.tasks.items()):
                            if not task.get("enabled"):
                                continue

                            minutes, hours, weekdays = parse_cron_expression(task.get("cron_expr", "10 15 * * 1-5"))

                            # 星期检查
                            if now.weekday() not in weekdays:
                                continue

                            # 时、分匹配检查
                            if now.hour in hours and now.minute in minutes:
                                print(f"\n⏰ [定时任务触发] 触发执行任务 #{t_id}: 【{task.get('name')}】 | 脚本: {task.get('python_script')} ...")
                                self.execute_task_now(t_id)

                                # 更新下次运行时间
                                nxt = calculate_next_run(task["cron_expr"], now + datetime.timedelta(minutes=1))
                                task["next_run_time"] = nxt.strftime("%Y-%m-%d %H:%M:%S")
                                self._sync_task_to_db(task)

                except Exception as e:
                    print(f"⚠️ [定时任务调度器异常]: {e}")

                time.sleep(5)

        self._thread = threading.Thread(target=_loop, daemon=True, name="CronTaskSchedulerThread")
        self._thread.start()

    def stop(self):
        """停止后台监听线程"""
        self._running = False
        self._stop_event.set()


# 全局调度器单例
scheduler_instance = TaskScheduler()
