# main.py
import asyncio
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from app.database import engine, Base
from app.routers import auth, donor, patient, admin, request, hospital, chatbot, ml

app = FastAPI(
    title='BloodBridge API',
    description='AI-Powered Blood Donor Coordination Platform',
    version='1.0.0'
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

# Include all routers
app.include_router(auth.router,     prefix='/api/auth',     tags=['Auth'])
app.include_router(donor.router,    prefix='/api/donors',   tags=['Donors'])
app.include_router(patient.router,  prefix='/api/patients', tags=['Patients'])
app.include_router(admin.router,    prefix='/api/admin',    tags=['Admin'])
app.include_router(request.router,  prefix='/api/requests', tags=['Requests'])
app.include_router(hospital.router, prefix='/api/hospital', tags=['Hospital'])
app.include_router(chatbot.router,  prefix='/api/chatbot',  tags=['Chatbot'])
app.include_router(ml.router,       prefix='/api/ml',       tags=['ML'])

os.makedirs('uploads', exist_ok=True)
app.mount('/files', StaticFiles(directory='uploads'), name='files')

@app.on_event('startup')
async def startup_event():
    max_attempts = 10
    delay_seconds = 3

    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            from app.scheduler import scheduler
            if not scheduler.running:
                scheduler.start()
            return
        except OperationalError as exc:
            if attempt == max_attempts:
                raise RuntimeError(
                    'Database startup failed. Check DATABASE_URL, PostgreSQL credentials, and whether the DB server is running.'
                ) from exc
            await asyncio.sleep(delay_seconds)

@app.get('/')
def root():
    return {'message': 'BloodBridge API is running 🩸'}
