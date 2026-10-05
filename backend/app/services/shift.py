"""入井管理业务规则：状态流转、字段校验与筛选口径都收在这里。

入井名单的待办（待编排）由矿区台账批量建档自动同步：每成功登记一条新矿区，
就在这里预留一条「待编排」的入井名额；在册人数按这些台账同步名额统计，
矿区台账页通过 roster_summary 读到的数字与本页完全一致。
"""
from __future__ import annotations

from typing import Any

from app.store import store

MODULE = "shift"
REQUIRED_FIELDS = ["记录编号", "入井人员", "所属班组"]
# 台账同步过来的新矿区先进入「待编排」待办，排班后再走登记入井
STATUS_ORDER = ["待编排", "入井中", "已升井", "超时未升", "已联系"]
ACTION_RULES = {"登记入井": "入井中", "登记升井": "已升井", "超时联系": "已联系"}
NEGATIVE_ACTIONS = []

# 台账同步待办的标记字段，方便和真实排班记录区分、保持两处口径一致
SYNC_SOURCE = "minearea"
SYNC_STATUS = "待编排"


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

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": self._next_id(rows)}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[1]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def sync_minearea_todo(self, minearea_code: str, minearea_name: str) -> dict[str, Any]:
        """矿区建档成功后同步一条入井名单待办：先把新矿区的入井名额挂起来待排班。"""
        rows = store.rows(MODULE)
        seq = sum(1 for row in rows if row.get("同步来源") == SYNC_SOURCE) + 1
        entry = {
            "id": self._next_id(rows),
            "记录编号": f"ROSTER-{seq:04d}",
            "入井人员": f"待安排（{minearea_name}）",
            "所属班组": "待编排",
            "入井时间": "",
            "升井时间": "",
            "携带设备": "",
            "出勤区域": minearea_name,
            "入井状态": SYNC_STATUS,
            "矿区编号": minearea_code,
            "同步来源": SYNC_SOURCE,
            "status": SYNC_STATUS,
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry

    def roster_summary(self) -> dict[str, int]:
        """入井名单口径：待办数与在册人数都从同一张 shift 表实时派生。

        - 待办清单：所有由矿区台账同步、尚未编排排班的入井名额（待编排）。
        - 在册人数：台账同步名额的总量，代表这些新矿区已挂入入井名单的在册规模。
        """
        rows = store.rows(MODULE)
        synced = [row for row in rows if row.get("同步来源") == SYNC_SOURCE]
        pending = [row for row in synced if row.get("status") == SYNC_STATUS]
        status_counts = {status: sum(1 for row in rows if row.get("status") == status) for status in STATUS_ORDER}
        return {
            "roster_total": len(synced),
            "roster_pending": len(pending),
            "roster_headcount": len(synced),
            "status_counts": status_counts,
        }

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
        if "入井状态" in entry:
            entry["入井状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"入井记录已{action}"

    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1
