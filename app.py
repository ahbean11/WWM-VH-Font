import os
import pandas as pd
import requests
import shutil
import tempfile
import struct
import re
import sys
import hashlib
import uuid # Dùng để tạo ID cho khách vãng lai
from datetime import datetime
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from authlib.integrations.flask_client import OAuth

# Load biến môi trường
load_dotenv()

app = Flask(__name__)

# --- CẤU HÌNH BẢO MẬT & DATABASE ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_khong_an_toan_123')

# Google OAuth Configuration
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.environ.get('GOOGLE_CLIENT_ID'),
    client_secret=os.environ.get('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={
        'scope': 'openid email profile'
    }
)

# Xử lý Database URL từ Render
database_url = os.environ.get('DATABASE_URL')
if database_url:
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
else:
    # Sử dụng SQLite với đường dẫn tuyệt đối cho môi trường development
    database_url = 'sqlite:///site.db'

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Khởi tạo Extension
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "Vui lòng đăng nhập để sử dụng tính năng này."
login_manager.login_message_category = "info"

# --- DATABASE MODELS ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(20), unique=True, nullable=False)
    password = db.Column(db.String(60), nullable=False)
    balance = db.Column(db.Integer, default=0)
    free_trials = db.Column(db.Integer, default=1)
    is_donor = db.Column(db.Boolean, default=False)
    email = db.Column(db.String(120), unique=True, nullable=True)  # Thêm email field
    transactions = db.relationship('Transaction', backref='author', lazy=True)

    # Ensure the is_donor column exists
    @staticmethod
    def add_missing_columns():
        # This is a simple approach to handle missing columns
        # In production, you should use proper migrations
        pass

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Integer, nullable=False)
    description = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='pending') # pending, success
    date_created = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) # Nullable cho khách vãng lai
    guest_id = db.Column(db.String(50), nullable=True) # ID tạm cho khách vãng lai

@login_manager.user_loader
def load_user(user_id):
    # Handle the case where the user table might not have the is_donor column yet
    try:
        return User.query.get(int(user_id))
    except Exception as e:
        print(f"Error loading user: {e}")
        # If there's an error, recreate the tables
        with app.app_context():
            db.create_all()
        return User.query.get(int(user_id))

# --- Cấu HÌNH SHEET ---
SHEET_URL = os.environ.get('SHEET_URL')

def get_data():
    if not SHEET_URL: return []
    try:
        df = pd.read_csv(SHEET_URL, dtype=str)
        df.columns = df.columns.str.lower().str.strip()
        df = df.dropna(subset=['platform'])
        df = df.fillna("")
        return df.to_dict('records')
    except: return []

# --- CÁC CLASS XỬ LÝ FONT (GIẢ LẬP) ---
# Bạn cần paste code SteamPatcher và LauncherPatcher thật vào đây
# Ở đây mình viết hàm giả lập để code chạy được demo
def process_font_logic(font_file_path, output_path):
    """
    Placeholder function for font processing.
    Will be implemented later as per requirements.
    """
    # TODO: Implement actual font patching logic here
    # For now, just copy the file as a placeholder
    shutil.copy(font_file_path, output_path)
    return True

# --- ROUTES CHÍNH ---

@app.route('/')
def home():
    versions = get_data()
    return render_template('index.html', versions=versions)

# --- AUTHENTICATION ---
# Removed register route as requested - only Google login is allowed now

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('font_tool'))
    # Removed username/password login as requested - only Google login is allowed now
    return render_template('login.html')

# Google Login Routes (kept as is)
@app.route('/login/google')
def google_login():
    # Hỗ trợ cả môi trường development và production
    if os.environ.get('RENDER'):
        # Môi trường production trên Render
        redirect_uri = url_for('google_callback', _external=True, _scheme='https')
    else:
        # Môi trường development local
        redirect_uri = request.url_root.rstrip('/') + url_for('google_callback')
    return google.authorize_redirect(redirect_uri)

@app.route('/login/google/callback')
def google_callback():
    try:
        token = google.authorize_access_token()
        user_info = token.get('userinfo')
        
        if user_info:
            # Check if user exists, create if not
            user = User.query.filter_by(username=user_info['email']).first()
            if not user:
                # Create new user with Google email as username
                # Set initial free_trials to 1 for regular users
                user = User(
                    username=user_info['email'], 
                    email=user_info['email'],  # Lưu email
                    password=bcrypt.generate_password_hash(str(uuid.uuid4())).decode('utf-8'),  # Random password
                    free_trials=1  # Regular users get 1 free trial
                )
                db.session.add(user)
                db.session.commit()
                flash('Tài khoản được tạo thành công bằng Google! Bạn có 1 lần dùng thử miễn phí.', 'success')
            else:
                # Cập nhật email nếu chưa có
                if not user.email:
                    user.email = user_info['email']
                    db.session.commit()
            
            login_user(user)
            return redirect(url_for('font_tool'))
        else:
            flash('Không thể xác thực với Google.', 'danger')
    except Exception as e:
        flash('Lỗi khi đăng nhập bằng Google: ' + str(e), 'danger')
    
    return redirect(url_for('login'))

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))

# --- TRANG TOOL FONT ---
@app.route('/tools/font-editor')
def font_tool():
    # Tạo ID phiên giao dịch cho khách vãng lai nếu chưa có
    if 'guest_session_id' not in session:
        session['guest_session_id'] = str(uuid.uuid4())[:8].upper() # Ví dụ: A1B2C3D4
    
    return render_template('font_tool.html', 
                           guest_id=session['guest_session_id'],
                           bank_acc="100872675193", # Số TK của bạn
                           bank_name="VietinBank")

