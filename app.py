import os
import pandas as pd
import requests
import shutil
import tempfile
import struct
import re
import sys
import hashlib
from io import BytesIO
import base64
import uuid # Dùng để tạo ID cho khách vãng lai
import time
import random
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

# XỬ LÝ DATABASE (CHỈ DÙNG POSTGRESQL)
database_url = os.environ.get('DATABASE_URL')

if not database_url:
    # Báo lỗi ngay lập tức nếu không tìm thấy biến môi trường, tránh dùng nhầm SQLite
    raise ValueError("LỖI: Chưa cấu hình biến môi trường 'DATABASE_URL'. Bắt buộc dùng PostgreSQL.")

# Fix lỗi tương thích cho thư viện SQLAlchemy đời mới (postgres:// -> postgresql://)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

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
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(100), unique=True)
    email = db.Column(db.String(100))
    username = db.Column(db.String(100))
    free_trials = db.Column(db.Integer, default=1)
    is_donor = db.Column(db.Boolean, default=False)
    # Thêm trường để lưu tổng số tiền donate
    total_donated = db.Column(db.Integer, default=0)

# Bảng lưu đơn hàng (Transactions)
class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_code = db.Column(db.String(50), unique=True)  # Mã đơn hàng (ví dụ: DH1234)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    amount = db.Column(db.Integer)  # Số tiền
    status = db.Column(db.String(20), default='PENDING')  # PENDING, SUCCESS, CANCELLED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Quan hệ với User
    user = db.relationship('User', backref=db.backref('transactions', lazy=True))

