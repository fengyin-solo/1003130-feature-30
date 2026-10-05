"""矿区台账业务规则：状态流转、字段校验、批量建档判重与安全等级口径都收在这里。"""
from __future__ import annotations

import csv
import io
import re
from typing import Any

from app.store import store

MODULE = "minearea"
REQUIRED_FIELDS = ["矿区编号", "矿区名称", "开采矿种"]
# 批量建档按列顺序解析时使用的完整列序，与前端表头一致
ALL_FIELDS = ["矿区编号", "矿区名称", "开采矿种", "核定产能", "开采方式", "服务年限", "安全等级", "矿区状态"]
STATUS_ORDER = ["正常生产", "停产整顿", "检修中", "已闭坑"]
ACTION_RULES = {"停产整顿": "停产整顿", "恢复生产": "正常生产", "闭坑登记": "已闭坑"}
NEGATIVE_ACTIONS = []

# 矿区编号：字母段（2 位以上）+ 连字符 + 4 位数字，例如 MINE-0004、MY-0123
CODE_PATTERN = re.compile(r"^[A-Z]{2,}-\d{4}$")

# 新建矿区：按开采矿种派生安全等级
MINERAL_SAFETY_LEVEL = {
    "煤矿": "一级",
    "煤与瓦斯突出矿": "一级",
    "高瓦斯矿": "一级",
    "铁矿": "二级",
    "铜矿": "二级",
    "金矿": "二级",
    "金属矿": "二级",
    "石灰岩": "三级",
    "非金属矿": "三级",
    "建筑用砂": "三级",
}

# 存量矿区：沿用原有开采方式口径，按开采方式回填安全等级
METHOD_SAFETY_LEVEL = {
    "地下开采": "一级",
    "井工开采": "一级",
    "联合开采": "二级",
    "露天开采": "三级",
}


def safety_level_by_mineral(mineral: str) -> str | None:
    """按开采矿种给安全等级；矿种不在口径表里时返回空串，由调用方决定是否提示。"""
    return MINERAL_SAFETY_LEVEL.get((mineral or "").strip())


def safety_level_by_method(method: str) -> str | None:
    """按开采方式给安全等级（存量记录回填口径）。"""
    return METHOD_SAFETY_LEVEL.get((method or "").strip())


def derive_stock_safety_level(row: dict[str, Any]) -> str:
    """存量记录回填口径：严格沿用原有开采方式，映射表之外的方式不动、等人工核定。

    按开采矿种补全是另一条口径，用于批量建档时遇到的已存在矿区，见
    safety_level_by_mineral 与 batch_create。
    """
    return safety_level_by_method(str(row.get("开采方式") or "")) or ""


