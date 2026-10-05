"""矿区台账业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

import re
from typing import Any

from app.store import store

MODULE = "minearea"
REQUIRED_FIELDS = ["矿区编号", "矿区名称", "开采矿种"]
EXTRA_FIELDS = ["核定产能", "开采方式", "服务年限", "安全等级", "矿区状态"]
STATUS_ORDER = ["正常生产", "停产整顿", "检修中", "已闭坑"]
ACTION_RULES = {"停产整顿": "停产整顿", "恢复生产": "正常生产", "闭坑登记": "已闭坑"}
NEGATIVE_ACTIONS = []

# 矿区编号格式：MINE- 加四位数字，批量建档按这个口径校验，不符合的整行退回
CODE_PATTERN = re.compile(r"^MINE-\d{4}$")

# 安全等级按开采矿种补全：存量矿区与新建矿区共用同一套口径
SAFETY_LEVEL_BY_MINERAL = {"煤矿": "一级", "金属矿": "二级", "非金属矿": "三级"}
DEFAULT_SAFETY_LEVEL = "三级"
# 存量矿区沿用原有的开采方式口径，缺省时按井工开采回填
LEGACY_MINING_METHOD = "井工开采"


class MineareaService:
    def __init__(self) -> None:
        # 服务启动时先回填存量记录，保证既有矿区读到的口径一致
        self.backfill_existing()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("矿区编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summary(self) -> dict[str, Any]:
        """台账概览：在册矿区数与状态分布，和入井名单读的是同一份数据。"""
        rows = store.rows(MODULE)
        by_status = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            name = str(row.get("status") or "")
            by_status[name] = by_status.get(name, 0) + 1
        return {
            "在册矿区数": len(rows),
            "待办数": sum(1 for row in rows if row.get("pending")),
            "状态分布": by_status,
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": self._next_id(rows)}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        self._enrich(entry)
        rows.append(entry)
        return entry, []

    def batch_create(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """批量建档：按矿区编号判重，缺开采矿种或编号格式不对的行整行退回。

        重复编号只留最早进来的那条（台账里已有的优先于本批，本批内先提交的优先）；
        每行都在回执里给出结果，入库的矿区同步生成入井名单待办。
        """
        from app.services.shift import ShiftService

        self.backfill_existing()
        ledger = store.rows(MODULE)
        seen = {str(row.get("矿区编号") or "").strip() for row in ledger}
        results: list[dict[str, Any]] = []
        created: list[dict[str, Any]] = []
        duplicated = 0
        rejected = 0
        for index, raw in enumerate(rows, start=1):
            values = raw if isinstance(raw, dict) else {}
            code = str(values.get("矿区编号") or "").strip()
            name = str(values.get("矿区名称") or "").strip()
            mineral = str(values.get("开采矿种") or "").strip()
            line = {"line": index, "code": code, "name": name}
            if not CODE_PATTERN.match(code):
                rejected += 1
                results.append({**line, "result": "整行退回", "message": "矿区编号缺失或格式不对，应为 MINE-0000 形式"})
                continue
            if not mineral:
                rejected += 1
                results.append({**line, "result": "整行退回", "message": "缺少开采矿种"})
                continue
            if code in seen:
                duplicated += 1
                results.append({**line, "result": "重复跳过", "message": "矿区编号已登记，只保留最早一条"})
                continue
            entry = {
                "id": self._next_id(ledger),
                "矿区编号": code,
                "矿区名称": name,
                "开采矿种": mineral,
                "核定产能": str(values.get("核定产能") or "").strip(),
                "服务年限": str(values.get("服务年限") or "").strip(),
                "矿区状态": str(values.get("矿区状态") or "").strip() or STATUS_ORDER[0],
                "status": STATUS_ORDER[0],
                "pending": True,
                "abnormal": False,
            }
            self._enrich(entry)
            ledger.append(entry)
            seen.add(code)
            created.append(entry)
            results.append({**line, "result": "已入库", "message": "矿区已登记"})
        todos = ShiftService().sync_mine_todos(created)
        message = (
            f"共提交 {len(rows)} 行：入库 {len(created)} 条、重复 {duplicated} 条、退回 {rejected} 条；"
            f"入井名单已同步 {len(todos)} 条待办"
        )
        return {
            "total": len(rows),
            "created": len(created),
            "duplicated": duplicated,
            "rejected": rejected,
            "synced_todos": len(todos),
            "results": results,
            "message": message,
        }

    def backfill_existing(self) -> int:
        """回填存量记录：安全等级按开采矿种补全，开采方式沿用原有口径补齐。"""
        touched = 0
        for row in store.rows(MODULE):
            if self._enrich(row):
                touched += 1
        return touched

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"矿区 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于矿区台账可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"矿区已{action}"

    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1

    @staticmethod
    def _enrich(entry: dict[str, Any]) -> bool:
        """补齐单条记录的派生字段，返回是否有改动；已有值一律不动。"""
        changed = False
        if not str(entry.get("安全等级") or "").strip():
            mineral = str(entry.get("开采矿种") or "").strip()
            entry["安全等级"] = SAFETY_LEVEL_BY_MINERAL.get(mineral, DEFAULT_SAFETY_LEVEL)
            changed = True
        if not str(entry.get("开采方式") or "").strip():
            entry["开采方式"] = LEGACY_MINING_METHOD
            changed = True
        return changed
