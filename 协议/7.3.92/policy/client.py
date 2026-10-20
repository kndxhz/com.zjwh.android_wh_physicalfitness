# -*- coding: utf-8 -*-
import hashlib
import json
import os
import sys
import time
import uuid
from typing import Optional, Dict, Any, Union, List

cur_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(cur_dir)
for p in [cur_dir, parent_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from core.client import BaseNetSecClient
from core.crypto import build_observed_envelope
from core.geo import gcj02_to_wgs84, haversine
from .config import (
    URL_RUN_POLICY,
    URL_INDOOR_POLICY,
    URL_GEO_FENCE,
    URL_SEMESTER_INFO,
    URL_SEMESTER_SUMMARY,
    URL_RUN_GOALS,
    URL_RUN_POINTS,
    POINTS_SIGN_SALT
)
from .models import RunRule, GeoFenceArea, GeoPoint, SemesterInfo

POINTS_CACHE_TTL = 30 * 60          # 30 分钟
POINTS_CACHE_MAX_ANCHOR_KM = 20.0   # 点位缓存与当前校区中心的最大偏差
POINTS_CACHE_PATH = os.path.join(parent_dir, "points_cache.json")


class PolicyClient(BaseNetSecClient):
    """运动世界校园 7.3.92 跑步规则与地理围栏客户端"""

    def __init__(self,
                 uid: Optional[Union[int, str]] = None,
                 token: Optional[str] = None,
                 unid: Optional[Union[int, str]] = None,
                 device_config: Optional[Dict[str, Any]] = None):
        super().__init__(uid=uid, token=token, unid=unid, device_config=device_config)
        self._points_cache: List[GeoPoint] = []
        self._envelope_first_ms: Optional[int] = None

    def get_run_policy(self, run_mode: int = 1, unid: Optional[Union[int, str]] = None) -> Optional[RunRule]:
        """获取指定运动模式的跑步规则（配速、步频、单次/单日里程、有效时段等）"""
        url = URL_INDOOR_POLICY if run_mode == 5 else URL_RUN_POLICY
        unid_val = int(unid or self.unid or 0)
        body = {
            "runMode": run_mode,
            "ruleUpdateTime": 0,
            "geoFenceUpdateTime": 0,
            "selectUnid": unid_val,
            "operateType": 0
        }
        res = self.execute_request("POST", url, body_plain=body)
        if isinstance(res, dict) and res.get("error") == 10000 and "data" in res and res["data"]:
            return RunRule.from_api_data(res["data"])
        return None

    def get_geo_fence(self, update_time: int = 0, run_mode: int = 1) -> List[GeoFenceArea]:
        """拉取学校电子围栏与打卡点。

        优先 getGeoFenceForRun；该接口在部分校区返回空或缺少打卡点，
        此时用 runModePolicy 的 data.geoFence 补齐/兜底（真机 App 实际使用的那份）。
        """
        fences = []
        body = {
            "geoFenceUpdateTime": update_time
        }
        res = self.execute_request("POST", URL_GEO_FENCE, body_plain=body)
        if isinstance(res, dict) and res.get("error") == 10000 and res.get("data"):
            d = res["data"]
            if isinstance(d, str):
                try:
                    d = json.loads(d)
                except Exception:
                    d = {}
            if isinstance(d, dict):
                raw_list = d.get("geoFences", []) or []
                for item in raw_list:
                    fence = GeoFenceArea.from_api_data(item)
                    if fence.polygon_points or fence.check_points:
                        fences.append(fence)

        # getGeoFenceForRun 在部分校区返回空 / 只有多边形没有打卡点
        policy_fences = self._get_policy_fences(run_mode=run_mode)
        if not fences:
            fences = policy_fences
        elif policy_fences:
            all_checks = [p for f in policy_fences for p in f.check_points]
            all_poly = [p for f in policy_fences for p in f.polygon_points]
            for fence in fences:
                matched = next(
                    (pf for pf in policy_fences if pf.fence_id == fence.fence_id),
                    None
                )
                if not fence.check_points:
                    fence.check_points = list(matched.check_points if matched else all_checks)
                if not fence.polygon_points:
                    fence.polygon_points = list(matched.polygon_points if matched else all_poly)

        # 围栏与 policy 都不含打卡点时，从 v560 拉取学校点位
        if fences and not any(f.check_points for f in fences):
            center = fences[0].center_gcj()
            if center:
                wlat, wlon = gcj02_to_wgs84(center[0], center[1])
                points = self.get_points(wlat, wlon, unid=self.unid, sport_type=4)
                if points:
                    fences[0].check_points = list(points)
        return fences

    def get_points(self, latitude: float, longitude: float,
                   unid: Optional[Union[int, str]] = None,
                   sport_type: int = 4,
                   force: bool = False) -> List[GeoPoint]:
        """拉取学校打卡点（/api/v560/get/1/distance/1）。

        该接口要求额外字段 sign + runec（内嵌 NetSec 信封），
        并且 5 分钟内最多 3 次，因此在本进程内做缓存。
        """
        if self._points_cache and not force:
            return list(self._points_cache)

        unid_val = str(unid if unid is not None else (self.unid or 0))
        cached = self._load_points_cache(latitude, longitude, unid_val)
        if cached and not force:
            self._points_cache = cached
            return list(cached)

        now_ms = int(time.time() * 1000)
        if self._envelope_first_ms is None:
            self._envelope_first_ms = now_ms
        first_ms = self._envelope_first_ms
        uid_val = int(self.uid or 0)
        runec = build_observed_envelope(
            f"{uid_val}{float(longitude):.6f}{float(latitude):.6f}{((now_ms // 1000) * 1000)}",
            first_ms=first_ms,
            ts_ms=now_ms
        )
        http_url = URL_RUN_POINTS.replace("https://", "http://", 1)
        sign = hashlib.md5((http_url + POINTS_SIGN_SALT).encode("utf-8")).hexdigest()
        body = {
            "sportType": int(sport_type),
            "longitude": float(longitude),
            "latitude": float(latitude),
            "sign": sign,
            "uuid": str(uuid.uuid4()),
            "selectedUnid": unid_val,
            "runec": runec
        }
        res = self.execute_request("POST", URL_RUN_POINTS, body_plain=body)
        if not isinstance(res, dict) or res.get("error") != 10000:
            # 限流/网络异常时允许使用过期但校区一致的缓存
            if cached:
                self._points_cache = cached
                return list(cached)
            return []

        data = res.get("data")
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("pointsResModels", "list", "points", "pointList", "rows"):
                value = data.get(key)
                if isinstance(value, list):
                    items = value
                    break
        points = []
        for item in items:
            point = GeoPoint.from_api_data(item)
            if point:
                points.append(point)
        if points:
            self._points_cache = points
            self._save_points_cache(latitude, longitude, unid_val, points)
        return points

    @staticmethod
    def _load_points_cache(latitude: float, longitude: float,
                           unid: str) -> List[GeoPoint]:
        try:
            with open(POINTS_CACHE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []
        if not isinstance(data, dict):
            return []
        if str(data.get("unid")) != str(unid):
            return []
        ts = int(data.get("ts", 0) or 0)
        if ts and (time.time() - ts) > POINTS_CACHE_TTL * 2:
            return []
        anchor = data.get("anchor") or []
        if isinstance(anchor, list) and len(anchor) == 2:
            try:
                if haversine(float(latitude), float(longitude),
                             float(anchor[0]), float(anchor[1])) > POINTS_CACHE_MAX_ANCHOR_KM * 1000.0:
                    return []
            except (TypeError, ValueError):
                return []
        points = []
        for item in data.get("points", []) or []:
            point = GeoPoint.from_api_data(item)
            if point:
                points.append(point)
        return points

    @staticmethod
    def _save_points_cache(latitude: float, longitude: float,
                           unid: str, points: List[GeoPoint]) -> None:
        try:
            data = {
                "unid": str(unid),
                "ts": int(time.time()),
                "anchor": [float(latitude), float(longitude)],
                "points": [p.raw for p in points],
            }
            with open(POINTS_CACHE_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass

    def get_policy_data(self, run_mode: int = 1, unid: Optional[Union[int, str]] = None) -> Dict[str, Any]:
        """拉取 runModePolicy 的 data 原始结构（含 geoFence 与可能存在的必经点列表）。"""
        url = URL_INDOOR_POLICY if run_mode == 5 else URL_RUN_POLICY
        body = {
            "runMode": run_mode,
            "ruleUpdateTime": 0,
            "geoFenceUpdateTime": 0,
            "selectUnid": int(unid or self.unid or 0),
            "operateType": 0
        }
        res = self.execute_request("POST", url, body_plain=body)
        if isinstance(res, dict) and res.get("error") == 10000 and isinstance(res.get("data"), dict):
            return res["data"]
        return {}

    def _get_policy_fences(self, run_mode: int = 1) -> List[GeoFenceArea]:
        """从 runModePolicy 响应中提取围栏与打卡点。"""
        data = self.get_policy_data(run_mode=run_mode)
        if not data:
            return []

        geo_fence = data.get("geoFence")
        if isinstance(geo_fence, str):
            try:
                geo_fence = json.loads(geo_fence)
            except Exception:
                geo_fence = None

        root_points = self._extract_policy_points(data)
        fences = []
        if isinstance(geo_fence, dict):
            for item in geo_fence.get("geoFences", []) or []:
                fence = GeoFenceArea.from_api_data(item, fallback_points=root_points)
                if fence.polygon_points or fence.check_points:
                    fences.append(fence)

        if not fences and root_points:
            fences.append(GeoFenceArea(
                fence_id=0,
                fence_name="runModePolicy",
                polygon_points=[],
                check_points=root_points,
                raw=data
            ))
        return fences

    @staticmethod
    def _extract_policy_points(data: Dict[str, Any]) -> List[GeoPoint]:
        """防御式提取 policy 根部的必经点列表（不同版本字段名可能不同）。"""
        keys = (
            "passPoints", "passPointList", "checkPoints", "checkPointList",
            "fixedPoints", "pointList", "runPointList", "mustPointList",
            "mustPoints", "runPoints", "nodeList", "points"
        )
        for key in keys:
            items = data.get(key)
            if not isinstance(items, list):
                continue
            points = []
            for item in items:
                point = GeoPoint.from_api_data(item)
                if point:
                    points.append(point)
            if points:
                return points
        return []

    def get_semester_info(self, run_mode: int = 1) -> Optional[SemesterInfo]:
        """查询学生本学期已完成公里数与剩余目标"""
        body = {
            "runMode": run_mode
        }
        res = self.execute_request("POST", URL_SEMESTER_INFO, body_plain=body)
        if isinstance(res, dict) and res.get("error") == 10000 and "data" in res and res["data"]:
            return SemesterInfo.from_api_data(res["data"])
        return None

    def get_semester_summary(self, sid: int = 0) -> Dict[str, Any]:
        """查询学期总体结算汇总"""
        return self.execute_request("POST", URL_SEMESTER_SUMMARY, body_plain={"sid": sid})

    def get_run_goals(self) -> Dict[str, Any]:
        """查询本学期考核指标与目标"""
        return self.execute_request("POST", URL_RUN_GOALS, body_plain={})


    def get_distance_route_points(self, sport_type: int = 1, distance_m: int = 1000) -> dict:
        """兼容旧入口：返回学校打卡点（真实数据源为 v560 拉点接口）。"""
        fences = self.get_geo_fence()
        center = fences[0].center_gcj() if fences else None
        if not center:
            return {"error": -1, "message": "未获取到围栏中心", "data": []}
        wlat, wlon = gcj02_to_wgs84(center[0], center[1])
        points = self.get_points(wlat, wlon, unid=self.unid, sport_type=4)
        return {
            "error": 10000 if points else -1,
            "message": "成功" if points else "未获取到打卡点",
            "data": [p.raw for p in points],
        }

