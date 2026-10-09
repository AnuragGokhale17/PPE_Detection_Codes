import os
import cv2
import json
import time
import boto3
import torch
import random
import threading
import psycopg2 as spg
import numpy as np
from dotenv import load_dotenv
from ultralytics import YOLO
from collections import defaultdict
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
import re
import urllib.parse

# --- Configuration & Setup ---
load_dotenv()

# Database Configuration
DB_HOST = os.getenv('DB_HOST')
DB_USER = os.getenv('DB_USER')
DB_PASS = os.getenv('DB_PASS')
DB_NAME = "postgres" # Default DB name

# S3 Configuration
BUCKET_NAME = os.getenv('BUCKET_NAME')
S3_ENDPOINT_URL = os.getenv('S3_ENDPOINT_URL')
AWS_ACCESS_KEY_ID = os.getenv('AWS_ACCESS_KEY_ID')
AWS_SECRET_ACCESS_KEY = os.getenv('AWS_SECRET_ACCESS_KEY')


def replace_env_vars(obj):
    if isinstance(obj, str):
        matches = re.findall(r"\$\{([^}]+)\}", obj)
        for var in matches:
            val = os.getenv(var, "")
            if not val:
                print(f"WARNING: Environment variable {var} is empty!")
            
            if "PASSWORD" in var:
                # If the value already contains '%25', it's already double encoded.
                # We quote only if it hasn't been quoted yet.
                # Also, we use safe=" " to ensure we don't break the URL structure.
                if "%" not in val:
                    val = urllib.parse.quote(val, safe="")
            
            obj = obj.replace("${" + var + "}", val)
        return obj
    elif isinstance(obj, dict):
        return {k: replace_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [replace_env_vars(i) for i in obj]
    return obj

def connect_to_db():
    try:
        con = spg.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port='5432')
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()
        cur.execute("SELECT version()")
        print("Connection established to:", cur.fetchone())
        return con, cur
    except spg.Error as e:
        print(f"Database connection failed: {e}")
        return None, None

def create_s3_client():
    try:
        return boto3.client(
            's3',
            endpoint_url=S3_ENDPOINT_URL,
            aws_access_key_id=AWS_ACCESS_KEY_ID,
            aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
        )
    except Exception as e:
        print(f"Failed to create S3 client: {e}")
        return None

def save_image_to_s3(s3_client, bucket_name, object_name, image_data):
    try:
        current_month_name = datetime.now().strftime("%B").lower()
        object_path_with_month = f"{current_month_name}/{object_name}"
        s3_client.put_object(
            Bucket=bucket_name,
            Key=object_path_with_month,
            Body=image_data,
            ContentType='image/jpeg'
        )
        image_url = f"{S3_ENDPOINT_URL}/{bucket_name}/{object_path_with_month}"
        print(f"Successfully uploaded to S3. URL: {image_url}")
        return image_url
    except Exception as e:
        print(f"!!!!!!!!!! FAILED TO UPLOAD TO S3 !!!!!!!!!!")
        print(f"Bucket: {bucket_name}, Object: {object_path_with_month}")
        print(f"Error Details: {e}") 
        return None
    
