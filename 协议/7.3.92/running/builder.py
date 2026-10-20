import base64
import gzip
import hashlib
import json
import math
import random
import time
import uuid
from typing import List, Tuple, Dict, Any, Optional, Union

from core.geo import (
    haversine,
    bd09_to_gcj02,
    gcj02_to_bd09,
    gcj02_to_wgs84,
    wgs84_to_gcj02,
    LocalProjection,
)
from .config import SPORT_STATIC_SALT
from .models import GpsPoint, FivePoint, StepBucket, SpeedBucket


def compute_sport_signature(field_map: Dict[str, Union[str, int, float, bool, None]],
                            salt: str = SPORT_STATIC_SALT) -> str:
    """计算 31 参数运动学加盐 MD5 校验签名"""
    valid_items = []
    for k, v in field_map.items():
        if v is None:
            continue
        if k.lower() == "signature":
            continue
        valid_items.append((k, str(v).lower() if isinstance(v, bool) else str(v)))
    
    valid_items.sort(key=lambda x: (x[0].lower(), x[0]))
    canonical_str = "&".join(f"{k}={v}" for k, v in valid_items)
    to_hash = (canonical_str + salt).encode("utf-8")
    return hashlib.md5(to_hash).hexdigest().lower()


def compute_original_sign(field_map: Dict[str, Union[str, int, float, bool, None]]) -> str:
    """计算原始参数键值对拼接串"""
    valid_items = []
    for k, v in field_map.items():
        if v is None:
            continue
        if k.lower() == "signature":
            continue
        valid_items.append((k, str(v).lower() if isinstance(v, bool) else str(v)))
    
    valid_items.sort(key=lambda x: x[0])
    return "&".join(f"{k}={v}" for k, v in valid_items)


def gzip_base64_encode(data: Union[str, bytes]) -> str:
    """Gzip 压缩并转为 Base64 字符串"""
    if isinstance(data, str):
        data_bytes = data.encode("utf-8")
    else:
        data_bytes = data
    compressed = gzip.compress(data_bytes)
    return base64.b64encode(compressed).decode("ascii")


