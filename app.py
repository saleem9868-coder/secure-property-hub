from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, threading, re
from datetime import datetime
from functools import wraps

# ─── CLOUDINARY SETUP ─────────────────────────────────────────────────────────
import cloudinary
import cloudinary.uploader

# Supports both CLOUDINARY_URL (e.g. Railway) and separate env vars
_cld_url = os.environ.get('CLOUDINARY_URL', '')
if _cld_url.startswith('cloudinary://'):
    # Parse cloudinary://api_key:api_secret@cloud_name manually
    try:
        _cld_rest = _cld_url[len('cloudinary://'):]
        _cld_auth, _cld_cloud = _cld_rest.rsplit('@', 1)
        _cld_key, _cld_secret = _cld_auth.split(':', 1)
        cloudinary.config(
            cloud_name = _cld_cloud.strip(),
            api_key    = _cld_key.strip(),
            api_secret = _cld_secret.strip(),
            secure     = True
        )
    except Exception as _e:
        print(f"Failed to parse CLOUDINARY_URL: {_e}")
else:
    cloudinary.config(
        cloud_name = os.environ.get('CLOUDINARY_CLOUD_NAME'),
        api_key    = os.environ.get('CLOUDINARY_API_KEY'),
        api_secret = os.environ.get('CLOUDINARY_API_SECRET'),
        secure     = True
    )

def _cloudinary_ready():
    """Return True if Cloudinary is configured (either via URL or separate vars)."""
    cfg = cloudinary.config()
    return bool(cfg.cloud_name and cfg.api_key and cfg.api_secret)

def upload_to_cloudinary(file_obj, prefix=''):
    """Upload a file to Cloudinary and return the secure URL."""
    try:
        if not file_obj or not allowed_file(file_obj.filename):
            return None
        ts = datetime.now().strftime('%Y%m%d%H%M%S')
        safe = secure_filename(file_obj.filename).rsplit('.', 1)[0]
        public_id = f"apnaghar/{prefix}{ts}_{safe}"
        result = cloudinary.uploader.upload(
            file_obj,
            public_id=public_id,
            overwrite=True,
            resource_type='image'
        )
        return result.get('secure_url')
    except Exception as e:
        print(f"Cloudinary upload error: {e}")
        return None
try:
    import urllib.request, json as _json
    def _get_geo(ip):
        if not ip or ip in ('127.0.0.1', '::1', ''):
            return 'Local', 'Local'
        try:
            url = f'http://ip-api.com/json/{ip}?fields=city,country,status'
            with urllib.request.urlopen(url, timeout=3) as r:
                data = _json.loads(r.read())
            if data.get('status') == 'success':
                return data.get('city',''), data.get('country','')
        except Exception:
            pass
        return '', ''
except Exception:
    def _get_geo(ip): return '', ''

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'fallback-dev-key-change-in-production')
app.config['UPLOAD_FOLDER'] = os.path.join('static', 'uploads', 'media')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}

# ─── UPLOAD SUBFOLDERS ────────────────────────────────────────────────────────
UPLOAD_BLOG       = os.path.join('static', 'uploads', 'blog')
UPLOAD_PAGES      = os.path.join('static', 'uploads', 'pages')
UPLOAD_PROPERTIES = os.path.join('static', 'uploads', 'properties')
UPLOAD_MEDIA      = os.path.join('static', 'uploads', 'media')

# ─── TRANSLATIONS ─────────────────────────────────────────────────────────────
def T():
    return {}

@app.template_filter('img_url')
def img_url_filter(filename):
    """Convert a filename or Cloudinary URL to a displayable src."""
    if not filename:
        return ''
    if filename.startswith('http://') or filename.startswith('https://'):
        return filename   # already a full Cloudinary URL
    return '/uploads/' + filename   # legacy local file

@app.context_processor
def inject_globals():
    # Inject dynamic menu items for the Resources dropdown
    try:
        conn = get_db()
        menu_items = conn.execute(
            "SELECT * FROM menu_items WHERE is_active=1 ORDER BY display_order ASC"
        ).fetchall()
        conn.close()
    except Exception:
        menu_items = []
    # Pop WhatsApp notify link from session (show once after a listing is submitted)
    wa_notify = session.pop('wa_notify', None)
    return dict(now=datetime.now(), T=T(), lang="en", menu_items=menu_items, wa_notify=wa_notify)

# ─── SECURITY BLOCKER ────────────────────────────────────────────────────────

BLOCKED_PATHS = (
    '/wp-admin', '/wp-login', '/wp-content', '/wp-includes',
    '/wordpress', '/wp-config', '/xmlrpc.php', '/wp-cron',
    '/.git', '/.env', '/.htaccess', '/.htpasswd',
    '/shell', '/cmd', '/eval', '/exec',
    '/phpmyadmin', '/pma', '/myadmin', '/mysql',
    '/admin/config', '/config.php', '/setup.php',
    '/install.php', '/setup-config.php',
    '/etc/passwd', '/proc/self',
    '/boaform', '/cgi-bin', '/vendor',
)

_banned_ips = {}
_BAN_THRESHOLD = 5
_ban_lock = threading.Lock()

def _record_bad_ip(ip):
    with _ban_lock:
        _banned_ips[ip] = _banned_ips.get(ip, 0) + 1

def _is_banned(ip):
    return _banned_ips.get(ip, 0) >= _BAN_THRESHOLD

@app.before_request
def block_hackers():
    ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
    if ',' in ip:
        ip = ip.split(',')[0].strip()
    if _is_banned(ip):
        from flask import abort
        abort(403)
    path = request.path.lower()
    if any(path.startswith(p) or path == p.rstrip('/') for p in BLOCKED_PATHS):
        _record_bad_ip(ip)
        from flask import abort
        abort(404)
    bad_exts = ('.php', '.asp', '.aspx', '.jsp', '.cgi', '.sh', '.bat', '.exe')
    if any(path.endswith(e) for e in bad_exts):
        _record_bad_ip(ip)
        from flask import abort
        abort(404)

# ─── TRAFFIC LOGGER ──────────────────────────────────────────────────────────

SKIP_PREFIXES = ('/uploads/', '/static/', '/favicon')

@app.before_request
def log_traffic():
    path = request.path
    if any(path.startswith(p) for p in SKIP_PREFIXES):
        return
    try:
        ip = request.headers.get('X-Forwarded-For', request.remote_addr or '')
        if ',' in ip:
            ip = ip.split(',')[0].strip()
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO page_views (path, method, ip, user_agent, referrer, user_id) VALUES (?,?,?,?,?,?)",
            (path, request.method, ip,
             request.user_agent.string[:200] if request.user_agent.string else '',
             request.referrer or '', session.get('user_id'))
        )
        row_id = cur.lastrowid
        conn.commit()
        conn.close()
        def update_geo(rid, visitor_ip):
            try:
                city, country = _get_geo(visitor_ip)
                if city or country:
                    c2 = get_db()
                    c2.execute("UPDATE page_views SET city=?, country=? WHERE id=?", (city, country, rid))
                    c2.commit()
                    c2.close()
            except Exception:
                pass
        threading.Thread(target=update_geo, args=(row_id, ip), daemon=True).start()
    except Exception:
        pass


# ─── LEGACY URDU URL REDIRECTS (301 permanent) ───────────────────────────────
@app.route('/kiraya-par-lena')
@app.route('/kiraya-par-lena/<int:pid>')
def legacy_rent_lena(pid=None):
    if pid: return redirect(url_for('rent_detail', pid=pid), 301)
    return redirect(url_for('rent_lena'), 301)

@app.route('/kiraya-par-dena', methods=['GET','POST'])
def legacy_rent_dena():
    return redirect(url_for('rent_dena'), 301)

@app.route('/kiraya-chahiye', methods=['GET','POST'])
def legacy_rent_chahiye():
    return redirect(url_for('rent_chahiye'), 301)

@app.route('/khareedna-chahta-hoon')
@app.route('/khareedna-chahta-hoon/<int:pid>')
def legacy_purchase_lena(pid=None):
    if pid: return redirect(url_for('sale_detail', pid=pid), 301)
    return redirect(url_for('purchase_lena'), 301)

@app.route('/bechna-chahta-hoon', methods=['GET','POST'])
def legacy_sale_dena():
    return redirect(url_for('sale_dena'), 301)

@app.route('/khareedna-chahiye', methods=['GET','POST'])
def legacy_purchase_chahiye():
    return redirect(url_for('purchase_chahiye'), 301)

def allowed_file(f):
    return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    import psycopg2
    import psycopg2.extras
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set!")
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    return PGConn(conn)

class PGConn:
    """Wrapper to make psycopg2 behave like sqlite3 for our app."""
    def __init__(self, conn):
        self._conn = conn
        self._cur = conn.cursor()

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        sql = sql.replace("SERIAL PRIMARY KEY", "SERIAL PRIMARY KEY")
        sql = sql.replace("CREATE TABLE IF NOT EXISTS", "CREATE TABLE IF NOT EXISTS")
        if params:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)
        return self

    def executemany(self, sql, params_list):
        sql = sql.replace("?", "%s")
        for params in params_list:
            self._cur.execute(sql, params)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    def cursor(self):
        return PGCursor(self._conn)

    def commit(self):
        self._conn.commit()

    def close(self):
        try:
            self._conn.commit()
        except Exception:
            pass
        self._conn.close()

    @property
    def lastrowid(self):
        try:
            self._cur.execute("SELECT lastval()")
            row = self._cur.fetchone()
            if row:
                return list(dict(row).values())[0]
        except Exception:
            pass
        return None

class PGCursor:
    """Wrapper for psycopg2 cursor to mimic sqlite3 cursor."""
    def __init__(self, conn):
        import psycopg2.extras
        self._cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._lastrowid = None

    def execute(self, sql, params=None):
        sql = sql.replace("?", "%s")
        sql = sql.replace("SERIAL PRIMARY KEY", "SERIAL PRIMARY KEY")
        # For INSERT, add RETURNING id to get lastrowid
        if sql.strip().upper().startswith("INSERT") and "RETURNING" not in sql.upper():
            sql = sql.rstrip().rstrip(";") + " RETURNING id"
        if params:
            self._cur.execute(sql, params)
        else:
            self._cur.execute(sql)
        if sql.strip().upper().startswith("INSERT"):
            try:
                row = self._cur.fetchone()
                if row:
                    self._lastrowid = dict(row).get("id")
            except Exception:
                pass
        return self

    def executemany(self, sql, params_list):
        sql = sql.replace("?", "%s")
        for params in params_list:
            self._cur.execute(sql, params)
        return self

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def fetchall(self):
        rows = self._cur.fetchall()
        return [dict(r) for r in rows]

    @property
    def lastrowid(self):
        return self._lastrowid

    def __iter__(self):
        return iter(self.fetchall())

def get_lang():
    return 'en'

