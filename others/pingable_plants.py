import smtplib
import ping3 # type: ignore
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import time
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

# --- CONFIGURATION ---
sender_email = os.getenv("SENDER_EMAIL")
sender_password = os.getenv("SMTP_PASSWORD")

# Ping settings
PING_TIMEOUT = 3
MAX_RETRIES = 3
CHECK_INTERVAL = 60 * 60 * 12  # 12 Hours

# Your Data Structure (Unchanged IPs/Emails)
plants = {
    # "LoRA ": {
    #     "plants": {
    #         "LoRA Gateway": {"ip": "10.2.1.2"}
    #     },
    #     "common_recipients": {
    #         "primary_recipients": ["saimadhu.muthyala@solargroup.com", 'ayush.shirbhate@solargroup.com'],
    #         "cc_recipients": ['sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
    #     },
    # },
    "Slurry": {
        "plants": {
            "PP-01": {"ip": "10.0.2.128"},
            "PP-01-KP ": {"ip": "10.0.36.189"},
            "PP-03": {"ip": "10.0.5.113"},
            "PP-11": {"ip": "10.0.5.127"},
            "PP-11-KP1": {"ip": "10.0.36.185"},
            "PP-11-KP2": {"ip": "10.0.36.181"},
        },
        "common_recipients": {
            "primary_recipients": ["sai.viswanathan@solargroup.com",'umesh.kubade@solargroup.com', 'shift.incharge@solargroup.com','maint.chk@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "Emulsion": {
        "plants": {
            "PP-04": {"ip": "10.0.5.131"},
            "PP-04-KP": {"ip": "10.0.36.183"},
            "PP-05": {"ip": "192.168.85.73"},
            "PP-05-KP": {"ip": "10.0.36.180"},
            "PP-16": {"ip": "10.0.3.251"},
            "PP-16-KP1": {"ip": "10.0.36.188"},
            "PP-16-KP2": {"ip": "10.0.36.179"},
            "PP-09": {"ip": "192.168.85.74"},
        },
       "common_recipients": {
            "primary_recipients": ['sai.viswanathan@solargroup.com', 'shift.incharge@solargroup.com','maint.chk@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "Shock Tube & DF & PD & SL": {
        "plants": {
            "SN-03-Machine 01": {"ip": "10.0.36.191"},
            "SN-03-Machine 02": {"ip": "10.0.36.194"},
            "SN-03-Machine 03": {"ip": "10.0.36.197"},
            "SN-03-Machine 04": {"ip": "10.0.36.200"},
            "SN-03-Machine 05": {"ip": "10.0.36.203"},
            "SN-03-Machine 06": {"ip": "10.0.36.206"},
            "SN-03-Machine 07": {"ip": "10.0.36.209"},
            "SN-03-Machine 08": {"ip": "10.0.36.212"},
            "SN-03-Machine 09": {"ip": "10.0.36.215"},
            "SN-03-Machine 10": {"ip": "10.0.36.218"},
            "SN-03-Machine 11": {"ip": "10.0.36.221"},
            "SN-03-Machine 12": {"ip": "10.0.36.224"},
            "SN-03-Machine 13": {"ip": "10.0.36.227"},
            "SN-03-Machine 14": {"ip": "10.0.36.230"},
            "SN-03-Machine 15": {"ip": "10.0.36.233"},
            "SN-03-Machine 16": {"ip": "10.0.36.236"},
            "SN-03-Machine 17": {"ip": "10.0.36.239"},
            "SN-03-Machine 18": {"ip": "10.0.36.242"},
            "SN-03-Machine 19": {"ip": "10.0.36.245"},
            "SN-03-Machine 20": {"ip": "10.0.13.113"},
            "SN01_L1_Main": {"ip": "10.0.13.121"},
            "SN01_L1_Powder": {"ip": "10.0.13.117"},
            "SN01_L1_Capston": {"ip": "10.0.13.121"},
            "SN01_L2_Main": {"ip": "10.0.13.96"},
            "SN01_L2_Powder": {"ip": "10.0.13.100"},
            "SN01_L2_Capston": {"ip": "10.0.13.104"},
            "DF_1_PLC_1": {"ip": "10.0.2.190"},
            "DF-2": {"ip": "10.0.2.228"},
            "DF-3": {"ip": "10.0.2.238"},
            "PD-04": {"ip": "10.0.2.124"},
            "PD-05": {"ip": "10.0.28.119"},
            "SL-03": {"ip": "10.0.7.50"},
            "SL-04": {"ip": "10.0.2.77"},
            "SL-05": {"ip": "10.0.13.88"},
        },
        "common_recipients": {
            "primary_recipients": ['prakash.baid@solargroup.com','sn1@solargroup.com', 'shift.inchargedet@solargroup.com','aniket.balsaraf@solargroup.com','yogesh.mishra@solargroup.com','n.mahakulkar@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "Hill-Top": {
        "plants": {
            "PP-15": {"ip": "10.0.28.08"},
            "GB-2": {"ip": "10.0.34.111"},
            "HD-05": {"ip": "10.0.36.199"},
            "PP-06": {"ip": "10.0.2.89"},
            "GB": {"ip": "10.0.28.08"},
            "PP-19": {"ip": "192.168.85.75"},
            "PD-01": {"ip": "10.0.6.251"},
            "Distillation": {"ip": "10.0.2.186"},
        },
        "common_recipients": {
            "primary_recipients": ['hilltop.shiftincharge@solargroup.com', 'hilltop.maint@solargroup.com', 'chetan.bhoyar@solargroup.com','atish.padole@solargroup.com','suresh.chikte@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['ramesh.kedar@solargroup.com','c.tripathi@solargroup.com','sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','jay.jogi@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "PETN & CBH & PD": {
        "plants": {
            "PP-08": {"ip": "10.0.13.122"},
            "PP-10": {"ip": "10.0.13.110"},
            "PP-14": {"ip": "192.168.85.72"},
            "CBH-03": {"ip": "10.0.2.212"},
            "CBH-04": {"ip": "10.0.2.213"},
            "CBH-05": {"ip": "10.0.36.223"},
            "CBH-06": {"ip": "10.0.2.130"},
            "CBH-07": {"ip": "10.0.13.51"},
            "PD-02": {"ip": "10.0.6.254"},
            "PD-03": {"ip": "10.0.2.214"},
            "PD-06": {"ip": "10.0.5.116"},
            "PD-07": {"ip": "10.0.5.138"},
            "PD-08": {"ip": "10.0.13.107"},
        },
        "common_recipients": {
            "primary_recipients": ['sachin.pokale@solargroup.com', 'shift.inchargeacce@solargroup.com', 'maintexe.chk@solargroup.com','maint-mgr.chk@solargroup.com','pushpendra.patel@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['n.mahakulkar@solargroup.com','sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "COB & BULK & SMO": {
        "plants": {
            "COB": {"ip": "10.0.5.241"},
            "BULK": {"ip": "10.0.5.164"},
        },
        "common_recipients": {
            "primary_recipients": ['cobmaint.chk@solargroup.com', 'incharge.cob@solargroup.com', 'jitendra.ojha@solargroup.com','aniket.balsaraf@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['n.mahakulkar@solargroup.com','sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "TNT": {
        "plants": {
            "PP-18": {"ip": "10.0.28.9"},
        },
        "common_recipients": {
            "primary_recipients": ['suchit.bakade@solargroup.com', 'rahul.burde@solargroup.com', 'pushpendra.patel@solargroup.com','maint-mgr.chk@solargroup.com','n.mahakulkar@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['sachin.jamgade@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','jay.jogi@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "CASTBOOSTER COUNTING MODULE": {
        "plants": {
            "CBH-03": {"ip": "10.0.35.250"},
            "CBH-04": {"ip": "10.0.2.223"},
            "CBH-05": {"ip": "10.0.34.250"},
            "CBH-06": {"ip": "10.0.2.80"},
            "CBH-07": {"ip": "10.0.2.81"},
        },
        "common_recipients": {
                "primary_recipients": ['sachin.pokale@solargroup.com', 'shift.inchargeacce@solargroup.com', 'pushpendra.patel@solargroup.com','chk.system@solargroup.com'],
                "cc_recipients": ['n.mahakulkar@solargroup.com','sachin.jamgade@solargroup.com','jay.jogi@solargroup.com','lalit.bopche@solargroup.com'],
        },
    },
    "UTILITY": {
        "plants": {
            "PP-15 COMPRESSOR": {"ip": "10.0.36.251"},
            "PP-19 COMPRESSOR": {"ip": "192.168.85.80"},
            "PP-26 COMPRESSOR": {"ip": "192.168.85.81"},
            "PP-12 COMPRESSOR": {"ip": "10.0.36.182"},
            "PP-14 COMPRESSOR": {"ip": "10.0.36.170"},
            "PP-09 COMPRESSOR": {"ip": "192.168.85.64"},
            "CPH-04 COMPRESSOR": {"ip": "192.168.85.69"},
            "GB-02 COMPRESSOR": {"ip": "10.0.36.190"},
            "SN-04 COMPRESSOR": {"ip": "10.0.36.177"},
            "20 TPH COMPRESSOR": {"ip": "10.0.36.164"},
            "GB-03 COMPRESSOR": {"ip": "10.0.36.166"},
            "RCGB-03 COMPRESSOR": {"ip": "192.168.85.70"},
            "RCGB-06 COMPRESSOR": {"ip": "192.168.85.68"},
            "RCGB-03 COMPRESSOR_2": {"ip": "192.168.85.72"},
            "HRCPH COMPRESSOR": {"ip": "192.168.85.67"},
        },
        "common_recipients": {
            "primary_recipients": ['pradeep.patle@solargroup.com', 'c.tripathi@solargroup.com', 'sachin.gupta@solargroup.com', 'hilltop.maint@solargroup.com','chk.system@solargroup.com'],
            "cc_recipients": ['satish.chordia@solargroup.com', 'sachin.jamgade@solargroup.com', 'lalit.bopche@solargroup.com', 'saimadhu.muthyala@solargroup.com', 'ayush.shirbhate@solargroup.com', 'jay.jogi@solargroup.com', 'anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
    "DART IIoT Server": {
        "plants": {
            "IIoT Thingsboard server": {"ip": "10.0.3.50"},
            "PTC Production server": {"ip": "10.0.3.164"},
            "PTC Quality server": {"ip": "10.0.3.163"},
            "PTC Prod server 2": {"ip": "10.0.3.162"},
            "PTC Qual server 2": {"ip": "10.0.3.165"},
            "KEPserver server": {"ip": "10.0.5.251"},
            "KEPserver server Quality": {"ip": "10.0.5.93"},
        },
        "common_recipients": {
            "primary_recipients": ['chk.system@solargroup.com'],
            "cc_recipients": ['sachin.k@solargroup.com','sachin.jamgade@solargroup.com','jay.jogi@solargroup.com','lalit.bopche@solargroup.com','saimadhu.muthyala@solargroup.com','ayush.shirbhate@solargroup.com','anurag.gokhale@solargroup.com','rashi.channawar@solargroup.com','avantika.malgewar@solargroup.com'],
        },
    },
}

def generate_html_body(plant_group, non_pingable_list):
    """Creates a styled HTML email with red accents."""
    rows = ""
    for name, ip in non_pingable_list:
        rows += f"""
        <tr>
            <td style="padding: 10px; border: 1px solid #ddd;">{name}</td>
            <td style="padding: 10px; border: 1px solid #ddd; color: #8b0000; font-weight: bold;">{ip}</td>
            <td style="padding: 10px; border: 1px solid #ddd; color: #8b0000;">No Response</td>
        </tr>
        """

    html = f"""
    <html>
    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
        <div style="max-width: 600px; margin: auto; border: 1px solid #e0e0e0; border-radius: 8px; overflow: hidden;">
            <div style="background-color: #8b0000; color: white; padding: 20px; text-align: center;">
                <h2 style="margin: 0;">Connectivity Alert</h2>
                <p style="margin: 5px 0 0 0;">Solar IIoT Monitoring System</p>
            </div>
            <div style="padding: 20px;">
                <p>Hello Team,</p>
                <p>The system has detected that the following devices in <strong>{plant_group}</strong> are currently unreachable:</p>
                
                <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                    <thead>
                        <tr style="background-color: #f8f8f8;">
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Plant/Machine Name</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">IP Address</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows}
                    </tbody>
                </table>

                <div style="background-color: #fff3f3; border-left: 5px solid #8b0000; padding: 15px; margin-bottom: 20px;">
                    <strong>Action Required:</strong> Please check the network connectivity or machine power status immediately.
                </div>
                
                <p style="font-size: 0.9em; color: #777;">
                    <em>Note: If the Plant/Machine is intentionally shutdown for maintenance, please ignore this alert.</em>
                </p>
            </div>
            <div style="background-color: #f4f4f4; color: #888; padding: 15px; text-align: center; font-size: 0.8em;">
                Sent by IIoT Server | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
        </div>
    </body>
    </html>
    """
    return html

def send_styled_email(plant_group, non_pingable_plants, recipients_data):
    """Handles SMTP connection and sends the HTML mail."""
    try:
        # Prepare list of (Name, IP) for the HTML generator
        failed_details = [(name, plants[plant_group]["plants"][name]["ip"]) for name in non_pingable_plants]
        
        subject = f"ALERT!!! Data Connectivity Lost | {plant_group} | Solar IIoT"
        
        message = MIMEMultipart("alternative")
        message['Subject'] = subject
        message['From'] = sender_email
        message['To'] = ', '.join(recipients_data["primary_recipients"])
        message['Cc'] = ', '.join(recipients_data["cc_recipients"])

        # Create HTML version
        html_content = generate_html_body(plant_group, failed_details)
        message.attach(MIMEText(html_content, 'html'))

        with smtplib.SMTP('smtp.office365.com', 587) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            all_recipients = recipients_data["primary_recipients"] + recipients_data["cc_recipients"]
            server.sendmail(sender_email, all_recipients, message.as_string())
        
        print(f"[{datetime.now()}] Email sent successfully for {plant_group}")
    except Exception as e:
        print(f"[{datetime.now()}] Failed to send email for {plant_group}: {e}")

def check_plants():
    """Iterates through all groups and pings devices."""
    for plant_group, group_data in plants.items():
        print(f"\nChecking Group: {plant_group}")
        non_pingable_plants = []

        for plant_name, plant_info in group_data["plants"].items():
            ip = plant_info["ip"]
            success = False
            
            # Retry logic
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    delay = ping3.ping(ip, timeout=PING_TIMEOUT)
                    if delay is not None:
                        print(f"  [OK] {plant_name} ({ip}) - {round(delay*1000, 2)}ms")
                        success = True
                        break
                    else:
                        print(f"  [FAIL] {plant_name} ({ip}) - Attempt {attempt}/{MAX_RETRIES}")
                except Exception as e:
                    print(f"  [ERROR] {plant_name} ({ip}): {e}")
            
            if not success:
                non_pingable_plants.append(plant_name)

        if non_pingable_plants:
            send_styled_email(plant_group, non_pingable_plants, group_data["common_recipients"])
        else:
            print(f"Result: All devices in {plant_group} are UP.")

def main():
    print("IIoT Monitoring Service Started...")
    while True:
        check_plants()
        print(f"\nCycle complete. Waiting {CHECK_INTERVAL/3600} hours for next check...")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()