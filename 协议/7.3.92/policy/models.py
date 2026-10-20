# -*- coding: utf-8 -*-
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Union, Tuple

cur_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(cur_dir)
for _p in (cur_dir, parent_dir):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from core.geo import bd09_to_gcj02, gcj02_to_bd09, gcj02_to_wgs84


def _num(data: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


@dataclass
class FaceCheckConfig:
    """人脸抽检配置模型"""
    enable: bool = False
    check_point_min: int = 0
    check_point_max: int = 0
    check_run_valid_time: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_data(cls, data: Dict[str, Any]) -> "FaceCheckConfig":
        if not data:
            return cls()
        return cls(
            enable=bool(data.get("enable", False)),
            check_point_min=int(data.get("checkPointMin", 0)),
            check_point_max=int(data.get("checkPointMax", 0)),
            check_run_valid_time=int(data.get("checkRunValidTime", 0)),
            raw=data
        )


@dataclass
class RunRule:
    """单次与单日跑步规则模型"""
    day_goal: int
    min_distance: int
    speed_top: str
    speed_bottom: str
    step_top: Union[int, str]
    step_bottom: Union[int, str]
    valid_times: List[str]
    face_check: FaceCheckConfig
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_data(cls, data: Dict[str, Any]) -> "RunRule":
        rule = data.get("runRuleModel", {}) or {}
        face = data.get("runFaceCheckConfigDTO", {}) or {}
        
        v_times = []
        for vt in rule.get("validTime", []):
            st = vt.get("start", "")
            et = vt.get("end", "")
            if st and et:
                v_times.append(f"{st}~{et}")

        s_top = rule.get("stepTop", "-")
        s_bot = rule.get("stepBottom", "-")
        step_top_text = "不限" if s_top in (0, "0") else s_top
        step_bot_text = "不限" if s_bot in (0, "0") else s_bot

        return cls(
            day_goal=int(rule.get("dayGoal", 0)),
            min_distance=int(rule.get("minDistance", 0)),
            speed_top=str(rule.get("speedTop", "-")),
            speed_bottom=str(rule.get("speedBottom", "-")),
            step_top=step_top_text,
            step_bottom=step_bot_text,
            valid_times=v_times,
            face_check=FaceCheckConfig.from_api_data(face),
            raw=data
        )


@dataclass
class GeoPoint:
    """经纬度坐标点。

    服务端通常同时下发两套坐标：
      - lat / lon  : BD-09
      - glat / glon: GCJ-02（服务端校验轨迹是否经过点位时使用）
    """
    lat: float
    lng: float
    point_id: Optional[int] = None
    name: Optional[str] = None
    glat: Optional[float] = None
    glon: Optional[float] = None
    radius: float = 15.0
    is_fixed: int = 0
    raw: Dict[str, Any] = field(default_factory=dict)

    def gcj(self) -> Tuple[float, float]:
        """返回 GCJ-02 坐标（优先使用服务端 glat/glon）。"""
        if self.glat is not None and self.glon is not None and (self.glat or self.glon):
            return float(self.glat), float(self.glon)
        return bd09_to_gcj02(float(self.lat), float(self.lng))

    def wgs(self) -> Tuple[float, float]:
        """返回 WGS-84 坐标，供轨迹生成器使用。"""
        glat, glon = self.gcj()
        return gcj02_to_wgs84(glat, glon)

    @classmethod
    def from_api_data(cls, data: Dict[str, Any]) -> Optional["GeoPoint"]:
        if not isinstance(data, dict):
            return None

        lat = _num(data, ("lat", "latitude"))
        lng = _num(data, ("lng", "lon", "longitude"))
        glat = _num(data, ("glat", "gLat"))
        glon = _num(data, ("glon", "gLng", "glng"))

        valid_bd = lat is not None and lng is not None and not (lat == 0.0 and lng == 0.0)
        valid_gcj = glat is not None and glon is not None and not (glat == 0.0 and glon == 0.0)

        if valid_gcj:
            if not valid_bd:
                lat, lng = gcj02_to_bd09(glat, glon)
                valid_bd = True
        elif valid_bd:
            glat, glon = bd09_to_gcj02(lat, lng)
            valid_gcj = True
        else:
            return None

        point_id = data.get("id")
        try:
            point_id = int(point_id) if point_id is not None else None
        except (TypeError, ValueError):
            point_id = None
        try:
            is_fixed = int(data.get("isFixed") or 0)
        except (TypeError, ValueError):
            is_fixed = 0

        return cls(
            lat=float(lat),
            lng=float(lng),
            point_id=point_id,
            name=data.get("name") or data.get("pointName"),
            glat=float(glat),
            glon=float(glon),
            radius=float(_num(data, ("radius",)) or 15.0),
            is_fixed=is_fixed,
            raw=data
        )


@dataclass
class GeoFenceArea:
    """学校电子围栏与必经打卡点模型"""
    fence_id: int
    fence_name: str
    polygon_points: List[GeoPoint]
    check_points: List[GeoPoint]
    raw: Dict[str, Any] = field(default_factory=dict)

    def center(self) -> Optional[Tuple[float, float]]:
        """围栏/打卡点中心（BD-09 原始坐标系）。"""
        pts = self.polygon_points or self.check_points
        if not pts:
            return None
        return (
            sum(p.lat for p in pts) / len(pts),
            sum(p.lng for p in pts) / len(pts),
        )

    def center_gcj(self) -> Optional[Tuple[float, float]]:
        """围栏/打卡点中心（GCJ-02，用于轨迹生成）。"""
        pts = self.polygon_points or self.check_points
        if not pts:
            return None
        gcj = [p.gcj() for p in pts]
        return (
            sum(p[0] for p in gcj) / len(gcj),
            sum(p[1] for p in gcj) / len(gcj),
        )

    @classmethod
    def from_api_data(cls, data: Dict[str, Any],
                      fallback_points: Optional[List[GeoPoint]] = None) -> "GeoFenceArea":
        if not isinstance(data, dict):
            data = {}

        poly = []
        for p in data.get("points", []) or []:
            point = GeoPoint.from_api_data(p)
            if point:
                poly.append(point)

        raw_checks = (
            data.get("passPoints")
            or data.get("checkPoints")
            or data.get("checkPointList")
            or data.get("fixedPoints")
            or data.get("pointList")
            or []
        )
        checks = []
        for cp in raw_checks:
            point = GeoPoint.from_api_data(cp)
            if point:
                checks.append(point)
        if not checks and fallback_points:
            checks = list(fallback_points)

        try:
            fence_id = int(data.get("id", 0) or 0)
        except (TypeError, ValueError):
            fence_id = 0

        return cls(
            fence_id=fence_id,
            fence_name=str(data.get("name", "未命名围栏") or "未命名围栏"),
            polygon_points=poly,
            check_points=checks,
            raw=data
        )


@dataclass
class SemesterInfo:
    """学期跑步进度模型"""
    semester_name: str
    total_completed_distance: float
    valid_count: int
    target_distance: float
    remaining_distance: float
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_data(cls, data: Dict[str, Any]) -> "SemesterInfo":
        tot = float(data.get("totalDistance", 0.0))
        tar = float(data.get("targetDistance", 0.0) or data.get("goalDistance", 0.0))
        rem = max(0.0, tar - tot)
        return cls(
            semester_name=str(data.get("semesterName", "")),
            total_completed_distance=tot,
            valid_count=int(data.get("validCount", 0)),
            target_distance=tar,
            remaining_distance=rem,
            raw=data
        )
