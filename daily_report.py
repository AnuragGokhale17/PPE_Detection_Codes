import os
import time
from datetime import datetime, timedelta
import psycopg2 as spg
import pandas as pd
import matplotlib.pyplot as plt
import io
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def connect_to_db():
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASS")
    db_name = "ppes"
    try:
        con = spg.connect(host=db_host, database=db_name, user=db_user, password=db_pass, port='5432', connect_timeout=10)
        return con
    except spg.Error as e:
        print(f"DATABASE CONNECTION FAILED: {e}")
        return None

def fetch_data_for_date(target_date):
    con = connect_to_db()
    if not con: return None
    query = "SELECT class1, production_house FROM ppes WHERE date1 = %s;"
    try:
        df = pd.read_sql_query(query, con, params=(target_date,))
        con.close()
        return df
    except Exception as e:
        print(f"Error querying data: {e}")
        return None

def generate_global_graphs(df, target_date):
    # Prepare data for STACKED BAR CHART
    pivot_df = df.groupby(['production_house', 'class1']).size().unstack(fill_value=0)
    
    # Calculate totals for sorting and for top-of-bar labels
    pivot_df['total_val'] = pivot_df.sum(axis=1)
    pivot_df = pivot_df.sort_values(by='total_val', ascending=False)
    totals = pivot_df['total_val'].tolist() # Keep for labels
    plot_df = pivot_df.drop(columns='total_val')

    # Larger figure for better spacing
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 9))
    fig.patch.set_facecolor('#ffffff')
    fig.suptitle(f"PPE Violation Analytics - {target_date}", fontsize=22, fontweight='bold', color='#1B365D', y=0.98)
    
    # Solar-inspired color palette
    class_colors = {
        "no_helmet": "#E31837",   # Solar Red
        "no_glove": "#1B365D",    # Solar Navy
        "no_shoes": "#45B7D1",    # Cyan
        "no_suit": "#FFB347",     # Orange
        "no_mask": "#98D8C8",     # Mint
        "no_goggles": "#77DD77"   # Green
    }
    
    current_colors = [class_colors.get(col, "#cccccc") for col in plot_df.columns]

    # --- GRAPH 1: STACKED BAR CHART ---
    plot_df.plot(kind='bar', stacked=True, ax=ax1, color=current_colors, edgecolor='white', linewidth=0.7)
    
    # Add numbers inside segments (White)
    for container in ax1.containers:
        labels = [int(v) if v > 0 else "" for v in container.datavalues]
        ax1.bar_label(container, labels=labels, label_type='center', color='white', fontweight='bold', fontsize=10)

    # Add TOTAL number on top of the bar (Navy)
    for i, total in enumerate(totals):
        ax1.text(i, total + 0.5, str(int(total)), ha='center', va='bottom', fontweight='bold', fontsize=12, color='#1B365D')

    ax1.set_title('Violations by Production Unit (Bifurcated)', fontsize=16, color='#1B365D', pad=20, fontweight='bold')
    ax1.set_ylabel('Total Number of Violations', color='#1B365D', fontsize=12, fontweight='bold')
    ax1.set_xlabel('Production House', color='#1B365D', fontsize=12, fontweight='bold')
    ax1.legend(title="Violation Type", fontsize=10, loc='upper right', frameon=True)
    ax1.grid(axis='y', linestyle='--', alpha=0.3)
    plt.setp(ax1.get_xticklabels(), rotation=45, ha='right', fontsize=10, fontweight='bold', color='#1B365D')

    # --- GRAPH 2: GLOBAL BREAKDOWN (PIE CHART) ---
    class_counts = df['class1'].value_counts()
    pie_colors = [class_colors.get(idx, "#cccccc") for idx in class_counts.index]
    
    # autopct labels set to white for visibility on dark slices
    wedges, texts, autotexts = ax2.pie(
        class_counts.values, 
        labels=class_counts.index, 
        autopct='%1.1f%%', 
        startangle=90, 
        colors=pie_colors, 
        wedgeprops={'edgecolor': 'white', 'linewidth': 2},
        pctdistance=0.75
    )
    
    # Styling text for pie chart
    plt.setp(texts, fontsize=12, fontweight='bold', color='#1B365D') # External labels
    plt.setp(autotexts, fontsize=11, fontweight='bold', color='white') # Percentages
    
    ax2.set_title('Global Breakdown by Class', fontsize=16, color='#1B365D', pad=20, fontweight='bold')

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    
    # Save to memory buffer
    img_buffer = io.BytesIO()
    plt.savefig(img_buffer, format='png', bbox_inches='tight', dpi=120)
    img_buffer.seek(0)
    plt.close()
    return img_buffer.getvalue()

