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

# Load biến môi trường
load_dotenv()

app = Flask(__name__)

# --- CẤU HÌNH BẢO MẬT & DATABASE ---
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_khong_an_toan_123')

# Xử lý Database URL từ Render
database_url = os.environ.get('DATABASE_URL')
if database_url and database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = database_url or 'sqlite:///site.db'
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
    free_trials = db.Column(db.Integer, default=2)
    transactions = db.relationship('Transaction', backref='author', lazy=True)

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
    return User.query.get(int(user_id))

# --- CẤU HÌNH SHEET ---
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
    # Giả lập xử lý file: Copy file gốc sang file đích
    shutil.copy(font_file_path, output_path)
    return True

# --- ROUTES CHÍNH ---

@app.route('/')
def home():
    versions = get_data()
    return render_template('index.html', versions=versions)

# --- AUTHENTICATION ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('font_tool'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Tên đăng nhập đã tồn tại.', 'danger')
            return redirect(url_for('register'))
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, password=hashed_password)
        db.session.add(user)
        db.session.commit()
        flash('Tạo tài khoản thành công! Tặng 2 lượt dùng thử.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('font_tool'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('font_tool'))
        else:
            flash('Sai thông tin đăng nhập.', 'danger')
    return render_template('login.html')

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
    # Kiểm tra file upload
    if 'font_file' not in request.files:
        flash('Vui lòng chọn file font (.ttf)', 'danger')
        return redirect(url_for('font_tool'))
    
    file = request.files['font_file']
    if file.filename == '':
        flash('Chưa chọn file', 'danger')
        return redirect(url_for('font_tool'))

    # --- TRƯỜNG HỢP 1: KHÁCH VÃNG LAI (10K) ---
    if not current_user.is_authenticated:
        guest_id = session.get('guest_session_id')
        payment_code = f"WWM {guest_id}"
        
        # Tìm xem có giao dịch nào thành công với mã này chưa?
        # Điều kiện: Status = success VÀ Amount >= 10000 VÀ chưa được dùng (Optional logic)
        transaction = Transaction.query.filter_by(
            description=payment_code, 
            status='success'
        ).order_by(Transaction.date_created.desc()).first()

        # Logic check mã DEMO để test (Xóa khi chạy thật)
        is_demo = request.form.get('payment_code_input') == "DEMO10K"

        if transaction or is_demo:
            # OK -> Xử lý file
            with tempfile.TemporaryDirectory() as temp_dir:
                input_path = os.path.join(temp_dir, file.filename)
                output_path = os.path.join(temp_dir, f"Patched_{file.filename}")
                file.save(input_path)
                
                # Gọi hàm xử lý font
                process_font_logic(input_path, output_path)
                
                # Nếu là giao dịch thật, có thể update status để không dùng lại mã này (tuỳ logic)
                # transaction.status = 'used'
                # db.session.commit()

                return send_file(output_path, as_attachment=True)
        else:
            flash('Chưa nhận được thanh toán. Vui lòng quét mã và đợi 1 phút.', 'warning')
            return redirect(url_for('font_tool'))

    # --- TRƯỜNG HỢP 2: THÀNH VIÊN (5K) ---
    else:
        cost = 5000
        can_process = False
        
        if current_user.free_trials > 0:
            current_user.free_trials -= 1
            can_process = True
            flash(f'Đã dùng 1 lượt miễn phí. Còn lại: {current_user.free_trials}', 'success')
        elif current_user.balance >= cost:
            current_user.balance -= cost
            can_process = True
            flash(f'Đã trừ {cost}đ. Số dư mới: {current_user.balance}đ', 'success')
        else:
            flash('Số dư không đủ. Vui lòng nạp thêm.', 'danger')
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
        # Dữ liệu mẫu SePay: {'gateway': 'MBBank', 'transferAmount': 10000, 'content': 'WWM 5 ...'}
        
        content = data.get('content', '')
        amount = data.get('transferAmount', 0)
        
        if not content: return jsonify({'success': False}), 400

        # LOGIC 1: NẠP TIỀN THÀNH VIÊN (WWM 123)
        user_match = re.search(r'WWM\s+(\d+)', content, re.IGNORECASE)
        if user_match:
            user_id = int(user_match.group(1))
            user = User.query.get(user_id)
            if user:
                user.balance += int(amount)
                new_trans = Transaction(amount=amount, description=content, status='success', user_id=user.id)
                db.session.add(new_trans)
                db.session.commit()
                return jsonify({'success': True, 'msg': 'User topup'}), 200

        # LOGIC 2: KHÁCH VÃNG LAI (WWM A1B2C3D4)
        guest_match = re.search(r'WWM\s+([A-Z0-9]{8})', content, re.IGNORECASE)
        if guest_match:
            guest_id = guest_match.group(1)
            # Lưu giao dịch vào DB để khách check
            new_trans = Transaction(amount=amount, description=f"WWM {guest_id}", status='success', guest_id=guest_id)
            db.session.add(new_trans)
            db.session.commit()
            return jsonify({'success': True, 'msg': 'Guest payment recorded'}), 200

        return jsonify({'success': True, 'msg': 'No match'}), 200

    except Exception as e:
        print(f"Webhook Error: {e}")
        return jsonify({'success': False}), 500

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

with app.app_context():
    try:
        db.create_all()
        print("✅ Đã khởi tạo bảng Database thành công!")
    except Exception as e:
        print(f"⚠️ Lỗi tạo bảng (Có thể do đã tồn tại): {e}")

if __name__ == '__main__':
    app.run(debug=True)
