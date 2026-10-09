import os

# ==============================================================================
# OPENCV RTSP NETWORK OPTIMIZATION (CRITICAL: MUST BE SET BEFORE IMPORTING CV2)
# ==============================================================================
# 1. Enforce TCP transport: stops UDP dropped packets & H.264 macroblock (MB) decoding errors
# 2. stimeout 5s (5000000 us): eliminates 30s thread hangs on unreachable cameras
# 3. buffer_size 1MB: prevents packet drops across industrial switches with 350 cameras
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|buffer_size;1024000"

from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from contextlib import contextmanager
import cv2
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from ultralytics import YOLO
import threading
import time
import boto3
import psycopg2 as spg
from psycopg2 import pool
from datetime import datetime
import json
import torch
import cProfile
import pstats
from io import StringIO
import numpy as np
import random
from dotenv import load_dotenv
from urllib.parse import quote_plus
from pathlib import Path
import argparse

# Load environment variables
load_dotenv()

dir_path = os.path.dirname(os.path.realpath(__file__))

# ==============================================================================
# MODEL CONFIGURATION & CROSS-PLATFORM PATH RESOLUTION
# ==============================================================================
# Prioritize best12classes.pt for positive and negative multi-class inference
DEFAULT_MODEL_PATH = os.getenv("MODEL_PATH", "model/best12classes.pt")


def resolve_model_path(specified_path=None):
    """
    Resolves the YOLO model weights path cross-platform (Windows & Ubuntu Linux).
    Checks specified path, MODEL_PATH env, script directory, and standard fallbacks.
    """
    candidates = []
    if specified_path:
        candidates.append(Path(specified_path))
    if os.getenv("MODEL_PATH"):
        candidates.append(Path(os.getenv("MODEL_PATH")))

    candidates.extend([
        Path(dir_path) / "model" / "best12classes.pt",
        Path("model/best12classes.pt"),
        Path("PPEsDetection/model/best12classes.pt"),
        Path(dir_path) / "best12classes.pt",
        Path(dir_path) / "model" / "best.pt",
        Path("model/best.pt"),
    ])

    for candidate in candidates:
        if candidate and candidate.exists():
            return str(candidate.resolve())

    # Return default fallback path
    return specified_path or str(Path(dir_path) / "model" / "best12classes.pt")


# ==============================================================================
# 12-CLASS MAPPINGS (6 Positive Compliant + 6 Negative Violation Classes)
# ==============================================================================
# 0: Gloves, 1: Goggles, 2: Helmet, 3: Mask, 4: No Gloves, 5: No Goggles,
# 6: No Helmet, 7: No Mask, 8: No Shoes, 9: No Suit, 10: Shoes, 11: Suit
YAML_CLASS_NAMES = {
    0: 'Gloves',
    1: 'Goggles',
    2: 'Helmet',
    3: 'Mask',
    4: 'No Gloves',
    5: 'No Goggles',
    6: 'No Helmet',
    7: 'No Mask',
    8: 'No Shoes',
    9: 'No Suit',
    10: 'Shoes',
    11: 'Suit'
}

# Standardized class metadata mapping: canonical key -> display name, base PPE item, violation flag
CLASS_METADATA = {
    # Compliant (Positive) classes -> Emerald Green
    "gloves": {"display": "Gloves", "base_item": "gloves", "is_violation": False},
    "goggles": {"display": "Goggles", "base_item": "goggles", "is_violation": False},
    "helmet": {"display": "Helmet", "base_item": "helmet", "is_violation": False},
    "mask": {"display": "Mask", "base_item": "mask", "is_violation": False},
    "shoes": {"display": "Shoes", "base_item": "shoes", "is_violation": False},
    "suit": {"display": "Suit", "base_item": "suit", "is_violation": False},
    # Non-Compliant / Violation (Negative) classes -> Alert Crimson Red
    "no_gloves": {"display": "No Gloves", "base_item": "gloves", "is_violation": True},
    "no_glove": {"display": "No Gloves", "base_item": "gloves", "is_violation": True},
    "no_goggles": {"display": "No Goggles", "base_item": "goggles", "is_violation": True},
    "no_helmet": {"display": "No Helmet", "base_item": "helmet", "is_violation": True},
    "no_mask": {"display": "No Mask", "base_item": "mask", "is_violation": True},
    "no_shoes": {"display": "No Shoes", "base_item": "shoes", "is_violation": True},
    "no_suit": {"display": "No Suit", "base_item": "suit", "is_violation": True}
}

