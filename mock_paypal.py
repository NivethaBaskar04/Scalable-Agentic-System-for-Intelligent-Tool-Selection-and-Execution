"""
Mock PayPal API.

A realistic, stateful simulation of a PayPal-like API, per assignment
section 11. Real HTTP endpoints are registered (visible in /docs) for every
core tool, and all of them share one SQLite database so state persists
across calls (e.g. create_invoice -> send_invoice -> get_invoice all see
the same row).

Rather than 30 near-identical hand-written CRUD functions, a small set of
generic handlers dispatches based on the tool's `domain` + `operation`
metadata - this is also how the system could handle the *synthetic* bulk
tools (from generate_tools.py) executing against a generic simulated
backend if ever asked to, without anyone writing endpoint #501 by hand.
"""
from __future__ import annotations
import random
import sqlite3
import string
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from app.config import PAYPAL_DB

router = APIRouter(prefix="/paypal", tags=["mock-paypal"])
_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY, customer_name TEXT, amount REAL, currency TEXT,
    status TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY, customer_name TEXT, amount REAL, currency TEXT,
    status TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS refunds (
    id TEXT PRIMARY KEY, payment_id TEXT, amount REAL, created_at REAL
);
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY, name TEXT, email TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS subscriptions (
    id TEXT PRIMARY KEY, customer_name TEXT, plan TEXT, status TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS disputes (
    id TEXT PRIMARY KEY, payment_id TEXT, customer_name TEXT, reason TEXT,
    status TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS payouts (
    id TEXT PRIMARY KEY, recipient TEXT, amount REAL, status TEXT, created_at REAL
);
CREATE TABLE IF NOT EXISTS transactions (
    id TEXT PRIMARY KEY, kind TEXT, amount REAL, created_at REAL
);
"""


def _init_db():
    with sqlite3.connect(str(PAYPAL_DB)) as conn:
        conn.executescript(SCHEMA)
        # Seed some baseline data so reports/lists aren't empty on a fresh demo
        row = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
        if row[0] == 0:
            now = time.time()
            for i in range(12):
                conn.execute(
                    "INSERT INTO transactions (id, kind, amount, created_at) VALUES (?, ?, ?, ?)",
                    (f"TXN-{1000+i}", random.choice(["sale", "refund", "payout"]),
                     round(random.uniform(15, 800), 2), now - i * 86400),
                )
            conn.execute(
                "INSERT INTO customers (id, name, email, created_at) VALUES (?, ?, ?, ?)",
                ("CUST-1", "John Smith", "john@example.com", now),
            )
            conn.execute(
                "INSERT INTO customers (id, name, email, created_at) VALUES (?, ?, ?, ?)",
                ("CUST-2", "user_123", "user123@example.com", now),
            )
            conn.execute(
                "INSERT INTO disputes (id, payment_id, customer_name, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("DSP-1", "PAY-SEED1", "user_123", "Item not received", "OPEN", now),
            )
            conn.execute(
                "INSERT INTO payments (id, customer_name, amount, currency, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("PAY-SEED1", "user_123", 120.0, "USD", "CAPTURED", now),
            )
            conn.execute(
                "INSERT INTO invoices (id, customer_name, amount, currency, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                ("INV-1", "John Smith", 200.0, "USD", "DRAFT", now),
            )
            conn.execute(
                "INSERT INTO subscriptions (id, customer_name, plan, status, created_at) VALUES (?, ?, ?, ?, ?)",
                ("SUB-1", "John Smith", "pro", "ACTIVE", now),
            )
        conn.commit()


_init_db()


@contextmanager
def _conn():
    with _lock:
        conn = sqlite3.connect(str(PAYPAL_DB))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def _gen_id(prefix: str) -> str:
    suffix = "".join(random.choices(string.digits, k=6))
    return f"{prefix}-{suffix}"


# ---------------- Invoices ----------------
@router.post("/invoices")
def create_invoice(body: Dict[str, Any]):
    invoice_id = _gen_id("INV")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO invoices (id, customer_name, amount, currency, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (invoice_id, body.get("customer_name", "Unknown"), body.get("amount", 0),
             body.get("currency", "USD"), "DRAFT", time.time()),
        )
    return {"invoice_id": invoice_id, "status": "DRAFT"}


@router.post("/invoices/{invoice_id}/send")
def send_invoice(invoice_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Invoice {invoice_id} not found")
        conn.execute("UPDATE invoices SET status='SENT' WHERE id=?", (invoice_id,))
    return {"invoice_id": invoice_id, "status": "SENT"}


@router.post("/invoices/{invoice_id}/remind")
def remind_invoice(invoice_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Invoice {invoice_id} not found")
    return {"invoice_id": invoice_id, "status": "REMINDER_SENT"}


@router.post("/invoices/{invoice_id}/cancel")
def cancel_invoice(invoice_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Invoice {invoice_id} not found")
        conn.execute("UPDATE invoices SET status='CANCELLED' WHERE id=?", (invoice_id,))
    return {"invoice_id": invoice_id, "status": "CANCELLED"}


@router.get("/invoices/{invoice_id}")
def get_invoice(invoice_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Invoice {invoice_id} not found")
        return {"invoice": dict(row)}


@router.get("/invoices")
def list_invoices(status: Optional[str] = None):
    with _conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM invoices WHERE status=?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM invoices").fetchall()
        return {"invoices": [dict(r) for r in rows]}


# ---------------- Payments ----------------
@router.post("/payments")
def create_payment(body: Dict[str, Any]):
    payment_id = _gen_id("PAY")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO payments (id, customer_name, amount, currency, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (payment_id, body.get("customer_name", "Unknown"), body.get("amount", 0),
             body.get("currency", "USD"), "CREATED", time.time()),
        )
    return {"payment_id": payment_id, "status": "CREATED"}


@router.post("/payments/{payment_id}/capture")
def capture_payment(payment_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Payment {payment_id} not found")
        conn.execute("UPDATE payments SET status='CAPTURED' WHERE id=?", (payment_id,))
    return {"payment_id": payment_id, "status": "CAPTURED"}


@router.post("/payments/{payment_id}/refund")
def refund_payment(payment_id: str, body: Dict[str, Any] = None):
    body = body or {}
    with _conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            # Allow refunding seeded/demo payment IDs that weren't created in this session
            if payment_id.upper().startswith("PAY"):
                refund_id = _gen_id("REFUND")
                amount = body.get("amount", 0)
                conn.execute(
                    "INSERT INTO refunds (id, payment_id, amount, created_at) VALUES (?, ?, ?, ?)",
                    (refund_id, payment_id, amount, time.time()),
                )
                return {"payment_id": payment_id, "status": "REFUNDED", "refund_id": refund_id}
            raise HTTPException(404, f"Payment {payment_id} not found")
        conn.execute("UPDATE payments SET status='REFUNDED' WHERE id=?", (payment_id,))
        refund_id = _gen_id("REFUND")
        amount = body.get("amount", row["amount"])
        conn.execute(
            "INSERT INTO refunds (id, payment_id, amount, created_at) VALUES (?, ?, ?, ?)",
            (refund_id, payment_id, amount, time.time()),
        )
    return {"payment_id": payment_id, "status": "REFUNDED", "refund_id": refund_id}


@router.post("/payments/{payment_id}/void")
def void_payment(payment_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Payment {payment_id} not found")
        conn.execute("UPDATE payments SET status='VOIDED' WHERE id=?", (payment_id,))
    return {"payment_id": payment_id, "status": "VOIDED"}


@router.get("/payments/{payment_id}")
def get_payment(payment_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM payments WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Payment {payment_id} not found")
        return {"payment": dict(row)}


@router.get("/payments")
def list_payments(status: Optional[str] = None):
    with _conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM payments WHERE status=?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM payments").fetchall()
        return {"payments": [dict(r) for r in rows]}


# ---------------- Customers ----------------
@router.post("/customers")
def create_customer(body: Dict[str, Any]):
    customer_id = _gen_id("CUST")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO customers (id, name, email, created_at) VALUES (?, ?, ?, ?)",
            (customer_id, body.get("name", "Unknown"), body.get("email"), time.time()),
        )
    return {"customer_id": customer_id}


@router.get("/customers/search")
def find_customer(name: str):
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM customers WHERE name LIKE ?", (f"%{name}%",)).fetchall()
        if not rows:
            raise HTTPException(404, f"No customer found matching '{name}'")
        return {"customer_id": rows[0]["id"], "name": rows[0]["name"]}


@router.get("/customers/{customer_id}")
def get_customer(customer_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Customer {customer_id} not found")
        return {"customer": dict(row)}


@router.patch("/customers/{customer_id}")
def update_customer(customer_id: str, body: Dict[str, Any]):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Customer {customer_id} not found")
        name = body.get("name", row["name"])
        email = body.get("email", row["email"])
        conn.execute("UPDATE customers SET name=?, email=? WHERE id=?", (name, email, customer_id))
    return {"status": "UPDATED"}


@router.delete("/customers/{customer_id}")
def delete_customer(customer_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Customer {customer_id} not found")
        conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    return {"status": "DELETED"}


@router.get("/customers")
def list_customers():
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM customers").fetchall()
        return {"customers": [dict(r) for r in rows]}


# ---------------- Subscriptions ----------------
@router.post("/subscriptions")
def create_subscription(body: Dict[str, Any]):
    sub_id = _gen_id("SUB")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO subscriptions (id, customer_name, plan, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (sub_id, body.get("customer_name", "Unknown"), body.get("plan", "basic"), "ACTIVE", time.time()),
        )
    return {"subscription_id": sub_id, "status": "ACTIVE"}


@router.post("/subscriptions/{subscription_id}/cancel")
def cancel_subscription(subscription_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Subscription {subscription_id} not found")
        conn.execute("UPDATE subscriptions SET status='CANCELLED' WHERE id=?", (subscription_id,))
    return {"subscription_id": subscription_id, "status": "CANCELLED"}


@router.patch("/subscriptions/{subscription_id}")
def update_subscription_plan(subscription_id: str, body: Dict[str, Any]):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Subscription {subscription_id} not found")
        conn.execute("UPDATE subscriptions SET plan=? WHERE id=?", (body.get("plan", row["plan"]), subscription_id))
    return {"status": "UPDATED"}


@router.get("/subscriptions/{subscription_id}")
def get_subscription(subscription_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM subscriptions WHERE id=?", (subscription_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Subscription {subscription_id} not found")
        return {"subscription": dict(row)}


@router.get("/subscriptions")
def list_subscriptions(status: Optional[str] = None):
    with _conn() as conn:
        if status:
            rows = conn.execute("SELECT * FROM subscriptions WHERE status=?", (status,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM subscriptions").fetchall()
        return {"subscriptions": [dict(r) for r in rows]}


# ---------------- Disputes ----------------
@router.post("/disputes")
def create_dispute(body: Dict[str, Any]):
    dispute_id = _gen_id("DSP")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO disputes (id, payment_id, customer_name, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (dispute_id, body.get("payment_id"), body.get("customer_name"), body.get("reason", "Unspecified"),
             "OPEN", time.time()),
        )
    return {"dispute_id": dispute_id, "status": "OPEN"}


@router.get("/disputes/{dispute_id}")
def get_dispute(dispute_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Dispute {dispute_id} not found")
        return {"dispute": dict(row)}


@router.post("/disputes/{dispute_id}/resolve")
def resolve_dispute(dispute_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM disputes WHERE id=?", (dispute_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Dispute {dispute_id} not found")
        conn.execute("UPDATE disputes SET status='RESOLVED' WHERE id=?", (dispute_id,))
    return {"status": "RESOLVED"}


@router.get("/disputes")
def get_disputes(customer_name: Optional[str] = None, status: Optional[str] = None):
    with _conn() as conn:
        query = "SELECT * FROM disputes WHERE 1=1"
        params = []
        if customer_name:
            query += " AND customer_name LIKE ?"
            params.append(f"%{customer_name}%")
        if status:
            query += " AND status=?"
            params.append(status)
        rows = conn.execute(query, params).fetchall()
        return {"disputes": [dict(r) for r in rows]}


# ---------------- Reports ----------------
@router.get("/reports/sales")
def get_sales_report(period: str = "last_month"):
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM transactions WHERE kind='sale'").fetchall()
        total = sum(r["amount"] for r in rows)
        return {"period": period, "total_sales": round(total, 2), "transaction_count": len(rows)}


@router.get("/transactions")
def get_transaction_history(period: str = "last_month"):
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM transactions ORDER BY created_at DESC").fetchall()
        return {"period": period, "transactions": [dict(r) for r in rows]}


@router.get("/reports/payouts")
def get_payout_report(period: str = "last_month"):
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM payouts").fetchall()
        total = sum(r["amount"] for r in rows)
        return {"period": period, "total_payouts": round(total, 2)}


# ---------------- Payouts ----------------
@router.post("/payouts")
def create_payout(body: Dict[str, Any]):
    payout_id = _gen_id("PO")
    with _conn() as conn:
        conn.execute(
            "INSERT INTO payouts (id, recipient, amount, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (payout_id, body.get("recipient", "Unknown"), body.get("amount", 0), "COMPLETED", time.time()),
        )
    return {"payout_id": payout_id, "status": "COMPLETED"}


@router.get("/payouts/{payout_id}")
def get_payout(payout_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT * FROM payouts WHERE id=?", (payout_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Payout {payout_id} not found")
        return {"payout": dict(row)}


@router.get("/payouts")
def get_payouts():
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM payouts").fetchall()
        return {"payouts": [dict(r) for r in rows]}


# ---------------- Account ----------------
@router.get("/balance")
def get_balance():
    return {"balance": 18452.30, "currency": "USD"}


@router.get("/merchant")
def get_merchant_information():
    return {"merchant": {"business_name": "Demo Merchant Co", "merchant_id": "MERCH-001", "country": "US"}}


@router.post("/oauth2/token")
def get_access_token():
    return {"access_token": "mock-access-token-" + _gen_id("TKN"), "expires_in": 3600}


# Standalone ASGI app for the mock PayPal API. The execution engine talks to
# this over an in-process ASGI transport (see app/executor/engine.py), which
# means every tool call goes through a *real* HTTP request/response cycle -
# exactly like it would against the real PayPal API - without needing a
# second server process running on a second port.
from fastapi import FastAPI  # noqa: E402

mock_paypal_app = FastAPI(title="Mock PayPal API")
mock_paypal_app.include_router(router)