class MineareaService:
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

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": self._next_id(rows)}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ALL_FIELDS[3:]:
            entry[field] = str(values.get(field) or "").strip()
        entry["status"] = STATUS_ORDER[0]
        if not entry.get("矿区状态"):
            entry["矿区状态"] = STATUS_ORDER[0]
        # 新建矿区安全等级按开采矿种补全（手工录入与批量建档同一口径）
        if not entry.get("安全等级"):
            entry["安全等级"] = safety_level_by_mineral(entry["开采矿种"]) or ""
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        self._sync_shift(entry)
        return entry, []

    def backfill_stock(self) -> int:
        """按开采方式口径回填存量矿区缺失的安全等级，返回回填条数。幂等。"""
        count = 0
        for row in store.rows(MODULE):
            if str(row.get("安全等级") or "").strip():
                continue
            level = derive_stock_safety_level(row)
            if level:
                row["安全等级"] = level
                count += 1
        return count

    def batch_create(
        self,
        *,
        content: str | None = None,
        filename: str | None = None,
        raw_rows: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """批量建档主流程：解析 → 存量回填 → 逐行校验判重 → 入库 → 同步入井名单。"""
        # 先把存量矿区缺失的安全等级按原开采方式口径补齐
        stock_backfilled = self.backfill_stock()

        parsed, parse_error = self._parse_rows(content=content, filename=filename, raw_rows=raw_rows)
        receipts: list[dict[str, Any]] = []
        existing_completed = 0
        shift_synced = 0

        if parse_error:
            return self._batch_summary(
                receipts=receipts,
                stock_backfilled=stock_backfilled,
                existing_completed=existing_completed,
                shift_synced=shift_synced,
                message=parse_error,
                ok=False,
            )

        rows = store.rows(MODULE)
        existing_codes = {str(row.get("矿区编号") or "").strip().upper(): row for row in rows}
        accepted_codes: set[str] = set()
        accepted_names = {str(row.get("矿区名称") or "").strip() for row in rows}

        for index, values in enumerate(parsed, start=1):
            line_no = int(values.get("_line", index))
            code = str(values.get("矿区编号") or "").strip()
            name = str(values.get("矿区名称") or "").strip()
            mineral = str(values.get("开采矿种") or "").strip()
            code_key = code.upper()

            # 1) 编号格式不对（小写、位数不符等一律不做大小写容错）：整行退回
            if not CODE_PATTERN.match(code):
                receipts.append(self._receipt(line_no, code, name, "rejected",
                                              f"矿区编号「{code or '空'}」格式不对，应为 MINE-0004 式编号（大写字母段-4位数字）"))
                continue
            # 2) 缺开采矿种（编号/名称同为必填，缺了也整行退回）
            missing = [label for field, label in (("矿区编号", "矿区编号"), ("矿区名称", "矿区名称"), ("开采矿种", "开采矿种"))
                       if not str(values.get(field) or "").strip()]
            if missing:
                receipts.append(self._receipt(line_no, code, name, "rejected",
                                              f"缺少必填字段：{'、'.join(missing)}，整行退回"))
                continue
            # 3) 按编号判重：台账已有或本批已收，只算最早进来的那条
            if code_key in existing_codes:
                warnings: list[str] = []
                target = existing_codes[code_key]
                if not str(target.get("安全等级") or "").strip():
                    level = safety_level_by_mineral(mineral)
                    if level:
                        target["安全等级"] = level
                        existing_completed += 1
                        warnings.append(f"已按开采矿种「{mineral}」为既有矿区补全安全等级：{level}")
                dup_name = str(target.get("矿区名称") or "").strip()
                receipts.append(self._receipt(
                    line_no, code, name, "duplicated",
                    f"编号重复：台账中已存在 {code}（{dup_name}），按编号判重只保留最早登记的一条，本行不入库",
                    entry=dict(target),
                    warnings=warnings,
                ))
                continue
            if code_key in accepted_codes:
                receipts.append(self._receipt(line_no, code, name, "duplicated",
                                              f"编号重复：{code} 在本批次前面已提交，重复登记的编号只算一次，只留最早进来的那条"))
                continue

            # 4) 通过校验，正常入库
            entry = {"id": self._next_id(rows)}
            entry["矿区编号"] = code_key
            entry["矿区名称"] = name
            entry["开采矿种"] = mineral
            for field in ALL_FIELDS[3:]:
                entry[field] = str(values.get(field) or "").strip()
            # 安全等级：文件里没给就按开采矿种补全
            warnings = []
            if not entry["安全等级"]:
                level = safety_level_by_mineral(mineral)
                if level:
                    entry["安全等级"] = level
                else:
                    warnings.append(f"开采矿种「{mineral}」暂无安全等级映射，安全等级留空待人工核定")
            # 名称重名只提示不拦截：重复的是名称，编号判重才作退回依据
            if name in accepted_names:
                warnings.append(f"矿区名称「{name}」与已有矿区重名，请核对是否同一矿区（编号不同，仍正常入库）")
            accepted_names.add(name)
            if not entry["矿区状态"]:
                entry["矿区状态"] = STATUS_ORDER[0]
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
            existing_codes[code_key] = entry
            accepted_codes.add(code_key)
            self._sync_shift(entry)
            shift_synced += 1
            receipts.append(self._receipt(line_no, code_key, name, "created", "建档成功，已同步入井名单待办",
                                          entry=dict(entry), warnings=warnings))

        return self._batch_summary(
            receipts=receipts,
            stock_backfilled=stock_backfilled,
            existing_completed=existing_completed,
            shift_synced=shift_synced,
            message="批量建档完成",
            ok=True,
        )

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
        if "矿区状态" in entry:
            entry["矿区状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"矿区已{action}"

    # ------ 批量建档内部辅助 ------

    @staticmethod
    def _parse_rows(
        *,
        content: str | None,
        filename: str | None,
        raw_rows: list[dict[str, Any]] | None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """把文件文本解析成字段字典列表；直接提交的 rows 原样透传。

        支持 CSV/TSV：首行是中文表头就按表头对齐，否则按 ALL_FIELDS 列序对齐；
        兼容 field_0..field_7 的按列写法（对应 ALL_FIELDS 的前 8 列）。
        """
        if raw_rows:
            return [dict(row, _line=i) for i, row in enumerate(raw_rows, start=1)], None
        if not content or not content.strip():
            return [], "未收到任何行：请选择表格文件或粘贴建档内容"

        delim = "\t" if (filename or "").lower().endswith(".tsv") else None
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            return [], "文件内容为空，没有可建档的行"
        split_lines = [MineareaService._split_line(line, delim) for line in lines]
        if delim is None:
            # 没从文件名判断出来，就用首行里出现最多的分隔符定口径
            first = split_lines[0]
            if len(first) == 1:
                candidates = ["\t", ";", ","]
                delim = max(candidates, key=lambda d: lines[0].count(d))
                split_lines = [MineareaService._split_line(line, delim) for line in lines]

        header = [cell.strip() for cell in split_lines[0]]
        has_header = any(cell in ALL_FIELDS for cell in header)
        body_start = 1 if has_header else 0
        result: list[dict[str, Any]] = []
        for offset, cells in enumerate(split_lines[body_start:], start=body_start + 1):
            row: dict[str, Any] = {}
            if has_header:
                for key, value in zip(header, cells):
                    row[key] = value.strip()
            else:
                for field, value in zip(ALL_FIELDS, cells):
                    row[field] = value.strip()
            row["_line"] = offset
            result.append(row)
        if not result:
            return [], "文件里只有表头，没有可建档的数据行"
        return result, None

    @staticmethod
    def _split_line(line: str, delim: str | None) -> list[str]:
        """按分隔符切一行；分隔符未定时依次尝试制表符/分号/逗号，兼容简单引号包裹。"""
        if delim is None:
            for candidate in ("\t", ";", ","):
                if candidate in line:
                    delim = candidate
                    break
            else:
                delim = ","
        reader = csv.reader(io.StringIO(line), delimiter=delim)
        return next(reader, [line.strip()])

    @staticmethod
    def _receipt(
        line: int,
        code: str | None,
        name: str | None,
        result: str,
        message: str,
        *,
        entry: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "line": line,
            "code": code or None,
            "name": name or None,
            "ok": result == "created",
            "result": result,
            "message": message,
            "entry": entry,
            "warnings": warnings or [],
        }

    @staticmethod
    def _batch_summary(
        *,
        receipts: list[dict[str, Any]],
        stock_backfilled: int,
        existing_completed: int,
        shift_synced: int,
        message: str,
        ok: bool,
    ) -> dict[str, Any]:
        # 延迟导入，避免和 shift 服务产生模块加载顺序耦合
        from app.services.shift import ShiftService

        roster = ShiftService().roster_summary()
        created = sum(1 for item in receipts if item["result"] == "created")
        duplicated = sum(1 for item in receipts if item["result"] == "duplicated")
        rejected = sum(1 for item in receipts if item["result"] == "rejected")
        return {
            "ok": ok,
            "message": message,
            "total": len(receipts),
            "created": created,
            "duplicated": duplicated,
            "rejected": rejected,
            "stock_backfilled": stock_backfilled,
            "existing_completed": existing_completed,
            "shift_synced": shift_synced,
            "roster_pending": roster["roster_pending"],
            "roster_headcount": roster["roster_headcount"],
            "receipts": receipts,
        }

    @staticmethod
    def _sync_shift(entry: dict[str, Any]) -> None:
        """建档成功后同步入井名单待办，保证两处读到的是同一份数据。"""
        from app.services.shift import ShiftService

        ShiftService().sync_minearea_todo(entry["矿区编号"], entry["矿区名称"])

    @staticmethod
    def _next_id(rows: list[dict[str, Any]]) -> int:
        return max((int(row.get("id", 0)) for row in rows), default=0) + 1
