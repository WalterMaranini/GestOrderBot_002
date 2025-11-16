# db_models.py

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session

# ===================== CONFIG DB =====================

# Per iniziare usiamo SQLite locale.
# In produzione potrai passare a Postgres/SQL Server cambiando solo DATABASE_URL.
DATABASE_URL = "sqlite:///./orders.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},  # necessario per SQLite + FastAPI
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

Base = declarative_base()


def get_db() -> Session:
    """
    Dependency per FastAPI:
    yield una Session e la chiude automaticamente alla fine della richiesta.
    (la useremo con Depends in orders_rest_api.py)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ===================== MODELLI ORM =====================

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(200), nullable=False)
    address = Column(String(200), nullable=True)
    city = Column(String(100), nullable=True)
    province = Column(String(10), nullable=True)
    country = Column(String(50), nullable=True)

    orders = relationship("OrderHeader", back_populates="customer")


class Article(Base):
    __tablename__ = "articles"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(50), unique=True, index=True, nullable=False)
    description = Column(String(200), nullable=False)
    unit = Column(String(20), nullable=False, default="PZ")

    prices = relationship("Price", back_populates="article")
    stock_levels = relationship("StockLevel", back_populates="article")
    order_lines = relationship("OrderLine", back_populates="article")


class Price(Base):
    """
    Prezzo per articolo e cliente (potrebbe essere generico se customer_id è NULL).
    """
    __tablename__ = "prices"
    __table_args__ = (
        UniqueConstraint("customer_id", "article_id", name="uq_price_customer_article"),
    )

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    price = Column(Float, nullable=False)
    currency = Column(String(10), nullable=False, default="EUR")

    customer = relationship("Customer")
    article = relationship("Article", back_populates="prices")


class StockLevel(Base):
    __tablename__ = "stock_levels"
    __table_args__ = (
        UniqueConstraint("article_id", "warehouse_code", name="uq_stock_article_warehouse"),
    )

    id = Column(Integer, primary_key=True, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    warehouse_code = Column(String(20), nullable=False, default="MAIN")
    quantity = Column(Float, nullable=False, default=0.0)

    article = relationship("Article", back_populates="stock_levels")


class OrderHeader(Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    order_date = Column(Date, nullable=False)
    delivery_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="INSERTED")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    customer = relationship("Customer", back_populates="orders")
    lines = relationship("OrderLine", back_populates="order", cascade="all, delete-orphan")


class OrderLine(Base):
    __tablename__ = "order_lines"

    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    line_no = Column(Integer, nullable=False)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    quantity = Column(Float, nullable=False)
    unit_price = Column(Float, nullable=True)  # opzionale
    discount = Column(Float, nullable=True)    # opzionale

    order = relationship("OrderHeader", back_populates="lines")
    article = relationship("Article", back_populates="order_lines")


# ===================== INIT DB =====================

def init_db() -> None:
    """
    Crea le tabelle se non esistono.
    Da chiamare una volta all'avvio dell'app FastAPI.
    """
    Base.metadata.create_all(bind=engine)
