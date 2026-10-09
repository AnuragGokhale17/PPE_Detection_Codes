import os
import json
from datetime import datetime, time, timedelta
from urllib.parse import urlparse
from functools import wraps
from urllib.parse import quote_plus, quote, urlparse, unquote, unquote_plus
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash, send_from_directory # type: ignore
import pandas as pd
from sqlalchemy import create_engine # type: ignore
from minio import Minio # type: ignore
from minio.error import S3Error # type: ignore
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix # type: ignore
import psycopg2

# Import Authentication Logic from your auth.py file
import auth

# --- CONFIGURATION & SETUP ---
load_dotenv()

# app = Flask(__name__)
# app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1)

# --- SECURITY RULE: 10 Minute Auto-Logout ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=10)

@app.before_request
def make_session_permanent():
    session.permanent = True  # Resets the 10-minute timer on every page click

# IMPORTANT: Ensure this matches the SECRET_KEY in your .env file
app.secret_key = os.getenv('SECRET_KEY', 'default_secret_key_replace_in_prod')

# Database Setup
# Note: %40 represents the @ symbol in the connection string
user=os.getenv("DB_USER")
pass_enc=os.getenv("DB_PASS_ENC")
host=os.getenv("DB_HOST")
database=os.getenv("DB_NAME")
DATABASE_URL = f"postgresql://{user}:{pass_enc}@{host}/{database}"
engine = create_engine(DATABASE_URL)

# MinIO Setup
minio_client = Minio(
    "127.0.0.1:9000",
    access_key="admin",
    secret_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
    secure=True
)


# --- DECORATORS (SECURITY LAYERS) ---

