"""矿区台账接口：维护矿区，覆盖批量建档、停产整顿、恢复生产、闭坑登记等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import (
    ActionResult,
    EntryPayload,
    MineareaBatchPayload,
    MineareaBatchResult,
    PageResult,
)
from app.services.minearea import MineareaService

router = APIRouter(prefix="/api/minearea", tags=["矿区台账"])

service = MineareaService()

LIST_FIELDS = ["矿区编号", "矿区名称", "开采矿种", "核定产能", "开采方式", "服务年限", "安全等级", "矿区状态"]
STATUSES = ["正常生产", "停产整顿", "检修中", "已闭坑"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按矿区编号检索"),
    status: str | None = Query(default=None, description="正常生产、停产整顿、检修中、已闭坑"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按矿区编号与状态过滤矿区台账列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


# 注意：固定路径要声明在 /{entry_id} 之前，否则会被当成矿区 id 解析
@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出矿区台账清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "minearea", "total": total, "items": items}


@router.post("/backfill-safety", response_model=ActionResult)
def backfill_safety() -> ActionResult:
    """存量矿区补全：沿用原有开采方式口径回填缺失的安全等级（幂等，可重复执行）。"""
    count = service.backfill_stock()
    return ActionResult(ok=True, message=f"已按开采方式口径回填 {count} 条存量矿区的安全等级")


@router.post("/batch", response_model=MineareaBatchResult)
def batch_create(payload: MineareaBatchPayload) -> MineareaBatchResult:
    """批量建档：从表格文本一次提交一批矿区。

    按矿区编号判重，重复登记的编号只保留最早进来的一条；编号格式不对或缺
    开采矿种等必填项的行整行退回，其余照常入库，结果逐条回执。建档成功的
    矿区会同步到入井名单待办；存量矿区按开采方式口径回填安全等级，已存在
    矿区按开采矿种补全安全等级。
    """
    raw_rows = [item.model_dump(exclude_none=True) for item in payload.rows]
    summary = service.batch_create(
        content=payload.content,
        filename=payload.filename,
        raw_rows=raw_rows,
    )
    return MineareaBatchResult(**summary)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条矿区明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"矿区 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条矿区，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="矿区已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条矿区执行停产整顿、恢复生产、闭坑登记；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