BASE_PPE_DISPLAY = {
    "helmet": "Helmet",
    "gloves": "Gloves",
    "shoes": "Shoes",
    "mask": "Mask",
    "goggles": "Goggles",
    "suit": "Suit"
}


def normalize_class_name(name):
    """Normalizes class string into metadata dictionary key."""
    s = str(name).strip().lower().replace(" ", "_")
    if s == "glove": s = "gloves"
    elif s == "shoe": s = "shoes"
    elif s == "goggle": s = "goggles"
    elif s == "no_glove": s = "no_gloves"
    elif s == "no_shoe": s = "no_shoes"
    elif s == "no_goggle": s = "no_goggles"
    return s


def get_base_ppe_item(name):
    """Extracts base PPE item (e.g. 'helmet', 'gloves', 'shoes', 'mask', 'goggles', 'suit')."""
    norm = normalize_class_name(name)
    if norm.startswith("no_"):
        norm = norm[3:]
    if norm in ("glove", "gloves"): return "gloves"
    if norm in ("shoe", "shoes"): return "shoes"
    if norm in ("goggle", "goggles"): return "goggles"
    if norm == "helmet": return "helmet"
    if norm == "mask": return "mask"
    if norm == "suit": return "suit"
    return norm


def is_violation_class(name):
    """Returns True if class represents a violation (non-compliance)."""
    norm = str(name).strip().lower().replace("_", " ")
    return norm.startswith("no ") or norm.startswith("no_")


def get_required_ppe_items(ppe_list):
    """
    Extracts set of base required PPE items for an area from camera configuration's ppeList.
    Supports negative identifiers ("no_helmet", "no_glove") and positive identifiers ("helmet", "gloves").
    Defaults to all 6 monitored PPE types if empty or unconfigured.
    """
    all_standard = {"helmet", "gloves", "shoes", "mask", "goggles", "suit"}
    if not ppe_list:
        return all_standard

    required = set()
    for item in ppe_list:
        base = get_base_ppe_item(item)
        if base in all_standard:
            required.add(base)
    return required if required else all_standard


# ==============================================================================
# S3 STORAGE INFRASTRUCTURE
# ==============================================================================
bucket_name = os.getenv('BUCKET_NAME')
s3_endpoint_url = os.getenv('S3_ENDPOINT_URL')
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')

s3 = None
try:
    if s3_endpoint_url and aws_access_key_id and aws_secret_access_key:
        s3 = boto3.client(
            's3',
            endpoint_url=s3_endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            verify=False
        )
except Exception as e:
    print(f"S3 client initialization note: {e}")


def save_image_to_s3(bucket, object_name, image_data):
    """Saves annotated image to MinIO S3 storage with local fallback."""
    if s3 is None or not bucket:
        local_dir = Path(dir_path) / "saved_violations"
        local_dir.mkdir(exist_ok=True)
        local_path = local_dir / object_name
        with open(local_path, "wb") as f:
            f.write(image_data)
        return str(local_path)
    try:
        current_month_name = datetime.now().strftime("%B").lower()
        object_path_with_month = current_month_name + "/" + object_name
        s3.put_object(
            Bucket=bucket,
            Key=object_path_with_month,
            Body=image_data
        )
        return object_path_with_month
    except Exception as e:
        print(f"S3 upload error: {e}")
        local_dir = Path(dir_path) / "saved_violations"
        local_dir.mkdir(exist_ok=True)
        local_path = local_dir / object_name
        with open(local_path, "wb") as f:
            f.write(image_data)
        return str(local_path)


# ==============================================================================
# DATABASE CONNECTION POOLING (ELIMINATES DB CONNECTION EXHAUSTION ON 350 CAMERAS)
# ==============================================================================
db_pool = None
db_pool_lock = threading.Lock()


