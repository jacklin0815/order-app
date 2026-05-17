import os
import uuid
import time
from functools import wraps
from datetime import datetime, timezone

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_from_directory,
    session,
    redirect,
    url_for,
)
from werkzeug.utils import secure_filename

from db import (
    init_db,
    create_order,
    get_order,
    list_orders,
    update_order_status,
    update_translation,
    approve_translation,
    add_file,
    get_files,
    delete_file,
    add_comment,
    get_comments,
    verify_user,
    get_user_by_id,
    create_user,
    list_users,
    delete_user,
    update_user_role,
    get_user_tasks,
    get_users_by_role,
    assign_sales,
    assign_designer,
    get_drawings_for_orders,
    move_to_production,
    set_customer_sales,
    get_customer_sales,
    get_all_customer_sales,
    set_sales_designer,
    get_sales_designer,
    get_all_sales_designers,
    delete_order,
)
from translate import translate_to_chinese

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "order-app-secret-key-change-in-production")
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
CUSTOMER_DIR = os.path.join(UPLOADS_DIR, "customer")
DRAWINGS_DIR = os.path.join(UPLOADS_DIR, "drawings")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "dwg", "dxf", "zip", "doc", "docx", "xls", "xlsx", "csv", "txt"}

def allowed_file(filename):
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def save_upload(file, subdir):
    filename = secure_filename(file.filename)
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    filepath = os.path.join(UPLOADS_DIR, subdir, unique_name)
    file.save(filepath)
    return filename, unique_name


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def get_current_user():
    if "user_id" in session:
        return get_user_by_id(session["user_id"])
    return None


# ---- CSRF protection ----

def generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = uuid.uuid4().hex
    return session["_csrf_token"]


@app.before_request
def csrf_protect():
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return None
    if request.path == "/login":
        return None
    token = request.form.get("_csrf_token") or request.headers.get("X-CSRF-Token") or (request.get_json(silent=True) or {}).get("_csrf_token")
    if not token or token != session.get("_csrf_token"):
        return jsonify({"error": "CSRF token missing or invalid"}), 403
    return None


app.jinja_env.globals["csrf_token"] = generate_csrf_token


# ---- Rate limiting ----

LOGIN_ATTEMPTS = {}

def check_rate_limit(key, max_attempts=5, window_seconds=300):
    now = time.time()
    attempts = LOGIN_ATTEMPTS.get(key, [])
    attempts = [t for t in attempts if now - t < window_seconds]
    LOGIN_ATTEMPTS[key] = attempts
    if len(attempts) >= max_attempts:
        return False
    attempts.append(now)
    return True


# ---- Auth routes ----

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if not check_rate_limit(f"login:{request.remote_addr}"):
            return render_template("login.html", error="Too many login attempts. Please wait a few minutes.")

        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            return render_template("login.html", error="Username and password are required.")

        user = verify_user(username, password)
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))

        return render_template("login.html", error="Invalid username or password.")

    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---- Dashboard ----

@app.route("/")
@login_required
def index():
    return redirect(url_for("dashboard"))


@app.route("/instructions")
@login_required
def instructions():
    user = get_current_user()
    return render_template("instructions.html", user=user)


@app.route("/dashboard")
@login_required
def dashboard():
    user = get_current_user()
    pending, approved, production = get_user_tasks(user["id"], user["role"])
    admin_users = list_users() if user["role"] == "admin" else None
    customer_sales = get_all_customer_sales() if user["role"] == "admin" else None
    sales_designers = get_all_sales_designers() if user["role"] == "admin" else None
    all_sales = get_users_by_role("sales") if user["role"] == "admin" else None
    all_designers = get_users_by_role("designer") if user["role"] == "admin" else None

    # Collect drawing files for approved and production orders
    approved_ids = [o["id"] for o in approved]
    prod_ids = [o["id"] for o in production]
    all_done_ids = approved_ids + prod_ids
    drawings_map = get_drawings_for_orders(all_done_ids) if all_done_ids else {}

    return render_template(
        "dashboard.html",
        user=user,
        pending=pending,
        approved=approved,
        production=production,
        drawings_map=drawings_map,
        admin_users=admin_users,
        customer_sales=customer_sales,
        sales_designers=sales_designers,
        all_sales=all_sales,
        all_designers=all_designers,
    )


# ---- Work page (existing 3-column order interface) ----

@app.route("/work/new")
@login_required
def work_new():
    """New order page for customers."""
    user = get_current_user()
    if user["role"] != "customer":
        return redirect(url_for("dashboard"))
    sales_users = get_users_by_role("sales")
    designer_users = get_users_by_role("designer")
    default_sales_id = get_customer_sales(user["id"]) if user["role"] == "customer" else None
    return render_template(
        "index.html",
        user=user,
        order=None,
        orders=[],
        sales_users=sales_users,
        designer_users=designer_users,
        default_sales_id=default_sales_id,
    )


