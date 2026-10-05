"""入井管理业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "shift"
REQUIRED_FIELDS = ["记录编号", "入井人员", "所属班组"]
STATUS_ORDER = ["入井中", "已升井", "超时未升", "已联系"]
ACTION_RULES = {"登记入井": "入井中", "登记升井": "已升井", "超时联系": "已联系"}
NEGATIVE_ACTIONS = []


class ShiftService:
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
            rows = [row for row in rows if keyword in str(row.get("记录编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def summary(self) -> dict[str, Any]:
        """入井名单概览：在册人数、待办数与待办清单，和矿区台账读的是同一份数据。"""
        rows = store.rows(MODULE)
        by_status = {status: 0 for status in STATUS_ORDER}
        for row in rows:
            name = str(row.get("status") or "")
            by_status[name] = by_status.get(name, 0) + 1
        todos = [row for row in rows if row.get("pending")]
        return {
            "在册人数": len(rows),
            "待办数": len(todos),
            "状态分布": by_status,
            "待办清单": [
                {
                    "id": row.get("id"),
                    "记录编号": row.get("记录编号"),
                    "出勤区域": row.get("出勤区域"),
                    "来源矿区": row.get("来源矿区", ""),
                    "入井状态": row.get("status"),
                }
                for row in todos
            ],
        }

    def sync_mine_todos(self, mines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把矿区建档结果同步成入井名单待办：一个矿区一条，编号与矿区编号对应。

        已存在的记录编号不再重复生成，重复执行不会产生重复待办。
        """
        rows = store.rows(MODULE)
        existing = {str(row.get("记录编号") or "") for row in rows}
        todos: list[dict[str, Any]] = []
        for mine in mines:
            code = str(mine.get("矿区编号") or "").strip()
            record_code = f"SHIF-{code.removeprefix('MINE-')}" if code else ""
            if not record_code or record_code in existing:
                continue
            todo = {
                "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
                "记录编号": record_code,
                "入井人员": "待登记",
                "所属班组": "待登记",
                "入井时间": "",
                "升井时间": "",
                "携带设备": "",
                "出勤区域": str(mine.get("矿区名称") or ""),
                "入井状态": STATUS_ORDER[0],
                "来源矿区": code,
                "status": STATUS_ORDER[0],
                "pending": True,
                "abnormal": False,
            }
            rows.append(todo)
            existing.add(record_code)
            todos.append(todo)
        return todos

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"入井记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于入井管理可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"入井记录已{action}"