# Bảng lưu lịch sử donate (giữ lại để tương thích ngược)
class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    amount = db.Column(db.Integer)  # Số tiền donate (VNĐ)
    transaction_id = db.Column(db.String(100), unique=True)  # ID giao dịch từ SePay
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    # Quan hệ với User
    user = db.relationship('User', backref=db.backref('donations', lazy=True))

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))
    # Bỏ đoạn try/except db.create_all() đi, nó không tốt cho production.
    # Việc tạo bảng nên chạy 1 lần lúc deploy bằng lệnh riêng hoặc để trong if __name__ == '__main__'

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
    Process font files according to requirements:
    - Rename uploaded TTF file to normal.ttf
    - Get title.ttf and art.ttf from /assets/ directory
    - Package everything in the correct directory structure
    """
    import os
    import zipfile
    from pathlib import Path
    
    try:
        # Create temporary directory for processing
        temp_dir = os.path.dirname(output_path)
        assets_dir = os.path.join(os.path.dirname(__file__), 'patch-font', 'assets')
        
        # Create directory structure
        engine_dir = os.path.join(temp_dir, 'Engine')
        content_dir = os.path.join(engine_dir, 'Content')
        fonts_dir = os.path.join(content_dir, 'Fonts')
        os.makedirs(fonts_dir, exist_ok=True)
        
        # 1. Rename uploaded TTF file to normal.ttf
        normal_ttf_path = os.path.join(fonts_dir, 'normal.ttf')
        shutil.copy(font_file_path, normal_ttf_path)
        
        # 2. Copy title.ttf and art.ttf from assets directory
        title_src = os.path.join(assets_dir, 'title.ttf')
        art_src = os.path.join(assets_dir, 'art.ttf')
        
        title_dst = os.path.join(fonts_dir, 'title.ttf')
        art_dst = os.path.join(fonts_dir, 'art.ttf')
        
        # Copy if files exist in assets
        if os.path.exists(title_src):
            shutil.copy(title_src, title_dst)
        else:
            # Fallback: copy normal.ttf as title.ttf if title.ttf not found
            shutil.copy(normal_ttf_path, title_dst)
            
        if os.path.exists(art_src):
            shutil.copy(art_src, art_dst)
        else:
            # Fallback: copy normal.ttf as art.ttf if art.ttf not found
            shutil.copy(normal_ttf_path, art_dst)
        
        # 3. Create Fonts.xml file
        fonts_xml_content = '''<?xml version="1.0" encoding="UTF-8"?>
<Root>
	<Font><Name>NormalFont</Name><File>normal.ttf</File></Font>
	<Font><Name>TitleFont</Name><File>title.ttf</File></Font>
	<Font><Name>ArtFont</Name><File>art.ttf</File></Font>
</Root>'''
        
        fonts_xml_path = os.path.join(fonts_dir, 'Fonts.xml')
        with open(fonts_xml_path, 'w', encoding='utf-8') as f:
            f.write(fonts_xml_content)
        
        # 4. Create Resources.mpk placeholder
        resources_path = os.path.join(temp_dir, 'Resources.mpk')
        with open(resources_path, 'w') as f:
            f.write('This is a placeholder for Resources.mpk')
        
        # 5. Create ZIP file with correct structure
        with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # Add Resources.mpk
            zipf.write(resources_path, 'Resources.mpk')
            
            # Add font files and Fonts.xml
            for root, dirs, files in os.walk(engine_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_path = os.path.relpath(file_path, temp_dir)
                    zipf.write(file_path, arc_path)
        
        return True
    except Exception as e:
        print(f"Error in process_font_logic: {e}")
        return False

# --- ROUTES CHÍNH ---
@app.route('/tutorial')
def tutorial():
    return render_template('tutorial.html')
@app.route('/')
def home():
    versions = get_data()
    return render_template('index.html', versions=versions)

# --- AUTHENTICATION ---
# Removed register route as requested - only Google login is allowed now

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated: return redirect(url_for('profile'))
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
            return redirect(url_for('profile'))
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
            # Đổi tên file output thành WWM_VietHoa_Full.zip thay vì Patched_{filename}
            output_path = os.path.join(temp_dir, "WWM_VietHoa_Full.zip")
            file.save(input_path)
            
            if process_font_logic(input_path, output_path):
                return send_file(output_path, as_attachment=True)
            else:
                flash('Có lỗi xảy ra trong quá trình xử lý font.', 'danger')
                return redirect(url_for('font_tool'))
    
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
def handle_sepay_webhook():
    # Kiểm tra API Key trong header
    auth_header = request.headers.get('Authorization')
    expected_api_key = os.getenv('SEPAY_API_KEY')
    
    if not auth_header or not expected_api_key:
        return jsonify({'success': False, 'message': 'Missing authorization header or API key not configured'}), 401
    
    # Kiểm tra định dạng Authorization: Apikey API_KEY_CUA_BAN
    if not auth_header.startswith('Apikey '):
        return jsonify({'success': False, 'message': 'Invalid authorization header format'}), 401
    
    provided_api_key = auth_header.split(' ')[1]
    if provided_api_key != expected_api_key:
        return jsonify({'success': False, 'message': 'Invalid API key'}), 401
    
    try:
        data = request.json
        # Dữ liệu mẫu SePay: {'gateway': 'MBBank', 'transferAmount': 10000, 'description': 'DH1234 chuyen khoan mua vip', 'id': 'TRANS123', 'customerEmail': 'user@example.com'}
        
        description = data.get('description', '')  # Nội dung CK ví dụ: "DH1234 chuyen khoan mua vip"
        real_amount = data.get('transferAmount', 0)  # Số tiền thực nhận
        sepay_trans_id = data.get('id', '')  # ID giao dịch phía ngân hàng (để chống trùng)
        customer_email = data.get('customerEmail', '')  # Lấy email từ SePay
        
        if not description: 
            return jsonify({'success': False, 'message': 'Không có nội dung chuyển khoản'}), 400

        # 2. Tìm Mã đơn hàng (DH1234) trong nội dung description
        import re
        order_code_match = re.search(r'(DH\d+)', description)
        if not order_code_match:
            # Nếu không tìm thấy mã đơn hàng, xử lý theo logic cũ
            return process_old_donation_logic(data)
            
        order_code = order_code_match.group(1)

        # 3. Query Database tìm đơn hàng
        transaction = Transaction.query.filter_by(order_code=order_code).first()

        # 4. Kiểm tra điều kiện an toàn
        if not transaction:
            return jsonify({'success': False, 'message': 'Đơn hàng không tồn tại'}), 200
        
        if transaction.status == 'SUCCESS':
            return jsonify({'success': False, 'message': 'Giao dịch này đã xử lý rồi'}), 200  # Chống xử lý lặp lại (Idempotency)

        if real_amount < transaction.amount:
            return jsonify({'success': False, 'message': 'Chuyển thiếu tiền'}), 200  # Hoặc xử lý treo đơn

        # 5. THỰC HIỆN CỘNG TIỀN & SET VIP (Transaction Atomic)
        try:
            # A. Cập nhật trạng thái giao dịch
            transaction.status = 'SUCCESS'
            transaction.updated_at = datetime.utcnow()

            # B. Cộng tiền vào ví user
            user = User.query.get(transaction.user_id)
            if user:
                user.total_donated += real_amount
                
                # C. Set VIP (Nếu gói nạp có logic set VIP)
                if real_amount >= 10000:  # Ví dụ nạp > 10k được VIP
                    user.is_donor = True
                
                # Tạo bản ghi donate để lưu lịch sử
                donation = Donation(
                    user_id=transaction.user_id,
                    amount=real_amount,
                    transaction_id=sepay_trans_id
                )
                db.session.add(donation)
                
                db.session.commit()
                
                return jsonify({"success": True, "message": f"Đã cộng tiền cho user {user.id}"}), 200
            else:
                db.session.rollback()
                return jsonify({"success": False, "message": "Không tìm thấy người dùng"}), 200

        except Exception as e:
            # Rollback nếu lỗi DB
            db.session.rollback()
            return jsonify({"success": False, "message": f"Lỗi khi xử lý giao dịch: {str(e)}"}), 500
            
    except Exception as e:
        return jsonify({"success": False, "message": f"Lỗi hệ thống: {str(e)}"}), 500

# Hàm xử lý logic cũ cho các giao dịch không theo định dạng mới
def process_old_donation_logic(data):
    """Xử lý logic cũ cho các giao dịch không theo định dạng mới"""
    try:
        content = data.get('description', '')  # Sử dụng description thay cho content
        amount = data.get('transferAmount', 0)
        transaction_id = data.get('id', '')  # Sử dụng id thay cho transactionId
        customer_email = data.get('customerEmail', '')
        
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
                    # Kiểm tra xem giao dịch này đã được xử lý chưa
                    existing_donation = Donation.query.filter_by(transaction_id=transaction_id).first()
                    if not existing_donation:
                        # Tạo bản ghi donate mới
                        donation = Donation(
                            user_id=user.id,
                            amount=int(amount),
                            transaction_id=transaction_id
                        )
                        db.session.add(donation)
                        
                        # Cập nhật tổng số tiền donate của user
                        user.total_donated += int(amount)
                        
                        # Set donor status nếu donate từ 10.000đ trở lên
                        if user.total_donated >= 10000:
                            user.is_donor = True
                            
                        db.session.commit()
                        return jsonify({'success': True, 'msg': 'User donation processed'}), 200
                    else:
                        return jsonify({'success': False, 'msg': 'Transaction already processed'}), 400

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
                # Kiểm tra xem giao dịch này đã được xử lý chưa
                existing_donation = Donation.query.filter_by(transaction_id=transaction_id).first()
                if not existing_donation:
                    # Tạo bản ghi donate mới
                    donation = Donation(
                        user_id=matched_user.id,
                        amount=int(amount),
                        transaction_id=transaction_id
                    )
                    db.session.add(donation)
                    
                    # Cập nhật tổng số tiền donate của user
                    matched_user.total_donated += int(amount)
                    
                    # Set donor status nếu donate từ 10.000đ trở lên
                    if matched_user.total_donated >= 10000:
                        matched_user.is_donor = True
                    
                    db.session.commit()
                    return jsonify({'success': True, 'msg': 'Existing user new donation processed'}), 200
                else:
                    return jsonify({'success': False, 'msg': 'Transaction already processed'}), 400
            else:
                # Lưu transaction cho user mới, sẽ xử lý khi họ đăng nhập
                new_trans = Transaction(amount=amount, description=content, status='pending', guest_id=email_hash)
                db.session.add(new_trans)
                db.session.commit()
                return jsonify({'success': True, 'msg': 'New user donation recorded, pending registration'}), 200

        return jsonify({'success': True, 'msg': 'No matching user found'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Lỗi khi xử lý logic cũ: {str(e)}'}), 500

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

# --- API để trừ lượt dùng thử ---
@app.route('/api/use-trial', methods=['POST'])
@login_required
def use_trial():
    """API endpoint để trừ một lượt dùng thử của người dùng"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Người dùng chưa đăng nhập'}), 401
    
    # Chỉ trừ lượt nếu người dùng không phải là donor
    if not current_user.is_donor and current_user.free_trials > 0:
        current_user.free_trials -= 1
        db.session.commit()
        return jsonify({
            'success': True, 
            'message': f'Đã dùng 1 lượt miễn phí. Còn lại: {current_user.free_trials}',
            'remaining_trials': current_user.free_trials,
            'is_donor': current_user.is_donor
        })
    elif current_user.is_donor:
        return jsonify({
            'success': True, 
            'message': 'Người dùng là VIP, không cần trừ lượt',
            'remaining_trials': current_user.free_trials,
            'is_donor': current_user.is_donor
        })
    else:
        return jsonify({
            'success': False, 
            'message': 'Người dùng đã hết lượt dùng thử',
            'remaining_trials': 0,
            'is_donor': current_user.is_donor
        }), 400

