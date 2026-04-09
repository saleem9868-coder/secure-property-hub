from flask import Flask, render_template, request, redirect, url_for, flash, session, send_from_directory, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, threading
from datetime import datetime
from functools import wraps
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
app.secret_key = 'sph-v2-secret-2024'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
DB_PATH = 'database.db'

# ─── TRANSLATIONS ─────────────────────────────────────────────────────────────
TRANSLATIONS = {
    'en': {
        'dir': 'ltr', 'lang': 'en',
        'switch_lang': 'اردو', 'switch_code': 'ur',
        # Navbar
        'nav_home': 'Home',
        'nav_rent': 'Rent',
        'nav_rent_lena': 'Rent a Property (Tenant)',
        'nav_rent_dena': 'List for Rent (Owner)',
        'nav_rent_req': 'Submit Rent Requirement',
        'nav_buy_sell': 'Buy / Sell',
        'nav_buy': 'Buy a Property',
        'nav_sell': 'Sell My Property',
        'nav_buy_req': 'Submit Buy Requirement',
        'nav_verify': 'Tenant Verify',
        'nav_docs': 'Documents',
        'nav_login': 'Login',
        'nav_register': 'Register',
        'nav_dashboard': 'Dashboard',
        'nav_admin': 'Admin',
        'nav_logout': 'Logout',
        # Hero
        'hero_tag': "KARACHI'S TRUSTED PROPERTY & DOCUMENT SERVICES",
        'hero_title': 'ApnaGhar',
        'hero_sub': 'Secure Deal, Easy Steps — Below Deal and Documents at One Platform.',
        'choose_title': 'What Would You Like to Do?',
        'choose_sub': 'Select your option below',
        # 4 Cards
        'card_rent_lena_title': 'I Want to\nRent a Property',
        'card_rent_lena_sub': 'Looking for a house, flat or shop on rent',
        'card_rent_lena_btn': 'Browse Properties →',
        'card_rent_dena_title': 'I Want to\nRent Out My Property',
        'card_rent_dena_sub': 'List your property for rent',
        'card_rent_dena_btn': 'List Property →',
        'card_buy_title': 'I Want to\nBuy a Property',
        'card_buy_sub': 'Looking to buy a house, flat or plot',
        'card_buy_btn': 'View Sale Properties →',
        'card_sell_title': 'I Want to\nSell My Property',
        'card_sell_sub': 'List your property for sale',
        'card_sell_btn': 'List for Sale →',
        # Requirement banners
        'rent_req_title': 'Submit Your Rent Requirement',
        'rent_req_sub': 'Tell us your budget and area — we will find the best options!',
        'rent_req_btn': 'Fill Form',
        'buy_req_title': 'Submit Your Purchase Requirement',
        'buy_req_sub': 'Tell us your budget and preferred area',
        'buy_req_btn': 'Fill Form',
        # Sections
        'rent_props_title': '🔑 Available Rental Properties',
        'rent_props_sub': 'Ready to move in',
        'sale_props_title': '🏡 Properties for Sale',
        'sale_props_sub': 'Available for purchase',
        'services_title': 'Our Other Services',
        'view_all': 'View All →',
        'per_month': '/month',
        'view_details': 'View Details',
        'featured': 'Featured',
        # Offer
        'offer_title': 'Special Offer for Akhtar Colony Residents',
        'offer_1': 'Free Property Consultation',
        'offer_2': 'Discount on Rent Agreements',
        'offer_3': 'Free Listing for Owners',
        'offer_btn': 'Claim on WhatsApp',
        # Footer
        'footer_desc': 'Trusted property and documentation services in Karachi.',
        'footer_rent': 'Rent',
        'footer_buy': 'Buy / Sell',
        'footer_contact': 'Contact Us',
        'footer_hours': 'Mon–Sat: 9am – 8pm',
        'footer_rights': 'All rights reserved.',
        # Pages
        'rent_lena_title': 'Rent a Property',
        'rent_lena_sub': 'properties available',
        'rent_req_banner': "Can't find what you need? Tell us your requirement — we will find it!",
        'filter_type': 'Property Type',
        'filter_all': 'All Types',
        'filter_beds': 'Bedrooms',
        'filter_any': 'Any',
        'filter_loc': 'Location / Area',
        'filter_search': 'Search',
        'filter_clear': 'Clear',
        'no_props': 'No properties found',
        'submit_req': 'Submit Requirement',
        # Detail
        'month': '/month',
        'beds': 'Beds',
        'baths': 'Baths',
        'possession': 'Possession',
        'wa_contact': 'WhatsApp — Get Info',
        'call_now': 'Call Now',
        'save': 'Save Property',
        'unsave': 'Remove from Saved',
        'login_save': 'Login to Save',
        'listed_by': 'Listed by',
        'date_posted': 'Posted',
        'prop_desc': 'Property Description',
        'interested': 'Interested in this property?',
        'contact_sub': 'Contact us for a site visit.',
        # Forms
        'owner_name': 'Owner Name',
        'owner_phone': 'Phone / WhatsApp',
        'prop_title': 'Property Title',
        'location': 'Area / Locality',
        'full_addr': 'Full Address',
        'prop_type': 'Property Type',
        'bedrooms': 'Bedrooms',
        'bathrooms': 'Bathrooms',
        'floor': 'Floor',
        'furnished': 'Furnished',
        'tenant_pref': 'Tenant Preference',
        'price_rent': 'Monthly Rent (Rs.)',
        'price_sale': 'Sale Price (Rs.)',
        'description': 'Description',
        'upload_img': 'Upload Images',
        'list_btn': 'List Property',
        'back': 'Go Back',
        'free_listing': 'Free Listing!',
        'free_listing_sub': 'List your property and we will find you the right tenant/buyer.',
        # Requirement forms
        'your_name': 'Your Name',
        'your_phone': 'Phone / WhatsApp',
        'pref_area': 'Preferred Area',
        'max_budget': 'Maximum Budget (Rs.)',
        'tenant_type': 'Tenant Type',
        'move_date': 'When do you need it?',
        'special': 'Any Special Requirements?',
        'submit': 'Submit',
        'how_works': 'How It Works',
        'step1': 'Fill in the form',
        'step2': 'We search for you',
        'step3': 'We call you in 24 hours',
        'step4': 'We arrange site visit',
        'wa_direct': 'Or WhatsApp Directly',
        'payment_method': 'Payment Method',
        'purpose': 'Purpose',
        # Auth
        'login_title': 'Welcome Back',
        'login_sub': 'Login to your account',
        'email': 'Email Address',
        'password': 'Password',
        'login_btn': 'Login',
        'no_account': "Don't have an account?",
        'register_here': 'Register',
        'reg_title': 'Create Account',
        'reg_sub': 'Join ApnaGhar',
        'full_name': 'Full Name',
        'confirm_pass': 'Confirm Password',
        'reg_btn': 'Create Account',
        'have_account': 'Already have an account?',
        # Dashboard
        'dash_title': 'My Dashboard',
        'my_rent': 'My Rent Listings',
        'my_sale': 'My Sale Listings',
        'my_reqs': 'My Requirements',
        'my_saved': 'Saved',
        'my_verif': 'Verifications',
        'profile': 'Profile',
        'no_rent': 'No rent listings yet.',
        'no_sale': 'No sale listings yet.',
        'add_rent': 'List for Rent',
        'add_sale': 'List for Sale',
        'save_profile': 'Save Changes',
        'logout': 'Logout',
        'view': 'View',
        'delete': 'Delete',
        'new_req': 'New Request',
        'rent_reqs': 'Rent Requirements',
        'buy_reqs': 'Purchase Requirements',
        'saved_rent': 'Saved Rental Properties',
        'saved_sale': 'Saved Sale Properties',
        # Verification
        'verif_title': 'Tenant Verification',
        'verif_sub': 'CNIC-based background check',
        'tenant_name': 'Tenant Name',
        'cnic': 'CNIC Number',
        'mobile': 'Mobile Number',
        'address': 'Current Address',
        'occupation': 'Occupation',
        'upload_cnic': 'Upload CNIC Copy',
        'upload_photo': 'Upload Photo',
        'verif_btn': 'Submit Verification Request',
        'verif_info': 'Verification completed within 24 hours. Result shared via WhatsApp.',
        'why_verify': 'Why Verify?',
        'v1': 'Confirm tenant identity',
        'v2': 'CNIC background check',
        'v3': 'Reduce fraud risk',
        'v4': 'Peace of mind for owners',
        'v5': 'Legal protection',
        # Documents
        'doc_title': 'Document Services',
        'doc_sub': 'Professional legal documentation services',
        'doc_more': 'Need a custom service?',
        'get_quote': 'Get Quote',
        # Admin
        'admin_title': 'Admin Panel',
    },
    'ur': {
        'dir': 'rtl', 'lang': 'ur',
        'switch_lang': 'English', 'switch_code': 'en',
        # Navbar
        'nav_home': 'ہوم',
        'nav_rent': 'کرایہ',
        'nav_rent_lena': 'کرایہ پر لینا (کرایہ دار)',
        'nav_rent_dena': 'کرایہ پر دینا (مالک)',
        'nav_rent_req': 'کرایہ ضرورت فارم',
        'nav_buy_sell': 'خریدیں / بیچیں',
        'nav_buy': 'پراپرٹی خریدنا',
        'nav_sell': 'پراپرٹی بیچنا',
        'nav_buy_req': 'خریداری ضرورت فارم',
        'nav_verify': 'کرایہ دار تصدیق',
        'nav_docs': 'دستاویزات',
        'nav_login': 'لاگ ان',
        'nav_register': 'رجسٹر',
        'nav_dashboard': 'ڈیش بورڈ',
        'nav_admin': 'ایڈمن',
        'nav_logout': 'لاگ آؤٹ',
        # Hero
        'hero_tag': 'کراچی کی قابل اعتماد پراپرٹی اور دستاویزات کی خدمات',
        'hero_title': 'اپنا گھر',
        'hero_sub': 'محفوظ ڈیل، آسان اقدام — ڈیل بھی، ڈاکومنٹس بھی — سب ایک جگہ۔',
        'choose_title': 'آپ کیا کرنا چاہتے ہیں؟',
        'choose_sub': 'نیچے اپنا آپشن چنیں',
        # 4 Cards
        'card_rent_lena_title': 'کرایہ پر\nلینا چاہتا ہوں',
        'card_rent_lena_sub': 'کرایہ پر گھر، فلیٹ یا دکان چاہیے',
        'card_rent_lena_btn': 'پراپرٹیز دیکھیں ←',
        'card_rent_dena_title': 'کرایہ پر\nدینا چاہتا ہوں',
        'card_rent_dena_sub': 'اپنی پراپرٹی کرایہ پر دیں',
        'card_rent_dena_btn': 'پراپرٹی لسٹ کریں ←',
        'card_buy_title': 'پراپرٹی\nخریدنا چاہتا ہوں',
        'card_buy_sub': 'گھر، فلیٹ یا پلاٹ خریدنا چاہتے ہیں',
        'card_buy_btn': 'سیل پراپرٹیز دیکھیں ←',
        'card_sell_title': 'پراپرٹی\nبیچنا چاہتا ہوں',
        'card_sell_sub': 'اپنا گھر، فلیٹ یا پلاٹ بیچیں',
        'card_sell_btn': 'سیل لسٹنگ کریں ←',
        # Requirement banners
        'rent_req_title': 'کرایہ کی ضرورت بتائیں',
        'rent_req_sub': 'اپنا بجٹ اور علاقہ بتائیں — ہم بہترین آپشن لائیں گے!',
        'rent_req_btn': 'فارم بھریں',
        'buy_req_title': 'خریداری کی ضرورت بتائیں',
        'buy_req_sub': 'اپنا بجٹ اور پسندیدہ علاقہ بتائیں',
        'buy_req_btn': 'فارم بھریں',
        # Sections
        'rent_props_title': '🔑 کرایہ کی پراپرٹیز',
        'rent_props_sub': 'فوری دستیاب',
        'sale_props_title': '🏡 سیل پراپرٹیز',
        'sale_props_sub': 'خریدنے کے لیے دستیاب',
        'services_title': 'ہماری دیگر خدمات',
        'view_all': 'سب دیکھیں ←',
        'per_month': '/ماہ',
        'view_details': 'تفصیل دیکھیں',
        'featured': 'نمایاں',
        # Offer
        'offer_title': 'اختر کالونی کے باشندوں کے لیے خصوصی آفر',
        'offer_1': 'مفت پراپرٹی مشاورت',
        'offer_2': 'کرایہ نامے پر رعایت',
        'offer_3': 'مالکان کے لیے مفت لسٹنگ',
        'offer_btn': 'واٹس ایپ پر کلیم کریں',
        # Footer
        'footer_desc': 'کراچی میں قابل اعتماد پراپرٹی اور دستاویزات کی خدمات۔',
        'footer_rent': 'کرایہ',
        'footer_buy': 'خریدیں / بیچیں',
        'footer_contact': 'رابطہ کریں',
        'footer_hours': 'پیر تا ہفتہ: صبح ۹ سے شام ۸',
        'footer_rights': 'جملہ حقوق محفوظ ہیں۔',
        # Pages
        'rent_lena_title': 'کرایہ پر لینا',
        'rent_lena_sub': 'پراپرٹیز دستیاب ہیں',
        'rent_req_banner': 'پسند کی پراپرٹی نہیں ملی؟ اپنی ضرورت بتائیں — ہم ڈھونڈیں گے!',
        'filter_type': 'پراپرٹی کی قسم',
        'filter_all': 'تمام اقسام',
        'filter_beds': 'بیڈرومز',
        'filter_any': 'کوئی بھی',
        'filter_loc': 'علاقہ / مقام',
        'filter_search': 'تلاش',
        'filter_clear': 'صاف کریں',
        'no_props': 'کوئی پراپرٹی نہیں ملی',
        'submit_req': 'ضرورت جمع کریں',
        # Detail
        'month': '/ماہ',
        'beds': 'کمرے',
        'baths': 'باتھ روم',
        'possession': 'قبضہ',
        'wa_contact': 'واٹس ایپ پر پوچھیں',
        'call_now': 'ابھی کال کریں',
        'save': 'محفوظ کریں',
        'unsave': 'محفوظ سے ہٹائیں',
        'login_save': 'محفوظ کرنے کے لیے لاگ ان کریں',
        'listed_by': 'درج کردہ',
        'date_posted': 'تاریخ',
        'prop_desc': 'پراپرٹی کی تفصیل',
        'interested': 'اس پراپرٹی میں دلچسپی ہے؟',
        'contact_sub': 'سائٹ وزٹ کے لیے رابطہ کریں۔',
        # Forms
        'owner_name': 'مالک کا نام',
        'owner_phone': 'فون / واٹس ایپ',
        'prop_title': 'پراپرٹی کا عنوان',
        'location': 'علاقہ / محلہ',
        'full_addr': 'پورا پتہ',
        'prop_type': 'پراپرٹی کی قسم',
        'bedrooms': 'بیڈرومز',
        'bathrooms': 'باتھ رومز',
        'floor': 'منزل',
        'furnished': 'فرنشڈ',
        'tenant_pref': 'کرایہ دار کی ترجیح',
        'price_rent': 'ماہانہ کرایہ (روپے)',
        'price_sale': 'قیمت فروخت (روپے)',
        'description': 'تفصیل',
        'upload_img': 'تصاویر اپلوڈ کریں',
        'list_btn': 'پراپرٹی لسٹ کریں',
        'back': 'واپس',
        'free_listing': 'مفت لسٹنگ!',
        'free_listing_sub': 'اپنی پراپرٹی لسٹ کریں اور ہم صحیح کرایہ دار / خریدار ڈھونڈیں گے۔',
        # Requirement forms
        'your_name': 'آپ کا نام',
        'your_phone': 'فون / واٹس ایپ',
        'pref_area': 'پسندیدہ علاقہ',
        'max_budget': 'زیادہ سے زیادہ بجٹ (روپے)',
        'tenant_type': 'کرایہ دار کی قسم',
        'move_date': 'کب چاہیے؟',
        'special': 'کوئی خاص ضرورت؟',
        'submit': 'جمع کریں',
        'how_works': 'یہ کیسے کام کرتا ہے؟',
        'step1': 'فارم بھریں',
        'step2': 'ہم پراپرٹی ڈھونڈیں گے',
        'step3': '۲۴ گھنٹے میں کال کریں گے',
        'step4': 'سائٹ وزٹ ترتیب دیں گے',
        'wa_direct': 'یا سیدھا واٹس ایپ کریں',
        'payment_method': 'ادائیگی کا طریقہ',
        'purpose': 'مقصد',
        # Auth
        'login_title': 'خوش آمدید',
        'login_sub': 'اپنے اکاؤنٹ میں لاگ ان کریں',
        'email': 'ای میل ایڈریس',
        'password': 'پاس ورڈ',
        'login_btn': 'لاگ ان',
        'no_account': 'اکاؤنٹ نہیں ہے؟',
        'register_here': 'رجسٹر کریں',
        'reg_title': 'اکاؤنٹ بنائیں',
        'reg_sub': 'سیکیور پراپرٹی ہب میں شامل ہوں',
        'full_name': 'پورا نام',
        'confirm_pass': 'پاس ورڈ کی تصدیق',
        'reg_btn': 'اکاؤنٹ بنائیں',
        'have_account': 'پہلے سے اکاؤنٹ ہے؟',
        # Dashboard
        'dash_title': 'میرا ڈیش بورڈ',
        'my_rent': 'میری کرایہ لسٹنگز',
        'my_sale': 'میری سیل لسٹنگز',
        'my_reqs': 'میری ضروریات',
        'my_saved': 'محفوظ شدہ',
        'my_verif': 'تصدیقات',
        'profile': 'پروفائل',
        'no_rent': 'ابھی کوئی کرایہ لسٹنگ نہیں۔',
        'no_sale': 'ابھی کوئی سیل لسٹنگ نہیں۔',
        'add_rent': 'کرایہ پر دیں',
        'add_sale': 'سیل لسٹنگ کریں',
        'save_profile': 'تبدیلیاں محفوظ کریں',
        'logout': 'لاگ آؤٹ',
        'view': 'دیکھیں',
        'delete': 'حذف کریں',
        'new_req': 'نئی درخواست',
        'rent_reqs': 'کرایہ کی ضروریات',
        'buy_reqs': 'خریداری کی ضروریات',
        'saved_rent': 'محفوظ کرایہ پراپرٹیز',
        'saved_sale': 'محفوظ سیل پراپرٹیز',
        # Verification
        'verif_title': 'کرایہ دار تصدیق',
        'verif_sub': 'شناختی کارڈ پر مبنی پس منظر کی جانچ',
        'tenant_name': 'کرایہ دار کا نام',
        'cnic': 'شناختی کارڈ نمبر',
        'mobile': 'موبائل نمبر',
        'address': 'موجودہ پتہ',
        'occupation': 'پیشہ',
        'upload_cnic': 'شناختی کارڈ کی کاپی اپلوڈ کریں',
        'upload_photo': 'تصویر اپلوڈ کریں',
        'verif_btn': 'تصدیق درخواست جمع کریں',
        'verif_info': 'تصدیق ۲۴ گھنٹے میں مکمل ہوتی ہے۔ نتیجہ واٹس ایپ پر بھیجا جائے گا۔',
        'why_verify': 'تصدیق کیوں ضروری ہے؟',
        'v1': 'کرایہ دار کی شناخت کی تصدیق',
        'v2': 'شناختی کارڈ سے بیک گراؤنڈ چیک',
        'v3': 'دھوکہ دہی کا خطرہ کم کریں',
        'v4': 'مالکان کے لیے سکون',
        'v5': 'قانونی تحفظ',
        # Documents
        'doc_title': 'دستاویز خدمات',
        'doc_sub': 'پیشہ ورانہ قانونی دستاویزات کی خدمات',
        'doc_more': 'کوئی اور خدمت چاہیے؟',
        'get_quote': 'قیمت معلوم کریں',
        # Admin
        'admin_title': 'ایڈمن پینل',
    }
}

