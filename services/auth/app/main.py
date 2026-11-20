import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5432/shop")
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGO = "HS256"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)


def init_db(retries: int = 10):
    for _ in range(retries):
        try:
            Base.metadata.create_all(engine)
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError("Database not reachable")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ShipSafe Auth Service", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class Credentials(BaseModel):
    email: str
    password: str


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}


@app.post("/register", status_code=201)
def register(creds: Credentials, db: Session = Depends(get_db)):
    if db.query(User).filter_by(email=creds.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")
    hashed = bcrypt.hashpw(creds.password.encode(), bcrypt.gensalt()).decode()
    user = User(email=creds.email, password_hash=hashed)
    db.add(user)
    db.commit()
    db.refresh(user)
    return {"id": user.id, "email": user.email}


@app.post("/login")
def login(creds: Credentials, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email=creds.email).first()
    if not user or not bcrypt.checkpw(creds.password.encode(), user.password_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = jwt.encode(
        {
            "sub": str(user.id),
            "email": user.email,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        JWT_SECRET,
        algorithm=JWT_ALGO,
    )
    return {"access_token": token, "token_type": "bearer"}


@app.get("/me")
def me(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], JWT_SECRET, algorithms=[JWT_ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return {"id": int(payload["sub"]), "email": payload["email"]}