# --- API để kiểm tra trạng thái dùng thử ---
@app.route('/api/check-trial', methods=['GET'])
@login_required
def check_trial():
    """API endpoint để kiểm tra trạng thái dùng thử của người dùng"""
    if not current_user.is_authenticated:
        return jsonify({'success': False, 'message': 'Người dùng chưa đăng nhập'}), 401
    
    return jsonify({
        'success': True,
        'is_donor': current_user.is_donor,
        'remaining_trials': current_user.free_trials,
        'can_use_trial': current_user.is_donor or current_user.free_trials > 0
    })

# --- API tạo đơn hàng ---
@app.route('/api/create-deposit', methods=['POST'])
@login_required
def create_deposit():
    """Tạo đơn hàng nạp tiền mới cho người dùng"""
    try:
        data = request.json
        amount = data.get('amount')
        
        if not amount or amount < 10000:
            return jsonify({'success': False, 'message': 'Số tiền phải lớn hơn hoặc bằng 10.000đ'}), 400
            
        # Tạo mã đơn hàng duy nhất
        order_code = f"DH{int(time.time())}{random.randint(100, 999)}"
        
        # Tạo giao dịch mới
        transaction = Transaction(
            order_code=order_code,
            user_id=current_user.id,
            amount=amount,
            status='PENDING'
        )
        
        db.session.add(transaction)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'order_code': order_code,
            'amount': amount,
            'message': 'Đơn hàng đã được tạo thành công'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': f'Lỗi khi tạo đơn hàng: {str(e)}'}), 500

