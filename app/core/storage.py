import os
import boto3
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv()

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")

if STORAGE_BACKEND == "b2":
    s3_client = boto3.client(
        "s3",
        endpoint_url = os.getenv("B2_ENDPOINT_URL"),
        aws_access_key_id = os.getenv("B2_KEY_ID"),
        aws_secret_access_key= os.getenv("B2_APPLICATION_KEY"),
        config=Config(signature_version="s3v4"),
    )
    BUCKET_NAME= os.getenv("B2_BUCKET_NAME")

def upload_bytes(key:str, data:bytes) -> None:
    if STORAGE_BACKEND == "b2":
        s3_client.put_object(Bucket=BUCKET_NAME, Key=key , Body=data)
    else:
        os.makedirs(UPLOAD_DIR , exist_ok=True)
        with open(os.path.join(UPLOAD_DIR, key), "wb") as f:
            f.write(data)

def download_bytes(key:str) -> bytes:
    if STORAGE_BACKEND == "b2":
        response = s3_client.get_object(Bucket=BUCKET_NAME, Key=key)
        return response["Body"].read()
    else:
        with open(os.path.join(UPLOAD_DIR, key), "rb") as f:
            return f.read()

def delete_bytes(key:str) -> None:
    if STORAGE_BACKEND == "b2":
        s3_client.delete_object(Bucket=BUCKET_NAME, Key=key)
    else:
        path =os.path.join(UPLOAD_DIR , key)
        if os.path.exists(path):
            os.remove(path)