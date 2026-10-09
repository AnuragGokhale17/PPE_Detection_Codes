import ssl

import urllib3
from minio import Minio
from minio.error import S3Error


# =========================================================
# MINIO CONFIGURATION
# =========================================================

MINIO_ENDPOINT = "127.0.0.1:19000"

MINIO_ACCESS_KEY = "vIzZ4i3JRaiCxbAOYWCT"

MINIO_SECRET_KEY = "K6IrscxNEJaSRG9orJbVqOMSJRxWq2DLeldBYWD8"

MINIO_BUCKET = "maintenance-attachement"


# Disable the warning because this test connects through
# localhost and skips certificate verification.
urllib3.disable_warnings(
    urllib3.exceptions.InsecureRequestWarning
)


# =========================================================
# SHOW CONFIGURATION WITHOUT DISPLAYING CREDENTIALS
# =========================================================

print()
print("========================================")
print("DIRECT MINIO CONNECTION TEST")
print("========================================")
print("Endpoint:", MINIO_ENDPOINT)
print("Protocol: HTTPS")
print("Bucket:", MINIO_BUCKET)
print("Access Key length:", len(MINIO_ACCESS_KEY))
print("Secret Key length:", len(MINIO_SECRET_KEY))
print("Nginx bypassed: Yes")
print("========================================")
print()


# =========================================================
# VALIDATE CONFIGURATION
# =========================================================

if (
    not MINIO_ACCESS_KEY or
    "PASTE_YOUR" in MINIO_ACCESS_KEY
):
    raise ValueError(
        "Enter the actual MinIO Access Key in the Python code."
    )


if (
    not MINIO_SECRET_KEY or
    "PASTE_YOUR" in MINIO_SECRET_KEY
):
    raise ValueError(
        "Enter the actual MinIO Secret Key in the Python code."
    )


# =========================================================
# HTTPS CLIENT FOR LOCAL MINIO
# =========================================================

http_client = urllib3.PoolManager(
    cert_reqs=ssl.CERT_NONE,
    timeout=urllib3.Timeout(
        connect=10.0,
        read=30.0
    ),
    retries=False
)


# =========================================================
# MINIO CLIENT
# =========================================================

minio_client = Minio(
    endpoint=MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=True,
    http_client=http_client
)


# =========================================================
# TEST AUTHENTICATION AND BUCKET ACCESS
# =========================================================

try:
    bucket_exists = minio_client.bucket_exists(
        MINIO_BUCKET
    )

    print("========================================")
    print("AUTHENTICATION SUCCESSFUL")
    print("Bucket exists:", bucket_exists)
    print("========================================")


except S3Error as error:
    print("========================================")
    print("AUTHENTICATION FAILED")
    print("Code:", error.code)
    print("Message:", error.message)

    request_id = getattr(
        error,
        "request_id",
        None
    )

    host_id = getattr(
        error,
        "host_id",
        None
    )

    bucket_name = getattr(
        error,
        "bucket_name",
        None
    )

    if request_id:
        print("Request ID:", request_id)

    if host_id:
        print("Host ID:", host_id)

    if bucket_name:
        print("Bucket:", bucket_name)

    print("========================================")

    if error.code == "SignatureDoesNotMatch":
        print()
        print(
            "The Access Key and Secret Key do not "
            "produce a valid matching signature."
        )

    elif error.code == "AccessDenied":
        print()
        print(
            "The credentials are valid, but the account "
            "does not have access to this bucket."
        )

    elif error.code == "InvalidAccessKeyId":
        print()
        print(
            "MinIO does not recognize the Access Key."
        )


except Exception as error:
    print("========================================")
    print("CONNECTION FAILED")
    print("Type:", type(error).__name__)
    print("Message:", str(error))
    print("========================================")