def login_required(f):
    """Decorator to restrict access to logged-in users only."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to restrict access to Admins only."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('user_role') != 'admin':
            flash('Access denied. Admin privileges required.', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

def deduplicate_5min(df):
    df = df.copy()

    df['datetime'] = pd.to_datetime({
        'year': df['date1'].apply(lambda x: x.year),
        'month': df['date1'].apply(lambda x: x.month),
        'day': df['date1'].apply(lambda x: x.day),
        'hour': df['time1'].apply(lambda x: x.hour),
        'minute': df['time1'].apply(lambda x: x.minute),
        'second': df['time1'].apply(lambda x: x.second),
    })

    df['bucket_5min'] = df['datetime'].dt.floor('5T')

    df = (
        df.sort_values('datetime')
          .drop_duplicates(
              subset=[
                  'area',
                  'production_house',
                  'class1',
                  'bucket_5min'
              ],
              keep='first'
          )
    )

    return df.drop(columns=['bucket_5min'])


def generate_presigned_url(bucket_name, object_name, expiry=3600):
    try:
        # Generate the presigned URL for accessing the object
        url = minio_client.presigned_get_object(bucket_name, object_name, expires=timedelta(seconds=expiry))
        return url
    except S3Error as err:
        print(f"Error generating presigned URL: {err}")
        return None


def get_unique_values(table, column_name):
    query = f"SELECT DISTINCT {column_name} FROM {table}"
    try:
        values = pd.read_sql(query, engine)[column_name].tolist()
        return [x for x in values if x]
    except:
        return []

def extract_name(email):
    if not email: return ""
    try:
        name_parts = email.split('@')[0].split('.')
        capitalized = [part.capitalize() for part in name_parts]
        return ' '.join(capitalized)
    except:
        return email

# --- CORE LOGIC: MAIN DASHBOARD & NON-COMPLIANT CLASS RESOLUTION ---

NON_COMPLIANT_CLASSES = [
    "No Helmet",
    "No Gloves",
    "No Shoes",
    "No Suit",
    "No Goggles",
    "No Mask"
]

def parse_non_compliant_violations(val):
    """
    Parses any raw, legacy, or multi-class violation string and returns
    only the distinct canonical non-compliant classes. Filters out compliant states.
    """
    if not val or pd.isna(val):
        return []
    
    results = set()
    parts = [p.strip() for p in str(val).replace(';', ',').split(',') if p.strip()]
    for p in parts:
        lower_p = p.lower()
        if lower_p in ['compliant', 'none', 'ok'] or lower_p.startswith('compliant'):
            continue
        
        if 'helmet' in lower_p and ('no' in lower_p or lower_p == 'no_helmet'):
            results.add('No Helmet')
        elif 'glove' in lower_p and ('no' in lower_p or 'no_glove' in lower_p):
            results.add('No Gloves')
        elif 'shoe' in lower_p and ('no' in lower_p or 'no_shoe' in lower_p):
            results.add('No Shoes')
        elif 'suit' in lower_p and ('no' in lower_p or lower_p == 'no_suit'):
            results.add('No Suit')
        elif 'goggle' in lower_p and ('no' in lower_p or 'no_goggle' in lower_p):
            results.add('No Goggles')
        elif 'mask' in lower_p and ('no' in lower_p or lower_p == 'no_mask'):
            results.add('No Mask')
            
    return [cls for cls in NON_COMPLIANT_CLASSES if cls in results]

def apply_deduplication_rule(df):
    """
    Filters the dataframe so that for a specific (Area, Class),
    violations only appear once every 10 minutes.
    """
    if df.empty:
        return df

    # Create a full datetime object for calculation
    df['full_dt'] = pd.to_datetime(df['date1'].astype(str) + ' ' + df['time1'].astype(str))
    
    # Sort strictly by time to ensure we process in order
    df = df.sort_values(by='full_dt')
    
    valid_indices = []
    # Dictionary to track last seen time: { ('Area1', 'Helmet'): timestamp }
    last_seen = {} 

    for index, row in df.iterrows():
        key = (row['area'], row['class1']) # The unique combination
        current_time = row['full_dt']
        
        if key not in last_seen:
            # First time seeing this violation in this area
            last_seen[key] = current_time
            valid_indices.append(index)
        else:
            # Check time difference
            time_diff = (current_time - last_seen[key]).total_seconds()
            if time_diff >= 300: # 600 seconds = 10 minutes
                last_seen[key] = current_time
                valid_indices.append(index)
    
    # Return only the rows that passed the logic
    return df.loc[valid_indices].copy()

# --- UPDATED DATA FETCHING ---
def get_main_data(start_date, end_date, selected_shifts, selected_areas, selected_production_houses, selected_classes):
    # 1. Fetch Raw Data from DB
    query = f"SELECT violation, id, camera_status, area, production_house, class1, date1, time1, image_url FROM ppes WHERE date1 >= '{start_date}' AND date1 <= '{end_date}' AND violation = true"
    data = pd.read_sql(query, engine)

    # 2. Apply Shift Logic (Before filtering, to ensure Shift filter works on raw times if needed, 
    # but usually better to apply shift logic first so we filter correct data)
    data['time1'] = pd.to_datetime(data['time1'].astype(str), format='%H:%M:%S').dt.time
    conditions = [
        ((data['time1'] >= time(6, 0)) & (data['time1'] <= time(14, 29, 59))),
        ((data['time1'] >= time(14, 30)) & (data['time1'] <= time(22, 59, 59))),
        ((data['time1'] >= time(23, 0)) | (data['time1'] <= time(5, 59, 59))) | ((data['time1'] >= time(0, 0)) & (data['time1'] <= time(2, 29, 59)))
    ]
    values = ['Shift A', 'Shift B', 'Shift C']
    data['shift'] = pd.Series(pd.NA, index=data.index)
    for condition, value in zip(conditions, values):
        data.loc[condition, 'shift'] = value

    # 3. Apply User Filters (Filters from Sidebar)
    if selected_shifts: data = data[data['shift'].isin(selected_shifts)]
    if selected_areas: data = data[data['area'].isin(selected_areas)]
    if selected_production_houses: data = data[data['production_house'].isin(selected_production_houses)]
    if selected_classes:
        data = data[data['class1'].apply(lambda val: any(c in parse_non_compliant_violations(val) for c in selected_classes))]

    # 4. === APPLY 10-MINUTE LOGIC HERE ===
    # This ensures the counts and the table only show the reduced data
    data = apply_deduplication_rule(data)

    # 5. Get Counts based on the filtered data
    total_v = len(data)

    # Camera Health (Independent of filters)
    try:
        camera_health_df = pd.read_sql("SELECT * FROM camera_health", engine)
        true_count = len(camera_health_df[camera_health_df['status'] == True])
        false_count = len(camera_health_df[camera_health_df['status'] == False])
    except:
        true_count = 0
        false_count = 0

    return data, total_v, true_count, false_count


# --- CORE LOGIC: NOTIFICATIONS DASHBOARD ---

def get_notification_data(start_date, end_date, shifts, areas, phs, classes, recipients):
    query = f"SELECT id, class_label, production_house, area, to_recipients, cc_recipients, insert_date, insert_time FROM ppes_emails_records WHERE insert_date >= '{start_date}' AND insert_date <= '{end_date}'"
    data = pd.read_sql(query, engine)
    
    # Shift Logic (Same as main)
    data['insert_time'] = pd.to_datetime(data['insert_time'].astype(str), format='%H:%M:%S').dt.time
    conditions = [
        ((data['insert_time'] >= time(6, 0)) & (data['insert_time'] <= time(14, 29, 59))),
        ((data['insert_time'] >= time(14, 30)) & (data['insert_time'] <= time(22, 59, 59))),
        ((data['insert_time'] >= time(23, 0)) | (data['insert_time'] <= time(5, 59, 59))) | ((data['insert_time'] >= time(0, 0)) & (data['insert_time'] <= time(2, 29, 59)))
    ]
    values = ['Shift A', 'Shift B', 'Shift C']
    data['shift'] = pd.Series(pd.NA, index=data.index)
    for condition, value in zip(conditions, values):
        data.loc[condition, 'shift'] = value

    # Filters
    if shifts: data = data[data['shift'].isin(shifts)]
    if areas: data = data[data['area'].isin(areas)]
    if phs: data = data[data['production_house'].isin(phs)]
    if classes: data = data[data['class_label'].isin(classes)]
    if recipients: data = data[data['to_recipients'].isin(recipients)]

    return data


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        user = auth.get_user_by_email(email)
        
        if user:
            # 1. RULE: Check if account is locked (3 failed attempts / 30 mins)
            is_locked, lockout_msg = auth.check_lockout(user)
            if is_locked:
                flash(lockout_msg, 'error')
                return render_template('login.html')

            if not user.is_active:
                flash('Account is inactive. Contact admin.', 'error')
                return redirect(url_for('login'))

            # 2. Verify Password
            if auth.verify_password(password, user._password_hash):
                # SUCCESS: Reset failed attempts
                auth.reset_login_attempts(user.id)

                # 3. RULE: Check Password Expiry (30 days)
                if auth.is_password_expired(user.password_updated_at):
                    session['temp_reset_email'] = email # Store to allow reset
                    flash('Your password has expired (30-day policy). Please reset it.', 'warning')
                    return redirect(url_for('forgot_password'))

                # Proceed to OTP
                otp_code = auth.generate_otp()
                try:
                    auth.store_otp(user.id, otp_code)
                    if auth.send_otp_email(email, otp_code):
                        session['temp_login_email'] = email
                        session['temp_user_id'] = user.id
                        session['temp_user_role'] = user.role
                        return redirect(url_for('verify_otp_route'))
                    else:
                        flash('Error sending OTP email.', 'error')
                except Exception as e:
                    print(f"Login error: {e}")
                    flash('System error during login.', 'error')
            else:
                # FAILURE: Increment failed attempts and log
                auth.handle_failed_login(user.id, user.failed_attempts)
                auth.log_activity('Login Failed', user.id, email, 'Incorrect password')
                flash('Invalid email or password.', 'error')
        else:
            # Email not found
            flash('Invalid email or password.', 'error')
            
    return render_template('login.html')


@app.route('/debug-ip')
def debug_ip():
    return jsonify({
        "remote_addr": request.remote_addr,
        "x_forwarded_for": request.headers.get("X-Forwarded-For"),
        "x_real_ip": request.headers.get("X-Real-IP"),
        "all_headers": dict(request.headers)
    })


# --- PASSWORD RESET ROUTES ---

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form.get('email')
        
        # 1. Check if user exists
        user = auth.get_user_by_email(email)
        
        # 2. If exists, send email. 
        # NOTE: For security, we usually show the same success message 
        # even if the email doesn't exist, to prevent email enumeration.
        if user:
            token = auth.generate_reset_token(email)
            if auth.send_password_reset_email(email, token):
                auth.log_activity('Password Reset Request', user.id, email, 'Reset link sent via email')
            else:
                flash('Error sending email. Please try again later.', 'error')
                return redirect(url_for('forgot_password'))
        
        flash('If an account exists for that email, we have sent a password reset link.', 'success')
        return redirect(url_for('login'))
        
    return render_template('forgot_password.html')


@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    email = auth.verify_reset_token(token)
    if not email:
        flash('The reset link is invalid or has expired.', 'error')
        return redirect(url_for('forgot_password'))
    
    if request.method == 'POST':
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            flash('Passwords do not match.', 'error')
            return redirect(url_for('reset_password', token=token))
        
        # This function now checks: 14 chars, Complexity, and Last 5 History
        success, message = auth.update_user_password(email, password)
        
        if success:
            user = auth.get_user_by_email(email)
            auth.log_activity('Password Reset Success', user.id if user else None, email, 'Password updated')
            flash('Password reset successful. Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            # This will show "Cannot reuse last 5 passwords" or "Too short"
            flash(message, 'error')
            
    return render_template('reset_password.html', token=token)


@app.route('/verify-otp', methods=['GET', 'POST'])
def verify_otp_route():
    if 'temp_user_id' not in session:
        return redirect(url_for('login'))
    
    email = session.get('temp_login_email')
    
    if request.method == 'POST':
        otp_input = request.form.get('otp')
        user_id = session.get('temp_user_id')
        
        is_valid, message = auth.verify_otp(user_id, otp_input)
        
        if is_valid:
            # Finalize Login
            session.pop('temp_user_id', None)
            session.pop('temp_login_email', None)
            
            session['user_id'] = user_id
            session['user_email'] = email
            session['user_role'] = session.get('temp_user_role')
            session.pop('temp_user_role', None)
            
            # Log Activity
            auth.log_activity('Login Success', user_id, email, 'User logged in via OTP')
            
            if session['user_role'] == 'admin':
                return redirect(url_for('admin_panel'))
            return redirect(url_for('index'))
        else:
            flash(message, 'error')
            
    return render_template('verify_otp.html', email=email)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        auth.log_activity('Logout', session['user_id'], session['user_email'], 'User logged out')
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

# --- ADMIN ROUTES ---

@app.route('/admin', methods=['GET'])
@admin_required
def admin_panel():
    users = auth.get_all_users()
    logs = auth.get_activity_logs(limit=100) # Fetch last 100 logs
    # logs = auth.log_activity(limit=1000) # Fetch last 100 logs

    return render_template('admin_panel.html', users=users, logs=logs)

@app.route('/admin/add_user', methods=['POST'])
@admin_required
def add_user():
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    success, message = auth.add_new_user(email, password, role)
    
    if success:
        auth.log_activity('Add User', session['user_id'], session['user_email'], f'Added user {email}')
        flash(message, 'success')
    else:
        flash(message, 'error')
        
    return redirect(url_for('admin_panel'))

@app.route('/admin/toggle_user', methods=['POST'])
@admin_required
def toggle_user():
    user_id = request.form.get('user_id')
    if auth.toggle_user_status(user_id):
        auth.log_activity('Toggle Status', session['user_id'], session['user_email'], f'Toggled user ID {user_id}')
        flash('User status updated.', 'success')
    else:
        flash('Failed to update user status.', 'error')
    return redirect(url_for('admin_panel'))

@app.route('/admin/delete_user', methods=['POST'])
@admin_required
def delete_user():
    user_id = request.form.get('user_id')
    if auth.delete_user(user_id):
        auth.log_activity('Delete User', session['user_id'], session['user_email'], f'Deleted user ID {user_id}')
        flash('User deleted successfully.', 'success')
    else:
        flash('Failed to delete user.', 'error')
    return redirect(url_for('admin_panel'))

# --- DASHBOARD API ROUTES (PROTECTED) ---

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/api/filters', methods=['GET', 'POST']) # Changed to accept POST
@login_required
def get_filters():
    # Default dates (today) if not provided
    today = datetime.now().strftime('%Y-%m-%d')
    start_date = today
    end_date = today

    # If the frontend sends specific dates, use them
    if request.method == 'POST':
        req_data = request.json
        start_date = req_data.get('start_date', today)
        end_date = req_data.get('end_date', today)

    # Helper to get values filtered by date
    def get_values_by_date(table, column, date_column):
        query = f"SELECT DISTINCT {column} FROM {table} WHERE {date_column} >= '{start_date}' AND {date_column} <= '{end_date}'"
        try:
            values = pd.read_sql(query, engine)[column].tolist()
            return sorted([x for x in values if x])
        except:
            return []

    return jsonify({
        "areas": get_values_by_date('ppes', 'area', 'date1'),
        "production_houses": get_values_by_date('ppes', 'production_house', 'date1'),
        "classes": NON_COMPLIANT_CLASSES,
        "recipients": get_values_by_date('ppes_emails_records', 'to_recipients', 'insert_date'),
        "shifts": ['Shift A', 'Shift B', 'Shift C']
    })

@app.route('/api/export_excel', methods=['POST'])
@login_required
def export_excel():
    payload = request.json

    df, total_v, cam_active, cam_inactive = get_main_data(
        payload['start_date'],
        payload['end_date'],
        payload.get('shifts', []),
        payload.get('areas', []),
        payload.get('production_houses', []),
        payload.get('classes', [])
    )

    if df.empty:
        return jsonify({"error": "No data found"}), 400

    # 🔥 5-minute dedup
    df = deduplicate_5min(df)

    # Summary sheets
    summary_df = pd.DataFrame([
        ["Total Violations", len(df)],
        ["Active Cameras", cam_active],
        ["Inactive Cameras", cam_inactive]
    ], columns=["Metric", "Value"])

    ph_df = df['production_house'].value_counts().reset_index()
    ph_df.columns = ["Production House", "Count"]

    area_df = df['area'].value_counts().reset_index()
    area_df.columns = ["Area", "Count"]

    class_counter = {cls: 0 for cls in NON_COMPLIANT_CLASSES}
    for val in df['class1']:
        for m in parse_non_compliant_violations(val):
            class_counter[m] += 1
    class_df = pd.DataFrame([
        {"Violation Class": k, "Count": v}
        for k, v in class_counter.items()
    ])

    filename = f"PPE_Report_{payload['start_date']}_to_{payload['end_date']}.xlsx"
    path = f"/tmp/{filename}"

    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        df.to_excel(writer, index=False, sheet_name="Raw Data")
        summary_df.to_excel(writer, index=False, sheet_name="Summary")
        ph_df.to_excel(writer, index=False, sheet_name="By Production House")
        area_df.to_excel(writer, index=False, sheet_name="By Area")
        class_df.to_excel(writer, index=False, sheet_name="By Class")

    return jsonify({"success": True, "filename": filename})


@app.route('/api/download_excel/<filename>')
@login_required
def download_excel(filename):
    return send_from_directory("/tmp", filename, as_attachment=True)


@app.route('/api/dashboard_data', methods=['POST'])
@login_required
def dashboard_data():
    req = request.json
    start_date = req.get('start_date')
    end_date = req.get('end_date')
    
    # Fetch Data
    df, total_v, cam_active, cam_inactive = get_main_data(
        start_date, end_date, 
        req.get('shifts', []), req.get('areas', []), 
        req.get('production_houses', []), req.get('classes', [])
    )
    
    df = df.sort_values(by=['date1', 'time1'], ascending=False)
    
    # Chart Prep: Categorical
    ph_counts = df['production_house'].value_counts().to_dict()
    bar_ph = [{"name": k, "value": v} for k,v in ph_counts.items()]

    area_counts = df['area'].value_counts().head(20).to_dict()
    bar_area = [{"name": k, "value": v} for k,v in area_counts.items()]

    violation_counts = {cls: 0 for cls in NON_COMPLIANT_CLASSES}
    if not df.empty:
        for val in df['class1']:
            for m in parse_non_compliant_violations(val):
                violation_counts[m] += 1
    pie_class = [{"name": cls, "value": count} for cls, count in violation_counts.items() if count > 0]
    if not pie_class:
        pie_class = [{"name": cls, "value": 0} for cls in NON_COMPLIANT_CLASSES]

    # --- UPDATED TREND LOGIC ---
    trend_series = []
    if not df.empty:
        # Create full datetime column
        df['datetime'] = pd.to_datetime(df['date1'].astype(str) + ' ' + df['time1'].astype(str))
        
        # Determine frequency based on date range
        start_dt = pd.to_datetime(start_date)
        end_dt = pd.to_datetime(end_date)
        day_diff = (end_dt - start_dt).days

        if day_diff <= 1:
            # Short Range (Today/Yesterday) -> Hourly Trend, Non-Cumulative
            df['rounded_datetime'] = df['datetime'].dt.floor('h') # Group by Hour
        else:
            # Long Range -> Daily Trend, Non-Cumulative
            df['rounded_datetime'] = df['datetime'].dt.floor('d') # Group by Day

        # Group and Count
        df_sorted = df.sort_values(by='rounded_datetime')
        grouped = df_sorted.groupby('rounded_datetime').size()
        
        # Format for ECharts (Non-Cumulative)
        for dt, count in grouped.items():
            # If Hourly, show Time; If Daily, show Date
            label = str(dt) 
            trend_series.append({"datetime": label, "value": int(count)})

    # Inactive Cameras Analysis
    try:
        health_df = pd.read_sql("SELECT * FROM camera_health WHERE status = false", engine)
        if not health_df.empty:
            ph_col = 'production_house' if 'production_house' in health_df.columns else None
            area_col = 'area' if 'area' in health_df.columns else None
            plant_col = 'plant' if 'plant' in health_df.columns else None
            
            if ph_col:
                ph_counts = health_df[ph_col].fillna('Unknown').value_counts()
                bar_inactive = [{"name": str(k), "value": int(v)} for k, v in ph_counts.items()]
            else:
                bar_inactive = []
                
            cols_to_keep = [c for c in [plant_col, ph_col, area_col] if c is not None]
            sort_cols = [c for c in [ph_col, area_col] if c is not None]
            if sort_cols:
                detail_inactive = health_df.sort_values(by=sort_cols)[cols_to_keep].fillna('-').to_dict(orient='records')
            else:
                detail_inactive = health_df[cols_to_keep].fillna('-').to_dict(orient='records')
        else:
            bar_inactive = []
            detail_inactive = []
    except Exception as e:
        print(f"Error querying camera_health: {e}")
        bar_inactive = []
        detail_inactive = []

    # Table Data
    df['date1'] = df['date1'].astype(str)
    df['time1'] = df['time1'].astype(str)
    table_data = df.drop(columns=['datetime', 'rounded_datetime', 'shift'], errors='ignore').to_dict(orient='records')

    return jsonify({
        "metrics": {"total_violations": total_v, "active_cameras": cam_active, "inactive_cameras": cam_inactive},
        "charts": {
            "production_house": bar_ph, "area": bar_area, 
            "class_pie": pie_class, "trend": trend_series, 
            "inactive_loc": bar_inactive,
            "inactive_by_ph": bar_inactive,
            "inactive_details": detail_inactive
        },
        "table": table_data
    })



@app.route('/api/notifications_data', methods=['POST'])
@login_required
def notifications_data():
    req = request.json
    start = req.get('start_date')
    end = req.get('end_date')
    
    # Calls the Helper function which contains your original logic
    df = get_notification_data(
        start, end, 
        req.get('shifts', []), req.get('areas', []), 
        req.get('production_houses', []), req.get('classes', []),
        req.get('recipients', [])
    )
    
    if df.empty:
        return jsonify({"metrics": {}, "charts": {}, "tree": {}})

    df = df.sort_values(by=['insert_date', 'insert_time'], ascending=False)
    
    # --- Metrics ---
    total_count = len(df)
    
    # Calculate counts specifically for the metrics logic
    df['Name'] = df['to_recipients'].apply(extract_name)
    name_counts = df['Name'].value_counts()
    
    # Top supervisor recipient by volume
    top_person_name = name_counts.index[0] if not name_counts.empty else '-'
    top_person_count = int(name_counts.iloc[0]) if not name_counts.empty else 0
    
    # Primary non-compliant alert class
    class_counts = df['class_label'].value_counts()
    top_class_name = class_counts.index[0] if not class_counts.empty else '-'
    top_class_count = int(class_counts.iloc[0]) if not class_counts.empty else 0
    
    # Highest alert facility
    ph_counts_series = df['production_house'].value_counts()
    top_ph_name = ph_counts_series.index[0] if not ph_counts_series.empty else '-'
    top_ph_count = int(ph_counts_series.iloc[0]) if not ph_counts_series.empty else 0

    metrics = {
        "total": total_count,
        "last_person": {"name": top_person_name, "count": top_person_count},
        "last_class": {"name": top_class_name, "count": top_class_count},
        "last_ph": {"name": top_ph_name, "count": top_ph_count}
    }

    # --- Charts ---
    # 1. Pie: By Person
    pie_person = [{"name": k, "value": v} for k,v in name_counts.items()]
    
    # 2. Pie: By Production House
    ph_counts = df['production_house'].value_counts().to_dict()
    pie_ph = [{"name": k, "value": v} for k,v in ph_counts.items()]

    # 3. Donut: By Class
    notif_counts = {cls: 0 for cls in NON_COMPLIANT_CLASSES}
    if not df.empty:
        for val in df['class_label']:
            for m in parse_non_compliant_violations(val):
                notif_counts[m] += 1
    pie_class = [{"name": cls, "value": count} for cls, count in notif_counts.items() if count > 0]
    if not pie_class:
        pie_class = [{"name": cls, "value": 0} for cls in NON_COMPLIANT_CLASSES]

    # --- Tree Diagram Logic ---
    # Position mapping (hardcoded from your script)
    position_map = {
        'Avinash Kambale': 'Slurry / Emulsion', 
        'Nikhil Bhatti': 'Hill Top', 
        'Pawan Hiwase': 'S Series', 
        'Vaibhav Indurkar': 'Bulk & Chemical', 
        'Pankaj Patil': 'PETN / TNT / PD / CBH', 
        'Sandesh Sakhare': 'MEEP'
    }

    tree_data = {"name": "SIIL\n\nChakdoh", "children": []}
    
    # Grouping for Tree
    unique_names = df['Name'].unique()
    
    for name in unique_names:
        name_df = df[df['Name'] == name]
        pos = position_map.get(name, 'Staff') # Default to Staff if not found
        
        person_node = {
            "name": f"{pos}\n\n( {name} )\n\n",
            "children": []
        }
        
        unique_phs = name_df['production_house'].unique()
        for ph in unique_phs:
            ph_df = name_df[name_df['production_house'] == ph]
            ph_count = len(ph_df)
            
            ph_node = {
                "name": f"{ph} ({ph_count})",
                "children": []
            }
            
            # Group by area within PH
            area_counts = ph_df['area'].value_counts()
            for area, count in area_counts.items():
                ph_node["children"].append({"name": f"{area} : {count}"})
                
            person_node["children"].append(ph_node)
            
        tree_data["children"].append(person_node)

    return jsonify({
        "metrics": metrics,
        "charts": {
            "person_pie": pie_person,
            "ph_pie": pie_ph,
            "class_pie": pie_class
        },
        "tree": tree_data
    })

def encode_url(path):
    """
    Ensures both '+' and ' ' are converted to '%20' 
    without double-encoding existing characters.
    """
    # 1. unquote_plus converts BOTH %20 and + into actual space characters
    decoded_path = unquote_plus(path)
    
    # 2. quote converts those spaces into %20 (it does NOT use +)
    # safe="/" ensures folders aren't encoded
    return quote(decoded_path, safe="/")

@app.route('/api/get_image_url', methods=['POST'])
@login_required
def get_image_url():
    original_url = request.json.get('image_url')
    if not original_url:
        return jsonify({"error": "No URL"}), 400
    
    try:
        parsed = urlparse(original_url)
        path = parsed.path
        
        # Remove leading slash and the bucket name prefix if it exists
        clean_path = path.lstrip('/')
        if clean_path.startswith('mybucket/'):
            clean_path = clean_path[len('mybucket/'):]

        # Apply the encoding fix
        encoded_path = encode_url(clean_path)

        # Reconstruct - quote() ensures spaces become %20
        final_url = f"https://ppes-siil.solargroup.com:9000/mybucket/{encoded_path}"
        # final_url = f"https://10.0.2.2:9000/mybucket/{encoded_path}"

        return jsonify({"url": final_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@app.route('/api/update_violation', methods=['POST'])
@login_required
def update_violation():
    try:
        row_id = request.json.get('id')
        # Using psycopg2 for direct update as per original code
        conn = psycopg2.connect(host="localhost", database=os.getenv("DB_NAME"), user=os.getenv("DB_USER"), password=os.getenv("DB_PASS"))
        cursor = conn.cursor()
        cursor.execute("UPDATE ppes SET violation = false WHERE id = %s", (row_id,))
        conn.commit()
        cursor.close()
        conn.close()
        
        # Log this action
        if 'user_id' in session:
            auth.log_activity('Update Violation', session['user_id'], session.get('user_email'), f'Cleared violation ID {row_id}')
            
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


if __name__ == '__main__':
    if not os.path.exists('templates'): os.makedirs('templates')
    app.run(
        host='0.0.0.0',
        port=8000,
        debug=True
    )