def login_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if 'user_id' not in session:
            flash('Please login first.' if get_lang()=='en' else 'پہلے لاگ ان کریں۔', 'warning')
            return redirect(url_for('login'))
        return f(*a, **kw)
    return dec

def admin_required(f):
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login_page'))
        return f(*a, **kw)
    return dec

# ─── SLUG HELPER ─────────────────────────────────────────────────────────────

def slugify(text):
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text

# ─── WHATSAPP NOTIFY HELPER ───────────────────────────────────────────────────

OWNER_WHATSAPP = '923111820660'   # Your WhatsApp number (92 = Pakistan country code)

def wa_link(message):
    """Return a WhatsApp click-to-chat URL with a pre-filled message."""
    import urllib.parse
    return f"https://wa.me/{OWNER_WHATSAPP}?text={urllib.parse.quote(message)}"

# ─── DB INIT ──────────────────────────────────────────────────────────────────

def init_db():
    import psycopg2
    import psycopg2.extras
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable not set!")
    raw_conn = psycopg2.connect(DATABASE_URL)
    raw_conn.autocommit = True
    c = raw_conn.cursor()
    conn = get_db()  # also keep wrapper for seed inserts below

    # ── Existing tables (unchanged) ──────────────────────────────────────────
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password TEXT, is_admin INTEGER DEFAULT 0,
        phone TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS rent_properties (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, owner_name TEXT, owner_phone TEXT,
        title TEXT, location TEXT, area TEXT,
        property_type TEXT, price TEXT,
        bedrooms TEXT, bathrooms TEXT,
        floor TEXT, furnished TEXT,
        tenant_preference TEXT, description TEXT,
        is_approved INTEGER DEFAULT 0,
        is_featured INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS sale_properties (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, owner_name TEXT, owner_phone TEXT,
        title TEXT, location TEXT, area TEXT,
        property_type TEXT, price TEXT,
        bedrooms TEXT, bathrooms TEXT,
        total_area TEXT, possession TEXT, description TEXT,
        is_approved INTEGER DEFAULT 0,
        is_featured INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS property_images (
        id SERIAL PRIMARY KEY,
        property_id INTEGER, property_cat TEXT, filename TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS rent_requirements (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, name TEXT, phone TEXT,
        preferred_area TEXT, property_type TEXT,
        max_budget TEXT, bedrooms TEXT,
        tenant_type TEXT, move_in_date TEXT,
        special_needs TEXT, status TEXT DEFAULT 'New',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS purchase_requirements (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, name TEXT, phone TEXT,
        preferred_area TEXT, property_type TEXT,
        max_budget TEXT, bedrooms TEXT,
        payment_method TEXT, purpose TEXT,
        special_needs TEXT, status TEXT DEFAULT 'New',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS tenant_verification (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, tenant_name TEXT, cnic TEXT,
        mobile TEXT, address TEXT, occupation TEXT,
        cnic_file TEXT, photo_file TEXT,
        status TEXT DEFAULT 'Pending',
        notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    c.execute('''CREATE TABLE IF NOT EXISTS saved_properties (
        id SERIAL PRIMARY KEY,
        user_id INTEGER, property_id INTEGER, property_cat TEXT)''')

    c.execute('''CREATE TABLE IF NOT EXISTS page_views (
        id SERIAL PRIMARY KEY,
        path TEXT NOT NULL, method TEXT DEFAULT 'GET',
        ip TEXT, user_agent TEXT, referrer TEXT,
        user_id INTEGER,
        city TEXT DEFAULT '', country TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Safe column additions for existing DBs
    for col_def in [("city", "TEXT DEFAULT ''"), ("country", "TEXT DEFAULT ''")]:
        try:
            c.execute(f"ALTER TABLE page_views ADD COLUMN {col_def[0]} {col_def[1]}")
        except Exception:
            pass

    # ── NEW CMS Tables ───────────────────────────────────────────────────────

    # Pages CMS
    c.execute('''CREATE TABLE IF NOT EXISTS cms_pages (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        content TEXT DEFAULT '',
        meta_title TEXT DEFAULT '',
        meta_description TEXT DEFAULT '',
        is_published INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Blog Posts
    c.execute('''CREATE TABLE IF NOT EXISTS blog_posts (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        content TEXT DEFAULT '',
        excerpt TEXT DEFAULT '',
        image TEXT DEFAULT '',
        category TEXT DEFAULT 'General',
        meta_title TEXT DEFAULT '',
        meta_description TEXT DEFAULT '',
        is_published INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Menu Items
    c.execute('''CREATE TABLE IF NOT EXISTS menu_items (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT NOT NULL,
        icon TEXT DEFAULT '',
        category TEXT DEFAULT 'resources',
        display_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        open_new_tab INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Media Library
    c.execute('''CREATE TABLE IF NOT EXISTS media_library (
        id SERIAL PRIMARY KEY,
        filename TEXT NOT NULL,
        original_name TEXT DEFAULT '',
        file_type TEXT DEFAULT '',
        file_size INTEGER DEFAULT 0,
        folder TEXT DEFAULT 'media',
        alt_text TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')

    # Seed default menu items if empty
    c.execute("SELECT COUNT(*) as cnt FROM menu_items")
    row = c.fetchone()
    count = row[0] if row else 0
    if count == 0:
        default_items = [
            ('Property Laws', '/property-laws', '⚖️', 'resources', 1, 1, 0),
            ('Calculators', '/calculators', '🧮', 'resources', 2, 1, 0),
            ('Karachi Area Guide', '/area-guide', '🗺️', 'resources', 3, 1, 0),
            ('About Us', '/about', '👤', 'resources', 4, 1, 0),
            ('Blog', '/blog', '📰', 'resources', 5, 1, 0),
            ('Contact Us', '/contact', '📞', 'resources', 6, 1, 0),
        ]
        for item in default_items:
            c.execute(
                "INSERT INTO menu_items (title, url, icon, category, display_order, is_active, open_new_tab) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                item
            )

    # Admin user
    c.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin=1")
    row = c.fetchone()
    cnt = row[0] if row else 0
    if cnt == 0:
        admin_pw = os.environ.get('ADMIN_PASSWORD', 'apnaghar6873')
        pw = generate_password_hash(admin_pw)
        c.execute("INSERT INTO users (name,email,password,is_admin) VALUES (%s,%s,%s,1)",
                  ('Admin', 'apnagharkarachi.pk@gmail.com', pw))

    raw_conn.close()
    conn.close()

# ─── UPLOADS ──────────────────────────────────────────────────────────────────

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    """Legacy route — kept for any old local files still on disk."""
    return send_from_directory(UPLOAD_PROPERTIES, filename)

def save_uploaded_file(file_obj, subfolder, prefix=''):
    """Upload to Cloudinary and return the secure URL.
    Falls back to local disk if Cloudinary is not configured."""
    if not file_obj or not allowed_file(file_obj.filename):
        return None
    # Try Cloudinary first
    if _cloudinary_ready():
        return upload_to_cloudinary(file_obj, prefix=prefix)
    # Fallback: local disk
    os.makedirs(subfolder, exist_ok=True)
    safe = secure_filename(file_obj.filename)
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    fname = f"{prefix}{ts}_{safe}" if prefix else f"{ts}_{safe}"
    file_obj.save(os.path.join(subfolder, fname))
    return fname

# ─── HOME ─────────────────────────────────────────────────────────────────────

# ─── DEBUG UPLOAD (remove after confirming images work) ──────────────────────
@app.route("/debug-upload", methods=["GET","POST"])
def debug_upload():
    if request.method == "POST":
        f = request.files.get("image")
        if not f:
            return "No file received"
        url = upload_to_cloudinary(f, prefix="test_")
        return f"Upload result: {url}"
    return """<form method="post" enctype="multipart/form-data">
        <input type="file" name="image">
        <button type="submit">Test Upload</button>
    </form>"""


@app.route('/')
def index():
    conn = get_db()
    featured_rent = conn.execute(
        "SELECT DISTINCT ON (r.id) r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE r.is_approved=1 AND r.is_featured=1 ORDER BY r.id LIMIT 3"
    ).fetchall()
    featured_sale = conn.execute(
        "SELECT DISTINCT ON (s.id) s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE s.is_approved=1 AND s.is_featured=1 ORDER BY s.id LIMIT 3"
    ).fetchall()
    stats = {
        'rent': conn.execute("SELECT COUNT(*) as cnt FROM rent_properties WHERE is_approved=1").fetchone()['cnt'],
        'sale': conn.execute("SELECT COUNT(*) as cnt FROM sale_properties WHERE is_approved=1").fetchone()['cnt'],
        'verified': conn.execute("SELECT COUNT(*) as cnt FROM tenant_verification WHERE status='Approved'").fetchone()['cnt'],
        'clients': conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin=0").fetchone()['cnt'],
    }
    conn.close()
    return render_template('index.html', featured_rent=featured_rent, featured_sale=featured_sale, stats=stats)

# ─── SEARCH ───────────────────────────────────────────────────────────────────

@app.route('/search')
def search():
    conn = get_db()
    purpose  = request.args.get('purpose', 'rent').strip().lower()
    location = request.args.get('location', '')
    ptype    = request.args.get('type', '')
    bedrooms = request.args.get('beds', '')

    if purpose in ('sale', 'buy'):
        pass
    elif purpose in ('tolet', 'to let'):
        purpose = 'rent'
    if purpose in ('sale', 'buy'):
        q = ("SELECT DISTINCT ON (s.id) s.*, pi.filename FROM sale_properties s "
             "LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' "
             "WHERE s.is_approved=1")
        params = []
        if ptype:    q += " AND s.property_type=?";                     params.append(ptype)
        if location: q += " AND (s.location ILIKE ? OR s.area ILIKE ?)";  params += [f'%{location}%', f'%{location}%']
        if bedrooms: q += " AND s.bedrooms=?";                          params.append(bedrooms)
        q += " ORDER BY s.id, s.is_featured DESC, s.created_at DESC"
        props = conn.execute(q, params).fetchall()
        conn.close()
        return render_template('purchase_lena.html', props=props, ptype=ptype, loc=location, bed=bedrooms, mode=purpose)
    else:
        q = ("SELECT DISTINCT ON (r.id) r.*, pi.filename FROM rent_properties r "
             "LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' "
             "WHERE r.is_approved=1")
        params = []
        if ptype:    q += " AND r.property_type=?";                     params.append(ptype)
        if location: q += " AND (r.location ILIKE ? OR r.area ILIKE ?)";  params += [f'%{location}%', f'%{location}%']
        if bedrooms: q += " AND r.bedrooms=?";                          params.append(bedrooms)
        q += " ORDER BY r.id, r.is_featured DESC, r.created_at DESC"
        props = conn.execute(q, params).fetchall()
        conn.close()
        return render_template('rent_lena.html', props=props, ptype=ptype, loc=location, bed=bedrooms)

# ─── RENT SECTION ─────────────────────────────────────────────────────────────

@app.route('/properties-for-rent')
def rent_lena():
    conn = get_db()
    ptype = request.args.get('type','')
    loc   = request.args.get('location','')
    bed   = request.args.get('bedrooms','')
    q = "SELECT DISTINCT ON (r.id) r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE r.is_approved=1"
    params = []
    if ptype: q += " AND r.property_type=?"; params.append(ptype)
    if loc:   q += " AND (r.location ILIKE ? OR r.area ILIKE ?)"; params += [f'%{loc}%', f'%{loc}%']
    if bed:   q += " AND r.bedrooms=?"; params.append(bed)
    q += " ORDER BY r.id, r.is_featured DESC, r.created_at DESC"
    props = conn.execute(q, params).fetchall()
    conn.close()
    return render_template('rent_lena.html', props=props, ptype=ptype, loc=loc, bed=bed)

@app.route('/properties-for-rent/<int:pid>')
def rent_detail(pid):
    conn = get_db()
    prop = conn.execute(
        "SELECT r.*, u.name as poster FROM rent_properties r LEFT JOIN users u ON r.user_id=u.id WHERE r.id=? AND r.is_approved=1", (pid,)
    ).fetchone()
    if not prop: return redirect(url_for('rent_lena'))
    images = conn.execute("SELECT filename FROM property_images WHERE property_id=? AND property_cat='rent'", (pid,)).fetchall()
    is_saved = False
    if session.get('user_id'):
        is_saved = bool(conn.execute("SELECT id FROM saved_properties WHERE user_id=? AND property_id=? AND property_cat='rent'", (session['user_id'], pid)).fetchone())
    conn.close()
    return render_template('property_detail.html', prop=prop, images=images, cat='rent', is_saved=is_saved)

@app.route('/list-for-rent', methods=['GET','POST'])
def rent_dena():
    if request.method == 'POST':
        conn = get_db()
        cur = conn.cursor()
        auto_approve = 1 if session.get('is_admin') else 0
        cur.execute('''INSERT INTO rent_properties (user_id,owner_name,owner_phone,title,location,area,
            property_type,price,bedrooms,bathrooms,floor,furnished,tenant_preference,description,is_approved)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            session.get('user_id'),
            request.form['owner_name'], request.form['owner_phone'],
            request.form['title'], request.form['location'], request.form['area'],
            request.form['property_type'], request.form['price'],
            request.form['bedrooms'], request.form.get('bathrooms','1'),
            request.form.get('floor',''), request.form.get('furnished','Unfurnished'),
            request.form.get('tenant_preference','Family'),
            request.form['description'], auto_approve))
        pid = cur.lastrowid
        print(f"DEBUG rent_dena: pid={pid}")
        for f in request.files.getlist('images'):
            if f and f.filename:
                print(f"DEBUG: uploading file {f.filename}")
                url = upload_to_cloudinary(f, prefix=f"rent_{pid}_") if _cloudinary_ready() else None
                print(f"DEBUG: upload url={url}")
                if url:
                    cur.execute("INSERT INTO property_images (property_id,property_cat,filename) VALUES (?,?,?)", (pid,'rent',url))
        conn.commit(); conn.close()
        # WhatsApp notification for admin
        msg = (
            f"🏠 *Nai Rent Listing!*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👤 Naam: {request.form['owner_name']}\n"
            f"📞 Phone: {request.form['owner_phone']}\n"
            f"🏡 Property: {request.form['title']}\n"
            f"📍 Area: {request.form['location']}\n"
            f"💰 Kiraya: Rs. {request.form['price']}/month\n"
            f"🛏 Beds: {request.form['bedrooms']}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"Admin: https://apnagharkarachi.com/admin/panel"
        )
        session['wa_notify'] = wa_link(msg)
        flash('Aapki property list ho gayi! Hum jald aap se rabta karenge.', 'success')
        return redirect(url_for('dashboard') if session.get('user_id') else url_for('index'))
    return render_template('rent_dena.html')

@app.route('/rent-requirement', methods=['GET','POST'])
def rent_chahiye():
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''INSERT INTO rent_requirements (user_id,name,phone,preferred_area,property_type,
            max_budget,bedrooms,tenant_type,move_in_date,special_needs) VALUES (?,?,?,?,?,?,?,?,?,?)''', (
            session.get('user_id'),
            request.form['name'], request.form['phone'],
            request.form['preferred_area'], request.form['property_type'],
            request.form['max_budget'], request.form['bedrooms'],
            request.form['tenant_type'], request.form.get('move_in_date',''),
            request.form.get('special_needs','')))
        conn.commit(); conn.close()
        # WhatsApp notification for admin
        msg = (
            f"\U0001f511 *Nai Rent Requirement!*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f464 Naam: {request.form['name']}\n"
            f"\U0001f4de Phone: {request.form['phone']}\n"
            f"\U0001f4cd Pasandida Area: {request.form['preferred_area']}\n"
            f"\U0001f4b0 Budget: Rs. {request.form['max_budget']}\n"
            f"\U0001f3e0 Property Type: {request.form['property_type']}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Admin: https://apnagharkarachi.com/admin/panel"
        )
        session['wa_notify'] = wa_link(msg)
        flash('Aapki requirement submit ho gayi! 24 ghante mein rabta karenge.', 'success')
        return redirect(url_for('index'))
    return render_template('rent_chahiye.html')

# ─── SALE / PURCHASE SECTION ──────────────────────────────────────────────────

@app.route('/properties-for-sale')
def purchase_lena():
    conn = get_db()
    ptype = request.args.get('type','')
    loc   = request.args.get('location','')
    q = "SELECT DISTINCT ON (s.id) s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE s.is_approved=1"
    params = []
    if ptype: q += " AND s.property_type=?"; params.append(ptype)
    if loc:   q += " AND (s.location ILIKE ? OR s.area ILIKE ?)"; params += [f'%{loc}%', f'%{loc}%']
    q += " ORDER BY s.id, s.is_featured DESC, s.created_at DESC"
    props = conn.execute(q, params).fetchall()
    conn.close()
    return render_template('purchase_lena.html', props=props, ptype=ptype, loc=loc)

@app.route('/properties-for-sale/<int:pid>')
def sale_detail(pid):
    conn = get_db()
    prop = conn.execute(
        "SELECT s.*, u.name as poster FROM sale_properties s LEFT JOIN users u ON s.user_id=u.id WHERE s.id=? AND s.is_approved=1", (pid,)
    ).fetchone()
    if not prop: return redirect(url_for('purchase_lena'))
    images = conn.execute("SELECT filename FROM property_images WHERE property_id=? AND property_cat='sale'", (pid,)).fetchall()
    is_saved = False
    if session.get('user_id'):
        is_saved = bool(conn.execute("SELECT id FROM saved_properties WHERE user_id=? AND property_id=? AND property_cat='sale'", (session['user_id'], pid)).fetchone())
    conn.close()
    return render_template('property_detail.html', prop=prop, images=images, cat='sale', is_saved=is_saved)

@app.route('/list-for-sale', methods=['GET','POST'])
def sale_dena():
    if request.method == 'POST':
        conn = get_db()
        cur = conn.cursor()
        auto_approve = 1 if session.get('is_admin') else 0
        cur.execute('''INSERT INTO sale_properties (user_id,owner_name,owner_phone,title,location,area,
            property_type,price,bedrooms,bathrooms,total_area,possession,description,is_approved)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            session.get('user_id'),
            request.form['owner_name'], request.form['owner_phone'],
            request.form['title'], request.form['location'], request.form['area'],
            request.form['property_type'], request.form['price'],
            request.form['bedrooms'], request.form.get('bathrooms','1'),
            request.form.get('total_area',''), request.form.get('possession','Immediate'),
            request.form['description'], auto_approve))
        pid = cur.lastrowid
        print(f"DEBUG sale_dena: pid={pid}")
        for f in request.files.getlist('images'):
            if f and f.filename:
                print(f"DEBUG: uploading file {f.filename}")
                url = upload_to_cloudinary(f, prefix=f"sale_{pid}_") if _cloudinary_ready() else None
                print(f"DEBUG: upload url={url}")
                if url:
                    cur.execute("INSERT INTO property_images (property_id,property_cat,filename) VALUES (?,?,?)", (pid,'sale',url))
        conn.commit(); conn.close()
        # WhatsApp notification for admin
        msg = (
            f"\U0001f3e1 *Nai Sale Listing!*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f464 Naam: {request.form['owner_name']}\n"
            f"\U0001f4de Phone: {request.form['owner_phone']}\n"
            f"\U0001f3e0 Property: {request.form['title']}\n"
            f"\U0001f4cd Area: {request.form['location']}\n"
            f"\U0001f4b0 Qeemat: Rs. {request.form['price']}\n"
            f"\U0001f6cf Beds: {request.form['bedrooms']}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Admin: https://apnagharkarachi.com/admin/panel"
        )
        session['wa_notify'] = wa_link(msg)
        flash('Aapki property sale listing ho gayi! Hum jald rabta karenge.', 'success')
        return redirect(url_for('dashboard') if session.get('user_id') else url_for('index'))
    return render_template('sale_dena.html')

# ─── UNIFIED PROPERTY SUBMISSION ─────────────────────────────────────────────

@app.route('/submit-property', methods=['GET','POST'])
def submit_property():
    if request.method == 'POST':
        purpose = request.form.get('purpose', 'rent')
        conn = get_db()
        cur  = conn.cursor()
        auto_approve = 1 if session.get('is_admin') else 0

        # Build amenities string for description append
        amenities = request.form.get('amenities', '')
        desc_full  = request.form.get('description', '')
        if amenities:
            desc_full += f"\n\nAmenities: {amenities}"
        # Extra details
        parking    = request.form.get('parking', '')
        size_unit  = request.form.get('size_unit', 'Sq Yards')
        owner_type = request.form.get('owner_type', 'Owner')
        call_time  = request.form.get('call_time', 'Anytime')
        negotiable = request.form.get('negotiable', 'Yes')
        desc_full += f"\n\nParking: {parking} | Size Unit: {size_unit} | Owner Type: {owner_type} | Call Time: {call_time} | Negotiable: {negotiable}"

        if purpose == 'rent':
            cur.execute('''INSERT INTO rent_properties
                (user_id, owner_name, owner_phone, title, location, area,
                 property_type, price, bedrooms, bathrooms,
                 floor, furnished, tenant_preference, description, is_approved)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                session.get('user_id'),
                request.form.get('owner_name',''),
                request.form.get('owner_phone',''),
                request.form.get('title',''),
                request.form.get('location',''),
                request.form.get('area',''),
                request.form.get('property_type',''),
                request.form.get('price',''),
                request.form.get('bedrooms','0'),
                request.form.get('bathrooms','1'),
                request.form.get('floor','Ground'),
                request.form.get('furnished','Unfurnished'),
                request.form.get('tenant_preference','Family'),
                desc_full, auto_approve))
            pid = cur.lastrowid
            cat = 'rent'
            msg = (
                f"🏠 *Nai Rent Listing!*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 Naam: {request.form.get('owner_name')}\n"
                f"📞 Phone: {request.form.get('owner_phone')}\n"
                f"🏡 Property: {request.form.get('title')}\n"
                f"📍 Area: {request.form.get('location')}\n"
                f"💰 Kiraya: Rs. {request.form.get('price')}/month\n"
                f"🛏 Beds: {request.form.get('bedrooms')}\n"
                f"🔑 Type: {request.form.get('owner_type','Owner')}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Admin: https://apnagharkarachi.com/admin/panel"
            )
        else:
            cur.execute('''INSERT INTO sale_properties
                (user_id, owner_name, owner_phone, title, location, area,
                 property_type, price, bedrooms, bathrooms,
                 total_area, possession, description, is_approved)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
                session.get('user_id'),
                request.form.get('owner_name',''),
                request.form.get('owner_phone',''),
                request.form.get('title',''),
                request.form.get('location',''),
                request.form.get('area',''),
                request.form.get('property_type',''),
                request.form.get('price',''),
                request.form.get('bedrooms','0'),
                request.form.get('bathrooms','1'),
                request.form.get('total_area',''),
                request.form.get('possession','Immediate'),
                desc_full, auto_approve))
            pid = cur.lastrowid
            cat = 'sale'
            msg = (
                f"🏡 *Nai Sale Listing!*\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 Naam: {request.form.get('owner_name')}\n"
                f"📞 Phone: {request.form.get('owner_phone')}\n"
                f"🏠 Property: {request.form.get('title')}\n"
                f"📍 Area: {request.form.get('location')}\n"
                f"💰 Qeemat: Rs. {request.form.get('price')}\n"
                f"🛏 Beds: {request.form.get('bedrooms')}\n"
                f"🔑 Type: {request.form.get('owner_type','Owner')}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"Admin: https://apnagharkarachi.com/admin/panel"
            )

        # Upload photos to Cloudinary
        for f in request.files.getlist('images'):
            if f and f.filename:
                url = upload_to_cloudinary(f, prefix=f"{cat}_{pid}_") if _cloudinary_ready() else None
                if url:
                    cur.execute(
                        "INSERT INTO property_images (property_id, property_cat, filename) VALUES (?,?,?)",
                        (pid, cat, url))

        conn.commit()
        conn.close()

        # WhatsApp notification for admin
        session['wa_notify'] = wa_link(msg)
        flash('🎉 Aapki property listing submit ho gayi! Hum 24 ghante mein review karke publish kar denge. WhatsApp par rabta hoga.', 'success')
        return redirect(url_for('submit_property'))

    return render_template('submit_property.html')

@app.route('/purchase-requirement', methods=['GET','POST'])
def purchase_chahiye():
    if request.method == 'POST':
        conn = get_db()
        conn.execute('''INSERT INTO purchase_requirements (user_id,name,phone,preferred_area,property_type,
            max_budget,bedrooms,payment_method,purpose,special_needs) VALUES (?,?,?,?,?,?,?,?,?,?)''', (
            session.get('user_id'),
            request.form['name'], request.form['phone'],
            request.form['preferred_area'], request.form['property_type'],
            request.form['max_budget'], request.form.get('bedrooms',''),
            request.form.get('payment_method','Cash'), request.form.get('purpose','Own Use'),
            request.form.get('special_needs','')))
        conn.commit(); conn.close()
        # WhatsApp notification for admin
        msg = (
            f"\U0001f3e0 *Nai Purchase Requirement!*\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"\U0001f464 Naam: {request.form['name']}\n"
            f"\U0001f4de Phone: {request.form['phone']}\n"
            f"\U0001f4cd Pasandida Area: {request.form['preferred_area']}\n"
            f"\U0001f4b0 Budget: Rs. {request.form['max_budget']}\n"
            f"\U0001f3e0 Property Type: {request.form['property_type']}\n"
            f"\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\u2501\n"
            f"Admin: https://apnagharkarachi.com/admin/panel"
        )
        session['wa_notify'] = wa_link(msg)
        flash('Aapki purchase requirement submit ho gayi! 24 ghante mein rabta karenge.', 'success')
        return redirect(url_for('index'))
    return render_template('purchase_chahiye.html')

# ─── SAVE / DELETE PROPERTY ───────────────────────────────────────────────────

@app.route('/save/<cat>/<int:pid>')
@login_required
def save_property(cat, pid):
    conn = get_db()
    existing = conn.execute("SELECT id FROM saved_properties WHERE user_id=? AND property_id=? AND property_cat=?", (session['user_id'], pid, cat)).fetchone()
    if existing:
        conn.execute("DELETE FROM saved_properties WHERE user_id=? AND property_id=? AND property_cat=?", (session['user_id'], pid, cat))
        flash('Saved se hata diya.', 'info')
    else:
        conn.execute("INSERT INTO saved_properties (user_id,property_id,property_cat) VALUES (?,?,?)", (session['user_id'], pid, cat))
        flash('Property save ho gayi!', 'success')
    conn.commit(); conn.close()
    return redirect(url_for('rent_detail', pid=pid) if cat == 'rent' else url_for('sale_detail', pid=pid))

@app.route('/delete/<cat>/<int:pid>')
@login_required
def delete_property(cat, pid):
    conn = get_db()
    table = 'rent_properties' if cat == 'rent' else 'sale_properties'
    prop = conn.execute(f"SELECT id FROM {table} WHERE id=? AND user_id=?", (pid, session['user_id'])).fetchone()
    if prop:
        conn.execute(f"DELETE FROM {table} WHERE id=?", (pid,))
        conn.execute("DELETE FROM property_images WHERE property_id=? AND property_cat=?", (pid, cat))
        conn.execute("DELETE FROM saved_properties WHERE property_id=? AND property_cat=?", (pid, cat))
        conn.commit()
        flash('Property delete ho gayi.', 'info')
    conn.close()
    return redirect(url_for('dashboard'))

# ─── TENANT VERIFICATION ──────────────────────────────────────────────────────

@app.route('/tenant-verification', methods=['GET','POST'])
@login_required
def tenant_verification():
    if request.method == 'POST':
        conn = get_db()
        cnic_file = photo_file = None
        for field, prefix in [('cnic_file','cnic'),('photo_file','photo')]:
            f = request.files.get(field)
            if f and allowed_file(f.filename):
                os.makedirs(UPLOAD_MEDIA, exist_ok=True)
                fname = f"{prefix}_{session['user_id']}_{secure_filename(f.filename)}"
                upload_path = os.path.join(UPLOAD_MEDIA, fname)
                print("Saving verification file to:", upload_path)
                f.save(upload_path)
                if field == 'cnic_file': cnic_file = fname
                else: photo_file = fname
        conn.execute('''INSERT INTO tenant_verification (user_id,tenant_name,cnic,mobile,address,occupation,cnic_file,photo_file)
            VALUES (?,?,?,?,?,?,?,?)''', (
            session['user_id'], request.form['tenant_name'], request.form['cnic'],
            request.form['mobile'], request.form['address'], request.form['occupation'],
            cnic_file, photo_file))
        conn.commit(); conn.close()
        flash('Verification request submit ho gayi! 24 ghante mein process hogi.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('tenant_verification.html')

# ─── DOCUMENT SERVICES ────────────────────────────────────────────────────────

@app.route('/document-services')
def document_services():
    return render_template('document_services.html')

# ─── AUTH ─────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        name  = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        pw    = request.form['password']
        if pw != request.form['confirm_password']:
            flash('Password match nahi kiya.', 'danger')
            return redirect(url_for('register'))
        conn = get_db()
        if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            flash('Email pehle se registered hai.', 'danger')
            conn.close()
            return redirect(url_for('register'))
        conn.execute("INSERT INTO users (name,email,password) VALUES (?,?,?)", (name, email, generate_password_hash(pw)))
        conn.commit(); conn.close()
        flash('Account ban gaya! Login karein.', 'success')
        return redirect(url_for('login'))
    conn = get_db()
    stats = {
        'rent': conn.execute("SELECT COUNT(*) as cnt FROM rent_properties WHERE is_approved=1").fetchone()['cnt'],
        'sale': conn.execute("SELECT COUNT(*) as cnt FROM sale_properties WHERE is_approved=1").fetchone()['cnt'],
        'verified': conn.execute("SELECT COUNT(*) as cnt FROM tenant_verification WHERE status='Approved'").fetchone()['cnt'],
        'clients': conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin=0").fetchone()['cnt'],
    }
    conn.close()
    return render_template('register.html', stats=stats)

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        pw    = request.form['password']
        conn  = get_db()
        user  = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and user['password'] and check_password_hash(user['password'], pw):
            session.update({'user_id': user['id'], 'user_name': user['name'],
                            'user_email': user['email'], 'is_admin': bool(user['is_admin'])})
            return redirect(url_for('admin_panel') if user['is_admin'] else url_for('dashboard'))
        flash('Email ya password galat hai.', 'danger')
    conn = get_db()
    stats = {
        'rent': conn.execute("SELECT COUNT(*) as cnt FROM rent_properties WHERE is_approved=1").fetchone()['cnt'],
        'sale': conn.execute("SELECT COUNT(*) as cnt FROM sale_properties WHERE is_approved=1").fetchone()['cnt'],
        'verified': conn.execute("SELECT COUNT(*) as cnt FROM tenant_verification WHERE status='Approved'").fetchone()['cnt'],
        'clients': conn.execute("SELECT COUNT(*) as cnt FROM users WHERE is_admin=0").fetchone()['cnt'],
    }
    conn.close()
    return render_template('login.html', stats=stats)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logout ho gaye.', 'info')
    return redirect(url_for('index'))

# ─── DASHBOARD ────────────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    uid = session['user_id']
    my_rent      = conn.execute("SELECT DISTINCT ON (r.id) r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE r.user_id=? ORDER BY r.id, r.created_at DESC", (uid,)).fetchall()
    my_sale      = conn.execute("SELECT DISTINCT ON (s.id) s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE s.user_id=? ORDER BY s.id, s.created_at DESC", (uid,)).fetchall()
    my_rent_reqs = conn.execute("SELECT * FROM rent_requirements WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    my_buy_reqs  = conn.execute("SELECT * FROM purchase_requirements WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    my_verifs    = conn.execute("SELECT * FROM tenant_verification WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    saved_rent   = conn.execute("SELECT DISTINCT ON (r.id) r.*, pi.filename FROM saved_properties sp JOIN rent_properties r ON sp.property_id=r.id LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE sp.user_id=? AND sp.property_cat='rent' ORDER BY r.id", (uid,)).fetchall()
    saved_sale   = conn.execute("SELECT DISTINCT ON (s.id) s.*, pi.filename FROM saved_properties sp JOIN sale_properties s ON sp.property_id=s.id LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE sp.user_id=? AND sp.property_cat='sale' ORDER BY s.id", (uid,)).fetchall()
    user = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return render_template('dashboard.html', my_rent=my_rent, my_sale=my_sale,
        my_rent_reqs=my_rent_reqs, my_buy_reqs=my_buy_reqs, my_verifs=my_verifs,
        saved_rent=saved_rent, saved_sale=saved_sale, user=user)

@app.route('/profile/update', methods=['POST'])
@login_required
def update_profile():
    conn = get_db()
    conn.execute("UPDATE users SET name=? WHERE id=?", (request.form['name'].strip(), session['user_id']))
    conn.commit(); conn.close()
    session['user_name'] = request.form['name'].strip()
    flash('Profile update ho gayi.', 'success')
    return redirect(url_for('dashboard'))

# ─── ADMIN ────────────────────────────────────────────────────────────────────

@app.route('/admin')
def admin_login_page():
    if session.get('is_admin'): return redirect(url_for('admin_panel'))
    return render_template('admin_login.html')

@app.route('/admin/login', methods=['POST'])
def admin_login():
    email = request.form['email'].strip().lower()
    pw    = request.form['password']
    conn  = get_db()
    user  = conn.execute("SELECT * FROM users WHERE email=? AND is_admin=1", (email,)).fetchone()
    conn.close()
    if user and check_password_hash(user['password'], pw):
        session.update({'user_id': user['id'], 'user_name': user['name'],
                        'user_email': user['email'], 'is_admin': True})
        return redirect(url_for('admin_panel'))
    flash('Galat credentials.', 'danger')
    return redirect(url_for('admin_login_page'))

@app.route('/admin/panel')
@admin_required
def admin_panel():
    conn = get_db()
    users      = conn.execute("SELECT * FROM users WHERE is_admin=0 ORDER BY created_at DESC").fetchall()
    rent_props = conn.execute("SELECT DISTINCT ON (r.id) r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' ORDER BY r.id, r.created_at DESC").fetchall()
    sale_props = conn.execute("SELECT DISTINCT ON (s.id) s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' ORDER BY s.id, s.created_at DESC").fetchall()
    rent_reqs  = conn.execute("SELECT rr.*, u.name as uname FROM rent_requirements rr LEFT JOIN users u ON rr.user_id=u.id ORDER BY rr.created_at DESC").fetchall()
    buy_reqs   = conn.execute("SELECT pr.*, u.name as uname FROM purchase_requirements pr LEFT JOIN users u ON pr.user_id=u.id ORDER BY pr.created_at DESC").fetchall()
    verifs     = conn.execute("SELECT tv.*, u.name as uname FROM tenant_verification tv LEFT JOIN users u ON tv.user_id=u.id ORDER BY tv.created_at DESC").fetchall()
    # CMS data
    pages      = conn.execute("SELECT * FROM cms_pages ORDER BY created_at DESC").fetchall()
    blog_posts = conn.execute("SELECT * FROM blog_posts ORDER BY created_at DESC").fetchall()
    menu_items = conn.execute("SELECT * FROM menu_items ORDER BY display_order ASC").fetchall()
    media      = conn.execute("SELECT * FROM media_library ORDER BY created_at DESC LIMIT 50").fetchall()
    stats = {'users': len(users), 'rent': len(rent_props), 'sale': len(sale_props),
             'rent_reqs': len(rent_reqs), 'buy_reqs': len(buy_reqs), 'verifs': len(verifs),
             'pages': len(pages), 'blogs': len(blog_posts)}
    # Traffic
    traffic_total    = conn.execute("SELECT COUNT(*) as cnt FROM page_views").fetchone()['cnt']
    traffic_today    = conn.execute("SELECT COUNT(*) as cnt FROM page_views WHERE DATE(created_at)=CURRENT_DATE").fetchone()['cnt']
    traffic_week     = conn.execute("SELECT COUNT(*) as cnt FROM page_views WHERE created_at >= NOW() - INTERVAL '7 days'").fetchone()['cnt']
    top_pages        = conn.execute("SELECT path, COUNT(*) as cnt FROM page_views GROUP BY path ORDER BY cnt DESC LIMIT 10").fetchall()
    recent_views     = conn.execute("SELECT path, ip, city, country, user_agent, created_at FROM page_views ORDER BY created_at DESC LIMIT 30").fetchall()
    daily_chart      = conn.execute("SELECT DATE(created_at) as day, COUNT(*) as cnt FROM page_views WHERE created_at >= NOW() - INTERVAL '14 days' GROUP BY day ORDER BY day ASC").fetchall()
    unique_ips_today = conn.execute("SELECT COUNT(DISTINCT ip) as cnt FROM page_views WHERE DATE(created_at)=CURRENT_DATE").fetchone()['cnt']
    conn.close()
    return render_template('admin_panel.html',
        users=users, rent_props=rent_props, sale_props=sale_props,
        rent_reqs=rent_reqs, buy_reqs=buy_reqs, verifs=verifs,
        pages=pages, blog_posts=blog_posts, menu_items=menu_items, media=media,
        stats=stats, traffic_total=traffic_total, traffic_today=traffic_today,
        traffic_week=traffic_week, top_pages=top_pages, recent_views=recent_views,
        daily_chart=daily_chart, unique_ips_today=unique_ips_today)

@app.route('/admin/delete/<table>/<int:rid>')
@admin_required
def admin_delete(table, rid):
    allowed = ['users','rent_properties','sale_properties','rent_requirements',
               'purchase_requirements','tenant_verification','cms_pages',
               'blog_posts','menu_items','media_library']
    if table not in allowed:
        flash('Invalid.', 'danger')
        return redirect(url_for('admin_panel'))
    conn = get_db()
    conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
    conn.commit(); conn.close()
    flash('Delete ho gaya.', 'success')
    return redirect(url_for('admin_panel'))

@app.route('/admin/update-verification/<int:vid>', methods=['POST'])
@admin_required
def update_verification(vid):
    conn = get_db()
    conn.execute("UPDATE tenant_verification SET status=?, notes=? WHERE id=?",
                 (request.form.get('status'), request.form.get('notes',''), vid))
    conn.commit(); conn.close()
    flash('Status update ho gaya.', 'success')
    return redirect(url_for('admin_panel'))

# ─── ADMIN: QUICK ADD PROPERTY ───────────────────────────────────────────────

@app.route('/admin/add-property', methods=['GET','POST'])
@admin_required
def admin_add_property():
    """Admin can directly add and auto-approve+feature a property."""
    if request.method == 'POST':
        cat = request.form.get('cat', 'rent')
        conn = get_db()
        cur = conn.cursor()
        if cat == 'rent':
            cur.execute('''INSERT INTO rent_properties
                (user_id,owner_name,owner_phone,title,location,area,
                 property_type,price,bedrooms,bathrooms,floor,furnished,
                 tenant_preference,description,is_approved,is_featured)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)''', (
                session['user_id'],
                request.form.get('owner_name','Admin'),
                request.form.get('owner_phone','0311-1820660'),
                request.form['title'],
                request.form.get('location',''),
                request.form.get('area',''),
                request.form.get('property_type','House'),
                request.form.get('price',''),
                request.form.get('bedrooms','2'),
                request.form.get('bathrooms','1'),
                request.form.get('floor',''),
                request.form.get('furnished','Unfurnished'),
                request.form.get('tenant_preference','Family'),
                request.form.get('description',''),
                1 if request.form.get('is_featured') else 0,
            ))
            pid = cur.lastrowid
            print(f"DEBUG admin rent: pid={pid}")
            for f in request.files.getlist('images'):
                if f and f.filename:
                    url = upload_to_cloudinary(f, prefix=f"rent_{pid}_") if _cloudinary_ready() else None
                    print(f"DEBUG admin rent upload url={url}")
                    if url:
                        cur.execute("INSERT INTO property_images (property_id,property_cat,filename) VALUES (?,?,?)", (pid,'rent',url))
            conn.commit(); conn.close()
            flash(f'Rent property "{request.form["title"]}" add aur approve ho gayi!', 'success')
        else:
            cur.execute('''INSERT INTO sale_properties
                (user_id,owner_name,owner_phone,title,location,area,
                 property_type,price,bedrooms,bathrooms,total_area,
                 possession,description,is_approved,is_featured)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)''', (
                session['user_id'],
                request.form.get('owner_name','Admin'),
                request.form.get('owner_phone','0311-1820660'),
                request.form['title'],
                request.form.get('location',''),
                request.form.get('area',''),
                request.form.get('property_type','House'),
                request.form.get('price',''),
                request.form.get('bedrooms','2'),
                request.form.get('bathrooms','1'),
                request.form.get('total_area',''),
                request.form.get('possession','Immediate'),
                request.form.get('description',''),
                1 if request.form.get('is_featured') else 0,
            ))
            pid = cur.lastrowid
            print(f"DEBUG admin sale: pid={pid}")
            for f in request.files.getlist('images'):
                if f and f.filename:
                    url = upload_to_cloudinary(f, prefix=f"sale_{pid}_") if _cloudinary_ready() else None
                    print(f"DEBUG admin sale upload url={url}")
                    if url:
                        cur.execute("INSERT INTO property_images (property_id,property_cat,filename) VALUES (?,?,?)", (pid,'sale',url))
            conn.commit(); conn.close()
            flash(f'Sale property "{request.form["title"]}" add aur approve ho gayi!', 'success')
        return redirect(url_for('admin_panel') + '#aRent')
    return render_template('admin_add_property.html')

@app.route('/admin/toggle/<table>/<field>/<int:pid>')
@admin_required
def admin_toggle(table, field, pid):
    allowed_tables = ['rent_properties', 'sale_properties', 'cms_pages', 'blog_posts', 'menu_items']
    allowed_fields = ['is_approved', 'is_featured', 'is_published', 'is_active']
    if table not in allowed_tables or field not in allowed_fields:
        return redirect(url_for('admin_panel'))
    conn = get_db()
    row = conn.execute(f"SELECT {field} FROM {table} WHERE id=?", (pid,)).fetchone()
    if row:
        conn.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (0 if row[field] else 1, pid))
        conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('admin_panel'))

# ─── ADMIN: PAGES CMS ────────────────────────────────────────────────────────

@app.route('/admin/pages/new', methods=['GET','POST'])
@admin_required
def admin_page_new():
    if request.method == 'POST':
        title = request.form['title'].strip()
        slug  = slugify(request.form.get('slug','') or title)
        conn  = get_db()
        # Ensure unique slug
        base_slug = slug
        counter = 1
        while conn.execute("SELECT id FROM cms_pages WHERE slug=?", (slug,)).fetchone():
            slug = f"{base_slug}-{counter}"; counter += 1
        conn.execute(
            "INSERT INTO cms_pages (title, slug, content, meta_title, meta_description, is_published) VALUES (?,?,?,?,?,?)",
            (title, slug,
             request.form.get('content',''),
             request.form.get('meta_title', title),
             request.form.get('meta_description',''),
             1 if request.form.get('is_published') else 0)
        )
        conn.commit(); conn.close()
        flash(f'Page "{title}" create ho gayi! URL: /page/{slug}', 'success')
        return redirect(url_for('admin_panel') + '#aPages')
    return render_template('admin_page_form.html', page=None, action='New')

@app.route('/admin/pages/edit/<int:pid>', methods=['GET','POST'])
@admin_required
def admin_page_edit(pid):
    conn = get_db()
    page = conn.execute("SELECT * FROM cms_pages WHERE id=?", (pid,)).fetchone()
    if not page:
        conn.close(); flash('Page nahi mili.', 'danger')
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        title = request.form['title'].strip()
        slug  = slugify(request.form.get('slug','') or title)
        # Ensure unique slug (excluding self)
        base_slug = slug; counter = 1
        while conn.execute("SELECT id FROM cms_pages WHERE slug=? AND id!=?", (slug, pid)).fetchone():
            slug = f"{base_slug}-{counter}"; counter += 1
        conn.execute(
            "UPDATE cms_pages SET title=?, slug=?, content=?, meta_title=?, meta_description=?, is_published=?, updated_at=? WHERE id=?",
            (title, slug,
             request.form.get('content',''),
             request.form.get('meta_title', title),
             request.form.get('meta_description',''),
             1 if request.form.get('is_published') else 0,
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'), pid)
        )
        conn.commit(); conn.close()
        flash('Page update ho gayi!', 'success')
        return redirect(url_for('admin_panel') + '#aPages')
    conn.close()
    return render_template('admin_page_form.html', page=page, action='Edit')

# ─── ADMIN: BLOG CMS ─────────────────────────────────────────────────────────

@app.route('/admin/blog/new', methods=['GET','POST'])
@admin_required
def admin_blog_new():
    if request.method == 'POST':
        title = request.form['title'].strip()
        slug  = slugify(request.form.get('slug','') or title)
        conn  = get_db()
        base_slug = slug; counter = 1
        while conn.execute("SELECT id FROM blog_posts WHERE slug=?", (slug,)).fetchone():
            slug = f"{base_slug}-{counter}"; counter += 1
        # Handle image upload
        image = ''
        f = request.files.get('image')
        if f and allowed_file(f.filename):
            fname = save_uploaded_file(f, UPLOAD_BLOG, 'blog_')
            if fname: image = fname
        conn.execute(
            "INSERT INTO blog_posts (title, slug, content, excerpt, image, category, meta_title, meta_description, is_published) VALUES (?,?,?,?,?,?,?,?,?)",
            (title, slug,
             request.form.get('content',''),
             request.form.get('excerpt',''),
             image,
             request.form.get('category','General'),
             request.form.get('meta_title', title),
             request.form.get('meta_description',''),
             1 if request.form.get('is_published') else 0)
        )
        conn.commit(); conn.close()
        flash(f'Blog post "{title}" publish ho gayi!', 'success')
        return redirect(url_for('admin_panel') + '#aBlog')
    return render_template('admin_blog_form.html', post=None, action='New')

@app.route('/admin/blog/edit/<int:bid>', methods=['GET','POST'])
@admin_required
def admin_blog_edit(bid):
    conn = get_db()
    post = conn.execute("SELECT * FROM blog_posts WHERE id=?", (bid,)).fetchone()
    if not post:
        conn.close(); flash('Post nahi mili.', 'danger')
        return redirect(url_for('admin_panel'))
    if request.method == 'POST':
        title = request.form['title'].strip()
        slug  = slugify(request.form.get('slug','') or title)
        base_slug = slug; counter = 1
        while conn.execute("SELECT id FROM blog_posts WHERE slug=? AND id!=?", (slug, bid)).fetchone():
            slug = f"{base_slug}-{counter}"; counter += 1
        image = post['image']
        f = request.files.get('image')
        if f and allowed_file(f.filename):
            fname = save_uploaded_file(f, UPLOAD_BLOG, 'blog_')
            if fname: image = fname
        conn.execute(
            "UPDATE blog_posts SET title=?, slug=?, content=?, excerpt=?, image=?, category=?, meta_title=?, meta_description=?, is_published=?, updated_at=? WHERE id=?",
            (title, slug,
             request.form.get('content',''),
             request.form.get('excerpt',''),
             image,
             request.form.get('category','General'),
             request.form.get('meta_title', title),
             request.form.get('meta_description',''),
             1 if request.form.get('is_published') else 0,
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'), bid)
        )
        conn.commit(); conn.close()
        flash('Blog post update ho gayi!', 'success')
        return redirect(url_for('admin_panel') + '#aBlog')
    conn.close()
    return render_template('admin_blog_form.html', post=post, action='Edit')

# ─── ADMIN: MENU MANAGER ─────────────────────────────────────────────────────

@app.route('/admin/menu/new', methods=['POST'])
@admin_required
def admin_menu_new():
    conn = get_db()
    conn.execute(
        "INSERT INTO menu_items (title, url, icon, category, display_order, is_active, open_new_tab) VALUES (?,?,?,?,?,?,?)",
        (request.form['title'].strip(),
         request.form['url'].strip(),
         request.form.get('icon',''),
         request.form.get('category','resources'),
         int(request.form.get('display_order', 99)),
         1 if request.form.get('is_active') else 0,
         1 if request.form.get('open_new_tab') else 0)
    )
    conn.commit(); conn.close()
    flash('Menu item add ho gaya!', 'success')
    return redirect(url_for('admin_panel') + '#aMenu')

@app.route('/admin/menu/edit/<int:mid>', methods=['POST'])
@admin_required
def admin_menu_edit(mid):
    conn = get_db()
    conn.execute(
        "UPDATE menu_items SET title=?, url=?, icon=?, category=?, display_order=?, is_active=?, open_new_tab=? WHERE id=?",
        (request.form['title'].strip(),
         request.form['url'].strip(),
         request.form.get('icon',''),
         request.form.get('category','resources'),
         int(request.form.get('display_order', 99)),
         1 if request.form.get('is_active') else 0,
         1 if request.form.get('open_new_tab') else 0,
         mid)
    )
    conn.commit(); conn.close()
    flash('Menu item update ho gaya!', 'success')
    return redirect(url_for('admin_panel') + '#aMenu')

# ─── ADMIN: MEDIA MANAGER ────────────────────────────────────────────────────

@app.route('/admin/media/upload', methods=['POST'])
@admin_required
def admin_media_upload():
    folder = request.form.get('folder', 'media')
    subfolder_map = {
        'blog': UPLOAD_BLOG, 'pages': UPLOAD_PAGES,
        'properties': UPLOAD_PROPERTIES, 'media': UPLOAD_MEDIA
    }
    subfolder = subfolder_map.get(folder, UPLOAD_MEDIA)
    uploaded = 0
    for f in request.files.getlist('files'):
        if f and allowed_file(f.filename):
            fname = save_uploaded_file(f, subfolder)
            if fname:
                # fname may be a Cloudinary URL (https://...) or a local filename
                if fname.startswith('http://') or fname.startswith('https://'):
                    size = 0
                    ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                else:
                    size = os.path.getsize(os.path.join(subfolder, fname))
                    ext  = fname.rsplit('.', 1)[-1].lower()
                conn = get_db()
                conn.execute(
                    "INSERT INTO media_library (filename, original_name, file_type, file_size, folder, alt_text) VALUES (?,?,?,?,?,?)",
                    (fname, f.filename, ext, size, folder, '')
                )
                conn.commit(); conn.close()
                uploaded += 1
    flash(f'{uploaded} file(s) upload ho gayi!', 'success')
    return redirect(url_for('admin_panel') + '#aMedia')

@app.route('/admin/media/delete/<int:mid>')
@admin_required
def admin_media_delete(mid):
    conn = get_db()
    m = conn.execute("SELECT * FROM media_library WHERE id=?", (mid,)).fetchone()
    if m:
        folder_map = {'blog': UPLOAD_BLOG, 'pages': UPLOAD_PAGES, 'properties': UPLOAD_PROPERTIES, 'media': UPLOAD_MEDIA}
        path = os.path.join(folder_map.get(m['folder'], UPLOAD_MEDIA), m['filename'])
        try: os.remove(path)
        except: pass
        conn.execute("DELETE FROM media_library WHERE id=?", (mid,))
        conn.commit()
    conn.close()
    flash('File delete ho gayi.', 'success')
    return redirect(url_for('admin_panel') + '#aMedia')

# ─── ADMIN: PDF GENERATOR ─────────────────────────────────────────────────────

@app.route('/admin/pdf/<int:vid>')
@admin_required
def generate_pdf(vid):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        from reportlab.lib.units import cm
        import io
        conn = get_db()
        v = conn.execute("SELECT tv.*, u.name as uname, u.email as uemail FROM tenant_verification tv LEFT JOIN users u ON tv.user_id=u.id WHERE tv.id=?", (vid,)).fetchone()
        conn.close()
        if not v:
            flash('Record nahi mila.', 'danger')
            return redirect(url_for('admin_panel'))
        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
        story = []
        styles = getSampleStyleSheet()
        title_s = ParagraphStyle('T', parent=styles['Heading1'], fontSize=20, textColor=colors.HexColor('#1a3c5e'))
        sub_s   = ParagraphStyle('S', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#6b7a99'))
        lbl_s   = ParagraphStyle('L', parent=styles['Normal'], fontSize=9, textColor=colors.HexColor('#6b7a99'), fontName='Helvetica-Bold')
        val_s   = ParagraphStyle('V', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor('#1a2535'))
        story.append(Paragraph("APNAGHAR | اپنا گھر", title_s))
        story.append(Paragraph("Akhtar Colony, Karachi | 0311-1820660 | apnagharkarachi.pk@gmail.com", sub_s))
        story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#c8973a')))
        story.append(Spacer(1, 0.4*cm))
        story.append(Paragraph("TENANT VERIFICATION REPORT", ParagraphStyle('R', parent=styles['Heading2'], fontSize=14, textColor=colors.HexColor('#2557a7'))))
        story.append(Spacer(1, 0.3*cm))
        sc = {'Approved':'#2e7d32','Rejected':'#c62828','Pending':'#e65100'}.get(v['status'],'#666')
        data = [
            [Paragraph('<b>Field</b>', lbl_s), Paragraph('<b>Details</b>', lbl_s)],
            [Paragraph('Tenant Name', lbl_s), Paragraph(v['tenant_name'] or '—', val_s)],
            [Paragraph('CNIC', lbl_s), Paragraph(v['cnic'] or '—', val_s)],
            [Paragraph('Mobile', lbl_s), Paragraph(v['mobile'] or '—', val_s)],
            [Paragraph('Address', lbl_s), Paragraph(v['address'] or '—', val_s)],
            [Paragraph('Occupation', lbl_s), Paragraph(v['occupation'] or '—', val_s)],
            [Paragraph('Status', lbl_s), Paragraph(f'<font color="{sc}"><b>{v["status"]}</b></font>', val_s)],
            [Paragraph('Notes', lbl_s), Paragraph(v['notes'] or '—', val_s)],
            [Paragraph('Date', lbl_s), Paragraph(str(v['created_at'])[:10], val_s)],
        ]
        tbl = Table(data, colWidths=[5*cm, 12*cm])
        tbl.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),colors.HexColor('#1a3c5e')),
            ('TEXTCOLOR',(0,0),(-1,0),colors.white),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#f8f9fc'),colors.white]),
            ('GRID',(0,0),(-1,-1),0.5,colors.HexColor('#e8edf5')),
            ('PADDING',(0,0),(-1,-1),8),
        ]))
        story.append(tbl)
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph(f"Report generated: {datetime.now().strftime('%d %B %Y %I:%M %p')}", sub_s))
        doc.build(story)
        buf.seek(0)
        resp = make_response(buf.read())
        resp.headers['Content-Type'] = 'application/pdf'
        resp.headers['Content-Disposition'] = f'attachment; filename=verification_{vid}.pdf'
        return resp
    except ImportError:
        flash('reportlab install karein: pip install reportlab', 'danger')
        return redirect(url_for('admin_panel'))

# ─── STATIC PAGES — 301 redirects to CMS slugs ───────────────────────────────

@app.route('/property-laws')
def property_laws():
    return redirect(url_for('cms_page', slug='property-laws'), 301)

@app.route('/calculators')
def calculators():
    return redirect(url_for('cms_page', slug='calculators'), 301)

@app.route('/area-guide')
def area_guide():
    return redirect(url_for('cms_page', slug='area-guide'), 301)

@app.route('/about')
def about():
    return redirect(url_for('cms_page', slug='about-us'), 301)

@app.route('/contact')
def contact():
    return redirect(url_for('cms_page', slug='contact-us'), 301)

# ─── DYNAMIC BLOG ROUTES ─────────────────────────────────────────────────────

@app.route('/blog')
def blog():
    conn = get_db()
    category = request.args.get('category', '')
    q = "SELECT * FROM blog_posts WHERE is_published=1"
    params = []
    if category:
        q += " AND category=?"; params.append(category)
    q += " ORDER BY created_at DESC"
    posts = conn.execute(q, params).fetchall()
    categories = conn.execute("SELECT DISTINCT category FROM blog_posts WHERE is_published=1").fetchall()
    conn.close()
    # If no CMS posts exist yet, fall back to static template
    if not posts:
        return render_template('blog.html', posts=[], categories=[], category=category)
    return render_template('blog_list.html', posts=posts, categories=categories, category=category)

@app.route('/blog/<slug>')
def blog_detail(slug):
    conn = get_db()
    post = conn.execute("SELECT * FROM blog_posts WHERE slug=? AND is_published=1", (slug,)).fetchone()
    conn.close()
    if not post:
        flash('Blog post nahi mili.', 'warning')
        return redirect(url_for('blog'))
    return render_template('blog_detail.html', post=post)

# ─── DYNAMIC CMS PAGE ROUTE ──────────────────────────────────────────────────

@app.route('/page/<slug>')
def cms_page(slug):
    conn = get_db()
    page = conn.execute("SELECT * FROM cms_pages WHERE slug=? AND is_published=1", (slug,)).fetchone()
    conn.close()
    if not page:
        from flask import abort
        abort(404)
    return render_template('cms_page.html', page=page)

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

@app.route('/admin/seed-pages')
@admin_required
def admin_seed_pages():
    """Force create the 3 missing CMS pages. Safe to run multiple times."""
    import json, os
    seed_file = os.path.join(os.path.dirname(__file__), 'cms_seed.json')
    if not os.path.exists(seed_file):
        flash('cms_seed.json not found.', 'danger')
        return redirect(url_for('admin_panel'))
    pages = json.load(open(seed_file, encoding='utf-8'))
    conn = get_db()
    c = conn.cursor()
    inserted = updated = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for pg in pages:
        exists = c.execute("SELECT id FROM cms_pages WHERE slug=?", (pg['slug'],)).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO cms_pages (title, slug, content, meta_title, meta_description, is_published) VALUES (?,?,?,?,?,1)",
                (pg['title'], pg['slug'], pg['content'], pg['meta_title'], pg['meta_desc'])
            )
            inserted += 1
        else:
            c.execute(
                "UPDATE cms_pages SET title=?, content=?, meta_title=?, meta_description=?, is_published=1, updated_at=? WHERE slug=?",
                (pg['title'], pg['content'], pg['meta_title'], pg['meta_desc'], now, pg['slug'])
            )
            updated += 1
    conn.commit(); conn.close()
    flash(f"Done! {inserted} pages created, {updated} pages updated.", "success")
    return redirect(url_for("admin_panel") + "#aPages")

# ─── DATABASE BACKUP ──────────────────────────────────────────────────────────

@app.route('/admin/backup-db')
@admin_required
def backup_db():
    """Backup not available with PostgreSQL - use Railway dashboard."""
    flash('Database backup: Use Railway dashboard to export PostgreSQL data.', 'info')
    return redirect(url_for('admin_panel'))


# ─── BLOG SEED ROUTE ─────────────────────────────────────────────────────────

@app.route('/admin/seed-blog')
@admin_required
def admin_seed_blog():
    """Seed the 3 blog posts shown on the homepage. Safe to run multiple times."""
    blog_posts = [
        {
            "title": "Rent vs Buy in Karachi 2026 — Which Makes More Sense?",
            "slug": "rent-vs-buy-karachi-2026",
            "category": "Guide",
            "excerpt": "Should you rent or buy property in Karachi in 2026? We break down the costs, benefits and risks for both options.",
            "meta_title": "Rent vs Buy in Karachi 2026 - ApnaGhar Guide",
            "meta_desc": "Should you rent or buy property in Karachi in 2026? Complete guide with cost comparison, pros and cons.",
            "content": """<div class="row justify-content-center"><div class="col-lg-10">
<h2 style="color:var(--primary);">Rent vs Buy in Karachi 2026 — Which Makes More Sense?</h2>
<p class="text-muted">Published: January 2026 &nbsp;·&nbsp; 5 min read</p>
<p>One of the most common questions we hear at ApnaGhar is: <strong>"Should I rent or buy a property in Karachi?"</strong> The answer depends on your financial situation, family plans, and the current market conditions. Let's break it down.</p>
<h3 style="color:var(--primary-light);">The Case for Renting</h3>
<ul>
<li><strong>Lower upfront cost</strong> — You only need a security deposit (usually 2-3 months rent) instead of millions in down payment.</li>
<li><strong>Flexibility</strong> — If your job changes or family grows, you can move without the hassle of selling.</li>
<li><strong>No maintenance burden</strong> — Major repairs are the landlord's responsibility.</li>
<li><strong>Better for short-term stays</strong> — If you plan to live in Karachi for less than 5 years, renting often makes more financial sense.</li>
</ul>
<h3 style="color:var(--primary-light);">The Case for Buying</h3>
<ul>
<li><strong>Asset building</strong> — Property in Karachi has historically appreciated in value. You build equity every year.</li>
<li><strong>Stability</strong> — No risk of landlord asking you to vacate. Your home, your rules.</li>
<li><strong>Rental income potential</strong> — If you move, you can rent out the property and earn monthly income.</li>
<li><strong>Hedge against inflation</strong> — Property values and rents both rise with inflation, protecting your wealth.</li>
</ul>
<h3 style="color:var(--primary-light);">A Simple Karachi Comparison (2026)</h3>
<div class="table-responsive mt-3">
<table class="table table-bordered rounded-3">
<thead style="background:var(--primary);color:#fff;">
<tr><th>Factor</th><th>Renting</th><th>Buying</th></tr>
</thead>
<tbody>
<tr><td>Upfront cost</td><td>Rs. 60,000-1.5 Lakh</td><td>Rs. 20-50 Lakh+</td></tr>
<tr><td>Monthly cost (2-bed Gulshan)</td><td>Rs. 35,000-50,000</td><td>Rs. 60,000-80,000 (with loan)</td></tr>
<tr><td>Flexibility</td><td>High</td><td>Low</td></tr>
<tr><td>Long-term wealth</td><td>Low</td><td>High</td></tr>
<tr><td>Risk</td><td>Landlord eviction</td><td>Market fluctuation</td></tr>
</tbody>
</table>
</div>
<h3 style="color:var(--primary-light);">Our Recommendation</h3>
<p><strong>Rent if:</strong> You are new to Karachi, your income is not yet stable, or you plan to move within 3-5 years.</p>
<p><strong>Buy if:</strong> You have stable income, plan to settle long-term, and have enough savings for a down payment without depleting your emergency fund.</p>
<div class="card border-0 rounded-4 p-4 mt-4" style="background:var(--primary);color:#fff;text-align:center;">
<h5 style="color:#fff;">Need Free Property Advice?</h5>
<p style="color:rgba(255,255,255,.85);">Talk to our experts — we help you decide what is best for your situation.</p>
<a href="https://wa.me/923111820660" target="_blank" class="btn btn-whatsapp rounded-pill px-4 fw-bold"><i class="bi bi-whatsapp me-2"></i>Free Consultation</a>
</div></div></div>"""
        },
        {
            "title": "Best Areas for Families in Karachi — 2026 Complete Guide",
            "slug": "best-areas-families-karachi",
            "category": "Area Guide",
            "excerpt": "Looking for the best area to raise your family in Karachi? Here are our top picks based on safety, schools, and affordability.",
            "meta_title": "Best Areas for Families in Karachi 2026 - ApnaGhar Area Guide",
            "meta_desc": "Top family-friendly areas in Karachi in 2026. Covers safety, schools, rent prices and community feel.",
            "content": """<div class="row justify-content-center"><div class="col-lg-10">
<h2 style="color:var(--primary);">Best Areas for Families in Karachi — 2026 Complete Guide</h2>
<p class="text-muted">Published: February 2026 &nbsp;·&nbsp; 7 min read</p>
<p>Choosing the right area for your family in Karachi is one of the most important decisions you will make. We have put together this guide based on safety, school quality, community feel, and affordability.</p>
<h3 style="color:var(--primary-light);">1. Gulshan-e-Iqbal — Best Overall</h3>
<div class="card border-0 shadow-sm rounded-4 p-3 mb-4" style="border-left:4px solid #2e7d32!important;">
<p>Gulshan-e-Iqbal is the most popular family area in Karachi. It has excellent schools (Beaconhouse, The City School), good hospitals, and a strong community. University Road connects it to the rest of the city.</p>
<p><strong>Rent:</strong> Rs. 25,000 - 80,000/month &nbsp; <strong>Verdict:</strong> 5/5</p>
</div>
<h3 style="color:var(--primary-light);">2. North Nazimabad — Best Value</h3>
<div class="card border-0 shadow-sm rounded-4 p-3 mb-4" style="border-left:4px solid #6a1b9a!important;">
<p>North Nazimabad offers wide roads, planned blocks, and a peaceful environment at a more affordable price. It has good schools and is well connected via main roads.</p>
<p><strong>Rent:</strong> Rs. 20,000 - 60,000/month &nbsp; <strong>Verdict:</strong> 4/5</p>
</div>
<h3 style="color:var(--primary-light);">3. PECHS — Best for Professionals</h3>
<div class="card border-0 shadow-sm rounded-4 p-3 mb-4" style="border-left:4px solid #1565c0!important;">
<p>PECHS is central, clean, and has great connectivity. Good for families where both parents work. Slightly more expensive but excellent quality of life.</p>
<p><strong>Rent:</strong> Rs. 35,000 - 90,000/month &nbsp; <strong>Verdict:</strong> 4/5</p>
</div>
<h3 style="color:var(--primary-light);">4. Akhtar Colony — Hidden Gem</h3>
<div class="card border-0 shadow-sm rounded-4 p-3 mb-4" style="border-left:4px solid #e65100!important;">
<p>Our home area! Akhtar Colony is a quiet, tight-knit community with affordable rents and a strong neighbourhood feel. Great for families on a budget who want safety and community.</p>
<p><strong>Rent:</strong> Rs. 15,000 - 45,000/month &nbsp; <strong>Verdict:</strong> 4/5</p>
</div>
<h3 style="color:var(--primary-light);">5. Bahria Town Karachi — Premium Option</h3>
<div class="card border-0 shadow-sm rounded-4 p-3 mb-4" style="border-left:4px solid #c62828!important;">
<p>If budget is not a concern, Bahria Town offers the most modern infrastructure — gated security, parks, international schools, and clean streets.</p>
<p><strong>Rent:</strong> Rs. 50,000 - 2,00,000/month &nbsp; <strong>Verdict:</strong> 5/5</p>
</div>
<div class="card border-0 rounded-4 p-4 mt-4" style="background:var(--primary);text-align:center;">
<h5 style="color:#fff;">Not Sure Which Area Suits You?</h5>
<p style="color:rgba(255,255,255,.85);">Tell us your budget and family size — we will recommend the best area for you!</p>
<a href="https://wa.me/923111820660" target="_blank" class="btn btn-whatsapp rounded-pill px-4 fw-bold"><i class="bi bi-whatsapp me-2"></i>Get Free Advice</a>
</div></div></div>"""
        },
        {
            "title": "How to Write a Rent Agreement in Pakistan — Step by Step",
            "slug": "rent-agreement-pakistan",
            "category": "Legal",
            "excerpt": "A proper rent agreement protects both landlord and tenant. Learn exactly what to include and how to make it legally valid in Pakistan.",
            "meta_title": "How to Write a Rent Agreement in Pakistan - ApnaGhar Legal Guide",
            "meta_desc": "Step by step guide to writing a legally valid rent agreement in Pakistan. What to include, stamp paper requirements, and witness rules.",
            "content": """<div class="row justify-content-center"><div class="col-lg-10">
<h2 style="color:var(--primary);">How to Write a Rent Agreement in Pakistan — Step by Step</h2>
<p class="text-muted">Published: March 2026 &nbsp;·&nbsp; 6 min read</p>
<p>A rent agreement is a legal contract between a landlord and tenant. A proper agreement protects both parties and prevents disputes. Here is how to write one correctly in Pakistan.</p>
<h3 style="color:var(--primary-light);">Step 1 — Use Stamp Paper</h3>
<p>The agreement must be written on <strong>stamp paper of appropriate value</strong>. In Sindh, a Rs. 500 to Rs. 1,000 stamp paper is typically used for residential rent agreements.</p>
<h3 style="color:var(--primary-light);">Step 2 — Include These Essential Details</h3>
<ul>
<li><strong>Full names and CNIC numbers</strong> of both landlord and tenant</li>
<li><strong>Complete property address</strong> with property description</li>
<li><strong>Monthly rent amount</strong> in both numbers and words</li>
<li><strong>Security/advance deposit amount</strong> and conditions for refund</li>
<li><strong>Lease start and end date</strong> (usually 11 months for residential)</li>
<li><strong>Utility bills responsibility</strong> — who pays electricity, gas, water</li>
<li><strong>Notice period</strong> — how much notice is required to vacate (usually 1 month)</li>
</ul>
<h3 style="color:var(--primary-light);">Step 3 — Signatures and Witnesses</h3>
<p>Both landlord and tenant must <strong>sign and thumb-print</strong> the agreement. Additionally, <strong>two witnesses</strong> must sign with their full names and CNICs.</p>
<h3 style="color:var(--primary-light);">Step 4 — Keep Copies</h3>
<p>Make at least <strong>two original copies</strong> on stamp paper — one for the landlord and one for the tenant.</p>
<h3 style="color:var(--primary-light);">Step 5 — Optional: Notarisation</h3>
<p>For extra legal protection, you can get the agreement <strong>attested by a notary public</strong>. Recommended for high-value properties or long-term leases.</p>
<div class="card border-0 rounded-3 p-3 mt-3 mb-3" style="background:#fff3cd;border-left:4px solid #e65100!important;">
<strong>Common Mistakes to Avoid:</strong>
<ul class="mb-0 mt-2">
<li>Not specifying the annual rent increase percentage</li>
<li>Forgetting to document the property condition at move-in</li>
<li>Not specifying what happens to the deposit if tenant leaves early</li>
</ul>
</div>
<div class="card border-0 rounded-4 p-4 mt-4" style="background:var(--primary);text-align:center;">
<h5 style="color:#fff;">Need a Professional Rent Agreement?</h5>
<p style="color:rgba(255,255,255,.85);">We prepare legally valid rent agreements on stamp paper. Fast, affordable, and professionally done.</p>
<a href="https://wa.me/923111820660" target="_blank" class="btn btn-whatsapp rounded-pill px-4 fw-bold"><i class="bi bi-whatsapp me-2"></i>Get Agreement Made</a>
</div></div></div>"""
        }
    ]

    conn = get_db()
    c = conn.cursor()
    inserted = updated = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    for post in blog_posts:
        exists = c.execute("SELECT id FROM blog_posts WHERE slug=?", (post['slug'],)).fetchone()
        if not exists:
            c.execute(
                "INSERT INTO blog_posts (title, slug, content, excerpt, category, meta_title, meta_description, is_published) VALUES (?,?,?,?,?,?,?,1)",
                (post['title'], post['slug'], post['content'], post['excerpt'], post['category'], post['meta_title'], post['meta_desc'])
            )
            inserted += 1
        else:
            c.execute(
                "UPDATE blog_posts SET title=?, content=?, excerpt=?, category=?, meta_title=?, meta_description=?, is_published=1, updated_at=? WHERE slug=?",
                (post['title'], post['content'], post['excerpt'], post['category'], post['meta_title'], post['meta_desc'], now, post['slug'])
            )
            updated += 1
    conn.commit()
    conn.close()
    flash(f"Done! {inserted} blog posts created, {updated} updated.", "success")
    return redirect(url_for("admin_panel"))


# ─── SITEMAP & ROBOTS ────────────────────────────────────────────────────────

@app.route('/sitemap.xml')
def sitemap():
    conn = get_db()
    rent_props = conn.execute("SELECT id FROM rent_properties WHERE is_approved=1").fetchall()
    sale_props = conn.execute("SELECT id FROM sale_properties WHERE is_approved=1").fetchall()
    blogs = conn.execute("SELECT slug FROM blog_posts WHERE is_published=1").fetchall()
    conn.close()
    base = "https://apnagharkarachi.com"
    urls = [
        f"<url><loc>{base}/</loc><priority>1.0</priority></url>",
        f"<url><loc>{base}/properties-for-rent</loc><priority>0.9</priority></url>",
        f"<url><loc>{base}/properties-for-sale</loc><priority>0.9</priority></url>",
        f"<url><loc>{base}/tenant-verification</loc><priority>0.8</priority></url>",
        f"<url><loc>{base}/document-services</loc><priority>0.8</priority></url>",
        f"<url><loc>{base}/blog</loc><priority>0.8</priority></url>",
        f"<url><loc>{base}/about</loc><priority>0.6</priority></url>",
        f"<url><loc>{base}/contact</loc><priority>0.6</priority></url>",
    ]
    for p in rent_props:
        urls.append(f"<url><loc>{base}/properties-for-rent/{p['id']}</loc><priority>0.7</priority></url>")
    for p in sale_props:
        urls.append(f"<url><loc>{base}/properties-for-sale/{p['id']}</loc><priority>0.7</priority></url>")
    for b in blogs:
        urls.append(f"<url><loc>{base}/blog/{b['slug']}</loc><priority>0.6</priority></url>")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    xml += '\n'.join(urls)
    xml += '\n</urlset>'
    resp = make_response(xml)
    resp.headers['Content-Type'] = 'application/xml'
    return resp

@app.route('/sw.js')
def service_worker():
    from flask import send_from_directory
    response = send_from_directory('static', 'sw.js')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Content-Type'] = 'application/javascript'
    return response

@app.route('/manifest.json')
def manifest():
    from flask import send_from_directory
    response = send_from_directory('static', 'manifest.json')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Content-Type'] = 'application/manifest+json'
    return response

@app.route('/robots.txt')
def robots():
    r = "User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /debug-upload\nSitemap: https://apnagharkarachi.com/sitemap.xml\n"
    resp = make_response(r)
    resp.headers['Content-Type'] = 'text/plain'
    return resp

# ─── STARTUP ──────────────────────────────────────────────────────────────────

os.makedirs('uploads', exist_ok=True)
os.makedirs(UPLOAD_BLOG, exist_ok=True)
os.makedirs(UPLOAD_PAGES, exist_ok=True)
os.makedirs(UPLOAD_PROPERTIES, exist_ok=True)
os.makedirs(UPLOAD_MEDIA, exist_ok=True)

# ─── MIGRATE OLD IMAGES TO CORRECT FOLDER ────────────────────────────────────
import glob, shutil
for old_file in glob.glob('uploads/rent_*') + glob.glob('uploads/sale_*'):
    fname = os.path.basename(old_file)
    new_path = os.path.join(UPLOAD_PROPERTIES, fname)
    if not os.path.exists(new_path):
        try:
            shutil.copy2(old_file, new_path)
            print(f"Migrated: {fname} -> {new_path}")
        except Exception as e:
            print(f"Migration failed for {fname}: {e}")

init_db()

# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  ✅  ApnaGhar CMS — Chal gaya!")
    print("  🌐  Website: http://localhost:5000")
    print("  🔐  Admin:   http://localhost:5000/admin")
    print("      Email:   apnagharkarachi.pk@gmail.com")
    print("      Password: (set via ADMIN_PASSWORD env variable)")
    print("="*55 + "\n")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
