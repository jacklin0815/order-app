import sqlite3
import os
import fcntl
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask import g

def hash_pw(password):
    return generate_password_hash(password, method="pbkdf2:sha256")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "orders.db")


def get_db():
    try:
        from flask import has_app_context
        if has_app_context() and "_db" in g:
            return g._db
    except RuntimeError:
        pass

    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    try:
        from flask import has_app_context
        if has_app_context():
            g._db = conn
    except RuntimeError:
        pass

    return conn


def close_db(e=None):
    conn = g.pop("_db", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def init_db():
    lock_path = DB_PATH + ".init_lock"
    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            conn = get_db()
            _db_init_with_conn(conn)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _db_init_with_conn(conn):
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
            po_name TEXT NOT NULL DEFAULT '',
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

    # Migrate orders table: add po_name column if missing
    cur = conn.execute("PRAGMA table_info(orders)")
    columns = [r["name"] for r in cur.fetchall()]
    if "po_name" not in columns:
        conn.execute("ALTER TABLE orders ADD COLUMN po_name TEXT NOT NULL DEFAULT ''")

    # Migrate files table: add uploaded_by_role column if missing
    cur = conn.execute("PRAGMA table_info(files)")
    columns = [r["name"] for r in cur.fetchall()]
    if "uploaded_by_role" not in columns:
        conn.execute("ALTER TABLE files ADD COLUMN uploaded_by_role TEXT NOT NULL DEFAULT ''")

    # Notifications table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            message TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            read INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Activity log table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            action TEXT NOT NULL,
            order_id INTEGER,
            details TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        )
    """)

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
        # Reset admin password and hash non-admin passwords
        conn.execute("UPDATE users SET password = ? WHERE username = 'admin'",
                     (hash_pw("admin123"),))
        for row in conn.execute("SELECT id, username FROM users WHERE role != 'admin'").fetchall():
            conn.execute("UPDATE users SET password = ? WHERE id = ?",
                         (hash_pw(row["username"] + "123"), row["id"]))
        conn.commit()

    # Migrate users table: add default_sales_id column if missing
    cur = conn.execute("PRAGMA table_info(users)")
    columns = [r["name"] for r in cur.fetchall()]
    if "default_sales_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN default_sales_id INTEGER REFERENCES users(id)")

    # Migrate users table: add default_designer_id column if missing
    cur = conn.execute("PRAGMA table_info(users)")
    columns = [r["name"] for r in cur.fetchall()]
    if "default_designer_id" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN default_designer_id INTEGER REFERENCES users(id)")

    # Migrate orders table: fix foreign keys referencing users_old -> users
    cur = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='orders'")
    row = cur.fetchone()
    if row and "users_old" in row["sql"]:
        conn.execute("DROP TABLE IF EXISTS orders_new")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript("""
            CREATE TABLE orders_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                po_name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'customer_input',
                original_text TEXT,
                translated_text TEXT,
                sales_revised_text TEXT,
                customer_id INTEGER REFERENCES users(id),
                assigned_sales_id INTEGER REFERENCES users(id),
                assigned_designer_id INTEGER REFERENCES users(id),
                created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            INSERT INTO orders_new (id, po_name, status, original_text, translated_text,
                sales_revised_text, customer_id, assigned_sales_id, assigned_designer_id, created_at)
            SELECT id, po_name, status, original_text, translated_text,
                sales_revised_text, customer_id, assigned_sales_id, assigned_designer_id, created_at
            FROM orders;
            DROP TABLE orders;
            ALTER TABLE orders_new RENAME TO orders;
        """)
        conn.execute("PRAGMA foreign_keys = ON")

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

    # Migrate: hash any remaining plaintext passwords
    for row in conn.execute("SELECT id, password FROM users").fetchall():
        pw = row["password"]
        if not pw.startswith(("scrypt:", "pbkdf2:")):
            conn.execute("UPDATE users SET password = ? WHERE id = ?",
                         (hash_pw(pw), row["id"]))
    conn.commit()

    # Migrate users table: add plaintext_password column if missing
    cur = conn.execute("PRAGMA table_info(users)")
    columns = [r["name"] for r in cur.fetchall()]
    if "plaintext_password" not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN plaintext_password TEXT")
        # Backfill: use username+123 pattern for non-admin, admin123 for admin
        for row in conn.execute("SELECT id, username, role FROM users").fetchall():
            pw = "admin123" if row["role"] == "admin" else row["username"] + "123"
            conn.execute("UPDATE users SET plaintext_password = ? WHERE id = ?",
                         (pw, row["id"]))
        conn.commit()

    # Seed default admin account if no users exist
    admin_exists = conn.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
    if not admin_exists:
        conn.execute(
            "INSERT INTO users (username, password, role, plaintext_password) VALUES (?, ?, ?, ?)",
            ("admin", hash_pw("admin123"), "admin", "admin123"),
        )
        conn.commit()

    # conn managed by Flask g teardown


# ---- User CRUD ----

def get_user_by_username(username):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def verify_user(username, password):
    user = get_user_by_username(username)
    if not user:
        return None
    stored = user["password"]
    if stored.startswith(("scrypt:", "pbkdf2:")):
        if check_password_hash(stored, password):
            return user
        return None
    # Legacy plaintext fallback — upgrade to hash on successful match
    if stored == password:
        conn = get_db()
        conn.execute("UPDATE users SET password = ? WHERE id = ?",
                     (hash_pw(password), user["id"]))
        conn.commit()
        # conn managed by Flask g teardown
        return user
    return None


def create_user(username, password, role):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password, role, plaintext_password) VALUES (?, ?, ?, ?)",
            (username, hash_pw(password), role, password),
        )
        conn.commit()
        user_id = cur.lastrowid
        # conn managed by Flask g teardown
        return user_id
    except sqlite3.IntegrityError:
        # conn managed by Flask g teardown
        return None


def list_users():
    conn = get_db()
    rows = conn.execute("SELECT id, username, role, created_at, plaintext_password FROM users ORDER BY role, username").fetchall()
    return [dict(r) for r in rows]


def get_users_by_role(role):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, username, role FROM users WHERE role = ? ORDER BY username", (role,)
    ).fetchall()
    return [dict(r) for r in rows]


def delete_user(user_id):
    conn = get_db()
    # Null out foreign key references in orders and users before deleting
    conn.execute("UPDATE orders SET customer_id = NULL WHERE customer_id = ?", (user_id,))
    conn.execute("UPDATE orders SET assigned_sales_id = NULL WHERE assigned_sales_id = ?", (user_id,))
    conn.execute("UPDATE orders SET assigned_designer_id = NULL WHERE assigned_designer_id = ?", (user_id,))
    conn.execute("UPDATE users SET default_sales_id = NULL WHERE default_sales_id = ?", (user_id,))
    conn.execute("UPDATE users SET default_designer_id = NULL WHERE default_designer_id = ?", (user_id,))
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    # conn managed by Flask g teardown


def update_user_role(user_id, role):
    conn = get_db()
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    conn.commit()
    # conn managed by Flask g teardown


def update_user_password(user_id, new_password):
    conn = get_db()
    conn.execute("UPDATE users SET password = ?, plaintext_password = ? WHERE id = ?",
                 (hash_pw(new_password), new_password, user_id))
    conn.commit()
    # conn managed by Flask g teardown


def set_customer_sales(customer_id, sales_id):
    conn = get_db()
    conn.execute("UPDATE users SET default_sales_id = ? WHERE id = ? AND role = 'customer'",
                 (sales_id, customer_id))
    conn.commit()
    # conn managed by Flask g teardown


def get_customer_sales(customer_id):
    conn = get_db()
    row = conn.execute(
        "SELECT default_sales_id FROM users WHERE id = ? AND role = 'customer'",
        (customer_id,),
    ).fetchone()
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
    return [dict(r) for r in rows]


# ---- Order CRUD ----

def create_order(original_text, customer_id=None, assigned_sales_id=None, po_name=''):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO orders (po_name, original_text, status, customer_id, assigned_sales_id) VALUES (?, ?, 'customer_input', ?, ?)",
        (po_name, original_text, customer_id, assigned_sales_id),
    )
    conn.commit()
    order_id = cur.lastrowid
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
        where = "AND (o.assigned_sales_id = ? OR o.assigned_sales_id IS NULL)"
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

    pending = q("AND o.status NOT IN ('approved', 'production', 'cancelled')")
    approved = q("AND o.status = 'approved'")
    production = q("AND o.status = 'production'")
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
    # conn managed by Flask g teardown
    result = {}
    for r in rows:
        d = dict(r)
        result.setdefault(d["order_id"], []).append(d)
    return result


def move_to_production(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status = 'production' WHERE id = ? AND status = 'approved'", (order_id,))
    conn.commit()
    # conn managed by Flask g teardown


def delete_order(order_id):
    """Delete an order and its associated files/comments. Returns deleted order dict or None."""
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if not order:
        # conn managed by Flask g teardown
        return None
    conn.execute("DELETE FROM files WHERE order_id = ?", (order_id,))
    conn.execute("DELETE FROM comments WHERE order_id = ?", (order_id,))
    conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
    conn.commit()
    return dict(order)


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
    return [dict(r) for r in rows]


def assign_sales(order_id, sales_id):
    conn = get_db()
    conn.execute("UPDATE orders SET assigned_sales_id = ? WHERE id = ?", (sales_id, order_id))
    conn.commit()
    # conn managed by Flask g teardown


def assign_designer(order_id, designer_id):
    conn = get_db()
    conn.execute("UPDATE orders SET assigned_designer_id = ? WHERE id = ?", (designer_id, order_id))
    conn.commit()
    # conn managed by Flask g teardown


def update_order_status(order_id, status):
    conn = get_db()
    conn.execute("UPDATE orders SET status = ? WHERE id = ?", (status, order_id))
    conn.commit()
    # conn managed by Flask g teardown


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
    # conn managed by Flask g teardown


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
    # conn managed by Flask g teardown


def set_sales_designer(sales_id, designer_id):
    conn = get_db()
    conn.execute("UPDATE users SET default_designer_id = ? WHERE id = ? AND role = 'sales'",
                 (designer_id, sales_id))
    conn.commit()
    # conn managed by Flask g teardown


def get_sales_designer(sales_id):
    conn = get_db()
    row = conn.execute(
        "SELECT default_designer_id FROM users WHERE id = ? AND role = 'sales'",
        (sales_id,),
    ).fetchone()
    return row["default_designer_id"] if row else None


def get_all_sales_designers():
    conn = get_db()
    rows = conn.execute("""
        SELECT u.id AS sales_id, u.username AS sales_name,
               d.id AS designer_id, d.username AS designer_name
        FROM users u
        LEFT JOIN users d ON u.default_designer_id = d.id
        WHERE u.role = 'sales'
        ORDER BY u.username
    """).fetchall()
    return [dict(r) for r in rows]


def add_file(order_id, file_type, filename, stored_path, uploaded_by_role=''):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO files (order_id, file_type, filename, stored_path, uploaded_by_role) VALUES (?, ?, ?, ?, ?)",
        (order_id, file_type, filename, stored_path, uploaded_by_role),
    )
    conn.commit()
    file_id = cur.lastrowid
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
    return [dict(r) for r in rows]


def delete_file(file_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM files WHERE id = ?", (file_id,)).fetchone()
    if not row:
        # conn managed by Flask g teardown
        return None
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))
    conn.commit()
    return dict(row)


def add_comment(order_id, step, role, comment_text):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO comments (order_id, step, role, comment_text) VALUES (?, ?, ?, ?)",
        (order_id, step, role, comment_text),
    )
    conn.commit()
    comment_id = cur.lastrowid
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
    return [dict(r) for r in rows]


def create_notification(user_id, message):
    conn = get_db()
    conn.execute(
        "INSERT INTO notifications (user_id, message) VALUES (?, ?)",
        (user_id, message),
    )
    conn.commit()


def get_user_notifications(user_id):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 50",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_unread_notification_count(user_id):
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM notifications WHERE user_id = ? AND read = 0",
        (user_id,),
    ).fetchone()
    return row["cnt"]


def mark_notifications_read(user_id):
    conn = get_db()
    conn.execute(
        "UPDATE notifications SET read = 1 WHERE user_id = ? AND read = 0",
        (user_id,),
    )
    conn.commit()


def add_activity_log(user_id, username, role, action, order_id=None, details=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO activity_log (user_id, username, role, action, order_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, username, role, action, order_id, details),
    )
    conn.commit()


def get_activity_logs(limit=200):
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def cancel_order(order_id):
    conn = get_db()
    conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    conn.commit()
