"""
Generates a large, realistic e-commerce-style SQLite database to stress-test
the AI DB Query Assistant: accuracy of generated SQL + response time on a
non-trivial amount of data.

Schema: customers, products, orders, order_items, payments
Sizes are deliberately "large enough to matter" but still generate in
under a minute or two on a normal laptop.

Usage:
    python generate_large_dataset.py [output_path] [--scale N]

    --scale 1   ~ 25k customers / 120k orders / 360k order_items  (default)
    --scale 2   ~ 50k customers / 240k orders / 720k order_items
"""
import argparse
import random
import sqlite3
import sys
import time
from datetime import datetime, timedelta

FIRST_NAMES = [
    "Ali", "Ahmed", "Sara", "Ayesha", "Bilal", "Hamza", "Zainab", "Usman",
    "Fatima", "Omar", "Hassan", "Maria", "John", "Emily", "Michael", "Sarah",
    "David", "Laura", "James", "Anna", "Chen", "Wei", "Yuki", "Aiko",
    "Carlos", "Sofia", "Diego", "Valentina", "Ibrahim", "Noor", "Sana", "Adeel",
]
LAST_NAMES = [
    "Khan", "Malik", "Sheikh", "Butt", "Raza", "Iqbal", "Farooq", "Chaudhry",
    "Smith", "Johnson", "Williams", "Brown", "Garcia", "Martinez", "Wang",
    "Li", "Tanaka", "Suzuki", "Silva", "Rossi", "Müller", "Ahmed", "Hussain",
]
CITIES = [
    ("Rawalpindi", "Pakistan"), ("Islamabad", "Pakistan"), ("Lahore", "Pakistan"),
    ("Karachi", "Pakistan"), ("Faisalabad", "Pakistan"), ("Multan", "Pakistan"),
    ("Dubai", "UAE"), ("London", "UK"), ("New York", "USA"), ("Toronto", "Canada"),
    ("Sydney", "Australia"), ("Berlin", "Germany"), ("Tokyo", "Japan"),
    ("Singapore", "Singapore"), ("Riyadh", "Saudi Arabia"),
]
CATEGORIES = [
    "Electronics", "Clothing", "Home & Kitchen", "Books", "Sports",
    "Beauty", "Toys", "Groceries", "Automotive", "Health",
]
PRODUCT_ADJ = ["Premium", "Classic", "Pro", "Basic", "Deluxe", "Compact", "Wireless", "Smart", "Eco", "Ultra"]
PRODUCT_NOUN = {
    "Electronics": ["Headphones", "Speaker", "Charger", "Smartwatch", "Camera", "Router"],
    "Clothing": ["T-Shirt", "Jacket", "Jeans", "Sneakers", "Cap", "Hoodie"],
    "Home & Kitchen": ["Blender", "Toaster", "Cookware Set", "Lamp", "Vacuum"],
    "Books": ["Novel", "Cookbook", "Notebook Set", "Comic Bundle"],
    "Sports": ["Yoga Mat", "Dumbbell Set", "Football", "Running Shoes"],
    "Beauty": ["Face Cream", "Shampoo", "Perfume", "Lipstick Set"],
    "Toys": ["Building Blocks", "RC Car", "Puzzle", "Action Figure"],
    "Groceries": ["Rice Pack", "Olive Oil", "Tea Box", "Snack Combo"],
    "Automotive": ["Car Vacuum", "Seat Cover", "Dash Cam", "Tire Inflator"],
    "Health": ["Vitamin Pack", "Thermometer", "First Aid Kit", "Massager"],
}
ORDER_STATUSES = ["completed", "completed", "completed", "completed", "pending", "cancelled", "refunded"]
PAYMENT_METHODS = ["credit_card", "debit_card", "cash_on_delivery", "bank_transfer", "wallet"]
PAYMENT_STATUSES = ["success", "success", "success", "success", "failed", "pending"]


def random_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=random.randint(0, int(delta.total_seconds())))


