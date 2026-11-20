import json
import os
import time
from contextlib import asynccontextmanager

import redis
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import Column, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5432/shop")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CACHE_TTL = int(os.getenv("CACHE_TTL", "60"))
CACHE_KEY = "products:all"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
cache = redis.Redis.from_url(REDIS_URL, decode_responses=True)


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    stock = Column(Integer, nullable=False, default=0)


SEED = [
    ("Wireless Mouse", 799.0, 50),
    ("Mechanical Keyboard", 3499.0, 20),
    ("USB-C Hub", 1299.0, 35),
    ("Laptop Stand", 1499.0, 15),
]


def init_db(retries: int = 10):
    for _ in range(retries):
        try:
            Base.metadata.create_all(engine)
            break
        except Exception:
            time.sleep(2)
    else:
        raise RuntimeError("Database not reachable")
    with SessionLocal() as db:
        if db.query(Product).count() == 0:
            db.add_all([Product(name=n, price=p, stock=s) for n, p, s in SEED])
            db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="ShipSafe Product Service", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_dict(p: Product) -> dict:
    return {"id": p.id, "name": p.name, "price": p.price, "stock": p.stock}


class NewProduct(BaseModel):
    name: str
    price: float
    stock: int = 0


@app.get("/health")
def health():
    return {"status": "ok", "service": "product"}


@app.get("/products")
def list_products(db: Session = Depends(get_db)):
    try:
        cached = cache.get(CACHE_KEY)
    except redis.RedisError:
        cached = None
    if cached:
        return {"source": "cache", "items": json.loads(cached)}

    items = [to_dict(p) for p in db.query(Product).order_by(Product.id).all()]
    try:
        cache.setex(CACHE_KEY, CACHE_TTL, json.dumps(items))
    except redis.RedisError:
        pass
    return {"source": "database", "items": items}


@app.get("/products/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return to_dict(product)


@app.post("/products", status_code=201)
def create_product(data: NewProduct, db: Session = Depends(get_db)):
    product = Product(name=data.name, price=data.price, stock=data.stock)
    db.add(product)
    db.commit()
    db.refresh(product)
    try:
        cache.delete(CACHE_KEY)
    except redis.RedisError:
        pass
    return to_dict(product)
