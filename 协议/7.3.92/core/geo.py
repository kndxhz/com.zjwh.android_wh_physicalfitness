# -*- coding: utf-8 -*-
"""地理坐标转换与局部平面投影工具。

运动世界校园服务端下发的打卡点/围栏通常同时带两套坐标：

    lat / lon   -> BD-09（百度）
    glat / glon -> GCJ-02（高德/火星）

客户端上报的轨迹使用 GCJ-02；生成器内部统一使用 WGS-84，
最后再转换回 GCJ-02 提交。
"""
import math
from typing import Tuple

EARTH_R = 6371008.8
M_PER_DEG_LAT = math.pi * EARTH_R / 180.0

X_PI = math.pi * 3000.0 / 180.0
GCJ_A = 6378245.0
GCJ_EE = 0.00669342162296594323


def out_of_china(lat: float, lng: float) -> bool:
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def _transform_lat(x: float, y: float) -> float:
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(x: float, y: float) -> float:
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lat: float, lng: float) -> Tuple[float, float]:
    """WGS-84 -> GCJ-02。"""
    if out_of_china(lat, lng):
        return lat, lng
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = math.radians(lat)
    magic = 1.0 - GCJ_EE * math.sin(radlat) ** 2
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((GCJ_A * (1.0 - GCJ_EE)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (GCJ_A / sqrtmagic * math.cos(radlat) * math.pi)
    return lat + dlat, lng + dlng


def gcj02_to_wgs84(lat: float, lng: float) -> Tuple[float, float]:
    """GCJ-02 -> WGS-84（迭代反解，往返误差 < 0.1m）。"""
    if out_of_china(lat, lng):
        return lat, lng
    wlat, wlng = lat, lng
    for _ in range(8):
        glat, glng = wgs84_to_gcj02(wlat, wlng)
        dlat, dlng = lat - glat, lng - glng
        wlat += dlat
        wlng += dlng
        if abs(dlat) < 1e-9 and abs(dlng) < 1e-9:
            break
    return wlat, wlng


def bd09_to_gcj02(lat: float, lng: float) -> Tuple[float, float]:
    """BD-09 -> GCJ-02。"""
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.sin(theta), z * math.cos(theta)


def gcj02_to_bd09(lat: float, lng: float) -> Tuple[float, float]:
    """GCJ-02 -> BD-09（数值迭代反解）。"""
    def residual(blat: float, blng: float) -> Tuple[float, float]:
        glat, glng = bd09_to_gcj02(blat, blng)
        return glat - lat, glng - lng

    blat, blng = lat, lng
    h = 1e-8
    for _ in range(20):
        f1, f2 = residual(blat, blng)
        if abs(f1) < 1e-11 and abs(f2) < 1e-11:
            break
        j11 = (residual(blat + h, blng)[0] - residual(blat - h, blng)[0]) / (2 * h)
        j12 = (residual(blat, blng + h)[0] - residual(blat, blng - h)[0]) / (2 * h)
        j21 = (residual(blat + h, blng)[1] - residual(blat - h, blng)[1]) / (2 * h)
        j22 = (residual(blat, blng + h)[1] - residual(blat, blng - h)[1]) / (2 * h)
        det = j11 * j22 - j12 * j21
        if abs(det) < 1e-18:
            break
        blat += -(f1 * j22 - j12 * f2) / det
        blng += -(j11 * f2 - f1 * j21) / det
    r1, r2 = residual(blat, blng)
    if abs(r1) > 1e-6 or abs(r2) > 1e-6:
        return lat, lng
    return blat, blng


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点球面距离（米）。"""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


class LocalProjection:
    """以某点为原点的局部米制投影，适合校区/操场这种小范围。"""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = float(lat0)
        self.lon0 = float(lon0)
        self.m_per_deg_lng = M_PER_DEG_LAT * math.cos(math.radians(self.lat0))

    def to_xy(self, lat: float, lng: float) -> Tuple[float, float]:
        return (
            (float(lng) - self.lon0) * self.m_per_deg_lng,
            (float(lat) - self.lat0) * M_PER_DEG_LAT,
        )

    def to_ll(self, x: float, y: float) -> Tuple[float, float]:
        return (
            self.lat0 + y / M_PER_DEG_LAT,
            self.lon0 + x / self.m_per_deg_lng,
        )