def init_db_pool():
    """
    Initializes a centralized ThreadedConnectionPool.
    Caps open PostgreSQL connections to max 20, completely eliminating
    'FATAL: sorry, too many clients already' when running 350 cameras.
    """
    global db_pool
    with db_pool_lock:
        if db_pool is not None and not getattr(db_pool, 'closed', False):
            return db_pool

        db_host = os.getenv("DB_HOST", "localhost")
        db_user = os.getenv("DB_USER", "postgres")
        db_pass = os.getenv("DB_PASS", "IIOTDARTarPPE")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "ppes")

        try:
            db_pool = pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=20,
                host=db_host,
                database=db_name,
                user=db_user,
                password=db_pass,
                port=db_port,
                connect_timeout=5
            )
            print("PostgreSQL ThreadedConnectionPool initialized (maxconn=20 shared across all cameras).")
            return db_pool
        except Exception as e:
            print(f"DATABASE POOL INITIALIZATION NOTICE: {e}")
            db_pool = None
            return None


@contextmanager
def get_db_connection():
    """
    Thread-safe context manager to lease a connection from the pool and
    guarantee its return upon block exit.
    """
    global db_pool
    if db_pool is None or getattr(db_pool, 'closed', False):
        init_db_pool()

    conn = None
    leased_from_pool = False

    if db_pool:
        try:
            conn = db_pool.getconn()
            leased_from_pool = True
        except Exception as e:
            print(f"Connection pool leasing notice: {e}")
            conn = None

    # Fallback to direct connection if pool is temporarily exhausted
    if conn is None:
        try:
            db_host = os.getenv("DB_HOST", "localhost")
            db_user = os.getenv("DB_USER", "postgres")
            db_pass = os.getenv("DB_PASS", "IIOTDARTarPPE")
            db_port = os.getenv("DB_PORT", "5432")
            db_name = os.getenv("DB_NAME", "ppes")
            conn = spg.connect(
                host=db_host, database=db_name, user=db_user,
                password=db_pass, port=db_port, connect_timeout=5
            )
            leased_from_pool = False
        except Exception as e:
            print(f"Database connection error: {e}")
            yield None
            return

    try:
        yield conn
    finally:
        if leased_from_pool and db_pool and conn:
            try:
                db_pool.putconn(conn)
            except Exception:
                try: conn.close()
                except: pass
        elif not leased_from_pool and conn:
            try: conn.close()
            except: pass


