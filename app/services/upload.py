import boto3
import uuid
import os
from fastapi import UploadFile
from app.config import settings

_use_s3 = bool(settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY)
s3 = None
if _use_s3:
    s3 = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


async def upload_file_local(file: UploadFile, folder: str = 'uploads') -> str:
    os.makedirs(f'./uploads/{folder}', exist_ok=True)
    ext = file.filename.split('.')[-1] if file.filename and '.' in file.filename else 'bin'
    filename = f'{uuid.uuid4()}.{ext}'
    path = f'./uploads/{folder}/{filename}'
    content = await file.read()
    with open(path, 'wb') as f:
        f.write(content)
    return f'/files/{folder}/{filename}'


async def upload_file_to_s3(file: UploadFile, folder: str = 'uploads') -> str:
    if not _use_s3:
        return await upload_file_local(file, folder)
    ext = file.filename.split('.')[-1] if file.filename and '.' in file.filename else 'bin'
    key = f'{folder}/{uuid.uuid4()}.{ext}'
    content = await file.read()
    s3.put_object(
        Bucket=settings.S3_BUCKET,
        Key=key,
        Body=content,
        ContentType=file.content_type or 'application/octet-stream',
    )
    return f'https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}'