def get_lang():
    return session.get('lang', 'en')

def T():
    return TRANSLATIONS.get(get_lang(), TRANSLATIONS['en'])

@app.context_processor
def inject_globals():
    return dict(now=datetime.now(), T=T(), lang=get_lang())

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
            (
                path,
                request.method,
                ip,
                request.user_agent.string[:200] if request.user_agent.string else '',
                request.referrer or '',
                session.get('user_id')
            )
        )
        row_id = cur.lastrowid
        conn.commit()
        conn.close()

        # Fetch city/country in background thread so page loads fast
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
        pass  # Never break the site due to logging errors


@app.route('/set-lang/<lang>')
def set_lang(lang):
    if lang in ['en', 'ur']:
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))

def allowed_file(f):
    return '.' in f and f.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

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

# ─── DB INIT ──────────────────────────────────────────────────────────────────

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, email TEXT UNIQUE NOT NULL,
        password TEXT, is_admin INTEGER DEFAULT 0,
        phone TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Properties for RENT (listed by owners who want to give on rent)
    c.execute('''CREATE TABLE IF NOT EXISTS rent_properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        owner_name TEXT, owner_phone TEXT,
        title TEXT, location TEXT, area TEXT,
        property_type TEXT, price TEXT,
        bedrooms TEXT, bathrooms TEXT,
        floor TEXT, furnished TEXT,
        tenant_preference TEXT,
        description TEXT,
        is_approved INTEGER DEFAULT 0,
        is_featured INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Properties for SALE (listed by owners who want to sell)
    c.execute('''CREATE TABLE IF NOT EXISTS sale_properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        owner_name TEXT, owner_phone TEXT,
        title TEXT, location TEXT, area TEXT,
        property_type TEXT, price TEXT,
        bedrooms TEXT, bathrooms TEXT,
        total_area TEXT,
        possession TEXT,
        description TEXT,
        is_approved INTEGER DEFAULT 0,
        is_featured INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Images for both types
    c.execute('''CREATE TABLE IF NOT EXISTS property_images (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        property_id INTEGER,
        property_cat TEXT,
        filename TEXT)''')

    # Rent Requirements (people who WANT to rent)
    c.execute('''CREATE TABLE IF NOT EXISTS rent_requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT, phone TEXT,
        preferred_area TEXT,
        property_type TEXT,
        max_budget TEXT,
        bedrooms TEXT,
        tenant_type TEXT,
        move_in_date TEXT,
        special_needs TEXT,
        status TEXT DEFAULT 'New',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Purchase Requirements (people who WANT to buy)
    c.execute('''CREATE TABLE IF NOT EXISTS purchase_requirements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT, phone TEXT,
        preferred_area TEXT,
        property_type TEXT,
        max_budget TEXT,
        bedrooms TEXT,
        payment_method TEXT,
        purpose TEXT,
        special_needs TEXT,
        status TEXT DEFAULT 'New',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Tenant Verification
    c.execute('''CREATE TABLE IF NOT EXISTS tenant_verification (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        tenant_name TEXT, cnic TEXT,
        mobile TEXT, address TEXT,
        occupation TEXT, cnic_file TEXT,
        photo_file TEXT,
        status TEXT DEFAULT 'Pending',
        notes TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Saved properties
    c.execute('''CREATE TABLE IF NOT EXISTS saved_properties (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        property_id INTEGER,
        property_cat TEXT)''')

    # Traffic / Page Views
    c.execute('''CREATE TABLE IF NOT EXISTS page_views (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path TEXT NOT NULL,
        method TEXT DEFAULT 'GET',
        ip TEXT,
        user_agent TEXT,
        referrer TEXT,
        user_id INTEGER,
        city TEXT DEFAULT '',
        country TEXT DEFAULT '',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)''')

    # Add city/country columns if upgrading from older DB
    try:
        c.execute("ALTER TABLE page_views ADD COLUMN city TEXT DEFAULT ''")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE page_views ADD COLUMN country TEXT DEFAULT ''")
    except Exception:
        pass

    # Admin user
    c.execute("SELECT COUNT(*) FROM users WHERE is_admin=1")
    if c.fetchone()[0] == 0:
        pw = generate_password_hash('apnaghar6873')
        c.execute("INSERT INTO users (name,email,password,is_admin) VALUES (?,?,?,1)",
                  ('Admin','apnagharkarachi.pk@gmail.com', pw))

    conn.commit()
    conn.close()

# ─── UPLOADS ──────────────────────────────────────────────────────────────────

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ─── HOME ─────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    conn = get_db()
    featured_rent = conn.execute("SELECT r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE r.is_approved=1 AND r.is_featured=1 GROUP BY r.id LIMIT 3").fetchall()
    featured_sale = conn.execute("SELECT s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE s.is_approved=1 AND s.is_featured=1 GROUP BY s.id LIMIT 3").fetchall()
    stats = {
        'rent': conn.execute("SELECT COUNT(*) FROM rent_properties WHERE is_approved=1").fetchone()[0],
        'sale': conn.execute("SELECT COUNT(*) FROM sale_properties WHERE is_approved=1").fetchone()[0],
        'verified': conn.execute("SELECT COUNT(*) FROM tenant_verification WHERE status='Approved'").fetchone()[0],
        'clients': conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0],
    }
    conn.close()
    return render_template('index.html', featured_rent=featured_rent, featured_sale=featured_sale, stats=stats)

# ─── RENT SECTION ─────────────────────────────────────────────────────────────

@app.route('/kiraya-par-lena')
def rent_lena():
    """People who WANT to rent - show available properties"""
    conn = get_db()
    ptype = request.args.get('type','')
    loc   = request.args.get('location','')
    bed   = request.args.get('bedrooms','')
    q = "SELECT r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE r.is_approved=1"
    params = []
    if ptype: q += " AND r.property_type=?"; params.append(ptype)
    if loc:   q += " AND (r.location LIKE ? OR r.area LIKE ?)"; params += [f'%{loc}%', f'%{loc}%']
    if bed:   q += " AND r.bedrooms=?"; params.append(bed)
    q += " GROUP BY r.id ORDER BY r.is_featured DESC, r.created_at DESC"
    props = conn.execute(q, params).fetchall()
    conn.close()
    return render_template('rent_lena.html', props=props, ptype=ptype, loc=loc, bed=bed)

@app.route('/kiraya-par-lena/<int:pid>')
def rent_detail(pid):
    conn = get_db()
    prop = conn.execute("SELECT r.*, u.name as poster FROM rent_properties r LEFT JOIN users u ON r.user_id=u.id WHERE r.id=? AND r.is_approved=1", (pid,)).fetchone()
    if not prop: return redirect(url_for('rent_lena'))
    images = conn.execute("SELECT filename FROM property_images WHERE property_id=? AND property_cat='rent'", (pid,)).fetchall()
    is_saved = False
    if session.get('user_id'):
        is_saved = bool(conn.execute("SELECT id FROM saved_properties WHERE user_id=? AND property_id=? AND property_cat='rent'", (session['user_id'], pid)).fetchone())
    conn.close()
    return render_template('property_detail.html', prop=prop, images=images, cat='rent', is_saved=is_saved)

@app.route('/kiraya-par-dena', methods=['GET','POST'])
@login_required
def rent_dena():
    """Property owners who WANT to list for rent"""
    if request.method == 'POST':
        conn = get_db()
        cur = conn.cursor()
        auto_approve = 1 if session.get('is_admin') else 0
        cur.execute('''INSERT INTO rent_properties (user_id,owner_name,owner_phone,title,location,area,
            property_type,price,bedrooms,bathrooms,floor,furnished,tenant_preference,description,is_approved)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            session['user_id'],
            request.form['owner_name'], request.form['owner_phone'],
            request.form['title'], request.form['location'], request.form['area'],
            request.form['property_type'], request.form['price'],
            request.form['bedrooms'], request.form.get('bathrooms','1'),
            request.form.get('floor',''), request.form.get('furnished','Unfurnished'),
            request.form.get('tenant_preference','Family'),
            request.form['description'], auto_approve))
        pid = cur.lastrowid
        for f in request.files.getlist('images'):
            if f and allowed_file(f.filename):
                fname = f"rent_{pid}_{secure_filename(f.filename)}"
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                conn.execute("INSERT INTO property_images (property_id,property_cat,filename) VALUES (?,?,?)", (pid,'rent',fname))
        conn.commit(); conn.close()
        flash('Aapki property list ho gayi! Hum jald aap se rabta karenge.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('rent_dena.html')

@app.route('/kiraya-chahiye', methods=['GET','POST'])
def rent_chahiye():
    """Requirement form for people who WANT to rent"""
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
        flash('Aapki requirement submit ho gayi! 24 ghante mein rabta karenge.', 'success')
        return redirect(url_for('index'))
    return render_template('rent_chahiye.html')

# ─── SALE / PURCHASE SECTION ──────────────────────────────────────────────────

@app.route('/khareedna-chahta-hoon')
def purchase_lena():
    """People who WANT to buy - show sale properties"""
    conn = get_db()
    ptype = request.args.get('type','')
    loc   = request.args.get('location','')
    q = "SELECT s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE s.is_approved=1"
    params = []
    if ptype: q += " AND s.property_type=?"; params.append(ptype)
    if loc:   q += " AND (s.location LIKE ? OR s.area LIKE ?)"; params += [f'%{loc}%', f'%{loc}%']
    q += " GROUP BY s.id ORDER BY s.is_featured DESC, s.created_at DESC"
    props = conn.execute(q, params).fetchall()
    conn.close()
    return render_template('purchase_lena.html', props=props, ptype=ptype, loc=loc)

@app.route('/khareedna-chahta-hoon/<int:pid>')
def sale_detail(pid):
    conn = get_db()
    prop = conn.execute("SELECT s.*, u.name as poster FROM sale_properties s LEFT JOIN users u ON s.user_id=u.id WHERE s.id=? AND s.is_approved=1", (pid,)).fetchone()
    if not prop: return redirect(url_for('purchase_lena'))
    images = conn.execute("SELECT filename FROM property_images WHERE property_id=? AND property_cat='sale'", (pid,)).fetchall()
    is_saved = False
    if session.get('user_id'):
        is_saved = bool(conn.execute("SELECT id FROM saved_properties WHERE user_id=? AND property_id=? AND property_cat='sale'", (session['user_id'], pid)).fetchone())
    conn.close()
    return render_template('property_detail.html', prop=prop, images=images, cat='sale', is_saved=is_saved)

@app.route('/bechna-chahta-hoon', methods=['GET','POST'])
@login_required
def sale_dena():
    """Property owners who WANT to sell"""
    if request.method == 'POST':
        conn = get_db()
        cur = conn.cursor()
        auto_approve = 1 if session.get('is_admin') else 0
        cur.execute('''INSERT INTO sale_properties (user_id,owner_name,owner_phone,title,location,area,
            property_type,price,bedrooms,bathrooms,total_area,possession,description,is_approved)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
            session['user_id'],
            request.form['owner_name'], request.form['owner_phone'],
            request.form['title'], request.form['location'], request.form['area'],
            request.form['property_type'], request.form['price'],
            request.form['bedrooms'], request.form.get('bathrooms','1'),
            request.form.get('total_area',''), request.form.get('possession','Immediate'),
            request.form['description'], auto_approve))
        pid = cur.lastrowid
        for f in request.files.getlist('images'):
            if f and allowed_file(f.filename):
                fname = f"sale_{pid}_{secure_filename(f.filename)}"
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                conn.execute("INSERT INTO property_images (property_id,property_cat,filename) VALUES (?,?,?)", (pid,'sale',fname))
        conn.commit(); conn.close()
        flash('Aapki property sale listing ho gayi! Hum jald rabta karenge.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('sale_dena.html')

@app.route('/khareedna-chahiye', methods=['GET','POST'])
def purchase_chahiye():
    """Requirement form for people who WANT to buy"""
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
        flash('Aapki purchase requirement submit ho gayi! 24 ghante mein rabta karenge.', 'success')
        return redirect(url_for('index'))
    return render_template('purchase_chahiye.html')

# ─── SAVE PROPERTY ────────────────────────────────────────────────────────────

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
    if cat == 'rent':
        return redirect(url_for('rent_detail', pid=pid))
    return redirect(url_for('sale_detail', pid=pid))

# ─── DELETE PROPERTY ──────────────────────────────────────────────────────────

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
                fname = f"{prefix}_{session['user_id']}_{secure_filename(f.filename)}"
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
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
        name = request.form['name'].strip()
        email = request.form['email'].strip().lower()
        pw = request.form['password']
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
    return render_template('register.html')

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        pw = request.form['password']
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        conn.close()
        if user and user['password'] and check_password_hash(user['password'], pw):
            session.update({'user_id': user['id'], 'user_name': user['name'],
                            'user_email': user['email'], 'is_admin': bool(user['is_admin'])})
            return redirect(url_for('admin_panel') if user['is_admin'] else url_for('dashboard'))
        flash('Email ya password galat hai.', 'danger')
    return render_template('login.html')

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
    my_rent = conn.execute("SELECT r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE r.user_id=? GROUP BY r.id ORDER BY r.created_at DESC", (uid,)).fetchall()
    my_sale = conn.execute("SELECT s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE s.user_id=? GROUP BY s.id ORDER BY s.created_at DESC", (uid,)).fetchall()
    my_rent_reqs = conn.execute("SELECT * FROM rent_requirements WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    my_buy_reqs  = conn.execute("SELECT * FROM purchase_requirements WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    my_verifs    = conn.execute("SELECT * FROM tenant_verification WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
    saved_rent   = conn.execute("SELECT r.*, pi.filename FROM saved_properties sp JOIN rent_properties r ON sp.property_id=r.id LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' WHERE sp.user_id=? AND sp.property_cat='rent' GROUP BY r.id", (uid,)).fetchall()
    saved_sale   = conn.execute("SELECT s.*, pi.filename FROM saved_properties sp JOIN sale_properties s ON sp.property_id=s.id LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' WHERE sp.user_id=? AND sp.property_cat='sale' GROUP BY s.id", (uid,)).fetchall()
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
    pw = request.form['password']
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email=? AND is_admin=1", (email,)).fetchone()
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
    users     = conn.execute("SELECT * FROM users WHERE is_admin=0 ORDER BY created_at DESC").fetchall()
    rent_props= conn.execute("SELECT r.*, pi.filename FROM rent_properties r LEFT JOIN property_images pi ON r.id=pi.property_id AND pi.property_cat='rent' GROUP BY r.id ORDER BY r.created_at DESC").fetchall()
    sale_props= conn.execute("SELECT s.*, pi.filename FROM sale_properties s LEFT JOIN property_images pi ON s.id=pi.property_id AND pi.property_cat='sale' GROUP BY s.id ORDER BY s.created_at DESC").fetchall()
    rent_reqs = conn.execute("SELECT rr.*, u.name as uname FROM rent_requirements rr LEFT JOIN users u ON rr.user_id=u.id ORDER BY rr.created_at DESC").fetchall()
    buy_reqs  = conn.execute("SELECT pr.*, u.name as uname FROM purchase_requirements pr LEFT JOIN users u ON pr.user_id=u.id ORDER BY pr.created_at DESC").fetchall()
    verifs    = conn.execute("SELECT tv.*, u.name as uname FROM tenant_verification tv LEFT JOIN users u ON tv.user_id=u.id ORDER BY tv.created_at DESC").fetchall()
    stats = {'users': len(users), 'rent': len(rent_props), 'sale': len(sale_props),
             'rent_reqs': len(rent_reqs), 'buy_reqs': len(buy_reqs), 'verifs': len(verifs)}

    # ── Traffic Stats ──
    traffic_total   = conn.execute("SELECT COUNT(*) FROM page_views").fetchone()[0]
    traffic_today   = conn.execute("SELECT COUNT(*) FROM page_views WHERE DATE(created_at)=DATE('now','localtime')").fetchone()[0]
    traffic_week    = conn.execute("SELECT COUNT(*) FROM page_views WHERE created_at >= datetime('now','-7 days')").fetchone()[0]
    top_pages       = conn.execute("SELECT path, COUNT(*) as cnt FROM page_views GROUP BY path ORDER BY cnt DESC LIMIT 10").fetchall()
    recent_views    = conn.execute("SELECT path, ip, city, country, user_agent, created_at FROM page_views ORDER BY created_at DESC LIMIT 30").fetchall()
    daily_chart     = conn.execute("""
        SELECT DATE(created_at,'localtime') as day, COUNT(*) as cnt
        FROM page_views
        WHERE created_at >= datetime('now','-14 days')
        GROUP BY day ORDER BY day ASC
    """).fetchall()
    unique_ips_today = conn.execute("SELECT COUNT(DISTINCT ip) FROM page_views WHERE DATE(created_at)=DATE('now','localtime')").fetchone()[0]

    conn.close()
    return render_template('admin_panel.html', users=users, rent_props=rent_props, sale_props=sale_props,
        rent_reqs=rent_reqs, buy_reqs=buy_reqs, verifs=verifs, stats=stats,
        traffic_total=traffic_total, traffic_today=traffic_today, traffic_week=traffic_week,
        top_pages=top_pages, recent_views=recent_views, daily_chart=daily_chart,
        unique_ips_today=unique_ips_today)

@app.route('/admin/delete/<table>/<int:rid>')
@admin_required
def admin_delete(table, rid):
    allowed = ['users','rent_properties','sale_properties','rent_requirements','purchase_requirements','tenant_verification']
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

@app.route('/admin/toggle/<table>/<field>/<int:pid>')
@admin_required
def admin_toggle(table, field, pid):
    allowed_tables = ['rent_properties', 'sale_properties']
    allowed_fields = ['is_approved', 'is_featured']
    if table not in allowed_tables or field not in allowed_fields:
        return redirect(url_for('admin_panel'))
    conn = get_db()
    row = conn.execute(f"SELECT {field} FROM {table} WHERE id=?", (pid,)).fetchone()
    if row:
        conn.execute(f"UPDATE {table} SET {field}=? WHERE id=?", (0 if row[field] else 1, pid))
        conn.commit()
    conn.close()
    return redirect(url_for('admin_panel'))

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
        story.append(Paragraph("SECURE PROPERTY HUB", title_s))
        story.append(Paragraph("Akhtar Colony, Karachi | 03111820660 | saleem9868@gmail.com", sub_s))
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

# ─── EXTRA PAGES ──────────────────────────────────────────────────────────────

@app.route('/property-laws')
def property_laws():
    return render_template('property_laws.html')

@app.route('/calculators')
def calculators():
    return render_template('calculators.html')

@app.route('/area-guide')
def area_guide():
    return render_template('area_guide.html')

@app.route('/blog')
def blog():
    return render_template('blog.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')

@app.route('/about')
def about():
    return render_template('about.html')

# ─── STARTUP — runs for both gunicorn and direct python ──────────────────────

os.makedirs('uploads', exist_ok=True)
init_db()

# ─── RUN ──────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n" + "="*55)
    print("  ✅  Secure Property Hub V2 - Chal gaya!")
    print("  🌐  Website: http://localhost:5000")
    print("  🔐  Admin:   http://localhost:5000/admin")
    print("      Email:   apnagharkarachi.pk@gmail.com")
    print("      Password: apnaghar6873")
    print("="*55 + "\n")
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
