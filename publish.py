import time
import os
import psycopg2 as spg
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from tb_device_mqtt import TBDeviceMqttClient
from dotenv import load_dotenv

# Load environment variables (Make sure your .env file is in the same folder)
load_dotenv()

# --- THINGSBOARD CONFIG ---
TB_SERVER = "10.0.3.50"
TB_PORT = 1883
TB_TOKEN = "KCDociGqE9couVSX91AG" 
UPDATE_INTERVAL = 10  # Seconds to wait between updates to ThingsBoard

def connect_to_db():
    """Connect to the PostgreSQL database."""
    try:
        con = spg.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database="ppes",
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            port='5432',
            connect_timeout=10
        )
        con.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        return con
    except spg.Error as e:
        print(f"❌ DATABASE CONNECTION FAILED: {e}")
        return None

def main():
    print("🚀 Starting ThingsBoard Publisher Service...")

    # Initialize ThingsBoard Client
    tb_client = TBDeviceMqttClient(TB_SERVER, port=TB_PORT, token=TB_TOKEN)
    try:
        tb_client.connect()
        print("✅ Connected to ThingsBoard!")
    except Exception as e:
        print(f"❌ Failed to connect to ThingsBoard: {e}")
        return

    # Loop forever
    while True:
        con = connect_to_db()
        if con is None:
            time.sleep(5)
            continue

        try:
            with con.cursor() as cur:
                # This query groups by production_house and counts ONLY today's violations
                cur.execute("""
                    SELECT production_house, COUNT(*) 
                    FROM ppes 
                    WHERE date1 = CURRENT_DATE 
                    GROUP BY production_house;
                """)
                
                results = cur.fetchall()
                
                if results:
                    # Format the result into a dictionary: {"Furnace_A": 12, "Line_1": 5}
                    telemetry_data = {row[0]: row[1] for row in results}
                    
                    # Send to ThingsBoard
                    tb_client.send_telemetry(telemetry_data)
                    print(f"📡 Published to TB: {telemetry_data}")
                else:
                    # If there are no violations today, send an empty or default payload if desired
                    print("👍 No violations found for today yet.")

        except spg.Error as e:
            print(f"⚠️ Database query error: {e}")
        except Exception as e:
            print(f"⚠️ ThingsBoard publish error: {e}")
        finally:
            # Always close the DB connection to prevent memory leaks, we will reopen it next loop
            con.close()

        # Wait before checking the database again
        time.sleep(UPDATE_INTERVAL)

if __name__ == '__main__':
    # Ensure script keeps running even if an unexpected error occurs
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\n🛑 Service stopped by user.")
            break
        except Exception as e:
            print(f"🔥 Critical error in main loop: {e}. Restarting in 10 seconds...")
            time.sleep(10)