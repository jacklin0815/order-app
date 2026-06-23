
# GeneralOrder-app

## Vision
Set up a web app integrate customer-sales-designers for order communications and approvals.

## Route
`/Users/jacklin0815/Projects/Business Apps/order-app/`

### Deployed URL
**Production**: [https://order-app-954k.onrender.com](https://order-app-954k.onrender.com)

### How to start (local dev)
```bash
cd "/Users/jacklin0815/Projects/Business Apps/order-app" && python3 app.py
```
Then open `http://localhost:5050`
(If port 5000 is blocked by macOS AirPlay, the app runs on 5050)

### Deployment
- **Platform**: Render (free tier)
- **Region**: Oregon
- **WSGI**: gunicorn with 2 workers, 120s timeout
- **Auto-deploy**: Enabled — pushes to `main` branch trigger automatic deploys. If webhook doesn't fire, use **Manual Deploy** → **Deploy latest commit** in Render dashboard.
- **Repo**: [github.com/jacklin0815/order-app](https://github.com/jacklin0815/order-app) (public)
- **Render dashboard**: [dashboard.render.com/web/srv-d82ntuhj2pic73ao6kr0](https://dashboard.render.com/web/srv-d82ntuhj2pic73ao6kr0)

### Tech Stack
- **Backend**: Flask (Python) — local dev on port 5050, Render uses `$PORT`
- **Database**: SQLite (`orders.db`) — persists across local restarts; on Render free tier, data resets on each deploy
- **Translation**: Azure Translator free tier by default, with optional no-key Google Translate fallback (`TRANSLATION_FALLBACK_PROVIDER=google_free`)
- **Frontend**: Vanilla HTML/CSS/JS with responsive grid layout. Work page: top button row + 3-column review area (Upload Box 1 | Comments | Designer Drawings Box 2) + 2-column bottom (Customer Input | Translation)
- **File storage**: Local filesystem under `uploads/customer/` and `uploads/drawings/`

### File Structure
```
order-app/
├── .env                # Environment variables (translation provider settings, SECRET_KEY) — gitignored
├── app.py              # Flask routes and workflow logic, .env auto-loader
├── db.py               # SQLite schema, CRUD helpers
├── translate.py        # Azure Translator + optional Google free fallback integration
├── templates/
│   ├── login.html      # Login page
│   ├── dashboard.html  # Task dashboard (3-column: Pending / Approved / Production)
│   ├── index.html      # Order work page (3-column layout)
│   ├── instructions.html # Role-based workflow instructions
│   └── audit_log.html  # Admin activity log viewer
├── static/
│   └── style.css       # Styling
└── uploads/
    ├── customer/       # Customer images/files
    └── drawings/       # Designer drawings
```

## Roles
- Administrator — manages user accounts, can assign customer/sales/designer roles
- Customer — submits order requirements, reviews drawings
- Sales — approves translations, reviews and approves/returns drawings
- Designer — uploads drawings for review
Each user logs in with their own username/password. Role is fixed per account.

### Default Administrator Account
- Username: `admin`
- Password: `admin123`

### Administrator Capabilities
- Create new user accounts (administrator, customer, sales, designer)
- Delete any user account (including other administrators)
- Change user roles (all 4 roles: administrator, customer, sales, designer). UI shows "Administrator", DB stores "admin". Changes apply immediately with green flash feedback — no page reload.
- **Reset user password** — "Reset PW" button on each user row. Prompts for new password (defaults to `reset123` if left blank). New password shown in alert and updated in the password column immediately.
- **View passwords** — password column shows `••••••` by default; "Show/Hide" toggle reveals the plaintext password stored alongside the hash.
- **Bulk user import** — upload CSV or Excel file (columns: `username, password, role`). Results shown with created/skipped/error counts. Roles accepted: admin/administrator, customer, sales, designer.
- **Confirm Changes & Refresh** — red button at bottom of admin panel. After making changes, click to hard-refresh the page and sync all changes. Individual operations no longer reload the page.
- **Sales → Designer Assignment** — designate a default designer for each sales person (optional). When that sales approves a translation without explicitly picking a designer, the default is auto-assigned. Dropdown flashes green on save; alerts on failure.
- **Customer → Sales Assignment** — designate a default sales person for each customer (optional). If set, the customer's new orders auto-assign to that sales. Customer can still override. Dropdown flashes green on save; alerts on failure.
- **Delete PO with notifications** — administrator can delete any order with a two-click confirmation (click ×, then "Sure?" within 3 seconds). Deletes the order, all associated files/comments, and sends a notification to each involved user (customer, sales, designer). A bell icon in the top bar shows unread notification count; clicking it opens a dropdown with recent notifications and a "Mark all read" button.

## Steps

### 0. Login
- User visits `/` → redirected to `/login`
- Enter username and password, click "Login"
- After login, redirected to **Dashboard** showing pending and approved tasks
- Role is fixed per account (no role switching)

### 0.5 Dashboard
- **3-column layout**: Pending | Approved | In Production
- Each column shows PO number, creation date, and status badge
- **Instructions button** in the top bar — opens a role-specific workflow guide at `/instructions`
- **Customer**: sees own orders + "+ New Order" button
- **Sales**: sees orders assigned to them
- **Designer**: sees orders assigned to them
- **Administrator**: sees all orders + "Manage Users" panel (user CRUD with password visibility toggle, reset password button, Customer→Sales assignments, Sales→Designer assignments, bulk CSV/Excel import). Assignment tables show empty-state guidance when no users exist yet. All changes (create user, delete user, change role, reset password) apply in-place without page reload; click "Confirm Changes & Refresh" to sync.
- **Notification bell** — top bar shows a bell icon with unread count badge; clicking opens a dropdown with recent notifications
- Click any pending task card to open the work page (`/work/<id>`)
- Approved / Production tasks show expandable drawing download links
- PO cards display PO name (or fallback to `#ID` for legacy orders)

### 1. Customer input
- Customer clicks "+ New Order" on dashboard or opens `/work/new`
- **PO Name** — required field; displayed everywhere instead of `#ID` (e.g., `PO-2024-001`, `Spring Collection`)
- Enter text on the left panel, upload images/files (supports pdf/csv/images)
- **Assign to Sales** via dropdown (picks from all sales users)
- Click "Submit & Translate"

### 2. Translation
- Azure Translator is the default free-tier provider (`TRANSLATION_PROVIDER=azure`)
- Optional no-key Google Translate fallback can be enabled with `TRANSLATION_FALLBACK_PROVIDER=google_free`
- Azure settings are loaded from `AZURE_TRANSLATOR_KEY` and `AZURE_TRANSLATOR_REGION`
- Text is auto-translated to Simplified Chinese
- If all translation providers fail, a visible manual-translation placeholder is saved so Sales can continue the workflow
- Translation appears in the center panel

### 3. Sales approve translation
- Sales opens the order from their dashboard
- Revise translation in the center panel (editable textarea)
- **Assign to Designer** via dropdown (picks from all designer users)，select random one as default.
- Click "Approve Translation" to confirm

### 4. Translation shown to designer
- Once approved, the translation is visible to the Designer role
- Designer sees the order in their dashboard

### 5. Designer upload drawings
- Designer opens the order from their dashboard
- Use upload button in the right panel to upload drawings (Box 2)
- All file formats supported. Max file size: 10 MB.
- Designer can delete own uploaded drawings with the × button (enforced by `uploaded_by_role`)
- Click "Submit Drawings for Review" to advance to Sales review

### 6. Sales approve or return drawings
- Sales opens the order from their dashboard
- Top row: **Approve Drawings** and **Return to Designer** buttons
- 3-column layout: **Upload Box 1** (sales can upload files) | **Comment box** | **Designer Drawings panel** (Box 2)
- **Approve Drawings** — advances to Customer review
- **Return to Designer** — status goes back to Designer work; optional comments added
- Sales can delete files they uploaded (enforced by `uploaded_by_role`)

### 7. Approved drawings shown to customer
- Customer sees the drawings in the right panel

### 8. Customer approve or return
- **Approve** — order marked as Approved (done), moves to Approved section on dashboard
- **Return to Sales** — order goes back to step 6 (sales_review_drawings); optional comments added

### 9. Loop
- If customer returns at step 8, the order loops back to step 6 where Sales re-reviews and can return to Designer, re-triggering the designer-workflow loop.

### 10. Download approved documents
- On approved orders, download links for all drawings appear in the right panel
- Anyone with access can view and download approved documents from the work page

## Workflow States
```
customer_input → translation_pending → sales_review_translation
                                           ├─ approve → designer_work
                                           └─ revise  → stays for re-review

designer_work → upload ⇄ delete → submit → sales_review_drawings
                            ├─ approve → customer_review
                            └─ return  → designer_work (with comments)

customer_review →
    ├─ approve → approved (done)
    └─ return  → sales_review_drawings (with comments, loop to step 6)

approved → production (final stage, documents downloadable)
```

## Data Model

**users**: id, username, password (hashed with werkzeug.security using pbkdf2:sha256), plaintext_password (for admin visibility), role (admin/customer/sales/designer — UI maps "Administrator" → "admin"), default_sales_id, default_designer_id, created_at
**orders**: id, po_name (required, displayed everywhere instead of #ID), status, original_text, translated_text, sales_revised_text, customer_id, assigned_sales_id, assigned_designer_id, created_at
**files**: id, order_id, file_type (customer/drawing), filename, stored_path, uploaded_by_role, uploaded_at
**comments**: id, order_id, step, role (sales/customer/designer), comment_text, created_at
**notifications**: id, user_id, message, created_at, read (0/1)

## API Routes
| Method   | Route                                  | Action                                                    |
| -------- | -------------------------------------- | --------------------------------------------------------- |
| GET/POST | `/login`                               | Login page / authenticate                                 |
| GET      | `/logout`                              | Logout (clears session)                                   |
| GET      | `/`                                    | Redirect to /dashboard                                    |
| GET      | `/dashboard`                           | Task dashboard (3-column with PO dates)                   |
| GET      | `/instructions`                        | Role-specific workflow instruction page                   |
| GET      | `/work/new`                            | New order form (customer only)                            |
| GET      | `/work/<id>`                           | Work page for specific order                              |
| POST     | `/api/orders`                          | Create order + auto-translate                             |
| GET      | `/api/orders/<id>`                     | Get order details, files, comments                        |
| POST     | `/api/orders/<id>/assign-sales`        | Assign sales person to order                              |
| POST     | `/api/orders/<id>/assign-designer`     | Assign designer to order                                  |
| POST     | `/api/orders/<id>/approve-translation` | Sales approves/revises translation (+ assign designer)    |
| POST     | `/api/orders/<id>/translate`           | Re-translate order text via configured translation provider |
| POST     | `/api/orders/<id>/upload-drawing`      | Designer uploads drawings                                 |
| POST     | `/api/orders/<id>/submit-drawings`     | Designer submits drawings for review                      |
| POST     | `/api/orders/<id>/approve-drawing`     | Sales approves drawings                                   |
| POST     | `/api/orders/<id>/return-drawing`      | Sales returns to designer                                 |
| POST     | `/api/orders/<id>/customer-approve`    | Customer approves (done)                                  |
| DELETE   | `/api/files/<id>`                      | Delete own file (role must match uploaded_by_role)        |
| POST     | `/api/orders/<id>/customer-return`     | Customer returns to sales                                 |
| POST     | `/api/orders/<id>/move-to-production`  | Move approved order to production                         |
| POST     | `/api/orders/move-to-production`       | Batch move approved orders to production                  |
| POST     | `/api/orders/<id>/update-text`         | Customer updates text + re-translate                      |
| GET      | `/api/users`                           | Administrator: list users                                 |
| POST     | `/api/users`                           | Administrator: create user                                |
| DELETE   | `/api/users/<id>`                      | Administrator: delete user                                |
| POST     | `/api/users/<id>/role`                 | Administrator: update user role                           |
| POST     | `/api/users/<id>/reset-password`       | Administrator: reset user password (defaults to reset123) |
| POST     | `/api/users/import`                    | Administrator: bulk import users via CSV or Excel file    |
| POST     | `/api/customers/<id>/assign-sales`     | Administrator: set customer's default sales               |
| POST     | `/api/sales/<id>/assign-designer`      | Administrator: set sales person's default designer        |
| DELETE   | `/api/orders/<id>`                     | Administrator: delete order, notify involved users        |
| POST     | `/api/orders/<id>/cancel`              | Administrator: soft-cancel order (status → cancelled)     |
| GET      | `/api/notifications`                   | Get current user's notifications (last 50)                |
| POST     | `/api/notifications/mark-read`         | Mark all notifications as read                            |
| GET      | `/audit-log`                           | Administrator: view activity log page                     |
| GET      | `/api/audit-log`                       | Administrator: get activity log JSON                      |

---

## Instructions System

Each role has a dedicated instruction page at `/instructions` accessible from the "Instructions" button in the top bar. Content covers the complete workflow for administrator, customer, sales, and designer roles with numbered step cards.

## PO Dates

Every order shows its creation date (`YYYY-MM-DD`) on the dashboard next to the PO number and on the work page status bar.

---

## To Do (do on your own)

### Security
- [x] **Remove DeepSeek translation supply** — translation now uses Azure Translator free tier by default, with optional `google_free` fallback
- [x] **Change Flask secret key** — `SECRET_KEY` env var auto-generated on Render
- [x] **Requirements fix** — added `requests>=2.31` to requirements.txt (needed by translate.py)
- [x] **Upgrade password hashing** — now using `werkzeug.security` with `pbkdf2:sha256` (scrypt unavailable on macOS LibreSSL); legacy plaintext auto-upgraded on login
- [x] **Add HTTPS** — Render provides HTTPS by default
- [x] ~~**Rate limiting**~~ — removed per user request (no login attempt restrictions)
- [x] **CSRF protection** — session-based CSRF token on all POST/PUT/DELETE routes; AJAX calls auto-inject token via fetch override
- [x] **Auth on all API routes** — `@login_required` added to 11 previously unprotected routes
- [x] **File upload validation** — `allowed_file()` now checks against a whitelist of 15 safe extensions
- [x] **Password visibility toggle** — administrator panel shows passwords hidden as `••••••` by default with Show/Hide toggle button; plaintext stored alongside hash

### Production
- [x] **Use a WSGI server** — gunicorn on Render with 2 workers
- [x] **Deploy on Render** — [https://order-app-954k.onrender.com](https://order-app-954k.onrender.com)
- [ ] **Database backup** — `orders.db` is one file, but should be backed up regularly (cron job to copy)
- [ ] **Session timeout** — Flask sessions currently never expire; add `PERMANENT_SESSION_LIFETIME`

### Features
- [x] **PO Names** — required field on order creation; displayed everywhere instead of `#ID`
- [x] **Notifications** — bell icon with badge on dashboard; alerts when admin deletes a PO involving you
- [ ] **User self-service password change** — users can't change their own password yet
- [ ] **Order numbering** — switch from auto-increment IDs to business format (e.g. `ORD-2026-001`)
- [x] **Activity log** — complete audit trail tracking who did what and when; accessible via `/audit-log` (admin only)
- [x] **Duplicate order prevention** — submit button disables on click; server-side dedup within 10s for same customer+PO+text
- [x] **Customer delete expansion** — delete available during customer_input, translation_pending, and sales_review_translation (before designer_work)
- [x] **Orphaned order fix** — sales users can now see and pick up orders without an assigned sales person
- [ ] **File size / count limits** — add per-order upload quotas
- [ ] **Mobile responsive layout** — 3-column grid breaks on small screens; add media queries

### Administrator
- [x] **Customer → Sales assignment** — administrator can designate default sales per customer on dashboard (dropdown, green flash on save, error alert on failure)
- [x] **Sales → Designer assignment** — administrator can designate default designer per sales person on dashboard (dropdown, green flash on save, error alert on failure)
- [x] **Role change in-place** — role changes apply immediately with green flash feedback; no page reload. "Confirm Changes & Refresh" button syncs all changes at once.
- [x] **Administrator role option** — role dropdown includes all 4 roles (Administrator, Customer, Sales, Designer) in both create and change-role forms
- [x] **Delete PO with notifications** — administrator can delete orders with two-click confirmation; notifies all involved users via bell icon
- [x] **Bulk user import** — CSV or Excel upload for creating many users at once (columns: username, password, role)
- [x] **Reset user password** — administrator can reset any user's password from the panel; prompt for new password with default fallback
- [x] **Audit Log page** — administrator can view full activity trail at `/audit-log` showing all user actions with timestamps, user info, and order references
- [x] **Cancel Order** — orders can be soft-cancelled (status set to `cancelled`) without deleting data; available via `cancel_order()` in db.py
