import json
import cv2
import time
import os
import pandas as pd
from sqlalchemy import text # type: ignore
import auth   # your existing DB engine

# -------------------------------------------------------------------
# IMPORTANT: Force RTSP over TCP (fixes auth & UDP issues)
# -------------------------------------------------------------------
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|stimeout;3000"

# -------------------------------------------------------------------
# DB INITIALIZATION
# -------------------------------------------------------------------
def init_db():
    try:
        with auth.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS camera_health (
                    camera_id TEXT PRIMARY KEY,
                    plant TEXT,
                    production_house TEXT,
                    area TEXT,
                    rtsp_link TEXT,
                    status BOOLEAN,
                    last_checked TIMESTAMP
                )
            """))
            conn.commit()
        print("✅ Database Table Ready")
    except Exception as e:
        print(f"❌ DB Error: {e}")

# -------------------------------------------------------------------
# ROBUST CAMERA HEALTH CHECK
# -------------------------------------------------------------------
def is_camera_online(rtsp_url):
    cap = None
    try:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

        if not cap.isOpened():
            return False

        # Allow camera auth + stream startup delay
        time.sleep(0.8)

        # Retry frame reads (CRITICAL FIX)
        for _ in range(5):
            ret, _ = cap.read()
            if ret:
                return True
            time.sleep(0.4)

        return False

    except Exception:
        return False

    finally:
        if cap:
            cap.release()

# -------------------------------------------------------------------
# MAIN MONITOR LOOP
# -------------------------------------------------------------------
def monitor_loop():
    init_db()

    with open("camera_list_v4.json", "r") as f:
        config = json.load(f)

    while True:
        print(f"\n--- Checking Cameras at {time.strftime('%Y-%m-%d %H:%M:%S')} ---")
        updates = []

        # LEVEL 1: Plant
        for plant_name, production_houses in config.items():

            # LEVEL 2: Production House
            for ph_name, areas in production_houses.items():

                # LEVEL 3: Area
                for area_name, details in areas.items():
                    rtsp = details.get("streamLink", "")

                    status = is_camera_online(rtsp)
                    status_str = "🟢 ONLINE" if status else "🔴 OFFLINE"

                    print(f"{plant_name} | {ph_name} | {area_name} → {status_str}")

                    updates.append({
                        "camera_id": f"{plant_name}_{ph_name}_{area_name}",
                        "plant": plant_name,
                        "production_house": ph_name,
                        "area": area_name,
                        "rtsp_link": rtsp,
                        "status": status,
                        "last_checked": pd.Timestamp.now()
                    })

        # -------------------------------------------------------------------
        # DATABASE UPDATE
        # -------------------------------------------------------------------
        if updates:
            df = pd.DataFrame(updates)

            try:
                with auth.engine.connect() as conn:
                    conn.execute(text("TRUNCATE TABLE camera_health"))
                    df.to_sql("camera_health", conn, if_exists="append", index=False)
                    conn.commit()

                print("✅ Database Updated Successfully")

            except Exception as e:
                print(f"❌ DB Update Failed: {e}")

        time.sleep(30)

# -------------------------------------------------------------------
# ENTRY POINT
# -------------------------------------------------------------------
if __name__ == "__main__":
    monitor_loop()
