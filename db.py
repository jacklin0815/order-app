import sqlite3
import os
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin', 'customer', 'sales', 'designer')),
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            status TEXT NOT NULL DEFAULT 'customer_input',
            original_text TEXT,
            translated_text TEXT,
            sales_revised_text TEXT,
            customer_id INTEGER REFERENCES users(id),
            assigned_sales_id INTEGER REFERENCES users(id),
            assigned_designer_id INTEGER REFERENCES users(id),
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            file_type TEXT NOT NULL CHECK(file_type IN ('customer', 'drawing')),
            filename TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL REFERENCES orders(id),
            step TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('sales', 'customer', 'designer')),
            comment_text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
    """)

    # Migrate orders table: add assignment columns if missing
    for col, col_type in [
        ("customer_id", "INTEGER REFERENCES users(id)"),
        ("assigned_sales_id", "INTEGER REFERENCES users(id)"),
        ("assigned_designer_id", "INTEGER REFERENCES users(id)"),
    ]:
        cur = conn.execute(f"PRAGMA table_info(orders)")
        columns = [r["name"] for r in cur.fetchall()]
        if col not in columns:
            conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")

    # Migrate users table: rename password_hash to password if needed
    cur = conn.execute("PRAGMA table_info(users)")
    columns = [r["name"] for r in cur.fetchall()]
    if "password_hash" in columns and "password" not in columns:
        conn.executescript("""
            ALTER TABLE users RENAME TO users_old;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'customer', 'sales', 'designer')),
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            INSERT INTO users (id, username, password, role, created_at)
                SELECT id, username, password_hash, role, created_at FROM users_old;
            DROP TABLE users_old;
        """)
        # Reset admin password and fix hashed non-admin passwords
        conn.execute("UPDATE users SET password = 'admin123' WHERE username = 'admin'")
        for row in conn.execute("SELECT id, username FROM users WHERE role != 'admin'").fetchall():
            conn.execute("UPDATE users SET password = ? WHERE id = ?",
                         (row["username"] + "123", row["id"]))
        conn.commit()

    # Migrate users table: add default_sales_id column if missing
    cur = conn.execute("PRAGMA table_info(users)")
    columns = [r["name"] for r in cur.fetchall()]
    if "default_sales_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN default_sales_id INTEGER REFERENCES users(id)")

    # Migrate comments table to include 'designer' role if needed
    cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='comments'")
    row = cur.fetchone()
    if row and "designer" not in row["sql"]:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS comments_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL REFERENCES orders(id),
                step TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('sales', 'customer', 'designer')),
                comment_text TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            INSERT INTO comments_new SELECT * FROM comments;
            DROP TABLE comments;
            ALTER TABLE comments_new RENAME TO comments;
        """)

    conn.commit()

    # Seed default admin account if no users exist
    admin_exists = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if not admin_exists:
        conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            ("admin", "admin123", "admin"),
        )
        conn.commit()

    conn.close()


# ---- User CRUD ----

def get_user_by_username(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def verify_user(username, password):
    user = get_user_by_username(username)
    if user and user["password"] == password:
        return user
    return None


def create_user(username, password, role):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
            (username, password, role),
        )
        conn.commit()
        user_id = cur.lastrowid
        conn.close()
        return user_id
    except sqlite3.IntegrityError:
        conn.close()
        return None


def list_users():
    conn = get_db()
    rows = conn.execute("SELECT id, username, password, role, created_at FROM users ORDER BY role, username").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_users_by_role(role):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, role FROM users WHERE role = ? ORDER BY username", (role,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_user(user_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ? AND role != 'admin'", (user_id,))
    conn.commit()
    conn.close()


def update_user_role(user_id, role):
    conn = get_db()
    conn.execute("UPDATE users SET role = ? WHERE id = ? AND role != 'admin'", (role, user_id))
    conn.commit()
    conn.close()


def set_customer_sales(customer_id, sales_id):
    conn = get_db()
    conn.execute("UPDATE users SET default_sales_id = ? WHERE id = ? AND role = 'customer'",
                 (sales_id, customer_id))
    conn.commit()
    conn.close()


def get_customer_sales(customer_id):
    conn = get_db()
    row = conn.execute(
        "SELECT default_sales_id FROM users WHERE id = ? AND role = 'customer'",
        (customer_id,),
    ).fetchone()
    conn.close()
    return row["default_sales_id"] if row else None


def get_all_customer_sales():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id AS customer_id, u.username AS customer_name,
               s.id AS sales_id, s.username AS sales_name
        FROM users u
        LEFT JOIN users s ON u.default_sales_id = s.id
        WHERE u.role = 'customer'
        ORDER BY u.username
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Order CRUD ----

def create_order(original_text, customer_id=None, assigned_sales_id=None):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO orders (original_text, status, customer_id, assigned_sales_id) VALUES (?, 'customer_input', ?, ?)",
        (original_text, customer_id, assigned_sales_id),
    )
    conn.commit()
    order_id = cur.lastrowid
    conn.close()
    return order_id


