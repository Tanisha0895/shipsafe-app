import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5432/shop")
ORDER_URL = os.getenv("ORDER_URL", "http://localhost:8003")
PRODUCT_URL = os.getenv("PRODUCT_URL", "http://localhost:8002")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class Payment(Base):
    __tablename__ = "payments"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    amount = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    reason = Column(String, nullable=True)
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


app = FastAPI(title="ShipSafe Payment Service", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class PaymentIn(BaseModel):
    order_id: int
    simulate_failure: bool = False


def internal_headers() -> dict:
    return {"X-Internal-Key": INTERNAL_API_KEY}


def record(db: Session, order: dict, status: str, reason: str | None = None) -> dict:
    p = Payment(
        order_id=order["id"],
        user_id=order["user_id"],
        amount=order["total"],
        status=status,
        reason=reason,
        created_at=datetime.now(timezone.utc),
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return {"payment_id": p.id, "order_id": p.order_id, "amount": p.amount, "status": p.status, "reason": p.reason}


def set_order_status(order_id: int, status: str):
    httpx.patch(
        f"{ORDER_URL}/orders/{order_id}/status",
        json={"status": status},
        headers=internal_headers(),
        timeout=5,
    ).raise_for_status()


@app.get("/health")
def health():
    return {"status": "ok", "service": "payment"}


@app.post("/payments", status_code=201)
def pay(data: PaymentIn, authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing token")

    # 1. Fetch the order as the user (Order checks the token and ownership)
    try:
        resp = httpx.get(f"{ORDER_URL}/orders/{data.order_id}", headers={"Authorization": authorization}, timeout=5)
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="Order service unavailable")
    if resp.status_code == 401:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="Order not found")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Order service error")
    order = resp.json()

    # 2. Only pending orders can be paid
    if order["status"] != "PENDING":
        raise HTTPException(status_code=409, detail=f"Order is already {order['status']}")

    try:
        # 3. Mock payment gateway
        if data.simulate_failure:
            set_order_status(order["id"], "PAYMENT_FAILED")
            result = record(db, order, "FAILED", "Card declined (simulated)")
            raise HTTPException(status_code=402, detail=result)

        # 4. Reduce stock
        stock = httpx.post(
            f"{PRODUCT_URL}/products/{order['product_id']}/reserve",
            json={"quantity": order["quantity"]},
            headers=internal_headers(),
            timeout=5,
        )
        if stock.status_code == 409:
            set_order_status(order["id"], "PAYMENT_FAILED")
            result = record(db, order, "FAILED", "Out of stock")
            raise HTTPException(status_code=409, detail=result)
        stock.raise_for_status()

        # 5. Mark order as paid
        set_order_status(order["id"], "PAID")
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Downstream service unavailable")

    return record(db, order, "SUCCESS")


@app.get("/payments")
def list_payments(db: Session = Depends(get_db)):
    return [
        {"payment_id": p.id, "order_id": p.order_id, "amount": p.amount, "status": p.status, "reason": p.reason}
        for p in db.query(Payment).order_by(Payment.id).all()
    ]