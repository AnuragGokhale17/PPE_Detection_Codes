import os

# ==============================================================================
# OPENCV RTSP NETWORK OPTIMIZATION (CRITICAL: MUST BE SET BEFORE IMPORTING CV2)
# ==============================================================================
# 1. Enforce TCP transport: stops UDP dropped packets & H.264 macroblock (MB) decoding errors
# 2. stimeout 5s (5000000 us): eliminates 30s thread hangs on unreachable cameras
# 3. buffer_size 1MB: prevents packet drops across industrial switches with 350 cameras
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|buffer_size;1024000"

import argparse
import gc
import logging
import random
import signal
import threading
import time
from collections import defaultdict, deque
from datetime import datetime

import cv2
import numpy as np
import torch
import urllib3
from ultralytics import YOLO

import worker_common as wc
from worker_logic import (
    FRAME_H,
    FRAME_W,
    ClassRegistry,
    build_camera_specs,
    classify_detections,
    detections_payload,
    diff_camera_specs,
    event_image_id,
    event_image_keys,
    local_image_url,
    public_image_url,
    summarize_event,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("inference")

# ==============================================================================
# RUNTIME SETTINGS (.env)
# ==============================================================================
CHECK_INTERVAL = wc.env_float("CHECK_INTERVAL_SECONDS", 60)  # one frame per camera per interval
EVENT_COOLDOWN = wc.env_float("EVENT_COOLDOWN_SECONDS", 3600)  # one event per area per hour
CONFIG_POLL = wc.env_float("CONFIG_POLL_SECONDS", 30)  # runtime_state polling
PREDICT_CONF = wc.env_float("PREDICT_CONF", 0.25)  # low, so reviewers see near-misses too
STARTUP_STAGGER = wc.env_float("STARTUP_STAGGER_SECONDS", 35)
PUBLIC_IMAGE_BASE = os.getenv("PUBLIC_IMAGE_BASE", "https://ppes-siil.solargroup.com:9000")
BUCKET_NAME = os.getenv("BUCKET_NAME", "mybucket")


# ==============================================================================
# CONFIGURATION FROM POSTGRESQL (replaces camera_list_*.json)
# ==============================================================================
CAMERA_SQL = """
    SELECT c.id, p.name, ph.name, c.area, c.stream_url, c.scale_up, pi.key
    FROM cameras c
    JOIN production_houses ph ON ph.id = c.production_house_id
    JOIN plants p ON p.id = ph.plant_id
    LEFT JOIN camera_ppe cp ON cp.camera_id = c.id
    LEFT JOIN ppe_items pi ON pi.id = cp.ppe_item_id AND pi.enabled
    WHERE c.enabled
    ORDER BY c.id
"""

CLASS_SQL = """
    SELECT mc.class_id, mc.name, mc.is_violation, mc.threshold, pi.key, pi.display_name
    FROM model_classes mc
    LEFT JOIN ppe_items pi ON pi.id = mc.ppe_item_id
    WHERE mc.enabled
    ORDER BY mc.class_id
"""


def load_config(pool):
    """Returns (camera specs by id, class registry) from the configuration tables."""
    with pool.connection() as conn:
        if conn is None:
            raise RuntimeError("Database unavailable")
        with conn.cursor() as cur:
            cur.execute("SELECT key, display_name FROM ppe_items WHERE enabled ORDER BY sort_order, id")
            ppe_rows = cur.fetchall()
            cur.execute(CLASS_SQL)
            class_rows = cur.fetchall()
            cur.execute(CAMERA_SQL)
            camera_rows = cur.fetchall()
        conn.commit()
    registry = ClassRegistry.from_rows(class_rows, ppe_rows)
    specs = build_camera_specs(camera_rows, [k for k, _ in ppe_rows])
    return specs, registry


def load_model_path(pool, model_id):
    with pool.connection() as conn:
        if conn is None:
            raise RuntimeError("Database unavailable")
        with conn.cursor() as cur:
            cur.execute("SELECT weights_path FROM model_versions WHERE id = %s", (model_id,))
            row = cur.fetchone()
        conn.commit()
    if not row:
        raise RuntimeError(f"model_versions row {model_id} not found")
    return wc.resolve_repo_path(row[0])


# ==============================================================================
# CAMERA HEALTH (camera_health upserts, edge-triggered with a 5 min keepalive)
# ==============================================================================
camera_status_cache = {}
camera_status_lock = threading.Lock()


def update_camera_status(pool, spec, status):
    """Maintains camera_health for the dashboard and the daily digest. Only writes when the
    status changes or the last write is older than 5 minutes."""
    now_ts = time.time()
    with camera_status_lock:
        prev = camera_status_cache.get(spec.health_id)
        if prev and prev["status"] == status and now_ts - prev["time"] < 300:
            return
        camera_status_cache[spec.health_id] = {"status": status, "time": now_ts}

    with pool.connection() as con:
        if con is None:
            return
        try:
            with con.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO camera_health (camera_id, plant, production_house, area, rtsp_link, status, last_checked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (camera_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        last_checked = EXCLUDED.last_checked,
                        rtsp_link = EXCLUDED.rtsp_link,
                        plant = EXCLUDED.plant,
                        production_house = EXCLUDED.production_house,
                        area = EXCLUDED.area;
                    """,
                    (spec.health_id, spec.plant, spec.production_house, spec.area, spec.stream_url, status, datetime.now()),
                )
            con.commit()
        except Exception:
            try:
                con.rollback()
            except Exception:
                pass


def forget_camera_health(pool, health_id):
    """A camera removed, disabled or renamed in the portal should not linger as online/offline."""
    with camera_status_lock:
        camera_status_cache.pop(health_id, None)
    with pool.connection() as con:
        if con is None:
            return
        try:
            with con.cursor() as cur:
                cur.execute("DELETE FROM camera_health WHERE camera_id = %s", (health_id,))
            con.commit()
        except Exception:
            con.rollback()


# ==============================================================================
# EVENT RECORDING (exactly one ppes row per violation image)
# ==============================================================================
def insert_event_record(pool, spec, now, image_url, summary, people_count, violator_count,
                        required_ppes_str, raw_image_key, detections, model_version_id):
    from psycopg2.extras import Json

    date1, time1 = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S")
    class1_str = summary["violations_str"] or "Compliant"
    with pool.connection() as con:
        if con is None:
            log.error("[DB ERROR] Cannot record violation: database unavailable.")
            return
        try:
            with con.cursor() as cur:
                try:
                    cur.execute(
                        """
                        INSERT INTO ppes (
                            class1, production_house, camera_unit, date1, time1, image_url, area,
                            camera_status, violation, violations, compliance,
                            violation_count, compliance_count, people_count, violator_count, required_ppes,
                            camera_id, raw_image_key, detections, frame_width, frame_height, model_version_id
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                                  %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            class1_str, spec.production_house, spec.ip_address, date1, time1, image_url, spec.area,
                            True, True, summary["violations_str"], summary["compliance_str"],
                            summary["violation_count"], summary["compliance_count"], people_count, violator_count,
                            required_ppes_str,
                            spec.id, raw_image_key, Json(detections), FRAME_W, FRAME_H, model_version_id,
                        ),
                    )
                    con.commit()
                    return
                except Exception as e:
                    con.rollback()
                    log.warning("v2 insert failed (%s); falling back to the legacy columns.", e)
                # Fallback for a database without the v2 migration
                cur.execute(
                    """
                    INSERT INTO ppes (class1, production_house, camera_unit, date1, time1, image_url, area)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (class1_str, spec.production_house, spec.ip_address, date1, time1, image_url, spec.area),
                )
                con.commit()
        except Exception as db_err:
            try:
                con.rollback()
            except Exception:
                pass
            log.error("[DB ERROR] Failed to record violation: %s", db_err)


# ==============================================================================
# COMPUTER VISION & MULTI-PERSON ASSOCIATION
# ==============================================================================
def group_detections_by_person(detections):
    """
    Associates detected PPE boxes into individual person instances.
    Groups body parts (Helmet/Head, Mask, Goggles, Suit/Torso, Gloves, Shoes)
    using horizontal alignment and vertical span constraints.

    Returns:
      total_people (int), violating_people (int), people_clusters (list)
    """
    if not detections:
        return 0, 0, []

    # Sort detections vertically (top to bottom)
    sorted_dets = sorted(detections, key=lambda d: d['center'][1])
    clusters = []

    for det in sorted_dets:
        dx1, dy1, dx2, dy2 = det['box']
        dcx, dcy = det['center']
        det_w = dx2 - dx1

        assigned_cluster = None
        min_dist = float('inf')

        for cluster in clusters:
            cx1, cy1, cx2, cy2 = cluster['bbox']
            cl_w = cx2 - cx1
            cl_cx = (cx1 + cx2) / 2

            # Adaptive horizontal alignment threshold
            max_allowed_x_dist = max(det_w, cl_w, 110) * 1.35
            x_dist = abs(dcx - cl_cx)

            # Plausible full-body vertical span on 1080p
            y_span = max(cy2, dy2) - min(cy1, dy1)

            # Each person has at most one head detection
            has_head = any(d['base_item'] == 'helmet' for d in cluster['detections'])
            is_head = det['base_item'] == 'helmet'

            if x_dist <= max_allowed_x_dist and y_span <= 750:
                if is_head and has_head and x_dist > 40:
                    continue  # Separate head detections indicate distinct people
                if x_dist < min_dist:
                    min_dist = x_dist
                    assigned_cluster = cluster

        if assigned_cluster is not None:
            assigned_cluster['detections'].append(det)
            cx1, cy1, cx2, cy2 = assigned_cluster['bbox']
            assigned_cluster['bbox'] = (min(cx1, dx1), min(cy1, dy1), max(cx2, dx2), max(cy2, dy2))
            if det['is_violation']:
                assigned_cluster['has_violation'] = True
        else:
            clusters.append({
                'detections': [det],
                'bbox': (dx1, dy1, dx2, dy2),
                'has_violation': det['is_violation']
            })

    total_people = len(clusters)
    violating_people = sum(1 for c in clusters if c['has_violation'])

    # Sanity checks
    total_violations = sum(1 for d in detections if d['is_violation'])
    if total_violations > 0 and total_people == 0:
        total_people = 1
        violating_people = 1
    if total_violations > 0 and violating_people == 0:
        violating_people = 1

    return total_people, violating_people, clusters


# ==============================================================================
# AESTHETIC VISUAL RENDERING (CLEAN BOUNDING BOXES & DYNAMIC HUD INDEX OVERLAY)
# ==============================================================================
def draw_aesthetic_box(image, box, is_violation):
    """
    Renders clean, aesthetic bounding boxes with modern high-tech focus corner brackets.
    Omits redundant text labels and percentage tags (which clutter the view),
    as all violation/compliance statuses are neatly presented in the HUD overlay.
      - Compliant (Positive) = Vibrant Emerald Green (46, 204, 113)
      - Violation (Negative) = Vivid Alert Crimson Red (45, 52, 240)
    """
    x1, y1, x2, y2 = [int(v) for v in box]
    h_img, w_img = image.shape[:2]

    x1 = max(0, min(x1, w_img - 1))
    y1 = max(0, min(y1, h_img - 1))
    x2 = max(0, min(x2, w_img - 1))
    y2 = max(0, min(y2, h_img - 1))

    if x2 <= x1 or y2 <= y1:
        return image

    box_w = x2 - x1
    box_h = y2 - y1

    main_color = (45, 52, 240) if is_violation else (46, 204, 113)

    # 1. Main bounding box outline (smooth line)
    cv2.rectangle(image, (x1, y1), (x2, y2), main_color, 2, cv2.LINE_AA)

    # 2. Sleek tech corner accent brackets (4 corners)
    corner_len = max(8, min(24, box_w // 4, box_h // 4))
    corner_thick = 3

    # Top-Left
    cv2.line(image, (x1, y1), (x1 + corner_len, y1), main_color, corner_thick, cv2.LINE_AA)
    cv2.line(image, (x1, y1), (x1, y1 + corner_len), main_color, corner_thick, cv2.LINE_AA)
    # Top-Right
    cv2.line(image, (x2, y1), (x2 - corner_len, y1), main_color, corner_thick, cv2.LINE_AA)
    cv2.line(image, (x2, y1), (x2, y1 + corner_len), main_color, corner_thick, cv2.LINE_AA)
    # Bottom-Left
    cv2.line(image, (x1, y2), (x1 + corner_len, y2), main_color, corner_thick, cv2.LINE_AA)
    cv2.line(image, (x1, y2), (x1, y2 - corner_len), main_color, corner_thick, cv2.LINE_AA)
    # Bottom-Right
    cv2.line(image, (x2, y2), (x2 - corner_len, y2), main_color, corner_thick, cv2.LINE_AA)
    cv2.line(image, (x2, y2), (x2, y2 - corner_len), main_color, corner_thick, cv2.LINE_AA)

    return image


def get_optimal_overlay_position(w_img, h_img, card_w, card_h, detected_boxes):
    """
    Dynamically determines the best placement for the HUD index overlay card
    to ensure workers and detected PPEs are NEVER hidden behind the overlay.

    Evaluates candidate corners:
      1. Top-Right:    (w_img - card_w - 24, 24)
      2. Top-Left:     (24, 24)
      3. Bottom-Right: (w_img - card_w - 24, h_img - card_h - 40)
      4. Bottom-Left:  (24, h_img - card_h - 60)
    Selects the position with zero (or minimum) overlap with detected people/PPEs.
    """
    candidates = [
        ("top_right", w_img - card_w - 24, 24),
        ("top_left", 24, 24),
        ("bottom_right", w_img - card_w - 24, h_img - card_h - 40),
        ("bottom_left", 24, h_img - card_h - 60)
    ]

    if not detected_boxes:
        return 24, 24

    best_pos = (candidates[0][1], candidates[0][2])
    min_overlap = float('inf')
    margin = 30  # Safety buffer around detections

    for _, cx1, cy1 in candidates:
        cx2 = cx1 + card_w
        cy2 = cy1 + card_h

        total_overlap = 0
        for b in detected_boxes:
            bx1, by1, bx2, by2 = b[0] - margin, b[1] - margin, b[2] + margin, b[3] + margin
            ix1 = max(cx1, bx1)
            iy1 = max(cy1, by1)
            ix2 = min(cx2, bx2)
            iy2 = min(cy2, by2)

            if ix2 > ix1 and iy2 > iy1:
                total_overlap += (ix2 - ix1) * (iy2 - iy1)

        # Zero overlap is an immediate winner
        if total_overlap == 0:
            return cx1, cy1

        if total_overlap < min_overlap:
            min_overlap = total_overlap
            best_pos = (cx1, cy1)

    return best_pos


def draw_translucent_index(
    image,
    production_house,
    area_type,
    date_str,
    time_str,
    required_base_items,
    detected_violations,
    detected_compliances,
    total_people,
    violating_people,
    all_boxes,
    ppe_display
):
    """
    Renders a translucent, high-aesthetic HUD index card on the frame.
    Dynamically positions itself in an unoccupied corner to avoid covering people.
    Displays:
      - Location & Timestamp
      - Metric statistics: People count, Violators count, Violation count, Compliance count
      - Required PPEs in that area with real-time status indicators (labels from ppe_items)
      - Summary of active violations
    """
    h_img, w_img = image.shape[:2]

    # Compact & sleek card dimensions
    card_w, card_h = 470, 220

    # Dynamically find the best position avoiding any detected person/PPE boxes
    x1, y1 = get_optimal_overlay_position(w_img, h_img, card_w, card_h, all_boxes)
    x2, y2 = x1 + card_w, y1 + card_h

    # Clip to boundary
    x1 = max(10, min(x1, w_img - card_w - 10))
    y1 = max(10, min(y1, h_img - card_h - 10))
    x2 = x1 + card_w
    y2 = y1 + card_h

    # 1. Translucent glassmorphism background (alpha 0.65 for high visibility of background)
    roi = image[y1:y2, x1:x2]
    overlay = np.full_like(roi, (20, 24, 30), dtype=np.uint8)  # Sleek dark slate
    blended = cv2.addWeighted(overlay, 0.65, roi, 0.35, 0)
    image[y1:y2, x1:x2] = blended

    # 2. Sleek card border
    cv2.rectangle(image, (x1, y1), (x2, y2), (70, 80, 95), 1, cv2.LINE_AA)

    # 3. Top accent stripe (Red if violations exist, Green if compliant)
    accent_color = (45, 52, 240) if len(detected_violations) > 0 else (46, 204, 113)
    cv2.rectangle(image, (x1, y1), (x2, y1 + 4), accent_color, -1)

    font_title = cv2.FONT_HERSHEY_DUPLEX
    font_body = cv2.FONT_HERSHEY_SIMPLEX

    # 4. Header title & location
    title_text = "AI SAFETY & PPE AUDIT"
    cv2.putText(image, title_text, (x1 + 12, y1 + 22), font_title, 0.52, (255, 255, 255), 1, cv2.LINE_AA)

    loc_text = f"{production_house} | {area_type}"
    cv2.putText(image, loc_text, (x1 + 12, y1 + 39), font_body, 0.40, (190, 210, 225), 1, cv2.LINE_AA)

    time_text = f"{date_str} {time_str}"
    (tw, _), _ = cv2.getTextSize(time_text, font_body, 0.38, 1)
    cv2.putText(image, time_text, (x2 - tw - 12, y1 + 22), font_body, 0.38, (150, 165, 180), 1, cv2.LINE_AA)

    # Divider line 1
    cv2.line(image, (x1 + 12, y1 + 48), (x2 - 12, y1 + 48), (55, 65, 80), 1, cv2.LINE_AA)

    # 5. Metric Statistics Badges (3 horizontal blocks)
    block_y1 = y1 + 55
    block_h = 44
    block_y2 = block_y1 + block_h
    block_spacing = 6
    total_avail_w = card_w - 24 - (block_spacing * 2)
    b_w = total_avail_w // 3

    # People Block
    bx_a1 = x1 + 12
    bx_a2 = bx_a1 + b_w
    cv2.rectangle(image, (bx_a1, block_y1), (bx_a2, block_y2), (32, 38, 48), -1)
    cv2.rectangle(image, (bx_a1, block_y1), (bx_a2, block_y2), (55, 68, 85), 1, cv2.LINE_AA)
    cv2.putText(image, "PEOPLE", (bx_a1 + 6, block_y1 + 14), font_body, 0.34, (170, 185, 200), 1, cv2.LINE_AA)
    ppl_val = f"{total_people}"
    cv2.putText(image, ppl_val, (bx_a1 + 6, block_y1 + 35), font_title, 0.60, (255, 255, 255), 1, cv2.LINE_AA)
    violator_tag = f"({violating_people} Violator{'s' if violating_people != 1 else ''})"
    vtag_color = (60, 80, 245) if violating_people > 0 else (120, 200, 120)
    cv2.putText(image, violator_tag, (bx_a1 + 28, block_y1 + 34), font_body, 0.32, vtag_color, 1, cv2.LINE_AA)

    # Violations Block
    bx_b1 = bx_a2 + block_spacing
    bx_b2 = bx_b1 + b_w
    cv2.rectangle(image, (bx_b1, block_y1), (bx_b2, block_y2), (40, 25, 30), -1)
    cv2.rectangle(image, (bx_b1, block_y1), (bx_b2, block_y2), (45, 52, 240) if len(detected_violations) > 0 else (60, 70, 85), 1, cv2.LINE_AA)
    cv2.putText(image, "VIOLATIONS", (bx_b1 + 6, block_y1 + 14), font_body, 0.34, (230, 140, 140), 1, cv2.LINE_AA)
    v_val = f"{len(detected_violations)}"
    v_col = (45, 52, 240) if len(detected_violations) > 0 else (180, 180, 180)
    cv2.putText(image, v_val, (bx_b1 + 6, block_y1 + 35), font_title, 0.65, v_col, 2, cv2.LINE_AA)

    # Compliance Block
    bx_c1 = bx_b2 + block_spacing
    bx_c2 = bx_c1 + b_w
    cv2.rectangle(image, (bx_c1, block_y1), (bx_c2, block_y2), (25, 38, 30), -1)
    cv2.rectangle(image, (bx_c1, block_y1), (bx_c2, block_y2), (46, 204, 113) if len(detected_compliances) > 0 else (60, 70, 85), 1, cv2.LINE_AA)
    cv2.putText(image, "COMPLIANCE", (bx_c1 + 6, block_y1 + 14), font_body, 0.34, (140, 220, 160), 1, cv2.LINE_AA)
    c_val = f"{len(detected_compliances)}"
    c_col = (46, 204, 113) if len(detected_compliances) > 0 else (180, 180, 180)
    cv2.putText(image, c_val, (bx_c1 + 6, block_y1 + 35), font_title, 0.65, c_col, 2, cv2.LINE_AA)

    # Divider line 2
    cv2.line(image, (x1 + 12, y1 + 107), (x2 - 12, y1 + 107), (55, 65, 80), 1, cv2.LINE_AA)

    # 6. Area Required PPEs Section
    cv2.putText(image, "AREA REQUIRED PPES:", (x1 + 12, y1 + 122), font_body, 0.36, (180, 195, 210), 1, cv2.LINE_AA)

    violation_items = {d['base_item'] for d in detected_violations}
    compliance_items = {d['base_item'] for d in detected_compliances}

    tag_x = x1 + 12
    tag_y = y1 + 130
    tag_h = 20
    pad = 5

    for base_item in sorted(list(required_base_items)):
        disp = ppe_display.get(base_item, base_item.capitalize())
        if base_item in violation_items:
            tag_status = f"[!] {disp}"
            tag_bg = (30, 25, 160)
            tag_border = (45, 52, 240)
            tag_text_color = (255, 255, 255)
        elif base_item in compliance_items:
            tag_status = f"[OK] {disp}"
            tag_bg = (20, 110, 45)
            tag_border = (46, 204, 113)
            tag_text_color = (255, 255, 255)
        else:
            tag_status = f"[-] {disp}"
            tag_bg = (30, 35, 45)
            tag_border = (65, 75, 90)
            tag_text_color = (175, 185, 195)

        (tw, th), _ = cv2.getTextSize(tag_status, font_body, 0.34, 1)
        tag_w = tw + pad * 2

        if tag_x + tag_w > x2 - 12:
            tag_x = x1 + 12
            tag_y += tag_h + 3

        cv2.rectangle(image, (tag_x, tag_y), (tag_x + tag_w, tag_y + tag_h), tag_bg, -1)
        cv2.rectangle(image, (tag_x, tag_y), (tag_x + tag_w, tag_y + tag_h), tag_border, 1, cv2.LINE_AA)
        cv2.putText(image, tag_status, (tag_x + pad, tag_y + 14), font_body, 0.34, tag_text_color, 1, cv2.LINE_AA)

        tag_x += tag_w + 5

    # 7. Active Violations Summary Bar
    summary_y = y1 + 192
    cv2.line(image, (x1 + 12, summary_y - 8), (x2 - 12, summary_y - 8), (55, 65, 80), 1, cv2.LINE_AA)

    if detected_violations:
        v_counts = defaultdict(int)
        for d in detected_violations:
            v_counts[d['display_name']] += 1
        summary_items = [f"{name} ({cnt})" if cnt > 1 else name for name, cnt in v_counts.items()]
        alert_str = "ACTIVE VIOLATIONS: " + ", ".join(summary_items)
        if len(alert_str) > 52:
            alert_str = alert_str[:49] + "..."
        cv2.putText(image, alert_str, (x1 + 12, summary_y + 12), font_title, 0.40, (50, 60, 245), 1, cv2.LINE_AA)
    else:
        cv2.putText(image, "STATUS: ALL MONITORED PPES COMPLIANT", (x1 + 12, summary_y + 12), font_title, 0.40, (46, 204, 113), 1, cv2.LINE_AA)

    return image


# ==============================================================================
# MODEL HOLDER (thread-safe GPU inference, hot-swappable weights)
# ==============================================================================
class ModelHolder:
    def __init__(self):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.lock = threading.Lock()
        self.model = None
        self.model_id = None
        self.path = None

    @property
    def loaded(self):
        return self.model is not None

    def load(self, path, model_id):
        """Loads new weights next to the old ones, then swaps under the lock."""
        log.info("Loading YOLO weights from %s (model id %s) on %s", path, model_id, self.device)
        model = YOLO(str(path)).to(self.device)
        with self.lock:
            old = self.model
            self.model, self.model_id, self.path = model, model_id, str(path)
        del old
        self._free_gpu()
        names = getattr(model, "names", {}) or {}
        log.info("Model ready with %d classes: %s", len(names), names)

    def unload(self):
        with self.lock:
            self.model, self.model_id, self.path = None, None, None
        self._free_gpu()

    def _free_gpu(self):
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def predict(self, frame):
        """[(class_name, conf, [x1, y1, x2, y2]), ...] at PREDICT_CONF. Serialized on the GPU."""
        with self.lock:
            if self.model is None:
                return [], None
            results = self.model.predict(frame, conf=PREDICT_CONF, verbose=False)
            names = self.model.names
            model_id = self.model_id
        out = []
        for result in results:
            boxes = result.boxes
            if boxes is None or len(boxes) == 0:
                continue
            for b, c, conf in zip(boxes.xyxy.tolist(), boxes.cls.tolist(), boxes.conf.tolist()):
                out.append((names.get(int(c), str(int(c))), conf, b))
        return out, model_id


# ==============================================================================
# CAMERA WORKER (one thread per camera, stoppable)
# ==============================================================================
class CameraWorker(threading.Thread):
    """
    Processes a single camera stream:
    1. Staggers startup to eliminate thundering herd network and CPU spikes.
    2. Uses CAP_PROP_BUFFERSIZE=1 and quick frame drain to eliminate packet drops.
    3. Checks one frame every CHECK_INTERVAL seconds and hands it to the service.
    4. Uses edge-triggered camera_health updates to avoid flooding the database.
    """

    def __init__(self, spec, service):
        super().__init__(name=f"cam-{spec.id}", daemon=True)
        self.spec = spec
        self.service = service
        self.stop_event = threading.Event()
        # Pause and config reloads stop workers without marking the camera offline
        self.mark_offline_on_exit = True

    def stop(self, mark_offline):
        self.mark_offline_on_exit = mark_offline
        self.stop_event.set()

    def _open(self):
        cap = cv2.VideoCapture(self.spec.stream_url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            # Enforce internal 1-frame buffer to eliminate buffer bloat and packet drops
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def run(self):
        spec, pool = self.spec, self.service.pool
        # Stagger camera startup to prevent concurrent RTSP connection bursts
        if self.stop_event.wait(random.uniform(0.5, STARTUP_STAGGER)):
            return
        log.info("[%s] Starting stream. Required PPE: %s", spec.label, ", ".join(sorted(spec.required_items)))

        cap = None
        last_check = 0.0
        try:
            while not self.stop_event.is_set():
                wait = CHECK_INTERVAL - (time.time() - last_check)
                if wait > 0 and self.stop_event.wait(wait):
                    break

                if cap is None or not cap.isOpened():
                    if cap is not None:
                        cap.release()
                    cap = self._open()
                    if not cap.isOpened():
                        update_camera_status(pool, spec, False)
                        if self.stop_event.wait(5):
                            break
                        continue

                # Quick frame drain (flush buffered frames to land on the current keyframe)
                for _ in range(3):
                    cap.grab()
                ret, frame = cap.read()
                if not ret or frame is None:
                    log.warning("[%s] Dropped frame or disconnect. Reconnecting...", spec.label)
                    update_camera_status(pool, spec, False)
                    cap.release()
                    cap = None
                    if self.stop_event.wait(3):
                        break
                    continue

                last_check = time.time()
                update_camera_status(pool, spec, True)
                try:
                    self.service.process_frame(spec, frame)
                except Exception as e:
                    log.exception("[%s] Frame processing failed: %s", spec.label, e)
        except Exception as e:
            log.exception("Unexpected camera processing exception on %s: %s", spec.label, e)
        finally:
            if cap is not None:
                cap.release()
            if self.mark_offline_on_exit:
                update_camera_status(pool, spec, False)
            log.info("[%s] Stream released.", spec.label)


# ==============================================================================
# INFERENCE SERVICE (supervisor: config hot-reload, pause/resume, model swaps)
# ==============================================================================
class InferenceService:
    def __init__(self, model_override=None):
        self.pool = wc.DbPool(minconn=2, maxconn=20)
        self.storage = wc.get_storage()
        self.local_storage = wc.LocalStorage()
        self.model = ModelHolder()
        self.model_override = model_override
        self.model_error = None

        self.registry = ClassRegistry([])  # swapped atomically on reload
        self.specs = {}
        self.workers = {}
        self.config_version = None
        self.paused = False
        self.pause_reason = None

        self.cooldown_tracker = defaultdict(float)
        self.cooldown_lock = threading.Lock()
        self.recent_events = deque()
        self.shutdown_event = threading.Event()

    # --- events -----------------------------------------------------------------

    def should_record_event(self, spec):
        """Thread-safe cooldown: one event per production house + area per EVENT_COOLDOWN."""
        key = f"{spec.production_house}_{spec.area}"
        now = time.time()
        with self.cooldown_lock:
            if now - self.cooldown_tracker[key] >= EVENT_COOLDOWN:
                self.cooldown_tracker[key] = now
                self.recent_events.append(now)
                return True
            return False

    def events_last_hour(self):
        cutoff = time.time() - 3600
        with self.cooldown_lock:
            while self.recent_events and self.recent_events[0] < cutoff:
                self.recent_events.popleft()
            return len(self.recent_events)

    def _store(self, key, data):
        """Primary storage, falling back to local disk. Returns (stored_key_or_local_ref, is_local)."""
        if self.storage.kind != "local":
            try:
                self.storage.put_bytes(key, data, "image/jpeg")
                return key, False
            except Exception as e:
                log.error("S3 upload error for %s: %s (saved locally instead)", key, e)
        self.local_storage.put_bytes(key, data, "image/jpeg")
        return key, True

    def process_frame(self, spec, frame):
        # Preprocessing to standardized 1920x1080 resolution
        if spec.scale_up:
            h_orig, w_orig = frame.shape[:2]
            frame = cv2.resize(frame, (w_orig * 2, h_orig * 2))
        frame = cv2.resize(frame, (FRAME_W, FRAME_H))

        raw, model_id = self.model.predict(frame)
        registry = self.registry  # one consistent snapshot for this frame
        detections = classify_detections(raw, registry, spec.required_items)
        used = [d for d in detections if d["used"]]
        detected_violations = [d for d in used if d["is_violation"]]
        detected_compliances = [d for d in used if not d["is_violation"]]

        # If no violation detected, proceed to next interval
        if not detected_violations:
            return

        # Multi-person clustering to calculate total people and violating people
        total_people, violating_people, _ = group_detections_by_person(used)

        # Cooldown check: 1 event per camera area per hour
        if not self.should_record_event(spec):
            return

        now = datetime.now()
        # Clean frame for retraining: captured before any box or HUD is drawn
        clean_jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()

        for d in detected_compliances:
            frame = draw_aesthetic_box(frame, d["box"], is_violation=False)
        for d in detected_violations:
            frame = draw_aesthetic_box(frame, d["box"], is_violation=True)

        frame = draw_translucent_index(
            image=frame,
            production_house=spec.production_house,
            area_type=spec.area,
            date_str=now.strftime("%Y-%m-%d"),
            time_str=now.strftime("%H:%M:%S"),
            required_base_items=spec.required_items,
            detected_violations=detected_violations,
            detected_compliances=detected_compliances,
            total_people=total_people,
            violating_people=violating_people,
            all_boxes=[d["box"] for d in used],
            ppe_display=registry.ppe_display,
        )

        im_id = event_image_id(now, spec.production_house, spec.area)
        annotated_key, raw_key = event_image_keys(now, im_id)
        annotated_jpeg = cv2.imencode(".jpg", frame)[1].tobytes()

        stored_key, annotated_local = self._store(annotated_key, annotated_jpeg)
        image_url = local_image_url(stored_key) if annotated_local else public_image_url(PUBLIC_IMAGE_BASE, BUCKET_NAME, stored_key)
        raw_stored, raw_local = self._store(raw_key, clean_jpeg)
        raw_image_key = local_image_url(raw_stored) if raw_local else raw_stored

        summary = summarize_event(used)
        required_ppes_str = ", ".join(registry.display_for(k) for k in sorted(spec.required_items))
        log.info(
            "[VIOLATION EVENT] %s -> Violations: [%s] | Compliances: [%s] | People: %s | Violators: %s",
            spec.label, summary["violations_str"], summary["compliance_str"], total_people, violating_people,
        )

        insert_event_record(
            self.pool, spec, now, image_url, summary, total_people, violating_people,
            required_ppes_str, raw_image_key, detections_payload(detections), model_id,
        )

    # --- supervision --------------------------------------------------------------

    def _ensure_model(self, state):
        want_id = None if self.model_override else state.active_model_id
        if self.model.loaded and self.model.model_id == want_id and (want_id is not None or self.model_override):
            return True
        try:
            if self.model_override:
                path = wc.resolve_repo_path(self.model_override)
            elif want_id is None:
                raise RuntimeError("runtime_state.active_model_id is not set")
            else:
                path = load_model_path(self.pool, want_id)
            if not path.exists():
                raise FileNotFoundError(f"Weights not found: {path}")
            self.model.load(path, want_id)
            self.model_error = None
            return True
        except Exception as e:
            self.model_error = str(e)
            log.error("Model load failed: %s", e)
            return self.model.loaded  # keep serving the previous weights if we have them

    def _stop_workers(self, ids, mark_offline, forget_health=False):
        workers = [self.workers.pop(cid) for cid in ids if cid in self.workers]
        for w in workers:
            w.stop(mark_offline)
        deadline = time.time() + 15
        for w in workers:
            w.join(timeout=max(0.0, deadline - time.time()))
            if forget_health:
                forget_camera_health(self.pool, w.spec.health_id)

    def _start_worker(self, spec):
        worker = CameraWorker(spec, self)
        self.workers[spec.id] = worker
        worker.start()

    def _reconcile(self, state):
        specs, registry = load_config(self.pool)
        self.registry = registry
        start, stop, restart = diff_camera_specs({cid: w.spec for cid, w in self.workers.items()}, specs)

        # Removed/disabled cameras disappear from camera_health; renamed ones get a new row
        self._stop_workers(stop, mark_offline=False, forget_health=True)
        renamed = [cid for cid in restart if self.workers[cid].spec.health_id != specs[cid].health_id]
        self._stop_workers(renamed, mark_offline=False, forget_health=True)
        self._stop_workers([cid for cid in restart if cid not in renamed], mark_offline=False)

        for cid in start + restart:
            self._start_worker(specs[cid])

        self.specs = specs
        self.config_version = state.config_version
        if start or stop or restart:
            log.info(
                "Config v%s applied: %d cameras (+%d started, -%d stopped, %d restarted), %d classes.",
                state.config_version, len(specs), len(start), len(stop), len(restart), len(registry),
            )

    def _enter_pause(self, reason):
        log.warning("Inference paused: %s. Releasing all streams and the GPU.", reason or "no reason given")
        self._stop_workers(list(self.workers), mark_offline=False)
        self.model.unload()
        self.paused = True
        self.pause_reason = reason
        # Forces a full reconcile on resume, even if the first resume tick fails to load the model
        self.config_version = None

    def _heartbeat(self, state_name):
        wc.heartbeat(self.pool, "inference", {
            "state": state_name,
            "pause_reason": self.pause_reason if self.paused else None,
            "cameras_configured": len(self.specs),
            "cameras_running": sum(1 for w in self.workers.values() if w.is_alive()),
            "model_id": self.model.model_id,
            "model_error": self.model_error,
            "config_version": self.config_version,
            "events_last_hour": self.events_last_hour(),
            "device": str(self.model.device),
        })

    def tick(self):
        state = wc.read_runtime_state(self.pool)
        if state is None:
            raise RuntimeError("runtime_state is missing; run `alembic upgrade head` in backend/")

        if state.inference_paused:
            if not self.paused:
                self._enter_pause(state.pause_reason)
            self.pause_reason = state.pause_reason
            self._heartbeat("paused")
            return

        if self.paused:
            log.info("Inference resumed.")
            self.paused = False
            self.pause_reason = None

        if not self._ensure_model(state):
            self._heartbeat("starting")
            return
        if state.config_version != self.config_version:
            self._reconcile(state)
        self._heartbeat("running")

    def run(self):
        self._heartbeat("starting")
        while not self.shutdown_event.is_set():
            try:
                self.tick()
            except Exception as e:
                log.exception("Supervisor tick failed: %s", e)
            self.shutdown_event.wait(CONFIG_POLL)

    def shutdown(self):
        log.info("Shutting down PPE inference service cleanly...")
        self.shutdown_event.set()
        # Like before: a stopped service shows its cameras as offline
        self._stop_workers(list(self.workers), mark_offline=True)
        self._heartbeat("stopped")
        self.pool.close()
        log.info("All camera workers stopped and database pool closed.")


# ==============================================================================
# CLI
# ==============================================================================
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="PPE multi-camera inference service. Cameras, PPE rules, class thresholds and the "
                    "active model come from the database (manage them in the portal)."
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=None,
        help="Debug override: use these weights instead of the active model_versions row",
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_arguments()
    service = InferenceService(model_override=args.model)

    def _handle_signal(signum, _frame):
        log.info("Received signal %s", signum)
        service.shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    supervisor = threading.Thread(target=service.run, name="supervisor", daemon=True)
    supervisor.start()
    try:
        while not service.shutdown_event.is_set():
            service.shutdown_event.wait(1)
    finally:
        supervisor.join(timeout=5)
        service.shutdown()
