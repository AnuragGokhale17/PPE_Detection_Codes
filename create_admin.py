# create_admin.py
import os
from sqlalchemy import create_engine, text
from passlib.context import CryptContext
from dotenv import load_dotenv

load_dotenv()

# Use the same password hashing context we'll use in the app
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Get DB details from environment

user=os.getenv("DB_USER")
pass_enc=os.getenv("DB_PASS_ENC")
host=os.getenv("DB_HOST")
database=os.getenv("DB_NAME")
DB_URL = f"postgresql://{user}:{pass_enc}@{host}/{database}"
engine = create_engine(DB_URL)

def create_admin_user(email, password):
    if not email.endswith('@solargroup.com'):
        print("Error: Email must be a @solargroup.com address.")
        return

    hashed_password = pwd_context.hash(password)
    role = 'admin'

    query = text("""
        INSERT INTO users (email, _password_hash, role)
        VALUES (:email, :password_hash, :role)
        ON CONFLICT (email) DO UPDATE SET
            _password_hash = EXCLUDED._password_hash,
            role = EXCLUDED.role;
    """)

    try:
        with engine.connect() as connection:
            connection.execute(query, {'email': email, 'password_hash': hashed_password, 'role': role})
            connection.commit() # Use this if not in a transaction block
        print(f"Admin user '{email}' created/updated successfully.")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    admin_email = input("Enter admin email (@solargroup.com): ")
    admin_password = input("Enter admin password: ")
    create_admin_user(admin_email, admin_password)