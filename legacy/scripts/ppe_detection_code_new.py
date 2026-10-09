import os
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;5000000|buffer_size;1024000"

from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
import cv2
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from ultralytics import YOLO
import threading
import time
import boto3
from botocore.client import Config

import psycopg2 as spg
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from datetime import datetime
import json
import torch
import cProfile
import pstats
from io import StringIO
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import numpy as np
import random
from dotenv import load_dotenv
from urllib.parse import quote_plus, quote
# from urllib.parse import quote_plus
import os
load_dotenv()


bucket_name = os.getenv('BUCKET_NAME')
s3_endpoint_url = os.getenv('S3_ENDPOINT_URL')
aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')

def send_email(subject, body, image_url, receivers, cc_receivers=None):
    # Email configuration
    sender_email = os.getenv('SENDER_EMAIL')
    receiver_email = os.getenv('RECEIVER_EMAIL')
    smtp_server = os.getenv('SMTP_SERVER')
    smtp_port = int(os.getenv('SMTP_PORT'))
    smtp_username = os.getenv('SMTP_USERNAME')
    smtp_password = os.getenv('SMTP_PASSWORD')

    # Combine receivers and cc_receivers into a single list
    all_receivers = receivers + (cc_receivers or [])

    # Create MIME message
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = ", ".join(receivers)
    if cc_receivers:
        message["Cc"] = ", ".join(cc_receivers)

    # Create HTML body part
    html_body = f"""
    <html>
        <body>
            Dear Maam/Sir,<br><br>
            
            Please note that we have found the following PPE's violation. You are requested to take immediate action to resolve the issue.<br><br>

            The details are as follows -<br>
            {body}<br><br>

            <img src="{image_url}" alt="Violation Image"><br><br>

            Regards,<br>
            IIoT Department,<br>
            SIIL Chakdoh 
        </body>
    </html>
    """

    # Attach HTML part to the message
    part = MIMEText(html_body, "html")
    message.attach(part)

    try:
        # Connect to SMTP server and send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.sendmail(sender_email, all_receivers, message.as_string())
        print("Email sent successfully.")
    except Exception as e:
        print(f"Error sending email: {str(e)}")


def connect_to_db(db_name="ppes"):
    """
    Connects to the database using credentials.
    """
    # --- CREDENTIALS ARE DEFINED HERE ---
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASS")

    try:
        # The password is a separate Python string variable.
        # psycopg2 handles the special characters correctly. No encoding is needed.
        con = spg.connect(
            host=db_host,
            database=db_name,
            user=db_user,
            password=db_pass,
            port='5432',
            connect_timeout=10
        )
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = con.cursor()
        cur.execute("select version()")
        data = cur.fetchone()
        print("Connection established to:", data)
        return con, cur
    except spg.Error as e:
        print(f"DATABASE CONNECTION FAILED: {e}")
        return None, None
    
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

bucket_name = os.getenv('BUCKET_NAME')

s3 = None

try:
    # Ensure this variable in your .env is: INTERNAL_S3_ENDPOINT_URL=http://127.0.0.1:19000
    endpoint = os.getenv('INTERNAL_S3_ENDPOINT_URL', 'https://127.0.0.1:19000')
    access_key = os.getenv('AWS_ACCESS_KEY_ID')
    secret_key = os.getenv('AWS_SECRET_ACCESS_KEY')

    s3 = boto3.client(
        's3',
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name='us-east-1', # Keep this unless your test script said 'ap-south-1'
        verify=False,
        use_ssl=True,
        config=Config(
            signature_version='s3v4',
            s3={'addressing_style': 'path'}, # <--- THIS FIXES THE CONNECTION ERROR
            retries={'max_attempts': 3}
        )
    )
    
    # Test the connection immediately
    response = s3.list_buckets()
    print("SUCCESS: Connected to MinIO. Buckets found:", [b['Name'] for b in response['Buckets']])

except Exception as e:
    print(f"CRITICAL: S3/MinIO Initialization Failed. Error: {e}")

dir_path = os.path.dirname(os.path.realpath(__file__))

def save_image_to_s3(bucket_name, object_name, image_data):
    global s3 # Ensure we use the global s3 client
    if s3 is None:
        print("CRITICAL: s3 client is not initialized!")
        return None
        
    try:
        current_month_name = datetime.now().strftime("%B").lower()
        object_path = f"{current_month_name}/{object_name}"
        
        s3.put_object(
            Bucket=bucket_name,
            Key=object_path,
            Body=image_data,
            ContentType='image/jpeg'  # <--- Add this so it displays properly in browsers
        )
        return object_path
    except Exception as e:
        print(f"CRITICAL UPLOAD ERROR: {e}")
        return None
    