def create_table_if_not_exists(cur):
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS ppes (
        id SERIAL PRIMARY KEY,
        class1 TEXT,
        production_house TEXT,
        camera_unit TEXT,
        date1 DATE,
        time1 TIME,
        image_url TEXT,
        area TEXT,
        camera_status BOOLEAN DEFAULT TRUE
    );
    """
    cur.execute(create_table_sql)


# --- Main Detection Class ---
class PpeDetector:
    def __init__(self, model_path):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        print(f"Using device: {self.device}")
        self.model = YOLO(model_path).to(self.device)
        self.class_names = self.model.names

        # Bright highlighting color mapping (Imported from Code 2)
        self.class_colors = {
            "no_helmet": (255, 0, 0),      # Bright Red / Blue depending on channel order
            "no_glove": (0, 255, 0),       # Bright Green
            "no_goggles": (0, 0, 255),     # Bright Blue / Red depending on channel order
            "no_mask": (255, 255, 0),      # Bright Yellow
            "no_suit": (255, 105, 180),    # Hot Pink
            "no_shoes": (255, 165, 0)      # Bright Orange
        }
        self.class_thresholds = {
            "no_helmet": 0.80,      
            "no_glove": 0.82,       
            "no_goggles": 0.60,     
            "no_mask": 0.58,        
            "no_suit": 0.65,        
            "no_shoes": 0.90        
        }
        # Default confidence threshold for all classes if not explicitly defined
        self.default_threshold = 0.55

    def random_color(self):
        """Generates a random color in RGB/BGR format."""
        return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    def draw_boxes(self, image, bbox, class_label, box_style=None):
        """Draws simple bounding boxes using styling parameters (from Code 2)."""
        x, y, width, height = bbox

        # Get the color for the class (or use a random color if not predefined)
        color = self.class_colors.get(class_label, self.random_color())

        # Box styling (default)
        box_thickness = box_style.get("thickness", 2) if box_style else 2
        box_line_type = box_style.get("line_type", cv2.LINE_AA) if box_style else cv2.LINE_AA

        # Draw the bounding box with color
        cv2.rectangle(image, 
                      (x - width // 2, y - height // 2), 
                      (x + width // 2, y + height // 2), 
                      color, box_thickness, box_line_type)

        return image

    def is_color_in_box(self, frame, bbox, target_color):
        """Checks if a specific color exists within the bounding box."""
        x_center, y_center, width, height = map(int, bbox)
        x1 = max(0, x_center - width // 2)
        y1 = max(0, y_center - height // 2)
        x2 = min(frame.shape[1], x_center + width // 2)
        y2 = min(frame.shape[0], y_center + height // 2)
 
        # Crop the detected violation area
        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return False
 
        hsv_crop = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
 
        if target_color == 'silver':
            lower = np.array([0, 0, 100]) 
            upper = np.array([180, 50, 255])
        elif target_color == 'orange':
            lower = np.array([5, 100, 100])
            upper = np.array([25, 255, 255])
        else:
            return False
 
        mask = cv2.inRange(hsv_crop, lower, upper)
        color_pixel_percentage = (np.sum(mask > 0) / mask.size) * 100
        return color_pixel_percentage > 15

    def draw_legend(self, image, detected_classes, x_offset=10, y_offset=10, font=cv2.FONT_HERSHEY_COMPLEX, font_scale=1, font_thickness=1, max_width=None, outline_color=(0, 0, 0)):
        """
        Draws a clean, horizontal-row list style legend at the top-left of the image (from Code 2).
        The text is generated with outlines for legibility.
        """
        # Ensure detected_classes is a list to handle index/looping properly
        detected_classes = list(detected_classes)

        x_position = x_offset
        y_position = y_offset
        
        box_width = 20
        box_height = 20
        spacing = 20  
        row_height = box_height + spacing  
        
        for idx, class_label in enumerate(detected_classes, start=1):
            color = self.class_colors.get(class_label, self.random_color())
            
            # Draw the filled color legend block
            cv2.rectangle(image, 
                        (x_position, y_position), 
                        (x_position + box_width, y_position + box_height), 
                        color, -1)

            # Create standard tag text
            label_text = f"{idx}. {class_label}"
            
            # Get text size
            (text_width, text_height), _ = cv2.getTextSize(label_text, font, font_scale, font_thickness)
            text_x = x_position + box_width + spacing
            text_y = y_position + box_height // 2 + text_height // 2

            # Draw outer text drop shadow
            outline_offset = 2  
            for dx in [-outline_offset, 0, outline_offset]:
                for dy in [-outline_offset, 0, outline_offset]:
                    if dx != 0 or dy != 0:
                        cv2.putText(image, label_text, 
                                    (text_x + dx, text_y + dy), 
                                    font, font_scale, outline_color, font_thickness, cv2.LINE_AA)
            
            # Draw the text overlay on top
            cv2.putText(image, label_text, 
                        (text_x, text_y), 
                        font, font_scale, (255, 255, 255), font_thickness, cv2.LINE_AA)

            # Shift x coordinates for the next element
            x_position += box_width + text_width + spacing

            # Check for width overflow and wrap rows
            if max_width and x_position > max_width:
                x_position = x_offset  
                y_position += row_height  
        
        return image

    def process_camera(self, stream_data, plant, production_house, area_type, ip_address, ppe_list):
        log_prefix = f"[{production_house} - {area_type}]"
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        
        stream_link = stream_data['streamLink']
        con, cur = None, None
        cap = None
        s3_client = create_s3_client()
        
        if not s3_client:
            print(f"{log_prefix} Could not create S3 client. Exiting thread.")
            return

        reconnect_delay = 5

        while True:
            try:
                con, cur = connect_to_db()
                if not con:
                    print(f"{log_prefix} DB connection failed. Retrying in {reconnect_delay}s...")
                    time.sleep(reconnect_delay)
                    continue
                create_table_if_not_exists(cur)

                print(f"{log_prefix} Attempting to connect to {stream_link}...")
                cap = cv2.VideoCapture(stream_link, cv2.CAP_FFMPEG)
                
                if not cap.isOpened():
                    raise ConnectionError("VideoCapture failed to open stream.")
                
                print(f"{log_prefix} Successfully connected to stream.")
                reconnect_delay = 5
                last_detection_time = 0

                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret:
                        print(f"{log_prefix} Lost stream (ret=False). Will attempt to reconnect.")
                        break

                    current_time = time.time()
                    if current_time - last_detection_time < 3:
                        time.sleep(0.1)
                        continue
                    last_detection_time = current_time

                    frame = cv2.resize(frame, (1920, 1080))
                    predictions = self.model.predict(frame, imgsz=1280, conf=0.01, verbose=True)

                    detected_violations = {}

                    for res in predictions:
                        for box in res.boxes:
                            class_id = int(box.cls[0])
                            class_name = self.class_names[class_id]
                            confidence = float(box.conf[0])
                            bbox = box.xywh[0].tolist()
                            class_threshold = self.class_thresholds.get(class_name, self.default_threshold)
                            if class_name in ppe_list and confidence >= class_threshold:
                                # --- COLOR EXCLUSION LOGIC START ---
                                if class_name == "no_shoes":
                                    if self.is_color_in_box(frame, bbox, 'silver'):
                                        print(f"{log_prefix} Suppressed no_shoes: Silver shoes detected.")
                                        continue 
                                if class_name == "no_glove":
                                    if self.is_color_in_box(frame, bbox, 'orange'):
                                        print(f"{log_prefix} Suppressed no_glove: Orange gloves detected.")
                                        continue 
                                # --- COLOR EXCLUSION LOGIC END ---
                                if class_name not in detected_violations:
                                    detected_violations[class_name] = []
                                detected_violations[class_name].append(bbox)
 
                    if detected_violations:
                        print(f"{log_prefix} Violations found: {list(detected_violations.keys())}")
                        
                        annotated_frame = frame.copy()
                        for class_name, bboxes in detected_violations.items():
                            for bbox in bboxes:
                                self.draw_boxes(annotated_frame, bbox, class_name)
                        
                        # Apply new legend styling
                        self.draw_legend(annotated_frame, list(detected_violations.keys()))

                        _, image_data = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                        now = datetime.now()
 
                        # Clean special characters in path
                        safe_area_type = area_type.replace(" ", "_").replace("/", "-")
                        safe_production_house = production_house.replace(" ", "_").replace("/", "-")

                        # Create filename structure
                        im_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{safe_production_house}_{safe_area_type}"
                        object_name = f"{im_id}.jpg"
                        
                        image_url = save_image_to_s3(s3_client, BUCKET_NAME, object_name, image_data.tobytes())

                        if image_url:
                            try: 
                                for class_name in detected_violations:
                                    cur.execute("""
                                        INSERT INTO ppes (class1, production_house, camera_unit, date1, time1, image_url, area, camera_status)
                                        VALUES(%s, %s, %s, %s, %s, %s, %s, %s);
                                    """, (class_name, production_house, ip_address, now.date(), now.strftime('%H:%M:%S'), image_url, area_type, True))
                                print(f"{log_prefix} Successfully inserted {len(detected_violations)} records into the database.")
                            
                            except spg.Error as db_error: 
                                print(f"!!!!!!!!!! DATABASE INSERTION FAILED !!!!!!!!!!")
                                print(f"DB Error Details: {db_error}")
                    else:
                        print(f"{log_prefix} No violations found in this frame.")

            except (cv2.error, ConnectionError, Exception) as e:
                print(f"{log_prefix} An error occurred: {e}. Retrying in {reconnect_delay}s.")
                time.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 300)
            
            finally:
                if cap and cap.isOpened():
                    cap.release()
                if con:
                    con.close()


# --- Execution Block ---
if __name__ == '__main__':
    try:
        with open('camera_list_v4.json') as f:
            devices = json.load(f)
        devices = replace_env_vars(devices)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading camera config: {e}. Exiting.")
        exit(1)

    total_cameras = 0
    for plant, plantData in devices.items():
        for productionHouse, productionHouseData in plantData.items():
            total_cameras += len(productionHouseData)
    
    print(f"Found a total of {total_cameras} cameras in the configuration.")

    model_path = "model/best.pt"
    detector = PpeDetector(model_path)

    with ThreadPoolExecutor(max_workers=total_cameras if total_cameras > 0 else 1) as executor:
        for plant, plantData in devices.items():
            for productionHouse, productionHouseData in plantData.items():
                for areaType, areaData in productionHouseData.items():
                    stream_link = areaData['streamLink']
                    
                    ip_address = 'N/A'
                    if '@' in stream_link and '/' in stream_link:
                        ip_address = stream_link.split('@')[1].split('/')[0]

                    ppe_list = areaData.get("ppeList", [])

                    print(f"Submitting task for {plant} -> {productionHouse} -> {areaType}")
                    executor.submit(detector.process_camera,
                                    areaData, plant, productionHouse, areaType, ip_address, ppe_list)