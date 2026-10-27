import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from typing import Annotated
from fastapi import Depends, Request

load_dotenv()

# آدرس اتصال به دیتابیس واقعی، محلی و نیتیو پستگرس شما
SQLALCHEMY_DATABASE_URL = os.getenv('DATABASE_URL', "postgresql+psycopg://postgres:123456@localhost:5432/logitrack")

if SQLALCHEMY_DATABASE_URL.startswith("postgresql://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db(request: Request = None) -> Session:
    # درخواست‌های نسخه نمایشی خصوصی به دیتابیس جدای دمو می‌روند و فقط کارهای مجاز را دارند (app/core/demo.py)
    from app.core import demo
    if demo.is_demo_request(request):
        demo.guard(request.method, request.url.path)
        db = demo.session_factory()()
        db.info["demo"] = True
    else:
        db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db_dependency = Annotated[Session, Depends(get_db)]