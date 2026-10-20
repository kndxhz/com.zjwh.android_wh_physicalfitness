# -*- coding: utf-8 -*-
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


def record_is_valid(data: Dict[str, Any]) -> bool:
    """判断跑步记录是否正常完成。

    真实 App 提交的 `status` 恒为 0，`status` 不是成功标志；
    以 complete / reasonList / unCompleteReason / stepFreqStatus 为准。
    """
    reasons = data.get("reasonList")
    if isinstance(reasons, list) and reasons:
        checked = [bool(item.get("complete")) for item in reasons if isinstance(item, dict)]
        if checked:
            return all(checked)

    if "complete" in data:
        if not bool(data.get("complete")):
            return False
        try:
            if int(data.get("unCompleteReason", 0) or 0) != 0:
                return False
            if int(data.get("stepFreqStatus", 0) or 0) != 0:
                return False
        except (TypeError, ValueError):
            pass
        valid_dis = data.get("validDis")
        if valid_dis is not None:
            try:
                if float(valid_dis) <= 0:
                    return False
            except (TypeError, ValueError):
                pass
        return True

    # 旧响应没有 complete 字段时，status=0 表示正常完成
    try:
        return int(data.get("status", -1)) == 0
    except (TypeError, ValueError):
        return False


def record_status_text(data: Dict[str, Any]) -> str:
    if record_is_valid(data):
        return "达标"
    status = data.get("status")
    return f"状态码={status}" if status is not None else "未达标"


@dataclass
class RunRecordDetail:
    """单次跑步详情模型 (/api/v70320/runnings/get_one_record)"""
    rrid: int
    sport_type: int
    total_distance: float
    valid_distance: float
    total_time: int
    valid_time: int
    calorie: int
    status: int
    is_valid: bool
    uncomplete_reason: int
    start_time: int
    stop_time: int
    avg_speed: str
    avg_step_freq: int
    complete: bool
    status_info: str
    reason_list: List[Dict[str, Any]]
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_data(cls, data: Dict[str, Any]) -> "RunRecordDetail":
        status = int(data.get("status", 0) or 0)
        un_reason = int(data.get("unCompleteReason", 0) or 0)
        return cls(
            rrid=int(data.get("rrid", 0) or data.get("id", 0)),
            sport_type=int(data.get("sportType", 1) or 1),
            total_distance=float(data.get("totalDis", 0.0) or data.get("distance", 0.0)),
            valid_distance=float(data.get("validDis", 0.0) or 0.0),
            total_time=int(data.get("totalTime", 0) or data.get("costTime", 0)),
            valid_time=int(data.get("validTime", 0) or 0),
            calorie=int(data.get("calorie", 0) or 0),
            status=status,
            is_valid=record_is_valid(data),
            uncomplete_reason=un_reason,
            start_time=int(data.get("startTime", 0) or 0),
            stop_time=int(data.get("stopTime", 0) or 0),
            avg_speed=str(data.get("speed", "-")),
            avg_step_freq=int(data.get("avgStepFreq", 0) or 0),
            complete=bool(data.get("complete", False)),
            status_info=str(data.get("statusInfo", "") or ""),
            reason_list=data.get("reasonList") or [],
            raw=data
        )
