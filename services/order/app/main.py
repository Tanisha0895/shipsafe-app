import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5432/shop")
AUTH_URL = os.getenv("AUTH_URL", "http://localhost:8001")
PRODUCT_URL = os.getenv("PRODUCT_URL", "http://localhost:8002")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False)
    quantity = Column(Integer, nullable=False)
    total = Column(Float, nullable=False)
    status = Column(String, nullable=False, default="PENDING")
    created_at = Column(DateTime(timezone=True), nullable=False)


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


app = FastAPI(title="ShipSafe Order Service", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def current_user(authorization: str | None = Header(default=None)) -> dict:
    """Ask the Auth service who owns this token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        resp = httpx.get(f"{AUTH_URL}/me", headers={"Authorization": authorization}, timeout=5)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Auth service unavailable")
    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return resp.json()


class OrderIn(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)


def to_dict(o: Order) -> dict:
    return {
        "id": o.id,
        "user_id": o.user_id,
        "product_id": o.product_id,
        "quantity": o.quantity,
        "total": o.total,
        "status": o.status,
        "created_at": o.created_at.isoformat(),
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "order"}


@app.post("/orders", status_code=201)
def create_order(data: OrderIn, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    try:
        resp = httpx.get(f"{PRODUCT_URL}/products/{data.product_id}", timeout=5)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Product service unavailable")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Product not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Product service error")

    product = resp.json()
    if product["stock"] < data.quantity:
        raise HTTPException(status_code=409, detail="Not enough stock")

    order = Order(
        user_id=user["id"],
        product_id=data.product_id,
        quantity=data.quantity,
        total=round(product["price"] * data.quantity, 2),
        status="PENDING",
        created_at=datetime.now(timezone.utc),
    )
    db.add(order)
    db.commit()
    db.refresh(order)
    return to_dict(order)


@app.get("/orders")
def my_orders(user: dict = Depends(current_user), db: Session = Depends(get_db)):
    orders = db.query(Order).filter_by(user_id=user["id"]).order_by(Order.id).all()
    return [to_dict(o) for o in orders]


@app.get("/orders/{order_id}")
def get_order(order_id: int, user: dict = Depends(current_user), db: Session = Depends(get_db)):
    order = db.get(Order, order_id)
    if not order or order.user_id != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found")
    return to_dict(order)