"""
Create a realistic sample SQLite database for demo / testing.
Run once:  python scripts/create_sample_db.py
"""

import os
import random
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
    Text,
    Boolean,
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "sample_company.db"
os.makedirs(DB_PATH.parent, exist_ok=True)

Base = declarative_base()


class Customer(Base):
    __tablename__ = "customers"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    email = Column(String(120), unique=True)
    city = Column(String(80))
    country = Column(String(60))
    registration_date = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    orders = relationship("Order", back_populates="customer")


class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(120), nullable=False)
    category = Column(String(60))
    price = Column(Float, nullable=False)
    stock = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    order_date = Column(DateTime, default=datetime.utcnow)
    status = Column(String(30), default="pending")
    total_amount = Column(Float, default=0.0)
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer, default=1)
    unit_price = Column(Float)
    order = relationship("Order", back_populates="items")


class Employee(Base):
    __tablename__ = "employees"
    id = Column(Integer, primary_key=True)
    full_name = Column(String(100))
    department = Column(String(60))
    hire_date = Column(DateTime)
    salary = Column(Float)
    manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)


def main():
    if DB_PATH.exists():
        DB_PATH.unlink()

    engine = create_engine(f"sqlite:///{DB_PATH}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Seed customers
    cities = [
        ("Karachi", "Pakistan"),
        ("Lahore", "Pakistan"),
        ("Islamabad", "Pakistan"),
        ("Dubai", "UAE"),
        ("London", "UK"),
        ("New York", "USA"),
        ("Berlin", "Germany"),
        ("Singapore", "Singapore"),
    ]
    customers = []
    for i in range(1, 61):
        city, country = random.choice(cities)
        c = Customer(
            name=f"Customer {i}",
            email=f"customer{i}@example.com",
            city=city,
            country=country,
            registration_date=datetime.utcnow() - timedelta(days=random.randint(1, 400)),
            is_active=random.random() > 0.1,
        )
        customers.append(c)
    session.add_all(customers)
    session.flush()

    # Products
    categories = ["Electronics", "Clothing", "Home", "Sports", "Books"]
    products = []
    for i in range(1, 31):
        p = Product(
            name=f"Product {i}",
            category=random.choice(categories),
            price=round(random.uniform(9.99, 499.99), 2),
            stock=random.randint(0, 200),
            created_at=datetime.utcnow() - timedelta(days=random.randint(30, 600)),
        )
        products.append(p)
    session.add_all(products)
    session.flush()

    # Orders + items
    statuses = ["pending", "shipped", "delivered", "cancelled"]
    for i in range(1, 121):
        cust = random.choice(customers)
        o = Order(
            customer_id=cust.id,
            order_date=datetime.utcnow() - timedelta(days=random.randint(0, 180)),
            status=random.choice(statuses),
        )
        session.add(o)
        session.flush()

        total = 0.0
        for _ in range(random.randint(1, 4)):
            prod = random.choice(products)
            qty = random.randint(1, 5)
            item = OrderItem(
                order_id=o.id,
                product_id=prod.id,
                quantity=qty,
                unit_price=prod.price,
            )
            total += qty * prod.price
            session.add(item)
        o.total_amount = round(total, 2)

    # Employees
    depts = ["Engineering", "Sales", "Support", "HR", "Finance"]
    for i in range(1, 21):
        e = Employee(
            full_name=f"Employee {i}",
            department=random.choice(depts),
            hire_date=datetime.utcnow() - timedelta(days=random.randint(100, 2000)),
            salary=round(random.uniform(30000, 120000), 2),
            manager_id=random.randint(1, 5) if i > 5 else None,
        )
        session.add(e)

    session.commit()
    session.close()
    print(f"✅ Sample database created at: {DB_PATH}")
    print("   Tables: customers, products, orders, order_items, employees")
    print("   You can connect to it from the app using dialect=sqlite and the path above.")


if __name__ == "__main__":
    main()