@app.route("/work/<int:order_id>")
@login_required
def work_page(order_id):
    user = get_current_user()
    order = get_order(order_id)
    if not order:
        return "Order not found", 404
    sales_users = get_users_by_role("sales")
    designer_users = get_users_by_role("designer")
    return render_template(
        "index.html",
        user=user,
        order=order,
        orders=list_orders(),
        sales_users=sales_users,
        designer_users=designer_users,
    )


# ---- Admin user management ----

@app.route("/api/users", methods=["GET"])
@login_required
def api_list_users():
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403
    return jsonify(list_users())


@app.route("/api/users", methods=["POST"])
@login_required
def api_create_user():
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    role = data.get("role", "").strip()

    if not username or not password or not role:
        return jsonify({"error": "Username, password, and role are required"}), 400
    if role not in ("administrator", "customer", "sales", "designer"):
        return jsonify({"error": "Invalid role"}), 400

    # Map display name to db value
    if role == "administrator":
        role = "admin"

    user_id = create_user(username, password, role)
    if user_id is None:
        return jsonify({"error": "Username already exists"}), 409

    return jsonify({"id": user_id, "username": username, "role": role})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@login_required
def api_delete_user(user_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403
    delete_user(user_id)
    return jsonify({"deleted": user_id})


@app.route("/api/users/<int:user_id>/role", methods=["POST"])
@login_required
def api_update_user_role(user_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json() or {}
    role = data.get("role", "").strip()
    if role not in ("administrator", "customer", "sales", "designer"):
        return jsonify({"error": "Invalid role"}), 400

    # Map display name to db value
    if role == "administrator":
        role = "admin"

    update_user_role(user_id, role)
    return jsonify({"updated": user_id, "role": role})


@app.route("/api/customers/<int:customer_id>/assign-sales", methods=["POST"])
@login_required
def api_set_customer_sales(customer_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json() or {}
    sales_id = data.get("sales_id")
    if sales_id is not None:
        sales_id = int(sales_id)

    set_customer_sales(customer_id, sales_id)
    return jsonify({"updated": customer_id, "default_sales_id": sales_id})


@app.route("/api/orders/<int:order_id>", methods=["DELETE"])
@login_required
def api_delete_order(order_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403
    deleted = delete_order(order_id)
    if not deleted:
        return jsonify({"error": "Order not found"}), 404
    return jsonify({"deleted": order_id})


@app.route("/api/sales/<int:sales_id>/assign-designer", methods=["POST"])
@login_required
def api_set_sales_designer(sales_id):
    if session.get("role") != "admin":
        return jsonify({"error": "Admin only"}), 403

    data = request.get_json() or {}
    designer_id = data.get("designer_id")
    if designer_id is not None:
        designer_id = int(designer_id)

    set_sales_designer(sales_id, designer_id)
    return jsonify({"updated": sales_id, "default_designer_id": designer_id})


# ---- File serving ----

@app.route("/uploads/<subdir>/<filename>")
def uploaded_file(subdir, filename):
    return send_from_directory(os.path.join(UPLOADS_DIR, subdir), filename)


# ---- Order API ----

@app.route("/api/orders", methods=["POST"])
@login_required
def api_create_order():
    text = request.form.get("text", "").strip()

    customer_id = session["user_id"] if session.get("role") == "customer" else None
    sales_id = request.form.get("assigned_sales_id")
    if sales_id:
        sales_id = int(sales_id)
    elif customer_id:
        sales_id = get_customer_sales(customer_id)

    order_id = create_order(text or "", customer_id, sales_id)

    for key in request.files:
        for f in request.files.getlist(key):
            if f.filename and allowed_file(f.filename):
                orig_name, stored_name = save_upload(f, "customer")
                add_file(order_id, "customer", orig_name, stored_name)

    if text:
        try:
            translated = translate_to_chinese(text)
            update_translation(order_id, translated)
        except Exception as e:
            app.logger.error("Translation failed: %s", e)
            update_translation(order_id, f"[Translation error: {e}]")

    order = get_order(order_id)
    order["files"] = get_files(order_id)
    return jsonify(order)


@app.route("/api/orders/<int:order_id>", methods=["GET"])
@login_required
def api_get_order(order_id):
    order = get_order(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    order["files"] = get_files(order_id)
    order["comments"] = get_comments(order_id)
    return jsonify(order)


# ---- Assignment API ----

@app.route("/api/orders/<int:order_id>/assign-sales", methods=["POST"])
@login_required
def api_assign_sales(order_id):
    data = request.get_json() or {}
    sales_id = data.get("sales_id")
    if sales_id:
        assign_sales(order_id, int(sales_id))
    else:
        order = get_order(order_id)
        if order and order["customer_id"]:
            default_sales = get_customer_sales(order["customer_id"])
            if default_sales:
                assign_sales(order_id, default_sales)
    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/assign-designer", methods=["POST"])
@login_required
def api_assign_designer(order_id):
    data = request.get_json() or {}
    designer_id = data.get("designer_id")
    if designer_id:
        assign_designer(order_id, int(designer_id))
    else:
        order = get_order(order_id)
        if order and order["assigned_sales_id"]:
            default_designer = get_sales_designer(order["assigned_sales_id"])
            if default_designer:
                assign_designer(order_id, default_designer)
    return jsonify(get_order(order_id))


# ---- Existing workflow API routes ----

@app.route("/api/orders/<int:order_id>/translate", methods=["POST"])
@login_required
def api_translate(order_id):
    order = get_order(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    try:
        translated = translate_to_chinese(order["original_text"])
        update_translation(order_id, translated)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/approve-translation", methods=["POST"])
@login_required
def api_approve_translation(order_id):
    data = request.get_json() or {}
    revised_text = data.get("revised_text", "").strip() or None
    designer_id = data.get("designer_id")
    approve_translation(order_id, revised_text)

    # Assign designer: use selected, or fall back to sales person's default
    if designer_id:
        assign_designer(order_id, int(designer_id))
    else:
        order = get_order(order_id)
        if order and order["assigned_sales_id"]:
            default_designer = get_sales_designer(order["assigned_sales_id"])
            if default_designer:
                assign_designer(order_id, default_designer)

    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/upload-drawing", methods=["POST"])
@login_required
def api_upload_drawing(order_id):
    order = get_order(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404

    for key in request.files:
        for f in request.files.getlist(key):
            if f.filename and allowed_file(f.filename):
                orig_name, stored_name = save_upload(f, "drawings")
                add_file(order_id, "drawing", orig_name, stored_name)

    update_order_status(order_id, "designer_work")

    order = get_order(order_id)
    order["files"] = get_files(order_id)
    return jsonify(order)


@app.route("/api/orders/<int:order_id>/submit-drawings", methods=["POST"])
@login_required
def api_submit_drawings(order_id):
    update_order_status(order_id, "sales_review_drawings")
    return jsonify(get_order(order_id))


@app.route("/api/files/<int:file_id>", methods=["DELETE"])
@login_required
def api_delete_file(file_id):
    row = delete_file(file_id)
    if not row:
        return jsonify({"error": "File not found"}), 404
    if row["file_type"] == "drawing":
        os.remove(os.path.join(DRAWINGS_DIR, row["stored_path"]))
    else:
        os.remove(os.path.join(CUSTOMER_DIR, row["stored_path"]))
    return jsonify({"deleted": file_id})


@app.route("/api/orders/<int:order_id>/approve-drawing", methods=["POST"])
@login_required
def api_approve_drawing(order_id):
    update_order_status(order_id, "customer_review")
    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/return-drawing", methods=["POST"])
@login_required
def api_return_drawing(order_id):
    data = request.get_json() or {}
    comment_text = data.get("comment", "").strip()
    if comment_text:
        add_comment(order_id, "sales_review_drawings", "sales", comment_text)
    update_order_status(order_id, "designer_work")
    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/customer-approve", methods=["POST"])
@login_required
def api_customer_approve(order_id):
    update_order_status(order_id, "approved")
    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/move-to-production", methods=["POST"])
@login_required
def api_move_to_production(order_id):
    move_to_production(order_id)
    return jsonify(get_order(order_id))


@app.route("/api/orders/move-to-production", methods=["POST"])
@login_required
def api_batch_move_to_production():
    data = request.get_json() or {}
    order_ids = data.get("order_ids", [])
    if not order_ids:
        return jsonify({"error": "order_ids is required"}), 400
    for oid in order_ids:
        move_to_production(int(oid))
    return jsonify({"moved": len(order_ids)})


@app.route("/api/orders/<int:order_id>/customer-return", methods=["POST"])
@login_required
def api_customer_return(order_id):
    data = request.get_json() or {}
    comment_text = data.get("comment", "").strip()
    if comment_text:
        add_comment(order_id, "customer_review", "customer", comment_text)
    update_order_status(order_id, "sales_review_translation")
    return jsonify(get_order(order_id))


@app.route("/api/orders/<int:order_id>/update-text", methods=["POST"])
@login_required
def api_update_text(order_id):
    """Customer updates text and triggers re-translation (step 9 loop)."""
    data = request.get_json() or {}
    new_text = data.get("text", "").strip()
    if not new_text:
        return jsonify({"error": "Text is required"}), 400

    from db import get_db
    conn = get_db()
    conn.execute(
        "UPDATE orders SET original_text = ?, sales_revised_text = NULL WHERE id = ?",
        (new_text, order_id),
    )
    conn.commit()
    conn.close()

    try:
        translated = translate_to_chinese(new_text)
        update_translation(order_id, translated)
    except Exception as e:
        app.logger.error("Re-translation failed: %s", e)

    order = get_order(order_id)
    order["files"] = get_files(order_id)
    order["comments"] = get_comments(order_id)
    return jsonify(order)


os.makedirs(CUSTOMER_DIR, exist_ok=True)
os.makedirs(DRAWINGS_DIR, exist_ok=True)
init_db()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