def _first_num(data: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _normalize_checkpoint(cp: Dict[str, Any], index: int = 0) -> Optional[Dict[str, Any]]:
    """把服务端点位统一成 GCJ-02 + WGS-84 两套坐标。

    服务端字段约定（参考 sw-campus-tool / NekoSportsWorldTool）：
      lat / lon   -> BD-09
      glat / glon -> GCJ-02（服务端判定轨迹是否经过点位时使用）
    """
    if not isinstance(cp, dict):
        return None

    lat = _first_num(cp, ("lat", "latitude"))
    lng = _first_num(cp, ("lng", "lon", "longitude"))
    glat = _first_num(cp, ("glat", "gLat"))
    glon = _first_num(cp, ("glon", "gLng", "glng"))

    valid_bd = lat is not None and lng is not None and not (lat == 0.0 and lng == 0.0)
    valid_gcj = glat is not None and glon is not None and not (glat == 0.0 and glon == 0.0)

    if valid_gcj:
        if not valid_bd:
            lat, lng = gcj02_to_bd09(glat, glon)
    elif valid_bd:
        glat, glon = bd09_to_gcj02(lat, lng)
    else:
        return None

    wlat, wlon = gcj02_to_wgs84(glat, glon)
    try:
        radius = float(cp.get("radius") or 15.0)
    except (TypeError, ValueError):
        radius = 15.0
    try:
        is_fixed = int(cp.get("isFixed") or 0)
    except (TypeError, ValueError):
        is_fixed = 0
    return {
        "name": str(cp.get("pointName") or cp.get("name") or f"P_{index + 1}"),
        "id": cp.get("id"),
        "lat": float(lat),
        "lon": float(lng),
        "glat": float(glat),
        "glon": float(glon),
        "wlat": float(wlat),
        "wlon": float(wlon),
        "radius": radius,
        "isFixed": is_fixed,
        "raw": cp,
    }


def _dedupe_checkpoints(points: List[Dict[str, Any]], min_m: float = 2.0) -> List[Dict[str, Any]]:
    out = []
    for p in points:
        if all(haversine(p["glat"], p["glon"], q["glat"], q["glon"]) >= min_m for q in out):
            out.append(p)
    return out


def _order_points_radial(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按质心方位角排序，形成自然闭环；点太少时补辅助点。"""
    n = len(points)
    if n <= 1:
        return list(points)

    lat0 = sum(p["wlat"] for p in points) / n
    lon0 = sum(p["wlon"] for p in points) / n
    proj = LocalProjection(lat0, lon0)
    xy = [proj.to_xy(p["wlat"], p["wlon"]) for p in points]
    cx = sum(q[0] for q in xy) / n
    cy = sum(q[1] for q in xy) / n
    order = sorted(range(n), key=lambda i: math.atan2(xy[i][1] - cy, xy[i][0] - cx))
    return [points[i] for i in order]


def _make_circle_points(center_glat: float, center_glon: float,
                        count: int = 8, radius_m: float = 80.0,
                        prefix: str = "Loop") -> List[Dict[str, Any]]:
    """在 GCJ-02 中心点周围构造一个圆形控制点环。"""
    proj = LocalProjection(center_glat, center_glon)
    out = []
    for i in range(max(3, count)):
        ang = 2.0 * math.pi * i / max(3, count)
        glat, glon = proj.to_ll(radius_m * math.cos(ang), radius_m * math.sin(ang))
        wlat, wlon = gcj02_to_wgs84(glat, glon)
        out.append({
            "name": f"{prefix}_{i + 1}",
            "id": i + 1,
            "lat": gcj02_to_bd09(glat, glon)[0],
            "lon": gcj02_to_bd09(glat, glon)[1],
            "glat": glat,
            "glon": glon,
            "wlat": wlat,
            "wlon": wlon,
            "radius": 15.0,
            "isFixed": 0,
            "raw": {},
        })
    return out


def _build_control_ring(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """构造闭环控制点；真实点位不足 3 个时补辅助点，避免退化。"""
    pts = _order_points_radial(points)
    n = len(pts)
    if n >= 3:
        return pts
    if n == 2:
        a, b = pts
        mid_lat = (a["wlat"] + b["wlat"]) / 2.0
        mid_lon = (a["wlon"] + b["wlon"]) / 2.0
        proj = LocalProjection(mid_lat, mid_lon)
        ax, ay = proj.to_xy(a["wlat"], a["wlon"])
        bx, by = proj.to_xy(b["wlat"], b["wlon"])
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return _make_circle_points(a["glat"], a["glon"], count=5, radius_m=50.0)
        offset = max(30.0, length * 0.45)
        px, py = -dy / length * offset, dx / length * offset
        mid_x, mid_y = (ax + bx) / 2.0, (ay + by) / 2.0
        synthetic = []
        for idx, (ox, oy) in enumerate(((px, py), (-px, -py))):
            wlat, wlon = proj.to_ll(mid_x + ox, mid_y + oy)
            glat, glon = wgs84_to_gcj02(wlat, wlon)
            synthetic.append({
                "name": f"Aux_{idx + 1}", "id": None,
                "lat": gcj02_to_bd09(glat, glon)[0], "lon": gcj02_to_bd09(glat, glon)[1],
                "glat": glat, "glon": glon, "wlat": wlat, "wlon": wlon,
                "radius": 15.0, "isFixed": 0, "raw": {},
            })
        return [a, synthetic[0], b, synthetic[1]]
    if n == 1:
        aux = _make_circle_points(pts[0]["glat"], pts[0]["glon"], count=4, radius_m=35.0, prefix="Aux")
        # 保证真实点也在环上
        return [pts[0]] + aux[1:]
    return []


def _catmull_rom_ring(controls: List[Dict[str, Any]],
                      samples_per_seg: int = 0) -> Tuple[LocalProjection, List[Tuple[float, float]], List[float]]:
    """闭合 Catmull-Rom 曲线：返回 (局部投影, 点集, 弧长表)。"""
    n = len(controls)
    lat0 = sum(p["wlat"] for p in controls) / n
    lon0 = sum(p["wlon"] for p in controls) / n
    proj = LocalProjection(lat0, lon0)
    xy = [proj.to_xy(p["wlat"], p["wlon"]) for p in controls]

    dense: List[Tuple[float, float]] = []
    for i in range(n):
        p0 = xy[(i - 1) % n]
        p1 = xy[i]
        p2 = xy[(i + 1) % n]
        p3 = xy[(i + 2) % n]
        seg_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        samples = samples_per_seg or max(10, min(64, int(seg_len / 3.0)))
        for j in range(samples):
            t = j / float(samples)
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2.0 * p1[0])
                       + (-p0[0] + p2[0]) * t
                       + (2.0 * p0[0] - 5.0 * p1[0] + 4.0 * p2[0] - p3[0]) * t2
                       + (-p0[0] + 3.0 * p1[0] - 3.0 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2.0 * p1[1])
                       + (-p0[1] + p2[1]) * t
                       + (2.0 * p0[1] - 5.0 * p1[1] + 4.0 * p2[1] - p3[1]) * t2
                       + (-p0[1] + 3.0 * p1[1] - 3.0 * p2[1] + p3[1]) * t3)
            dense.append((x, y))

    dense.append(dense[0])
    arcs = [0.0]
    for i in range(1, len(dense)):
        arcs.append(arcs[-1] + math.hypot(
            dense[i][0] - dense[i - 1][0],
            dense[i][1] - dense[i - 1][1]
        ))
    return proj, dense, arcs


def _ring_point_at(dense: List[Tuple[float, float]], arcs: List[float], s: float) -> Tuple[float, float]:
    total = arcs[-1] if arcs else 0.0
    if total <= 0:
        return dense[0] if dense else (0.0, 0.0)
    s = s % total
    lo, hi = 0, len(arcs) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if arcs[mid] < s:
            lo = mid + 1
        else:
            hi = mid
    i = max(1, lo)
    a, b = dense[i - 1], dense[i]
    span = arcs[i] - arcs[i - 1]
    f = 0.0 if span <= 0 else (s - arcs[i - 1]) / span
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f


def _snap_checkpoints(points: List[GpsPoint], checkpoints: List[Dict[str, Any]],
                      max_snap_m: float = 60.0) -> int:
    """把最近轨迹点吸附到打卡点坐标，保证服务端点位判定命中。"""
    used = set()
    snapped = 0
    for cp in checkpoints:
        best_i, best_d = None, 1e18
        for i, p in enumerate(points):
            if i in used:
                continue
            d = haversine(cp["glat"], cp["glon"], p.lat, p.lon)
            if d < best_d:
                best_d, best_i = d, i
        if best_i is not None and best_d <= max_snap_m:
            points[best_i].lat = round(cp["glat"], 7)
            points[best_i].lon = round(cp["glon"], 7)
            used.add(best_i)
            snapped += 1
    return snapped


def _track_distance(points: List[GpsPoint]) -> float:
    return sum(
        haversine(p1.lat, p1.lon, p2.lat, p2.lon)
        for p1, p2 in zip(points, points[1:])
    )


def check_checkpoint_hits(points: List[GpsPoint],
                          checkpoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """校验轨迹到每个打卡点的最小距离（GCJ-02）。"""
    normalized = []
    for idx, cp in enumerate(checkpoints or []):
        item = _normalize_checkpoint(cp, idx)
        if item:
            normalized.append(item)
    stats = []
    for cp in normalized:
        if points:
            dist = min(haversine(cp["glat"], cp["glon"], p.lat, p.lon) for p in points)
        else:
            dist = 1e18
        threshold = max(float(cp.get("radius") or 15.0), 15.0)
        stats.append({
            "name": cp["name"],
            "isFixed": cp["isFixed"],
            "dist_m": round(dist, 2),
            "hit": dist <= threshold,
        })
    return stats


class RunningTrackBuilder:
    """运动轨迹、传感器步频分桶与 7.3.92 报文组装构建器"""

    def __init__(self, uid: int, unid: int, sport_type: int = 1, uuid_str: Optional[str] = None):
        self.uid = int(uid)
        self.unid = int(unid)
        # sport_type: 1 为计分跑（校园考核），6 为自由跑（阳光跑/课外自由锻炼）
        self.sport_type = int(sport_type)
        self.uuid_str = uuid_str or str(uuid.uuid4())

    def generate_track_around_points(self,
                                    center_lat: float,
                                    center_lng: float,
                                    checkpoints: Optional[List[Dict[str, Any]]] = None,
                                    total_distance_m: int = 2100,
                                    total_time_sec: int = 760,
                                    start_time_ms: int = 0) -> Tuple[List[GpsPoint], List[FivePoint]]:
        """根据模式生成经过全部打卡点的平滑 GPS 轨迹。

        坐标链（与参考项目一致）：
          服务端 lat/lon(BD-09) + glat/glon(GCJ-02)
            -> WGS-84 生成闭环
            -> GCJ-02 写入 allLocJson
        服务端判定“是否经过打卡点”使用的是 GCJ-02。
        """
        interval_sec = 3
        num_points = max(10, int(total_time_sec // interval_sec))

        real_cps: List[Dict[str, Any]] = []
        for idx, cp in enumerate(checkpoints or []):
            item = _normalize_checkpoint(cp, idx)
            if item:
                real_cps.append(item)
        real_cps = _dedupe_checkpoints(real_cps)

        five_points: List[FivePoint] = []
        snap_cps: List[Dict[str, Any]] = []

        # 只要服务端下发了真实点位，计分跑/自由跑都必须经过；
        # 自由跑没有点位时才生成普通环线。
        if real_cps:
            controls = _build_control_ring(real_cps)
            snap_cps = real_cps
            for idx, cp in enumerate(real_cps):
                five_points.append(FivePoint(
                    lat=round(cp["lat"], 7),
                    lon=round(cp["lon"], 7),
                    glat=round(cp["glat"], 7),
                    glon=round(cp["glon"], 7),
                    radius=float(cp.get("radius") or 15.0),
                    isFixed=int(cp.get("isFixed") or 0),
                    isPass=True,
                    pointName=str(cp.get("name") or f"P_{idx + 1}"),
                    position=idx + 1
                ))
        elif self.sport_type == 1:
            # 计分跑无真实点位时的兜底：围绕校区中心生成 5 个虚拟必经点
            if not center_lat and not center_lng:
                center_lat, center_lng = 31.894350, 118.892580
            fake = _make_circle_points(center_lat, center_lng, count=5,
                                       radius_m=60.0, prefix="CheckPoint")
            for idx, cp in enumerate(fake):
                cp["isFixed"] = 1
                cp["name"] = f"CheckPoint_{idx + 1}"
            controls = _build_control_ring(fake)
            snap_cps = fake
            for idx, cp in enumerate(fake):
                five_points.append(FivePoint(
                    lat=round(cp["lat"], 7),
                    lon=round(cp["lon"], 7),
                    glat=round(cp["glat"], 7),
                    glon=round(cp["glon"], 7),
                    radius=float(cp.get("radius") or 15.0),
                    isFixed=1,
                    isPass=True,
                    pointName=cp["name"],
                    position=idx + 1
                ))
        else:
            # 自由跑且服务端未下发点位：普通环线，fivePointJson 为空
            if not center_lat and not center_lng:
                center_lat, center_lng = 31.894350, 118.892580
            controls = _make_circle_points(center_lat, center_lng, count=8,
                                           radius_m=80.0, prefix="Free")
            five_points = []

        if not controls:
            return [], five_points

        proj, dense, arcs = _catmull_rom_ring(controls)
        if len(dense) < 2:
            return [], five_points

        mapping_distance = float(total_distance_m)
        points: List[GpsPoint] = []
        # 目标：实际轨迹略高于提交里程（+0.3%），避免卡在学校 minDistance 线下
        desired_actual = float(total_distance_m) * 1.003 if total_distance_m > 0 else 0.0
        for _ in range(3):
            points = self._generate_from_ring(
                proj, dense, arcs, mapping_distance,
                total_time_sec, start_time_ms, num_points
            )
            actual = _track_distance(points)
            if total_distance_m <= 0 or actual <= 0:
                break
            if total_distance_m <= actual <= total_distance_m * 1.02:
                break
            mapping_distance *= desired_actual / actual

        if snap_cps:
            _snap_checkpoints(points, snap_cps)

        return points, five_points

    def _generate_from_ring(self,
                            proj: LocalProjection,
                            dense: List[Tuple[float, float]],
                            arcs: List[float],
                            distance_m: float,
                            total_time_sec: int,
                            start_time_ms: int,
                            num_points: int) -> List[GpsPoint]:
        """沿闭环按累计里程采样，输出 GCJ-02 轨迹点。"""
        loop_len = arcs[-1] if arcs else 0.0
        base_speed = (distance_m / total_time_sec) if total_time_sec > 0 else 2.6
        points: List[GpsPoint] = []
        for i in range(num_points):
            t_frac = i / max(1, num_points - 1)
            d = distance_m * t_frac
            s = (d % loop_len) if loop_len > 0 else 0.0
            x, y = _ring_point_at(dense, arcs, s)
            # 轻微 GPS 漂移（约 0.5m），不影响点位命中
            x += random.uniform(-0.5, 0.5)
            y += random.uniform(-0.5, 0.5)
            wlat, wlon = proj.to_ll(x, y)
            glat, glon = wgs84_to_gcj02(wlat, wlon)
            pt_time = int(start_time_ms + t_frac * total_time_sec * 1000)
            spd = max(1.8, min(4.8, base_speed * random.uniform(0.92, 1.08)))
            points.append(GpsPoint(
                lat=round(glat, 6),
                lon=round(glon, 6),
                time=pt_time,
                speed=round(spd, 2),
                accuracy=round(random.uniform(2.5, 4.8), 1),
                isValid=True
            ))
        return points

    def build_submission_payload(self,
                                total_distance_m: int,
                                total_time_sec: int,
                                total_steps: int,
                                start_time_ms: int,
                                stop_time_ms: int,
                                gps_points: List[GpsPoint],
                                five_points: List[FivePoint],
                                sel_distance_m: int = 2000,
                                sel_run_time_s: int = 1200,
                                calorie: int = 135,
                                avg_power: int = 150) -> Tuple[dict, dict, str]:
        """组装完整的 save/record 报文、OBS 上传大对象与相对路径"""
        complete = (total_distance_m >= sel_distance_m) and (total_time_sec >= sel_run_time_s)
        un_complete_reason = 0 if complete else 10
        avg_step_freq = round(total_steps * 60.0 / total_time_sec) if total_time_sec > 0 else 165
        speed_val = round((total_distance_m / total_time_sec) * 1000) if total_time_sec > 0 else 2600

        # 1. 签名参数字典 (严格按照 7.3.92 规则)
        sign_map = {
            "address": "",
            "avgPower": avg_power,
            "avgStepFreq": avg_step_freq,
            "calorie": calorie,
            "complete": complete,
            "errorCode": 0,
            "faceCheck": 0,
            "geeToken": "",
            "getPrize": False,
            "goalId": "null",
            "policy": 1,
            "selDistance": sel_distance_m,
            "selRunTime": sel_run_time_s,
            "selectedUnid": self.unid,
            "speed": speed_val,
            "sportType": self.sport_type,
            "startTime": start_time_ms,
            "status": 1,
            "stopTime": stop_time_ms,
            "themeId": 0,
            "totalAscent": 0,
            "totalDis": total_distance_m,
            "totalSteps": total_steps,
            "totalTime": total_time_sec,
            "uid": self.uid,
            "unCompleteReason": un_complete_reason,
            "unauthorized": 0,
            "useMobilityTools": 0,
            "uuid": self.uuid_str,
            "validDis": total_distance_m,
            "validTime": total_time_sec
        }
        signature = compute_sport_signature(sign_map)
        original_sign = compute_original_sign(sign_map)

        # 2. 生成 10 秒步频与速度分桶
        num_buckets = max(1, total_time_sec // 10)
        dist_per_bucket = round(total_distance_m / num_buckets, 2)
        steps_per_bucket = total_steps // num_buckets
        speed_buckets = []
        step_buckets = []
        for i in range(num_buckets):
            b_start = start_time_ms + i * 10000
            b_end = min(stop_time_ms, b_start + 10000)
            speed_buckets.append(SpeedBucket(dist_per_bucket, b_start, b_end, queueNum=i + 1))
            step_buckets.append(StepBucket(steps_per_bucket, b_start, b_end, queueNum=i + 1))

        all_loc_json = json.dumps([p.to_dict() for p in gps_points], separators=(",", ":"))
        five_pt_json = json.dumps([p.to_dict() for p in five_points], separators=(",", ":")) if five_points else "[]"
        speed_json = json.dumps([b.to_dict() for b in speed_buckets], separators=(",", ":"))
        step_json = json.dumps([b.to_dict() for b in step_buckets], separators=(",", ":"))

        # 3. 组装 save/record 报文体
        first_pt = gps_points[0] if gps_points else GpsPoint(0.0, 0.0, start_time_ms)
        save_record = {
            "address": "",
            "allLocJson": all_loc_json,
            "avgPower": avg_power,
            "avgStepFreq": avg_step_freq,
            "calorie": calorie,
            "complete": complete,
            "errorCode": 0,
            "faceCheck": 0,
            "fivePointJson": five_pt_json,
            "geeToken": "",
            "getPrize": False,
            "goalId": None,
            "isUpload": False,
            "latitude": first_pt.lat,
            "longitude": first_pt.lon,
            "maxRunTime": 7200,
            "minSteps": 2000,
            "originalSign": original_sign,
            "policy": 1,
            "recordUrl": "",
            "roomId": 0,
            "segmentJson": "[]",
            "selDistance": sel_distance_m,
            "selRunTime": sel_run_time_s,
            "selectedUnid": self.unid,
            "signature": signature,
            "speed": speed_val,
            "speedPerTenSec": [b.to_dict() for b in speed_buckets],
            "sportType": self.sport_type,
            "startTime": start_time_ms,
            "status": 1,
            "stepsPerTenSec": [b.to_dict() for b in step_buckets],
            "stopTime": stop_time_ms,
            "themeId": 0,
            "totalAscent": 0,
            "totalDis": total_distance_m,
            "totalSteps": total_steps,
            "totalTime": total_time_sec,
            "uid": self.uid,
            "unCompleteReason": un_complete_reason,
            "unauthorized": 0,
            "useMobilityTools": 0,
            "uuid": self.uuid_str,
            "validDis": total_distance_m,
            "validTime": total_time_sec
        }

        # 4. 组装 OBS Gzip-Base64 载荷
        obs_payload = {
            "rrid": gzip_base64_encode(""),
            "uid": gzip_base64_encode(str(self.uid)),
            "uuid": gzip_base64_encode(self.uuid_str),
            "run_data": gzip_base64_encode(all_loc_json),
            "step_freq_json": gzip_base64_encode(step_json),
            "speed_json": gzip_base64_encode(speed_json),
            "segment_json": gzip_base64_encode("[]"),
            "fixed_point_json": gzip_base64_encode(five_pt_json),
            "runFaceCheck": gzip_base64_encode(""),
            "extension_json": gzip_base64_encode(""),
            "laps_json": gzip_base64_encode("")
        }

        # 5. 生成 OBS 目标对象 Key
        hour_str = time.strftime("%Y%m%d%H", time.localtime(start_time_ms / 1000.0))
        object_key = f"run_data/{hour_str}/{self.uuid_str}.json"

        return save_record, obs_payload, object_key
