# relay_app.py
import os
from flask import Flask, request, jsonify
from flask_mail import Mail, Message
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

# --- Mail Configuration ---
# We no longer need MAIL_DEFAULT_SENDER here
app.config['MAIL_SERVER'] = os.getenv('MAIL_SERVER')
app.config['MAIL_PORT'] = int(os.getenv('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = os.getenv('MAIL_USE_TLS', 'True').lower() in ['true', 'on', '1']
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
mail = Mail(app)

# --- Security & Sender Name ---
API_SECRET_KEY = os.getenv('API_SECRET_KEY')
# Load the sender name and email from .env
SENDER_NAME = os.getenv('MAIL_SENDER_NAME')
SENDER_EMAIL = os.getenv('MAIL_USERNAME')


@app.route('/send_email', methods=['POST'])
def send_email():
    auth_key = request.headers.get('X-API-Key')
    if not auth_key or auth_key != API_SECRET_KEY:
        return jsonify({'error': 'Unauthorized'}), 401

    data = request.get_json()
    if not data or not all(k in data for k in ['recipient', 'subject', 'body']):
        return jsonify({'error': 'Missing required data'}), 400

    try:
        # --- MODIFICATION: Explicitly set the sender ---
        # This creates a sender tuple like ("IIoT Team", "your-email@example.com")
        # which is the format Flask-Mail's Message object requires.
        msg = Message(
            subject=data['subject'],
            recipients=[data['recipient']],
            body=data['body'],
            html=data.get('html'),
            sender=(SENDER_NAME, SENDER_EMAIL) # This is the critical line
        )
        mail.send(msg)
        return jsonify({'success': True, 'message': 'Email sent successfully.'}), 200
    except Exception as e:
        print(f"Relay failed to send email: {e}")
        return jsonify({'error': 'Failed to send email'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)

