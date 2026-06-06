# app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    SMTP_HOST: str = 'smtp.gmail.com'
    SMTP_PORT: int = 587
    SMTP_USER: str = ''
    SMTP_PASS: str = ''
    AWS_ACCESS_KEY_ID: str = ''
    AWS_SECRET_ACCESS_KEY: str = ''
    AWS_REGION: str = 'ap-south-1'
    S3_BUCKET: str = 'bloodbridge-docs'
    ML_MODEL_PATH: str = './ml/donor_probability/donor_model.pkl'
    GROQ_API_KEY: str = ''
    GROQ_MODEL: str = 'llama-3.3-70b-versatile'
    EMBEDDINGS_MODEL: str = 'BAAI/bge-base-en-v1.5'
    FAISS_INDEX_PATH: str = './faiss_index'

    class Config:
        env_file = '.env'


settings = Settings()