def create_table_if_not_exists(cur):
    """
    Initializes PostgreSQL tables and ensures extended analytics columns exist.
    Executed ONCE at startup in the main thread to prevent DDL lock contention.
    """
    if cur is None:
        return
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS ppes (
        id SERIAL PRIMARY KEY,
        class1 TEXT,
        production_house TEXT,
        camera_unit TEXT,
        date1 date,
        time1 time,
        image_url TEXT,
        area TEXT,
        camera_status BOOLEAN DEFAULT TRUE,
        violation BOOLEAN DEFAULT TRUE,
        violations TEXT,
        compliance TEXT,
        violation_count INTEGER DEFAULT 0,
        compliance_count INTEGER DEFAULT 0,
        people_count INTEGER DEFAULT 0,
        violator_count INTEGER DEFAULT 0,
        required_ppes TEXT
    );
    """
    try:
        cur.execute(create_table_sql)
        # Ensure extended analytics columns exist on pre-existing deployment databases
        columns_to_ensure = [
            ("violation", "BOOLEAN DEFAULT TRUE"),
            ("violations", "TEXT"),
            ("compliance", "TEXT"),
            ("violation_count", "INTEGER DEFAULT 0"),
            ("compliance_count", "INTEGER DEFAULT 0"),
            ("people_count", "INTEGER DEFAULT 0"),
            ("violator_count", "INTEGER DEFAULT 0"),
            ("required_ppes", "TEXT"),
        ]
        for col_name, col_def in columns_to_ensure:
            try:
                cur.execute(f"ALTER TABLE ppes ADD COLUMN IF NOT EXISTS {col_name} {col_def};")
            except Exception:
                pass

        # Ensure camera_health table exists for dashboard and health alerting
        cur.execute("""
            CREATE TABLE IF NOT EXISTS camera_health (
                camera_id TEXT PRIMARY KEY,
                plant TEXT,
                production_house TEXT,
                area TEXT,
                rtsp_link TEXT,
                status BOOLEAN,
                last_checked TIMESTAMP
            );
        """)
    except Exception as e:
        print(f"Error checking/creating table: {e}")


def insert_single_violation_record(
    production_house,
    ip_address,
    date1,
    time1,
    image_url,
    area_type,
    violations_str,
    compliance_str,
    violation_count,
    compliance_count,
    people_count,
    violator_count,
    required_ppes_str
):
    """
    Inserts EXACTLY ONE ROW per violation image event into PostgreSQL using pooled connections.
    Consolidates all violations, compliances, people count, violator count,
    and required PPEs into that single row.
    """
    class1_str = violations_str if violations_str else "Compliant"

    with get_db_connection() as con:
        if con is None:
            print("[DB ERROR] Cannot record violation: Database connection unavailable.")
            return

        try:
            with con.cursor() as cur:
                try:
                    # Primary insert with extended analytics columns
                    cur.execute("""
                        INSERT INTO ppes (
                            class1, production_house, camera_unit,
                            date1, time1, image_url, area,
                            camera_status, violation, violations, compliance,
                            violation_count, compliance_count, people_count,
                            violator_count, required_ppes
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                    """, (
                        class1_str,
                        production_house,
                        ip_address,
                        date1,
                        time1,
                        image_url,
                        area_type,
                        True,
                        True,
                        violations_str,
                        compliance_str,
                        violation_count,
                        compliance_count,
                        people_count,
                        violator_count,
                        required_ppes_str
                    ))
                    con.commit()
                    print(f"[DB LOGGED (Single Row)] Violations: {violations_str} | Compliance: {compliance_str} | People: {people_count} | Violators: {violator_count}")
                except Exception:
                    con.rollback()
                    # Fallback to standard schema columns if custom columns fail
                    cur.execute("""
                        INSERT INTO ppes (
                            class1, production_house, camera_unit,
                            date1, time1, image_url, area
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                    """, (
                        class1_str,
                        production_house,
                        ip_address,
                        date1,
                        time1,
                        image_url,
                        area_type
                    ))
                    con.commit()
                    print(f"[DB LOGGED (Single Row, Standard Schema)] {class1_str}")
        except Exception as db_err:
            try: con.rollback()
            except Exception: pass
            print(f"[DB ERROR] Failed to record violation: {db_err}")


# In-memory status cache to enable edge-triggered camera status updates
camera_status_cache = {}
camera_status_lock = threading.Lock()


def update_camera_status(plant, production_house, area_type, stream_link="", status=False):
    """
    Maintains real-time camera health in PostgreSQL table `camera_health`.
    Eliminates the need for a separate camera_monitoring.py process, cutting
    network bandwidth in half and preventing stream collisions.
    Uses edge-triggering + periodic keepalive heartbeat (every 5 min) to prevent DB spam.
    """
    camera_id = f"{plant}_{production_house}_{area_type}"
    now_ts = time.time()

    with camera_status_lock:
        prev_entry = camera_status_cache.get(camera_id)
        # If status unchanged AND updated within the last 5 minutes (300s), skip write
        if prev_entry and prev_entry.get("status") == status and (now_ts - prev_entry.get("time", 0)) < 300:
            return
        camera_status_cache[camera_id] = {"status": status, "time": now_ts}

    with get_db_connection() as con:
        if con is None:
            return
        try:
            with con.cursor() as cur:
                cur.execute("""
                    INSERT INTO camera_health (camera_id, plant, production_house, area, rtsp_link, status, last_checked)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (camera_id) DO UPDATE SET
                        status = EXCLUDED.status,
                        last_checked = EXCLUDED.last_checked,
                        rtsp_link = EXCLUDED.rtsp_link,
                        plant = EXCLUDED.plant,
                        production_house = EXCLUDED.production_house,
                        area = EXCLUDED.area;
                """, (camera_id, plant, production_house, area_type, stream_link, status, datetime.now()))
            con.commit()
        except Exception:
            try: con.rollback()
            except: pass


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
    all_boxes
):
    """
    Renders a translucent, high-aesthetic HUD index card on the frame.
    Dynamically positions itself in an unoccupied corner to avoid covering people.
    Displays:
      - Location & Timestamp
      - Metric statistics: People count, Violators count, Violation count, Compliance count
      - Required PPEs in that area with real-time status indicators
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
        disp = BASE_PPE_DISPLAY.get(base_item, base_item.capitalize())
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
# DETECT TRAY INFERENCE ENGINE
# ==============================================================================
class DetectTray:
    """
    High-capacity PPE Vision Inference Engine supporting dual-class (compliant & violation)
    detection with translucent HUD metrics overlays, connection pooling, and single-row DB logging.
    """

    def __init__(self, model_path=None):
        # 1. Device detection - utilizes NVIDIA GPU if available, else CPU
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Initializing DetectTray on device: {self.device}")

        # 2. Model resolution - prioritize best12classes.pt
        chosen_model_path = resolve_model_path(model_path)
        print(f"Loading YOLO weights from: {chosen_model_path}")
        self.model = YOLO(chosen_model_path).to(self.device)

        # 3. Model class names extracted directly from trained model or data.yaml
        if hasattr(self.model, "names") and isinstance(self.model.names, dict) and len(self.model.names) > 0:
            self.model_names = self.model.names
        else:
            self.model_names = YAML_CLASS_NAMES

        print(f"Loaded class mapping ({len(self.model_names)} classes): {self.model_names}")

        # 4. Mutex lock for thread-safe serialized GPU inference across camera threads
        self.model_lock = threading.Lock()

        # 5. Class-specific confidence thresholds matching deployment specs
        self.class_thresholds = {
            "no_helmet": 0.78,
            "no_gloves": 0.80,
            "no_glove": 0.80,
            "no_goggles": 0.60,
            "no_mask": 0.58,
            "no_suit": 0.65,
            "no_shoes": 0.80,
            "helmet": 0.70,
            "gloves": 0.70,
            "goggles": 0.60,
            "mask": 0.60,
            "suit": 0.65,
            "shoes": 0.70
        }
        self.default_threshold = 0.55

        # 6. Thread-safe alert cooldown tracker (1-hour cooldown per camera area)
        self.cooldown_tracker = defaultdict(float)
        self.cooldown_lock = threading.Lock()

        # Shutdown controller
        self.running = True

    def should_record_event(self, production_house, area_type):
        """Thread-safe 1-hour cooldown check to prevent event spamming in database."""
        key = f"{production_house}_{area_type}"
        current_time = time.time()
        cooldown_period = 3600  # 1 hour in seconds

        with self.cooldown_lock:
            last_sent_time = self.cooldown_tracker[key]
            if current_time - last_sent_time >= cooldown_period:
                self.cooldown_tracker[key] = current_time
                return True
            return False

    # Backwards compatibility alias
    should_send_email = should_record_event

    def process_camera(self, stream_data, plant, production_house, area_type,
                       ip_address, ppe_list, non_uniform_scale=False):
        """
        Processes a single camera stream.
        Optimized for 350+ cameras:
        1. Staggers startup to eliminate thundering herd network and CPU spikes.
        2. Uses CAP_PROP_BUFFERSIZE=1 and quick frame drain to eliminate packet drops.
        3. Serializes GPU inference safely via self.model_lock.
        4. Associates detections into people instances and counts violators.
        5. Renders clean bounding boxes (green=compliant, red=violation) without
           cluttering confidence percentage labels.
        6. Dynamically positions translucent HUD overlay in an unoccupied corner
           to ensure workers are never obscured.
        7. Records EXACTLY ONE ROW per violation image to PostgreSQL using connection pooling.
        8. Uses edge-triggered updates to prevent flooding DB with camera status queries.
        """
        # Stagger camera startup across 0.5-35s to prevent concurrent RTSP connection bursts
        initial_stagger = random.uniform(0.5, 35.0)
        time.sleep(initial_stagger)

        # Extract required base PPE items for this area
        required_base_items = get_required_ppe_items(ppe_list)
        required_display_items = [BASE_PPE_DISPLAY.get(b, b.capitalize()) for b in sorted(list(required_base_items))]
        required_ppes_str = ", ".join(required_display_items)

        stream_link = stream_data.get('streamLink', '')
        print(f"[{production_house} | {area_type}] Initializing camera stream: {stream_link}")
        print(f"[{production_house} | {area_type}] Required PPEs in zone: {required_ppes_str}")

        front = None
        try:
            front = cv2.VideoCapture(stream_link, cv2.CAP_FFMPEG)
            if front.isOpened():
                # Enforce internal 1-frame buffer to eliminate buffer bloat and packet drops
                front.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception as cv2_error:
            print(f"Error creating VideoCapture for {stream_link}: {cv2_error}")
            update_camera_status(plant, production_house, area_type, stream_link, False)
            return

        last_detection_time = 0.0
        check_interval = 60.0  # Periodic check interval per camera in seconds

        try:
            while self.running:
                now = time.time()
                time_since_last = now - last_detection_time

                if time_since_last < check_interval:
                    sleep_time = min(1.0, check_interval - time_since_last)
                    time.sleep(sleep_time)
                    continue

                if front is None or not front.isOpened():
                    print(f"Reconnecting stream for {production_house}_{area_type}...")
                    if front:
                        front.release()
                    time.sleep(3)
                    front = cv2.VideoCapture(stream_link, cv2.CAP_FFMPEG)
                    if front.isOpened():
                        front.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    else:
                        update_camera_status(plant, production_house, area_type, stream_link, False)
                        time.sleep(5)
                        continue

                # Quick frame drain (flush buffered frames to land on current real-time keyframe)
                for _ in range(3):
                    front.grab()

                ret, frame = front.read()
                if not ret or frame is None:
                    print(f"[{production_house}_{area_type}] Dropped frame or disconnect. Reconnecting...")
                    update_camera_status(plant, production_house, area_type, stream_link, False)
                    front.release()
                    time.sleep(3)
                    front = cv2.VideoCapture(stream_link, cv2.CAP_FFMPEG)
                    if front.isOpened():
                        front.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    continue

                last_detection_time = time.time()
                update_camera_status(plant, production_house, area_type, stream_link, True)

                # Preprocessing to standardized 1920x1080 resolution
                if non_uniform_scale:
                    h_orig, w_orig = frame.shape[:2]
                    frame = cv2.resize(frame, (w_orig * 2, h_orig * 2))

                frame = cv2.resize(frame, (1920, 1080))

                # Thread-safe GPU Inference
                with self.model_lock:
                    predictions = self.model.predict(frame, conf=0.45, verbose=False)

                raw_detections = []

                # ---- Collect detections using exact class mappings ----
                for result in predictions:
                    boxes = result.boxes
                    if boxes is None or len(boxes) == 0:
                        continue
                    xyxy = boxes.xyxy
                    classes = boxes.cls
                    confidences = boxes.conf

                    for b, c, conf in zip(xyxy, classes, confidences):
                        cid = int(c)
                        raw_name = self.model_names.get(cid, str(cid))
                        norm_name = normalize_class_name(raw_name)
                        meta = CLASS_METADATA.get(norm_name)

                        if meta:
                            is_viol = meta["is_violation"]
                            base_item = meta["base_item"]
                            display_name = meta["display"]
                        else:
                            is_viol = is_violation_class(raw_name)
                            base_item = get_base_ppe_item(raw_name)
                            display_name = raw_name

                        conf_score = float(conf)
                        thresh = self.class_thresholds.get(norm_name, self.class_thresholds.get(base_item, self.default_threshold))

                        # Filter: must meet class confidence threshold and be a required PPE in this area
                        if conf_score >= thresh and base_item in required_base_items:
                            b_coords = [round(float(x)) for x in b.tolist()]
                            cx = (b_coords[0] + b_coords[2]) / 2
                            cy = (b_coords[1] + b_coords[3]) / 2
                            raw_detections.append({
                                'box': b_coords,
                                'center': (cx, cy),
                                'class_name': norm_name,
                                'display_name': display_name,
                                'base_item': base_item,
                                'is_violation': is_viol,
                                'conf': conf_score
                            })

                detected_violations = [d for d in raw_detections if d['is_violation']]
                detected_compliances = [d for d in raw_detections if not d['is_violation']]

                # If no violation detected, proceed to next interval
                if not detected_violations:
                    continue

                # Multi-person clustering to calculate total people and violating people
                total_people, violating_people, _ = group_detections_by_person(raw_detections)

                # Cooldown check: 1 event per camera area per hour
                if not self.should_record_event(production_house, area_type):
                    continue

                # Render clean, aesthetic bounding boxes (no cluttering percentage text):
                # 1. Compliant detections in vibrant Emerald Green
                for d in detected_compliances:
                    frame = draw_aesthetic_box(frame, d['box'], is_violation=False)

                # 2. Violation detections in alert Crimson Red with focus corner brackets
                for d in detected_violations:
                    frame = draw_aesthetic_box(frame, d['box'], is_violation=True)

                # 3. Translucent HUD index card overlay placed in unoccupied corner
                date1 = datetime.now().strftime("%Y-%m-%d")
                time1 = datetime.now().strftime("%H:%M:%S")
                time_code = datetime.now().strftime("%H%M%S")
                all_boxes = [d['box'] for d in raw_detections]

                frame = draw_translucent_index(
                    image=frame,
                    production_house=production_house,
                    area_type=area_type,
                    date_str=date1,
                    time_str=time1,
                    required_base_items=required_base_items,
                    detected_violations=detected_violations,
                    detected_compliances=detected_compliances,
                    total_people=total_people,
                    violating_people=violating_people,
                    all_boxes=all_boxes
                )

                # Save labeled image
                labeled_image = frame.copy()
                im_id = f"{date1}{time_code}_{production_house}_{area_type}"

                image_data = cv2.imencode(".jpg", labeled_image)[1].tobytes()
                s3_key = save_image_to_s3(bucket_name, f"{im_id}.jpg", image_data)

                if bucket_name:
                    encoded_key = quote_plus(f"{datetime.now().strftime('%B').lower()}/{im_id}.jpg")
                    image_url = f"https://ppes-siil.solargroup.com:9000/{bucket_name}/{encoded_key}"
                else:
                    image_url = f"local://saved_violations/{im_id}.jpg"

                # Prepare summary strings for single-row logging
                unique_violations = sorted(list({d['display_name'] for d in detected_violations}))
                unique_compliances = sorted(list({d['display_name'] for d in detected_compliances}))
                violations_str = ", ".join(unique_violations)
                compliance_str = ", ".join(unique_compliances) if unique_compliances else "None"

                print(f"[VIOLATION EVENT] {production_house} | {area_type} -> Violations: [{violations_str}] | Compliances: [{compliance_str}] | People: {total_people} | Violators: {violating_people}")
                print(f"Image URL: {image_url}")

                # Database insertion: Exactly ONE ROW per image (via thread-safe connection pool)
                insert_single_violation_record(
                    production_house=production_house,
                    ip_address=ip_address,
                    date1=date1,
                    time1=time1,
                    image_url=image_url,
                    area_type=area_type,
                    violations_str=violations_str,
                    compliance_str=compliance_str,
                    violation_count=len(detected_violations),
                    compliance_count=len(detected_compliances),
                    people_count=total_people,
                    violator_count=violating_people,
                    required_ppes_str=required_ppes_str
                )

        except Exception as e:
            print(f"Unexpected camera processing exception on {production_house}_{area_type}: {e}")
        finally:
            update_camera_status(plant, production_house, area_type, stream_link, False)
            if front:
                front.release()
            print(f"[{production_house} | {area_type}] Stream released and closed.")

    def profile_process_camera(self, stream_data, plant, production_house, area_type, ip_address, ppe_list):
        """Optional profiling wrapper for individual camera execution."""
        pr = cProfile.Profile()
        pr.enable()
        try:
            self.process_camera(stream_data, plant, production_house, area_type, ip_address, ppe_list)
        finally:
            pr.disable()
            s = StringIO()
            sortby = 'cumulative'
            ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
            ps.print_stats()
            print(s.getvalue())


# ==============================================================================
# CLI ARGUMENT PARSER & SERVICE RUNNER
# ==============================================================================
def parse_arguments():
    # Detect default camera configuration file
    default_camera_file = "camera_list_v4.json"
    if not os.path.exists(default_camera_file) and not (Path(dir_path) / default_camera_file).exists():
        default_camera_file = "camera_list_v4_newplants.json"

    parser = argparse.ArgumentParser(description="PPE Multi-Camera Vision Inference Service")
    parser.add_argument(
        "--cameras", "-c",
        type=str,
        default=default_camera_file,
        help="Path to camera_list JSON configuration file"
    )
    parser.add_argument(
        "--model", "-m",
        type=str,
        default=DEFAULT_MODEL_PATH,
        help="Path to YOLO trained weights (.pt)"
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=None,
        help="Worker thread count (defaults to camera count, max 250)"
    )
    return parser.parse_args()


if __name__ == '__main__':
    args = parse_arguments()

    # 1. Initialize PostgreSQL Connection Pool
    init_db_pool()

    # 2. Run Database Schema Migration ONCE at startup (prevents DDL lock contention)
    with get_db_connection() as setup_con:
        if setup_con:
            try:
                with setup_con.cursor() as setup_cur:
                    create_table_if_not_exists(setup_cur)
                setup_con.commit()
                print("Database table schema validated successfully.")
            except Exception as e:
                print(f"Schema setup note: {e}")

    # 3. Locate camera list configuration file
    camera_file = args.cameras
    if not os.path.exists(camera_file):
        script_dir_camera = Path(dir_path) / camera_file
        if script_dir_camera.exists():
            camera_file = str(script_dir_camera)
        else:
            print(f"Notice: Camera list '{camera_file}' not found.")
            print(f"Creating a sample camera_list_v4.json template in {dir_path}...")
            sample_config = {
                "Plant1": {
                    "PB-1": {
                        "SEIVING": {
                            "streamLink": "rtsp://admin:admin123@192.168.1.100:554/stream1",
                            "ppeList": ["no_helmet", "no_glove", "no_goggles", "no_mask", "no_suit", "no_shoes"]
                        }
                    }
                }
            }
            with open(camera_file, "w") as f:
                json.dump(sample_config, f, indent=4)
            print(f"Template created at {camera_file}. Edit with your actual camera RTSP feeds.")

    print(f"Loading camera device configurations from: {camera_file}")
    with open(camera_file, "r") as f:
        devices = json.load(f)

    # 4. Initialize detection engine (loads model once on GPU)
    tray_detector = DetectTray(model_path=args.model)

    # 5. Flatten camera list into individual tasks
    camera_tasks = []
    for plant, plantData in devices.items():
        if not isinstance(plantData, dict):
            continue
        for productionHouse, productionHouseData in plantData.items():
            if not isinstance(productionHouseData, dict):
                continue
            for areaType, areaData in productionHouseData.items():
                if not isinstance(areaData, dict):
                    continue
                stream_link = areaData.get('streamLink', '')
                if not stream_link:
                    continue
                after_at = stream_link.split('@')[1] if '@' in stream_link else stream_link
                ip_address = after_at.split(':')[0] if ':' in after_at else "0.0.0.0"
                ppe_list = areaData.get("ppeList", [
                    "no_helmet", "no_glove", "no_goggles", "no_mask", "no_suit", "no_shoes"
                ])

                camera_tasks.append((areaData, plant, productionHouse, areaType, ip_address, ppe_list))

    total_cameras = len(camera_tasks)
    print(f"Total camera endpoints registered: {total_cameras}")

    # Worker allocation optimized for Xeon Gold 6326 (caps at 250 threads to avoid OS scheduler thrashing)
    if args.workers:
        max_workers = args.workers
    else:
        max_workers = max(16, min(250, total_cameras)) if total_cameras > 0 else 32

    print(f"Starting ThreadPoolExecutor with {max_workers} worker threads for {total_cameras} cameras.")
    print("Camera check intervals staggered across 60 seconds with 1-frame buffers to prevent network packet drops.")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(
                tray_detector.process_camera,
                areaData, plant, productionHouse, areaType, ip_address, ppe_list
            )
            for areaData, plant, productionHouse, areaType, ip_address, ppe_list in camera_tasks
        ]

        try:
            # Keep main thread alive while workers run
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down PPE inference service cleanly...")
            tray_detector.running = False
            executor.shutdown(wait=False)
            if db_pool and not getattr(db_pool, 'closed', False):
                db_pool.closeall()
            print("All camera workers stopped and database pool closed.")