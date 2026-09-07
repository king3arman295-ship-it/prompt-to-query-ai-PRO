"""
Generate a large, realistic Streaming Platform + Telecom Services SQLite DB.

Domain matches typical client databases of a software house that builds
OTT / IPTV / mobile & broadband BSS systems.

Tables:
  customers, plans, subscriptions, devices, content_catalog, series, episodes,
  watch_history, data_usage, invoices, payments, support_tickets, network_events

Usage:
    python generate_streaming_telecom_db.py [output_path] [--scale N]
    --scale 1  ~ 30k customers / 80k subscriptions / 400k watch events  (default)
    --scale 2  roughly 2x
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import time
from datetime import datetime, timedelta

random.seed(42)

FIRST = [
    "Ali", "Ahmed", "Sara", "Ayesha", "Bilal", "Hamza", "Zainab", "Usman",
    "Fatima", "Omar", "Hassan", "Maria", "John", "Emily", "Michael", "Sarah",
    "David", "Laura", "James", "Anna", "Chen", "Wei", "Yuki", "Aiko",
    "Carlos", "Sofia", "Diego", "Valentina", "Ibrahim", "Noor", "Sana", "Adeel",
    "Raza", "Hina", "Kamran", "Nida", "Tariq", "Mehreen", "Farhan", "Sobia",
]
LAST = [
    "Khan", "Malik", "Sheikh", "Butt", "Raza", "Iqbal", "Farooq", "Chaudhry",
    "Smith", "Johnson", "Williams", "Brown", "Garcia", "Martinez", "Wang",
    "Li", "Tanaka", "Suzuki", "Silva", "Rossi", "Müller", "Ahmed", "Hussain",
    "Abbasi", "Qureshi", "Mirza", "Baig", "Ansari",
]
CITIES = [
    ("Lahore", "Pakistan"), ("Karachi", "Pakistan"), ("Islamabad", "Pakistan"),
    ("Rawalpindi", "Pakistan"), ("Faisalabad", "Pakistan"), ("Multan", "Pakistan"),
    ("Peshawar", "Pakistan"), ("Quetta", "Pakistan"), ("Dubai", "UAE"),
    ("Abu Dhabi", "UAE"), ("Riyadh", "Saudi Arabia"), ("Jeddah", "Saudi Arabia"),
    ("London", "UK"), ("Manchester", "UK"), ("Toronto", "Canada"),
    ("New York", "USA"), ("Singapore", "Singapore"), ("Doha", "Qatar"),
]
PLAN_TYPES = ["mobile_prepaid", "mobile_postpaid", "broadband", "streaming_only", "bundle"]
PLAN_NAMES = {
    "mobile_prepaid": ["EasyLoad Basic", "TalkTime Plus", "Data Booster 5GB", "Unlimited Night"],
    "mobile_postpaid": ["Postpaid 500", "Postpaid 1000", "Postpaid Unlimited", "Business Postpaid"],
    "broadband": ["Fiber 20Mbps", "Fiber 50Mbps", "Fiber 100Mbps", "Fiber 200Mbps", "DSL 10Mbps"],
    "streaming_only": ["Stream Basic", "Stream Standard", "Stream Premium", "Stream Family"],
    "bundle": ["Family Bundle", "Super Bundle", "All-in-One Elite", "Home + Mobile"],
}
DEVICE_TYPES = ["android_tv", "smart_tv", "mobile", "tablet", "stb", "web", "ios"]
CONTENT_TYPES = ["movie", "series", "live_tv", "sports", "kids", "documentary"]
GENRES = [
    "Action", "Drama", "Comedy", "Thriller", "Romance", "Horror", "Sci-Fi",
    "Sports", "Kids", "Documentary", "News", "Reality", "Anime",
]
TICKET_CATEGORIES = [
    "billing", "connectivity", "streaming_buffering", "account", "device",
    "plan_change", "payment_failed", "content_missing", "speed", "other",
]
TICKET_STATUSES = ["open", "in_progress", "resolved", "closed", "escalated"]
INVOICE_STATUSES = ["paid", "pending", "overdue", "cancelled"]
PAYMENT_METHODS = ["credit_card", "debit_card", "jazzcash", "easypaisa", "bank_transfer", "wallet"]
PAYMENT_STATUSES = ["success", "failed", "pending", "refunded"]
SUB_STATUSES = ["active", "active", "active", "active", "suspended", "cancelled", "expired"]


def rand_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(seconds=random.randint(0, max(1, int(delta.total_seconds()))))


def build(output_path: str, scale: int = 1) -> None:
    n_customers = 30_000 * scale
    n_plans = 40
    n_content = 2_500 * scale
    n_series = 400 * scale
    n_subs = 80_000 * scale
    n_devices = 55_000 * scale
    n_watch = 400_000 * scale
    n_usage = 200_000 * scale
    n_invoices = 150_000 * scale
    n_payments = 140_000 * scale
    n_tickets = 25_000 * scale
    n_events = 50_000 * scale

    t0 = time.time()
    conn = sqlite3.connect(output_path)
    cur = conn.cursor()
    cur.execute("PRAGMA journal_mode=OFF")
    cur.execute("PRAGMA synchronous=OFF")
    cur.execute("PRAGMA cache_size=-64000")

    # ------------------------------------------------------------------ schema
    cur.executescript(
        """
        DROP TABLE IF EXISTS network_events;
        DROP TABLE IF EXISTS support_tickets;
        DROP TABLE IF EXISTS payments;
        DROP TABLE IF EXISTS invoices;
        DROP TABLE IF EXISTS data_usage;
        DROP TABLE IF EXISTS watch_history;
        DROP TABLE IF EXISTS episodes;
        DROP TABLE IF EXISTS series;
        DROP TABLE IF EXISTS content_catalog;
        DROP TABLE IF EXISTS devices;
        DROP TABLE IF EXISTS subscriptions;
        DROP TABLE IF EXISTS plans;
        DROP TABLE IF EXISTS customers;

        CREATE TABLE customers (
            customer_id     INTEGER PRIMARY KEY,
            full_name       TEXT NOT NULL,
            email           TEXT,
            phone           TEXT,
            city            TEXT,
            country         TEXT,
            signup_date     TEXT NOT NULL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            segment         TEXT  -- consumer | sme | enterprise
        );

        CREATE TABLE plans (
            plan_id         INTEGER PRIMARY KEY,
            plan_name       TEXT NOT NULL,
            plan_type       TEXT NOT NULL,  -- mobile_prepaid, mobile_postpaid, broadband, streaming_only, bundle
            monthly_price   REAL NOT NULL,
            data_gb         REAL,           -- null for unlimited
            voice_minutes   INTEGER,
            streaming_quality TEXT,         -- sd | hd | uhd | null
            max_streams     INTEGER DEFAULT 1,
            is_active       INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE subscriptions (
            subscription_id INTEGER PRIMARY KEY,
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            plan_id         INTEGER NOT NULL REFERENCES plans(plan_id),
            start_date      TEXT NOT NULL,
            end_date        TEXT,
            status          TEXT NOT NULL,  -- active, suspended, cancelled, expired
            auto_renew      INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE devices (
            device_id       INTEGER PRIMARY KEY,
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            device_type     TEXT NOT NULL,
            device_name     TEXT,
            os_version      TEXT,
            last_active     TEXT,
            is_registered   INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE content_catalog (
            content_id      INTEGER PRIMARY KEY,
            title           TEXT NOT NULL,
            content_type    TEXT NOT NULL,  -- movie, series, live_tv, sports, kids, documentary
            genre           TEXT,
            release_year    INTEGER,
            duration_minutes INTEGER,
            rating          REAL,           -- 0-10
            language        TEXT,
            is_premium      INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE series (
            series_id       INTEGER PRIMARY KEY,
            content_id      INTEGER NOT NULL REFERENCES content_catalog(content_id),
            total_seasons   INTEGER NOT NULL,
            total_episodes  INTEGER NOT NULL
        );

        CREATE TABLE episodes (
            episode_id      INTEGER PRIMARY KEY,
            series_id       INTEGER NOT NULL REFERENCES series(series_id),
            season_number   INTEGER NOT NULL,
            episode_number  INTEGER NOT NULL,
            title           TEXT,
            duration_minutes INTEGER
        );

        CREATE TABLE watch_history (
            watch_id        INTEGER PRIMARY KEY,
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            content_id      INTEGER NOT NULL REFERENCES content_catalog(content_id),
            device_id       INTEGER REFERENCES devices(device_id),
            watched_at      TEXT NOT NULL,
            watch_seconds   INTEGER NOT NULL,
            completion_pct  REAL,
            quality         TEXT            -- sd, hd, uhd
        );

        CREATE TABLE data_usage (
            usage_id        INTEGER PRIMARY KEY,
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            subscription_id INTEGER REFERENCES subscriptions(subscription_id),
            usage_date      TEXT NOT NULL,
            data_mb         REAL NOT NULL,
            voice_minutes   INTEGER DEFAULT 0,
            sms_count       INTEGER DEFAULT 0
        );

        CREATE TABLE invoices (
            invoice_id      INTEGER PRIMARY KEY,
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            subscription_id INTEGER REFERENCES subscriptions(subscription_id),
            invoice_date    TEXT NOT NULL,
            due_date        TEXT NOT NULL,
            amount          REAL NOT NULL,
            tax_amount      REAL DEFAULT 0,
            status          TEXT NOT NULL,  -- paid, pending, overdue, cancelled
            billing_period  TEXT
        );

        CREATE TABLE payments (
            payment_id      INTEGER PRIMARY KEY,
            invoice_id      INTEGER REFERENCES invoices(invoice_id),
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            payment_date    TEXT NOT NULL,
            amount          REAL NOT NULL,
            method          TEXT NOT NULL,
            status          TEXT NOT NULL,  -- success, failed, pending, refunded
            transaction_ref TEXT
        );

        CREATE TABLE support_tickets (
            ticket_id       INTEGER PRIMARY KEY,
            customer_id     INTEGER NOT NULL REFERENCES customers(customer_id),
            category        TEXT NOT NULL,
            subject         TEXT,
            status          TEXT NOT NULL,
            priority        TEXT NOT NULL DEFAULT 'medium',  -- low, medium, high, critical
            created_at      TEXT NOT NULL,
            resolved_at     TEXT,
            assigned_to     TEXT
        );

        CREATE TABLE network_events (
            event_id        INTEGER PRIMARY KEY,
            customer_id     INTEGER REFERENCES customers(customer_id),
            event_type      TEXT NOT NULL,  -- outage, speed_drop, reconnect, maintenance
            severity        TEXT,
            started_at      TEXT NOT NULL,
            ended_at        TEXT,
            city            TEXT,
            description     TEXT
        );
        """
    )

    # ------------------------------------------------------------------ plans
    print("Inserting plans...")
    plans = []
    pid = 1
    for ptype, names in PLAN_NAMES.items():
        for name in names:
            price = {
                "mobile_prepaid": random.choice([300, 500, 800, 1200]),
                "mobile_postpaid": random.choice([999, 1499, 2499, 4999]),
                "broadband": random.choice([1500, 2500, 3500, 5000, 8000]),
                "streaming_only": random.choice([299, 499, 799, 1199]),
                "bundle": random.choice([2999, 3999, 5999, 8999]),
            }[ptype]
            data_gb = None if "Unlimited" in name or ptype == "streaming_only" else random.choice([5, 10, 20, 50, 100, 200])
            quality = random.choice(["sd", "hd", "uhd"]) if ptype in ("streaming_only", "bundle") else None
            max_s = random.choice([1, 2, 4]) if quality else 1
            plans.append((pid, name, ptype, price, data_gb, random.choice([None, 500, 1000, 3000]), quality, max_s, 1))
            pid += 1
    # pad to n_plans
    while len(plans) < n_plans:
        ptype = random.choice(PLAN_TYPES)
        name = f"{ptype.replace('_', ' ').title()} Extra {len(plans)}"
        plans.append((pid, name, ptype, random.uniform(200, 9000), random.choice([5, 20, 50, None]), None, None, 1, 1))
        pid += 1
    cur.executemany(
        "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?)",
        plans[:n_plans],
    )
    plan_ids = list(range(1, n_plans + 1))

    # ------------------------------------------------------------------ customers
    print(f"Inserting {n_customers} customers...")
    start = datetime(2020, 1, 1)
    end = datetime(2026, 8, 1)
    customers = []
    for i in range(1, n_customers + 1):
        city, country = random.choice(CITIES)
        customers.append(
            (
                i,
                f"{random.choice(FIRST)} {random.choice(LAST)}",
                f"user{i}@example.com",
                f"+92{random.randint(3000000000, 3499999999)}",
                city,
                country,
                rand_date(start, end).strftime("%Y-%m-%d"),
                1 if random.random() > 0.12 else 0,
                random.choices(["consumer", "sme", "enterprise"], weights=[85, 12, 3])[0],
            )
        )
        if i % 5000 == 0:
            cur.executemany(
                "INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)",
                customers,
            )
            customers = []
    if customers:
        cur.executemany("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?,?)", customers)

    # ------------------------------------------------------------------ content
    print(f"Inserting {n_content} content items...")
    content_rows = []
    for i in range(1, n_content + 1):
        ctype = random.choices(CONTENT_TYPES, weights=[35, 25, 15, 10, 8, 7])[0]
        genre = random.choice(GENRES)
        title = f"{genre} {ctype.replace('_', ' ').title()} {i}"
        content_rows.append(
            (
                i,
                title,
                ctype,
                genre,
                random.randint(1995, 2026),
                random.randint(20, 180) if ctype != "series" else None,
                round(random.uniform(3.5, 9.5), 1),
                random.choice(["en", "ur", "ar", "hi", "tr"]),
                1 if random.random() < 0.35 else 0,
            )
        )
    cur.executemany(
        "INSERT INTO content_catalog VALUES (?,?,?,?,?,?,?,?,?)",
        content_rows,
    )

    # series + episodes
    print("Inserting series & episodes...")
    series_content = [c for c in content_rows if c[2] == "series"][:n_series]
    series_rows = []
    episode_rows = []
    eid = 1
    for sid, c in enumerate(series_content, 1):
        seasons = random.randint(1, 5)
        eps_per = random.randint(6, 12)
        total_eps = seasons * eps_per
        series_rows.append((sid, c[0], seasons, total_eps))
        for s in range(1, seasons + 1):
            for e in range(1, eps_per + 1):
                episode_rows.append((eid, sid, s, e, f"S{s}E{e}", random.randint(22, 55)))
                eid += 1
    cur.executemany("INSERT INTO series VALUES (?,?,?,?)", series_rows)
    cur.executemany("INSERT INTO episodes VALUES (?,?,?,?,?,?)", episode_rows)

    # ------------------------------------------------------------------ subscriptions
    print(f"Inserting {n_subs} subscriptions...")
    subs = []
    for i in range(1, n_subs + 1):
        cid = random.randint(1, n_customers)
        start_d = rand_date(datetime(2021, 1, 1), datetime(2026, 6, 1))
        status = random.choices(SUB_STATUSES, weights=[70, 70, 70, 70, 8, 12, 10])[0]
        end_d = None
        if status in ("cancelled", "expired"):
            end_d = (start_d + timedelta(days=random.randint(30, 400))).strftime("%Y-%m-%d")
        elif status == "active" and random.random() < 0.3:
            end_d = (start_d + timedelta(days=random.randint(365, 730))).strftime("%Y-%m-%d")
        subs.append(
            (
                i,
                cid,
                random.choice(plan_ids),
                start_d.strftime("%Y-%m-%d"),
                end_d,
                status,
                1 if random.random() > 0.2 else 0,
            )
        )
        if i % 10000 == 0:
            cur.executemany(
                "INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?)",
                subs,
            )
            subs = []
    if subs:
        cur.executemany("INSERT INTO subscriptions VALUES (?,?,?,?,?,?,?)", subs)

    # ------------------------------------------------------------------ devices
    print(f"Inserting {n_devices} devices...")
    devices = []
    for i in range(1, n_devices + 1):
        devices.append(
            (
                i,
                random.randint(1, n_customers),
                random.choice(DEVICE_TYPES),
                f"Device-{i}",
                random.choice(["Android 12", "Android 13", "iOS 17", "Tizen", "webOS", "Windows"]),
                rand_date(datetime(2024, 1, 1), datetime(2026, 8, 1)).strftime("%Y-%m-%d %H:%M:%S"),
                1 if random.random() > 0.05 else 0,
            )
        )
        if i % 10000 == 0:
            cur.executemany("INSERT INTO devices VALUES (?,?,?,?,?,?,?)", devices)
            devices = []
    if devices:
        cur.executemany("INSERT INTO devices VALUES (?,?,?,?,?,?,?)", devices)

    # ------------------------------------------------------------------ watch_history
    print(f"Inserting {n_watch} watch events...")
    watches = []
    content_ids = list(range(1, n_content + 1))
    for i in range(1, n_watch + 1):
        cid = random.randint(1, n_customers)
        content_id = random.choice(content_ids)
        secs = random.randint(30, 7200)
        watches.append(
            (
                i,
                cid,
                content_id,
                random.randint(1, n_devices) if random.random() > 0.1 else None,
                rand_date(datetime(2024, 1, 1), datetime(2026, 8, 20)).strftime("%Y-%m-%d %H:%M:%S"),
                secs,
                min(100.0, round(secs / random.uniform(60, 120), 1)),
                random.choice(["sd", "hd", "hd", "uhd"]),
            )
        )
        if i % 20000 == 0:
            cur.executemany(
                "INSERT INTO watch_history VALUES (?,?,?,?,?,?,?,?)",
                watches,
            )
            watches = []
            print(f"  ... {i} watches")
    if watches:
        cur.executemany("INSERT INTO watch_history VALUES (?,?,?,?,?,?,?,?)", watches)

    # ------------------------------------------------------------------ data_usage
    print(f"Inserting {n_usage} usage records...")
    usage = []
    for i in range(1, n_usage + 1):
        usage.append(
            (
                i,
                random.randint(1, n_customers),
                random.randint(1, n_subs) if random.random() > 0.2 else None,
                rand_date(datetime(2025, 1, 1), datetime(2026, 8, 20)).strftime("%Y-%m-%d"),
                round(random.uniform(10, 15000), 1),
                random.randint(0, 300),
                random.randint(0, 50),
            )
        )
        if i % 20000 == 0:
            cur.executemany("INSERT INTO data_usage VALUES (?,?,?,?,?,?,?)", usage)
            usage = []
    if usage:
        cur.executemany("INSERT INTO data_usage VALUES (?,?,?,?,?,?,?)", usage)

    # ------------------------------------------------------------------ invoices
    print(f"Inserting {n_invoices} invoices...")
    invoices = []
    for i in range(1, n_invoices + 1):
        inv_d = rand_date(datetime(2024, 1, 1), datetime(2026, 8, 1))
        amount = round(random.uniform(299, 8999), 2)
        status = random.choices(INVOICE_STATUSES, weights=[65, 15, 12, 8])[0]  # paid, pending, overdue, cancelled
        invoices.append(
            (
                i,
                random.randint(1, n_customers),
                random.randint(1, n_subs) if random.random() > 0.15 else None,
                inv_d.strftime("%Y-%m-%d"),
                (inv_d + timedelta(days=15)).strftime("%Y-%m-%d"),
                amount,
                round(amount * 0.05, 2),
                status,
                inv_d.strftime("%Y-%m"),
            )
        )
        if i % 20000 == 0:
            cur.executemany(
                "INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?)",
                invoices,
            )
            invoices = []
    if invoices:
        cur.executemany("INSERT INTO invoices VALUES (?,?,?,?,?,?,?,?,?)", invoices)

    # ------------------------------------------------------------------ payments
    print(f"Inserting {n_payments} payments...")
    payments = []
    for i in range(1, n_payments + 1):
        payments.append(
            (
                i,
                random.randint(1, n_invoices) if random.random() > 0.1 else None,
                random.randint(1, n_customers),
                rand_date(datetime(2024, 1, 1), datetime(2026, 8, 20)).strftime("%Y-%m-%d %H:%M:%S"),
                round(random.uniform(100, 9000), 2),
                random.choice(PAYMENT_METHODS),
                random.choices(PAYMENT_STATUSES, weights=[75, 8, 7, 10])[0],
                f"TXN{random.randint(10**10, 10**12)}",
            )
        )
        if i % 20000 == 0:
            cur.executemany(
                "INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)",
                payments,
            )
            payments = []
    if payments:
        cur.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?,?,?)", payments)

    # ------------------------------------------------------------------ tickets
    print(f"Inserting {n_tickets} support tickets...")
    tickets = []
    for i in range(1, n_tickets + 1):
        created = rand_date(datetime(2024, 6, 1), datetime(2026, 8, 20))
        status = random.choices(TICKET_STATUSES, weights=[20, 25, 35, 15, 5])[0]
        resolved = None
        if status in ("resolved", "closed"):
            resolved = (created + timedelta(hours=random.randint(1, 120))).strftime("%Y-%m-%d %H:%M:%S")
        tickets.append(
            (
                i,
                random.randint(1, n_customers),
                random.choice(TICKET_CATEGORIES),
                f"Issue report #{i}",
                status,
                random.choices(["low", "medium", "high", "critical"], weights=[20, 45, 25, 10])[0],
                created.strftime("%Y-%m-%d %H:%M:%S"),
                resolved,
                random.choice(["Agent A", "Agent B", "Agent C", "L2 Support", None]),
            )
        )
        if i % 5000 == 0:
            cur.executemany(
                "INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?,?)",
                tickets,
            )
            tickets = []
    if tickets:
        cur.executemany("INSERT INTO support_tickets VALUES (?,?,?,?,?,?,?,?,?)", tickets)

    # ------------------------------------------------------------------ network events
    print(f"Inserting {n_events} network events...")
    events = []
    for i in range(1, n_events + 1):
        started = rand_date(datetime(2025, 1, 1), datetime(2026, 8, 20))
        ended = started + timedelta(minutes=random.randint(5, 480))
        events.append(
            (
                i,
                random.randint(1, n_customers) if random.random() > 0.3 else None,
                random.choice(["outage", "speed_drop", "reconnect", "maintenance"]),
                random.choice(["low", "medium", "high"]),
                started.strftime("%Y-%m-%d %H:%M:%S"),
                ended.strftime("%Y-%m-%d %H:%M:%S"),
                random.choice([c[0] for c in CITIES]),
                "Automated network event",
            )
        )
    cur.executemany(
        "INSERT INTO network_events VALUES (?,?,?,?,?,?,?,?)",
        events,
    )

    # indexes for realistic query speed
    print("Creating indexes...")
    cur.executescript(
        """
        CREATE INDEX idx_sub_customer ON subscriptions(customer_id);
        CREATE INDEX idx_sub_status ON subscriptions(status);
        CREATE INDEX idx_sub_plan ON subscriptions(plan_id);
        CREATE INDEX idx_watch_customer ON watch_history(customer_id);
        CREATE INDEX idx_watch_content ON watch_history(content_id);
        CREATE INDEX idx_watch_at ON watch_history(watched_at);
        CREATE INDEX idx_usage_customer ON data_usage(customer_id);
        CREATE INDEX idx_usage_date ON data_usage(usage_date);
        CREATE INDEX idx_inv_customer ON invoices(customer_id);
        CREATE INDEX idx_inv_status ON invoices(status);
        CREATE INDEX idx_pay_customer ON payments(customer_id);
        CREATE INDEX idx_pay_status ON payments(status);
        CREATE INDEX idx_ticket_customer ON support_tickets(customer_id);
        CREATE INDEX idx_ticket_status ON support_tickets(status);
        CREATE INDEX idx_device_customer ON devices(customer_id);
        CREATE INDEX idx_content_type ON content_catalog(content_type);
        CREATE INDEX idx_content_genre ON content_catalog(genre);
        """
    )

    conn.commit()
    conn.close()
    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.1f}s → {output_path}")
    print(
        f"Approx sizes: customers={n_customers}, subs={n_subs}, "
        f"watch={n_watch}, invoices={n_invoices}, tickets={n_tickets}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", default="streaming_telecom.db")
    parser.add_argument("--scale", type=int, default=1)
    args = parser.parse_args()
    build(args.output, args.scale)