def upload_file_to_s3(file, bucket_name, st, acl="public-read"):
    try:

        objectpath = st

        # objectpath = "mybucket/" + st
        s3.upload_fileobj(
            file,
            bucket_name,
            objectpath,
            ExtraArgs={
                "ACL": acl
            }
        )
        return "successful"
    except Exception as e:
        print(e)

def create_table_if_not_exists(cur):
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS ppes (
        id SERIAL PRIMARY KEY,
        class1 TEXT,
        production_house TEXT,
        camera_unit TEXT,
        date1 date,
        time1 time,
        image_url TEXT,
        area TEXT
    );
    """
    cur.execute(create_table_sql)



class DetectTray:

    def __init__(self):
        self.device = torch.device("cuda")
        # self.model = YOLO("best_single_v2.pt").to(self.device)
        self.model = YOLO("/home/administrator/Desktop/ppes/best.pt").to(self.device)
        # self.cooldown_tracker = defaultdict(float)

        
        # Bright highlighting color mapping
        self.class_colors = {
            "no_helmet": (255, 0, 0),      # Bright Red (High Contrast)
            "no_glove": (0, 255, 0),       # Bright Green (Vivid)
            "no_goggles": (0, 0, 255),     # Bright Blue (Striking)
            "no_mask": (255, 255, 0),      # Bright Yellow (Very Visible)
            "no_suit": (255, 105, 180),    # Hot Pink (Vibrant)
            "no_shoes": (255, 165, 0)      # Bright Orange (Bold)
        }

        # Class-specific prediction thresholds (adjust these values as needed)
        # self.class_thresholds = {
        #     "no_helmet": 0.80,      # 80% confidence for no_helmet
        #     "no_glove": 0.60,       # 82% confidence for no_glove
        #     "no_goggles": 0.56,     # 62% confidence for no_goggles
        #     "no_mask": 0.58,        # 58% confidence for no_mask
        #     "no_suit": 0.75,        # 80% confidence for no_suit
        #     "no_shoes": 0.80        # 82% confidence for no_shoes
        # }

        self.class_thresholds = {
            "no_helmet": 0.80,      # 80% confidence for no_helmet
            "no_glove": 0.82,       # 82% confidence for no_glove
            "no_goggles": 0.60,     # 60% confidence for no_goggles
            "no_mask": 0.58,        # 58% confidence for no_mask
            "no_suit": 0.65,        # 65% confidence for no_suit
            "no_shoes": 0.85        # 85% confidence for no_shoes
        }
        # Default confidence threshold for all classes if not explicitly defined
        self.default_threshold = 0.55

        # List to store class labels for legend (dynamically updated)
        self.class_labels = list(self.class_colors.keys())

        self.cooldown_tracker = defaultdict(float)



    def random_color(self):
        """
        Generates a random color in RGB format.
        """
        return (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))


    def draw_boxes(self, image, bbox, class_label, box_style=None):
        """
        Draw bounding boxes with color but no text.
        """
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

    def draw_legend(self, image, detected_classes, x_offset=10, y_offset=10, font=cv2.FONT_HERSHEY_COMPLEX, font_scale=1, font_thickness=1, max_width=None, outline_color=(0, 0, 0)):
        """
        Draw a legend showing only the detected classes in the top-left corner of the image.
        The legend is displayed horizontally with outlined text.
        
        :param image: The image on which the legend will be drawn.
        :param detected_classes: List of detected class labels.
        :param x_offset: Horizontal offset for the start position.
        :param y_offset: Vertical offset for the start position.
        :param font: Font type for the text.
        :param font_scale: Font size.
        :param font_thickness: Font thickness.
        :param max_width: Maximum width for a row before wrapping to the next line (optional).
        :param outline_color: Color for the text outline (default is black).
        :return: Image with the drawn legend.
        """
        # Start position for the legend
        x_position = x_offset
        y_position = y_offset
        
        # Define space between boxes and labels
        box_width = 20
        box_height = 20
        spacing = 20  # Space between boxes and labels
        
        # Optional: Define max width for wrapping legend into multiple rows
        row_height = box_height + spacing  # Height of each row (box + label space)
        
        for idx, class_label in enumerate(detected_classes, start=1):
            color = self.class_colors.get(class_label, self.random_color())
            
            # Draw the color box for the class label
            cv2.rectangle(image, 
                        (x_position, y_position), 
                        (x_position + box_width, y_position + box_height), 
                        color, -1)  # -1 to fill the rectangle

            # Create the label text
            label_text = f"{idx}. {class_label}"
            
            # Calculate text size to position it correctly
            (text_width, text_height), _ = cv2.getTextSize(label_text, font, font_scale, font_thickness)
            text_x = x_position + box_width + spacing
            text_y = y_position + box_height // 2 + text_height // 2

            # Draw the outline (by drawing the text multiple times with slight offsets)
            outline_offset = 2  # Offset for the outline

            # Draw the outline text in different directions (top, bottom, left, right)
            for dx in [-outline_offset, 0, outline_offset]:
                for dy in [-outline_offset, 0, outline_offset]:
                    if dx != 0 or dy != 0:
                        cv2.putText(image, label_text, 
                                    (text_x + dx, text_y + dy), 
                                    font, font_scale, outline_color, font_thickness, cv2.LINE_AA)
            
            # Now draw the text itself in the primary color (white or any other)
            cv2.putText(image, label_text, 
                        (text_x, text_y), 
                        font, font_scale, (255, 255, 255), font_thickness, cv2.LINE_AA)

            # Update x_position for the next entry
            x_position += box_width + text_width + spacing

            # Check if we exceed the image width and wrap to the next row
            if max_width and x_position > max_width:
                x_position = x_offset  # Reset x_position to the start of the next row
                y_position += row_height  # Move y_position down for the next row
        
        return image
    
    def should_send_email(self, production_house, area_type):
        key = f"{production_house}_{area_type}"
        last_sent_time = self.cooldown_tracker[key]
        current_time = time.time()
        cooldown_period = 3600  # 15 minutes in seconds

        if current_time - last_sent_time >= cooldown_period:
            self.cooldown_tracker[key] = current_time
            return True
        else:
            return False

        

    def process_camera(self, stream_data, plant, production_house, area_type, ip_address, ppe_list, non_uniform_scale=False):
        try:
            con, cur = connect_to_db()
            if con is None or cur is None:
                print("Failed to connect to the database.")
                return

            create_table_if_not_exists(cur)

            stream_link = stream_data['streamLink']
            print(f"Processing stream: {stream_link}")

            try:
                front = cv2.VideoCapture(stream_link, cv2.CAP_FFMPEG)
            except cv2.error as cv2_error:
                print(f"Error opening video stream {stream_link}: {cv2_error}")
                return

            frame_number = 0
            last_detection_time = time.time()
            update_camera_status(con, production_house, area_type, True)

            if not front.isOpened():
                print(f"Error: Video stream not opened for {stream_link}.")
                return

            while True:
                try:
                    ret, frame = front.read()
                    if not ret:
                        print("Error reading frame: ret =", ret)
                        # Try to reopen the stream
                        front.release()
                        front = cv2.VideoCapture(stream_link, cv2.CAP_FFMPEG)
                        time.sleep(5)  # Add a delay before retrying
                        continue

                    current_time = time.time()
                    if current_time - last_detection_time < 60:
                        continue
                    last_detection_time = current_time

                    if non_uniform_scale:
                        height, width = frame.shape[:2]
                        frame = cv2.resize(frame, (width * 2, height * 2))  # Example of non-uniform scaling

                    # frame = cv2.resize(frame, (1280, 720))  # Change to 1280x720 for higher quality
                    frame = cv2.resize(frame, (1920, 1080))

                    names = {
                        0: 'dog', 1: 'person', 2: 'cat', 3: 'tv', 4: 'car', 5: 'meatballs', 6: 'marinara sauce',
                        7: 'tomato soup', 8: 'chicken noodle soup', 9: 'french onion soup', 10: 'french onion soup',
                        11: 'ribs', 12: 'pulled pork', 13: 'hamburger', 14: 'cavity', 15: 'no_helmet',
                        16: 'no_glove', 17: 'no_goggles', 18: 'no_mask', 19: 'no_suit', 20: 'no_shoes'
                    }

                    # Get predictions from the YOLO model
                    # predictions = self.model.predict(frame, conf=0.65)
                    # detected_classes = set()  # To store unique detected classes
                    # filtered_boxes = []  # To store boxes of relevant detections (filtered by ppe_list)


                    # Get predictions from the YOLO model
                    predictions = self.model.predict(frame, conf=0.65)

                    detected_classes = set()
                    filtered_boxes = []

                    # ---- Collect detections FIRST ----
                    for result in predictions:
                        boxes = result.boxes
                        xywh = boxes.xywh
                        classes = boxes.cls
                        confidences = boxes.conf

                        for b, c, conf in zip(xywh, classes, confidences):
                            b = [round(x) for x in b.tolist()]
                            class_name = names[int(c)]
                            confidence_score = float(conf)

                            class_threshold = self.class_thresholds.get(
                                class_name, self.default_threshold
                            )

                            if confidence_score >= class_threshold and class_name in ppe_list:
                                filtered_boxes.append((b, class_name))
                                detected_classes.add(class_name)

                    # ⛔ NO violation → skip everything
                    if not detected_classes or not filtered_boxes:
                        continue

                    # ⏳ COOLDOWN CHECK (prevents spam)
                    if not self.should_send_email(production_house, area_type):
                        continue

                    # ---- Draw detections ----
                    for b, class_name in filtered_boxes:
                        frame = self.draw_boxes(frame, b, class_name)

                    frame = self.draw_legend(frame, list(detected_classes))

                    # ---- Save image ONCE ----
                    labeled_image = frame.copy()

                    date1 = datetime.now().strftime("%Y-%m-%d")
                    time1 = datetime.now().strftime("%H:%M:%S")
                    time_1 = datetime.now().strftime("%H%M%S")

                    im_id = f"{date1}{time_1}_{production_house}_{area_type}"
                    
                    image_data = cv2.imencode(".jpg", labeled_image)[1].tobytes()
                    filename = f"{im_id}.jpg"

                    actual_s3_path = save_image_to_s3(bucket_name, filename, image_data)

                    if actual_s3_path:
                        # URL Encode the path (turns spaces into %20 but leaves the '/' alone)
                        safe_s3_path = quote(actual_s3_path)
                        
                        # Construct the URL using the SAFE path
                        image_url = f"https://ppes-siil.solargroup.com:9000/{bucket_name}/{safe_s3_path}"
                        print(f"Public Link: {image_url}")

                        print(production_house)
                        print(area_type)

                        # ---- DB insert (one image, many violations) ----
                        with con, con.cursor() as cur_thread:
                            for class_name in detected_classes:
                                try:
                                    cur_thread.execute("""
                                        INSERT INTO ppes (
                                            class1, production_house, camera_unit,
                                            date1, time1, image_url, area
                                        )
                                        VALUES (%s, %s, %s, %s, %s, %s, %s);
                                    """, (
                                        class_name,
                                        production_house,
                                        ip_address,
                                        date1,
                                        time1,
                                        image_url,
                                        area_type
                                    ))
                                    con.commit()
                                    print(f"Detected: {class_name}")

                                except spg.Error as e:
                                    con.rollback()
                                    print("DB insert error:", e)
                    else:
                        print("S3 Upload Failed: Skipping database insert to prevent broken URLs.")
                    frame_number += 1

                except cv2.error as cv2_error:
                    print("OpenCV Error: ", cv2_error)
                    print(f"Error opening video stream {stream_link}: {cv2_error}")
                    update_camera_status(con, production_house, area_type, False)
                    time.sleep(5)  # Add a delay before retrying
                except Exception as e:
                    print("An error occurred:", str(e))
                finally:
                    time.sleep(0.1)  # Optional: Add a small delay to reduce CPU usage
        finally:
            update_camera_status(con, production_house, area_type, False)
            con.close()  # Close the connection when the thread is done
            front.release()  # Release the video capture object

            
    def profile_process_camera(self, stream_data, plant, production_house, area_type, ip_address, ppe_list):
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



def update_camera_status(connection, production_house, area_type, status):
    try:
        with connection, connection.cursor() as cur:
            cur.execute("""
                UPDATE ppes
                SET camera_status = %s
                WHERE production_house = %s AND area = %s;
            """, (status, production_house, area_type))
        print("Camera status updated successfully.")
    except spg.Error as e:
        print("Error updating camera status:", str(e))



if __name__ == '__main__':
    devices = json.loads(open('camera_list_v4_newplants.json').read())

    tray_detector = DetectTray()

    with ThreadPoolExecutor(max_workers=175) as executor:  # Adjust max_workers based on your system resources
        for plant, plantData in devices.items():
            for productionHouse, productionHouseData in plantData.items():
                for areaType, areaData in productionHouseData.items():
                    stream_link = areaData['streamLink']
                    after_at = stream_link.split('@')[1]
                    ip_address = after_at.split(':')[0]

                    ppe_list = areaData.get("ppeList", [])

                    executor.submit(tray_detector.profile_process_camera,
                                    areaData, plant, productionHouse, areaType, ip_address, ppe_list)
                