def get_order(order_id):
    conn = get_db()
    row = conn.execute("""
        SELECT o.*,
               cu.username AS customer_name,
               su.username AS sales_name,
               du.username AS designer_name
        FROM orders o
        LEFT JOIN users cu ON o.customer_id = cu.id
        LEFT JOIN users su ON o.assigned_sales_id = su.id
        LEFT JOIN users du ON o.assigned_designer_id = du.id
        WHERE o.id = ?
    """, (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_tasks(user_id, role):
    """Return (pending_orders, approved_orders, production_orders) for a given user and role."""
    conn = get_db()
    base_query = """
        SELECT o.*, cu.username AS customer_name, su.username AS sales_name, du.username AS designer_name
        FROM orders o
        LEFT JOIN users cu ON o.customer_id = cu.id
        LEFT JOIN users su ON o.assigned_sales_id = su.id
        LEFT JOIN users du ON o.assigned_designer_id = du.id
        WHERE 1=1
    """

    if role == "customer":
        where = "AND o.customer_id = ?"
        params = (user_id,)
    elif role == "sales":
        where = "AND o.assigned_sales_id = ?"
        params = (user_id,)
    elif role == "designer":
        where = "AND o.assigned_designer_id = ?"
        params = (user_id,)
    else:
        where = ""
        params = ()

    def q(extra_where, extra_params=None):
        extras = [where] if where else []
        if extra_where:
            extras.append(extra_where)
        clause = " ".join(extras) if extras else ""
        return conn.execute(
            f"{base_query} {clause} ORDER BY o.created_at DESC",
            params + (extra_params or ()),
        ).fetchall()

    pending = q("AND o.status NOT IN ('approved', 'production')")
    approved = q("AND o.status = 'approved'")
    production = q("AND o.status = 'production'")
    conn.close()
    return [dict(r) for r in pending], [dict(r) for r in approved], [dict(r) for r in production]


def get_drawings_for_orders(order_ids):
    """Return {order_id: [file_dict, ...]} mapping for drawing files."""
    if not order_ids:
        return {}
    conn = get_db()
    placeholders = ",".join("?" for _ in order_ids)
    rows = conn.execute(
        f"SELECT * FROM files WHERE order_id IN ({placeholders}) AND file_type = 'drawing' ORDER BY uploaded_at DESC",
        order_ids,
    ).fetchall()
    conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["order_id"], []).append(d)
    return result


def move_to_production(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status = 'production' WHERE id = ? AND status = 'approved'", (order_id,))
    conn.commit()
    conn.close()


def list_orders():
    conn = get_db()
    rows = conn.execute("""
        SELECT o.*, cu.username AS customer_name, su.username AS sales_name, du.username AS designer_name
        FROM orders o
        LEFT JOIN users cu ON o.customer_id = cu.id
        LEFT JOIN users su ON o.assigned_sales_id = su.id
        LEFT JOIN users du ON o.assigned_designer_id = du.id
        ORDER BY o.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def assign_sales(order_id, sales_id):
    conn = get_db()
    conn.execute("UPDATE orders SET assigned_sales_id = ? WHERE id = ?", (sales_id, order_id))
    conn.commit()
    conn.close()


def assign_designer(order_id, designer_id):
    conn = get_db()
    conn.execute("UPDATE orders SET assigned_designer_id = ? WHERE id = ?", (designer_id, order_id))
    conn.commit()
    conn.close()


def update_order_status(order_id, status):
    conn = get_db()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    conn.close()


def update_translation(order_id, translated_text, sales_revised_text=None):
    conn = get_db()
    if sales_revised_text:
        conn.execute(
            "UPDATE orders SET translated_text = ?, sales_revised_text = ?, status = 'sales_review_translation' WHERE id = ?",
            (translated_text, sales_revised_text, order_id),
        )
    else:
        conn.execute(
            "UPDATE orders SET translated_text = ?, status = 'translation_pending' WHERE id = ?",
            (translated_text, order_id),
        )
    conn.commit()
    conn.close()


def approve_translation(order_id, revised_text=None):
    conn = get_db()
    if revised_text:
        conn.execute(
            "UPDATE orders SET sales_revised_text = ?, status = 'designer_work' WHERE id = ?",
            (revised_text, order_id),
        )
    else:
        conn.execute(
            "UPDATE orders SET status = 'designer_work' WHERE id = ?",
            (order_id,),
        )
    conn.commit()
    conn.close()


def add_file(order_id, file_type, filename, stored_path):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO files (order_id, file_type, filename, stored_path) VALUES (?, ?, ?, ?)",
        (order_id, file_type, filename, stored_path),
    )
    conn.commit()
    file_id = cur.lastrowid
    conn.close()
    return file_id


def get_files(order_id, file_type=None):
    conn = get_db()
    if file_type:
        rows = conn.execute(
            "SELECT * FROM files WHERE order_id = ? AND file_type = ? ORDER BY uploaded_at DESC",
            (order_id, file_type),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM files WHERE order_id = ? ORDER BY uploaded_at DESC",
            (order_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_file(file_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    conn.close()
    return dict(row)


def add_comment(order_id, step, role, comment_text):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO comments (order_id, step, role, comment_text) VALUES (?, ?, ?, ?)",
        (order_id, step, role, comment_text),
    )
    conn.commit()
    comment_id = cur.lastrowid
    conn.close()
    return comment_id


def get_comments(order_id, step=None):
    conn = get_db()
    if step:
        rows = conn.execute(
            "SELECT * FROM comments WHERE order_id = ? AND step = ? ORDER BY created_at ASC",
            (order_id, step),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM comments WHERE order_id = ? ORDER BY created_at ASC",
            (order_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