# --- API kiểm tra trạng thái đơn hàng ---
@app.route('/api/check-status/<order_code>')
@login_required
def check_transaction_status(order_code):
    """Kiểm tra trạng thái của giao dịch"""
    try:
        # Tìm giao dịch theo mã
        transaction = Transaction.query.filter_by(order_code=order_code, user_id=current_user.id).first()
        
        if not transaction:
            return jsonify({'success': False, 'message': 'Không tìm thấy giao dịch'}), 404
            
        # Trả về thông tin giao dịch
        return jsonify({
            'success': True,
            'order_code': transaction.order_code,
            'amount': transaction.amount,
            'status': transaction.status,
            'created_at': transaction.created_at.isoformat() if transaction.created_at else None,
            'updated_at': transaction.updated_at.isoformat() if transaction.updated_at else None
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'Lỗi khi kiểm tra giao dịch: {str(e)}'}), 500

# --- API tạo mã QR cho donate ---
@app.route('/api/generate-qr')
@login_required
def generate_qr():
    """Tạo mã QR cho donate với nội dung chứa user ID và email hash"""
    try:
        # Tạo nội dung cho QR code: WWM <user_id> <email_hash>
        email_hash = hashlib.md5(current_user.email.lower().encode()).hexdigest()
        content = f"WWM {current_user.id} {email_hash}"
        
        # Tạo mã QR
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(content)
        qr.make(fit=True)
        
        # Tạo ảnh QR
        img = qr.make_image(fill_color="black", back_color="white")
        
        # Chuyển đổi ảnh sang base64 để trả về
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        img_str = base64.b64encode(buffer.getvalue()).decode()
        
        return jsonify({
            'success': True,
            'qr_code': f'data:image/png;base64,{img_str}',
            'content': content
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# --- API lấy top donor ---
@app.route('/api/top-donors')
def top_donors():
    """Lấy danh sách top donor để hiển thị trên trang chủ"""
    try:
        # Lấy top 3 donor có tổng số tiền donate cao nhất
        top_donors = User.query.filter(User.total_donated > 0)\
                              .order_by(User.total_donated.desc())\
                              .limit(3)\
                              .all()
        
        # Format dữ liệu để trả về
        donors_data = []
        for i, user in enumerate(top_donors):
            # Che dấu một phần email để bảo vệ privacy
            email_parts = user.email.split('@')
            if len(email_parts) == 2:
                hidden_email = email_parts[0][:4] + '****@' + email_parts[1]
            else:
                hidden_email = '****@****'
                
            donors_data.append({
                'rank': i + 1,
                'email': hidden_email,
                'total_donated': user.total_donated
            })
        
        return jsonify({
            'success': True,
            'top_donors': donors_data
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Hàm tạo bảng tự động (chạy được cả trên Gunicorn/Render)
def create_tables():
    with app.app_context():
        db.create_all()
        # Kiểm tra xem có cần tạo dữ liệu mẫu hay không ở đây

# Gọi hàm tạo bảng ngay khi import app (để đảm bảo bảng luôn được tạo trên server)
create_tables()

if __name__ == '__main__':
    app.run(debug=True)