def build(output_path: str, scale: int):
    random.seed(42)  # reproducible dataset

    n_customers = 25_000 * scale
    n_products = 400 * scale if scale > 1 else 500
    n_orders = 120_000 * scale
    avg_items_per_order = 3

    t0 = time.time()
    conn = sqlite3.connect(output_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")

    cur.executescript("""
    DROP TABLE IF EXISTS payments;
    DROP TABLE IF EXISTS order_items;
    DROP TABLE IF EXISTS orders;
    DROP TABLE IF EXISTS products;
    DROP TABLE IF EXISTS customers;

    CREATE TABLE customers (
        id INTEGER PRIMARY KEY,
        full_name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        city TEXT,
        country TEXT,
        signup_date TEXT,
        is_active INTEGER
    );

    CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        category TEXT,
        price REAL,
        stock INTEGER
    );

    CREATE TABLE orders (
        id INTEGER PRIMARY KEY,
        customer_id INTEGER NOT NULL,
        order_date TEXT,
        status TEXT,
        total_amount REAL,
        FOREIGN KEY (customer_id) REFERENCES customers(id)
    );

    CREATE TABLE order_items (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        quantity INTEGER,
        unit_price REAL,
        FOREIGN KEY (order_id) REFERENCES orders(id),
        FOREIGN KEY (product_id) REFERENCES products(id)
    );

    CREATE TABLE payments (
        id INTEGER PRIMARY KEY,
        order_id INTEGER NOT NULL,
        payment_date TEXT,
        method TEXT,
        amount REAL,
        status TEXT,
        FOREIGN KEY (order_id) REFERENCES orders(id)
    );
    """)

    signup_start = datetime(2021, 1, 1)
    signup_end = datetime(2026, 9, 1)

    # ---------------- customers ----------------
    print(f"Generating {n_customers:,} customers...")
    batch = []
    for i in range(1, n_customers + 1):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        city, country = random.choice(CITIES)
        email = f"user{i}@example.com"
        phone = f"03{random.randint(0,9)}{random.randint(1000000,9999999)}"
        signup = random_date(signup_start, signup_end).strftime("%Y-%m-%d")
        is_active = 1 if random.random() > 0.08 else 0
        batch.append((i, name, email, phone, city, country, signup, is_active))
        if len(batch) >= 5000:
            cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", batch)
            batch.clear()
    if batch:
        cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", batch)

    # ---------------- products ----------------
    print(f"Generating {n_products:,} products...")
    batch = []
    for i in range(1, n_products + 1):
        cat = random.choice(CATEGORIES)
        noun = random.choice(PRODUCT_NOUN[cat])
        adj = random.choice(PRODUCT_ADJ)
        name = f"{adj} {noun}"
        price = round(random.uniform(5, 2500), 2)
        stock = random.randint(0, 500)
        batch.append((i, name, cat, price, stock))
    cur.executemany("INSERT INTO products VALUES (?,?,?,?,?)", batch)

    # ---------------- orders + order_items + payments ----------------
    print(f"Generating {n_orders:,} orders (~{n_orders * avg_items_per_order:,} order_items)...")
    order_start = datetime(2024, 1, 1)
    order_end = datetime(2026, 9, 4)

    order_batch, item_batch, payment_batch = [], [], []
    item_id = 1
    payment_id = 1
    flush_every = 5000

    for oid in range(1, n_orders + 1):
        cust_id = random.randint(1, n_customers)
        odate = random_date(order_start, order_end)
        status = random.choice(ORDER_STATUSES)

        n_items = random.randint(1, 5)
        order_total = 0.0
        for _ in range(n_items):
            pid = random.randint(1, n_products)
            qty = random.randint(1, 4)
            # small price jitter vs catalog price to simulate historical pricing
            unit_price = round(random.uniform(5, 2500), 2)
            order_total += qty * unit_price
            item_batch.append((item_id, oid, pid, qty, unit_price))
            item_id += 1

        order_batch.append((oid, cust_id, odate.strftime("%Y-%m-%d %H:%M:%S"), status, round(order_total, 2)))

        if status != "cancelled":
            pay_status = random.choice(PAYMENT_STATUSES) if status != "refunded" else "success"
            pdate = odate + timedelta(hours=random.randint(0, 48))
            payment_batch.append((
                payment_id, oid, pdate.strftime("%Y-%m-%d %H:%M:%S"),
                random.choice(PAYMENT_METHODS), round(order_total, 2),
                "refunded" if status == "refunded" else pay_status,
            ))
            payment_id += 1

        if len(order_batch) >= flush_every:
            cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", order_batch)
            cur.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", item_batch)
            cur.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", payment_batch)
            order_batch.clear(); item_batch.clear(); payment_batch.clear()
            if oid % 20000 == 0:
                print(f"  ...{oid:,} orders done")

    if order_batch:
        cur.executemany("INSERT INTO orders VALUES (?,?,?,?,?)", order_batch)
        cur.executemany("INSERT INTO order_items VALUES (?,?,?,?,?)", item_batch)
        cur.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?)", payment_batch)

    print("Creating indexes...")
    cur.executescript("""
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE INDEX idx_orders_date ON orders(order_date);
        CREATE INDEX idx_items_order ON order_items(order_id);
        CREATE INDEX idx_items_product ON order_items(product_id);
        CREATE INDEX idx_payments_order ON payments(order_id);
    """)

    conn.commit()

    counts = {}
    for t in ["customers", "products", "orders", "order_items", "payments"]:
        counts[t] = cur.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    conn.close()

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s -> {output_path}")
    for t, c in counts.items():
        print(f"  {t:<14} {c:,} rows")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="large_client_sample.db")
    parser.add_argument("--scale", type=int, default=1, help="1x or 2x default row counts")
    args = parser.parse_args()
    build(args.output, args.scale)