# --- XỬ LÝ THANH TOÁN & TẠO FONT (QUAN TRỌNG) ---
@app.route('/process-font', methods=['POST'])
def process_font():
    # Require authentication - no guest access anymore
    if not current_user.is_authenticated:
        flash('Vui lòng đăng nhập để sử dụng tính năng này.', 'danger')
        return redirect(url_for('login'))
    
    # Kiểm tra file upload
    if 'font_file' not in request.files:
        flash('Vui lòng chọn file font (.ttf)', 'danger')
        return redirect(url_for('font_tool'))
    
    file = request.files['font_file']
    if file.filename == '':
        flash('Chưa chọn file', 'danger')
        return redirect(url_for('font_tool'))

    # --- CHỈ DÀNH CHO THÀNH VIÊN ĐÃ ĐĂNG NHẬP ---
    can_process = False
    
    # VIP donors can use unlimited times
    if current_user.is_donor:
        can_process = True
        flash('Xin chào Nhà tài trợ VIP! Font sẽ được xử lý ngay.', 'success')
    # Regular members get 1 free trial
    elif current_user.free_trials > 0:
        current_user.free_trials -= 1
        can_process = True
        flash(f'Đã dùng 1 lượt miễn phí. Còn lại: {current_user.free_trials}', 'success')
    else:
        flash('Bạn đã hết lượt dùng thử. Hãy trở thành Nhà tài trợ VIP để sử dụng không giới hạn!', 'warning')
        return redirect(url_for('font_tool'))

    if can_process:
        db.session.commit() # Lưu thay đổi số dư
        
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = os.path.join(temp_dir, file.filename)
            output_path = os.path.join(temp_dir, f"Patched_{file.filename}")
            file.save(input_path)
            
            process_font_logic(input_path, output_path)
            
            return send_file(output_path, as_attachment=True)
    
    return redirect(url_for('font_tool'))

# --- NẠP TIỀN CHO THÀNH VIÊN ---
@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', 
                           bank_acc="100872675193", 
                           bank_name="VietinBank",
                           transfer_content=f"WWM {current_user.id}")

# --- WEBHOOK SEPAY (XỬ LÝ TỰ ĐỘNG) ---
@app.route('/api/sepay-webhook', methods=['POST'])
def sepay_webhook():
    try:
        data = request.json
        # Dữ liệu mẫu SePay: {'gateway': 'MBBank', 'transferAmount': 10000, 'content': 'WWM 5 abc123...', 'customerEmail': 'user@example.com'}
        
        content = data.get('content', '')
        amount = data.get('transferAmount', 0)
        customer_email = data.get('customerEmail', '')  # Lấy email từ SePay
        
        if not content: return jsonify({'success': False}), 400

        import hashlib
        
        # LOGIC 1: Xác thực donate từ user đã tồn tại
        # Format: WWM <user_id> <email_hash>
        user_match = re.search(r'WWM\s+(\d+)\s+([a-f0-9]{32})', content, re.IGNORECASE)
        if user_match:
            user_id = int(user_match.group(1))
            email_hash = user_match.group(2)
            user = User.query.get(user_id)
            if user and user.email:
                # Kiểm tra hash email
                expected_hash = hashlib.md5(user.email.lower().encode()).hexdigest()
                if expected_hash == email_hash:
                    user.balance += int(amount)
                    # Set donor status nếu donate từ 10.000đ trở lên
                    if int(amount) >= 10000:
                        user.is_donor = True
                    new_trans = Transaction(amount=amount, description=content, status='success', user_id=user.id)
                    db.session.add(new_trans)
                    db.session.commit()
                    return jsonify({'success': True, 'msg': 'User donation processed'}), 200

        # LOGIC 2: Xác thực donate từ user mới
        # Format: WWM NEW <email_hash>
        new_user_match = re.search(r'WWM\s+NEW\s+([a-f0-9]{32})', content, re.IGNORECASE)
        if new_user_match:
            email_hash = new_user_match.group(1)
            # Tìm user theo email hash (nếu đã có trong hệ thống)
            all_users = User.query.all()
            matched_user = None
            for user in all_users:
                if user.email:
                    user_hash = hashlib.md5(user.email.lower().encode()).hexdigest()
                    if user_hash == email_hash:
                        matched_user = user
                        break
            
            if matched_user:
                matched_user.balance += int(amount)
                # Set donor status nếu donate từ 10.000đ trở lên
                if int(amount) >= 10000:
                    matched_user.is_donor = True
                new_trans = Transaction(amount=amount, description=content, status='success', user_id=matched_user.id)
                db.session.add(new_trans)
                db.session.commit()
                return jsonify({'success': True, 'msg': 'Existing user new donation processed'}), 200
            else:
                # Lưu transaction cho user mới, sẽ xử lý khi họ đăng nhập
                new_trans = Transaction(amount=amount, description=content, status='pending', guest_id=email_hash)
                db.session.add(new_trans)
                db.session.commit()
                return jsonify({'success': True, 'msg': 'New user donation recorded, pending registration'}), 200

        return jsonify({'success': True, 'msg': 'No matching user found'}), 200

    except Exception as e:
        print(f"Webhook Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# --- API CHECK THANH TOÁN (CHO KHÁCH VÃNG LAI) ---
@app.route('/api/check-guest-payment')
def check_guest_payment():
    guest_id = session.get('guest_session_id')
    if not guest_id: return jsonify({'paid': False})
    
    # Tìm giao dịch thành công của Guest ID này
    trans = Transaction.query.filter_by(guest_id=guest_id, status='success').first()
    if trans and trans.amount >= 10000:
        return jsonify({'paid': True})
    return jsonify({'paid': False})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)