def send_daily_report_email(target_date, image_bytes, total_count):
    sender_email = os.getenv('SENDER_EMAIL')
    receivers = [os.getenv('RECEIVER_EMAIL', 'jay.jogi@solargroup.com')]
    smtp_server, smtp_port = os.getenv('SMTP_SERVER'), int(os.getenv('SMTP_PORT'))
    
    message = MIMEMultipart("related")
    message["Subject"] = f"DAILY PPE REPORT: {total_count} Violations - {target_date}"
    message["From"] = sender_email
    message["To"] = ", ".join(receivers)
    
    html_content = f"""
    <html>
        <body style="margin: 0; padding: 20px; background-color: #DDEAF6; font-family: 'Segoe UI', Tahoma, sans-serif;">
            <div style="max-width: 1100px; margin: 0 auto;">
                
                <h1 style="color: #1B365D; border-bottom: 4px solid #E31837; padding-bottom: 10px; margin-bottom: 5px;">PPE Safety Violation Analytics</h1>
                <p style="color: #555; margin-bottom: 25px; font-weight: bold;">Reporting Period: {target_date}</p>

                <!-- Summary Highlight Box -->
                <div style="background-color: #ffffff; padding: 25px; border-left: 8px solid #E31837; border-radius: 4px; margin-bottom: 30px; box-shadow: 0 4px 10px rgba(0,0,0,0.08);">
                    <span style="color: #1B365D; font-size: 14px; font-weight: bold; text-transform: uppercase; letter-spacing: 1.2px;">Operational Summary</span><br>
                    <p style="margin: 10px 0 0 0; color: #333; font-size: 19px;">
                        Total violations recorded across all units: <b style="color: #E31837; font-size: 28px;">{total_count}</b>
                    </p>
                </div>

                <div style="width: 100%;">
                    <img src="cid:summary_graph" style="width: 100%; display: block; border-radius: 6px; box-shadow: 0 6px 18px rgba(0,0,0,0.15);">
                </div>

                <p style="margin-top: 40px; color: #1B365D; font-size: 15px; line-height: 1.6;">
                    This report provides a detailed classification of safety non-compliance for managerial review.<br>
                    Regards,<br><b>IIoT Department</b><br>SIIL Chakdoh
                </p>
            </div>
        </body>
    </html>
    """
    message.attach(MIMEText(html_content, "html"))
    part_image = MIMEImage(image_bytes)
    part_image.add_header('Content-ID', '<summary_graph>')
    message.attach(part_image)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(os.getenv('SMTP_USERNAME'), os.getenv('SMTP_PASSWORD'))
            server.sendmail(sender_email, receivers, message.as_string())
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Analytics Report Dispatched.")
    except Exception as e:
        print(f"SMTP Error: {e}")

def generate_and_send_report():
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    df = fetch_data_for_date(yesterday)
    
    if df is None or df.empty:
        print(f"Zero data found for {yesterday}.")
        return

    total_violations = len(df)
    img_bytes = generate_global_graphs(df, yesterday)
    send_daily_report_email(yesterday, img_bytes, total_violations)

def run_scheduler():
    # Initial trigger for testing
    generate_and_send_report()
    
    while True:
        now = datetime.now()
        target = now.replace(hour=9, minute=30, second=0, microsecond=0)
        if now >= target: target += timedelta(days=1)
        
        wait_seconds = (target - now).total_seconds()
        print(f"Engine Sleeping. Next report: {target.strftime('%Y-%m-%d %H:%M')}")
        time.sleep(wait_seconds)
        
        generate_and_send_report()
        time.sleep(60)

if __name__ == '__main__':
    run_scheduler()