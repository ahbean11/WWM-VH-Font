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

# --- CÁC CLASS XỬ LÝ FONT ---
class LauncherPatcher:
    ZH_FONTS = [
        b'HanYiQuanTangShiS.ttf', b'ZHJB-Xiangjiahong_fanti.TTF', b'AaShiSongTi-2.ttf'
    ]
    EUROPEAN_FONTS = [
        b'AlegreyaSans-Medium.ttf', b'AlegreyaSans-Regular.ttf', b'MrsEavSmaCap.ttf'
    ]

    @staticmethod
    def find_font_entries(data):
        entries = []
        target_fonts = LauncherPatcher.ZH_FONTS + LauncherPatcher.EUROPEAN_FONTS
        
        for font_name in target_fonts:
            pos = 0
            while True:
                pos = data.find(font_name, pos)
                if pos == -1: break
                start = max(0, pos - 50)
                end = min(len(data), pos + len(font_name) + 50)
                context = data[start:end]
                if not (b'<File>' in context and b'</File>' in context):
                     entries.append({'type': 'font_raw', 'font_name': font_name, 'position': pos})
                pos += len(font_name)

        pos = 0
        while True:
            pos = data.find(b'<Root>', pos)
            if pos == -1: break
            root_end = data.find(b'</Root>', pos)
            if root_end != -1:
                root_end += len(b'</Root>')
                xml_content = data[pos:root_end]
                if b'<Font>' in xml_content:
                    entries.append({
                        'type': 'xml',
                        'position': pos,
                        'length': len(xml_content),
                        'content': xml_content
                    })
            pos += len(b'<Root>')
        return entries

    @classmethod
    def patch(cls, mpk_path, output_path, font_filename_str="normal.ttf"):
        if not os.path.exists(mpk_path): return False, "File MPK không tồn tại trên server"
        
        print(f"--> [INFO] Đang đọc file: {mpk_path}", flush=True)
        try:
            with open(mpk_path, 'rb') as f:
                data = bytearray(f.read())
            print(f"--> [INFO] Kích thước file: {len(data)/1024/1024:.2f} MB", flush=True)
        except Exception as e:
            return False, f"Lỗi đọc file: {e}"

        new_font_name = font_filename_str.encode('utf-8')
        entries = cls.find_font_entries(data)
        
        if not entries:
            # Check xem có phải file đã patch rồi không?
            if b'NormalFont' in data or b'custom.ttf' in data or b'normal.ttf' in data:
                return False, "File này CÓ VẼ ĐÃ ĐƯỢC PATCH RỒI (Tìm thấy 'normal.ttf' hoặc 'NormalFont'). Vui lòng dùng file gốc chưa sửa."
            return False, "Không tìm thấy dữ liệu Font gốc trong file MPK. Hãy chắc chắn bạn upload đúng file Resources.mpk gốc."

        print(f"--> [INFO] Tìm thấy {len(entries)} vị trí cần sửa.", flush=True)
        replacements = 0
        
        for entry in entries:
            if entry['type'] == 'xml':
                try:
                    old_xml = entry['content']
                    xml_str = old_xml.decode('utf-8', errors='ignore')
                    font_block_pattern = r'(<Font>[\s\S]*?</Font>)'
                    
                    def block_replacer(match):
                        block_content = match.group(1)
                        targets = ['normal text', 'title text', 'art text', 'europe', 'zh_tw']
                        is_target = any(t in block_content.lower() for t in targets)
                        
                        if not is_target:
                            for f_bytes in (cls.ZH_FONTS + cls.EUROPEAN_FONTS):
                                if f_bytes.decode('utf-8', errors='ignore') in block_content:
                                    is_target = True; break

                        if is_target:
                            block_content = re.sub(r'<File>([^<]+)</File>', f'<File>{font_filename_str}</File>', block_content)
                            block_content = re.sub(r'<Name>([^<]+)</Name>', f'<Name>NormalFont</Name>', block_content)
                        return block_content

                    new_xml_str = re.sub(font_block_pattern, block_replacer, xml_str)
                    new_xml = new_xml_str.encode('utf-8')
                    
                    start = entry['position']
                    length = entry['length']
                    
                    if len(new_xml) <= length:
                        padding_len = length - len(new_xml)
                        padded = new_xml + b' ' * padding_len 
                        data[start : start+length] = padded
                        replacements += 1
                except: continue

            elif entry['type'] == 'font_raw':
                pos = entry['position']
                old_len = len(entry['font_name'])
                expand_end = pos + old_len
                while expand_end < len(data) and data[expand_end] == 0:
                    expand_end += 1
                available_len = expand_end - pos
                
                if len(new_font_name) <= available_len:
                    padded = new_font_name + b'\x00' * (available_len - len(new_font_name))
                    data[pos : expand_end] = padded
                    replacements += 1

        if replacements > 0:
            print(f"--> [INFO] Đã thay thế {replacements} vị trí. Đang ghi file...", flush=True)
            try:
                with open(output_path, 'wb') as f:
                    f.write(data)
                return True, f"Thành công! Patch {replacements} vị trí."
            except OSError as e:
                return False, f"Lỗi ghi đĩa (Ổ cứng đầy?): {e}"
        
        return False, "Không có thay đổi nào được thực hiện (Logic thay thế không khớp)."


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


# --- CHỨC NĂNG PATCH FONT CHO LAUNCHER ---
@app.route('/patch-font-launcher', methods=['GET', 'POST'])
@login_required
def patch_font_launcher():
    # Kiểm tra quyền truy cập - chỉ VIP hoặc người dùng có lượt dùng thử
    can_access = False
    
    # VIP donors can use unlimited times
    if current_user.is_donor:
        can_access = True
        flash('Xin chào Nhà tài trợ VIP! Bạn có thể sử dụng chức năng patch font không giới hạn.', 'success')
    # Regular members get 1 free trial
    elif current_user.free_trials > 0:
        can_access = True
        flash(f'Bạn có 1 lần dùng thử miễn phí. Lượt còn lại: {current_user.free_trials}', 'info')
    else:
        flash('Bạn đã hết lượt dùng thử. Hãy trở thành Nhà tài trợ VIP để sử dụng không giới hạn!', 'warning')
        return redirect(url_for('font_tool'))
    
    if request.method == 'POST' and can_access:
        # Kiểm tra file upload
        if 'mpk_file' not in request.files or 'font_file' not in request.files:
            flash('Vui lòng chọn đủ file MPK và file Font!', 'danger')
            return redirect(request.url)
            
        mpk = request.files['mpk_file']
        font = request.files['font_file']
        
        if mpk.filename == '' or font.filename == '':
            flash('Vui lòng chọn đủ file MPK và file Font!', 'danger')
            return redirect(request.url)
        
        print("--> [REQ] Nhận được yêu cầu patch...", flush=True)
        temp_dir = None
        try:
            # Tự động tìm ổ đĩa trống để tạo temp (tránh lỗi ổ C đầy)
            temp_dir = tempfile.mkdtemp()
            
            from werkzeug.utils import secure_filename
            mpk_name = secure_filename(mpk.filename)
            
            mpk_path = os.path.join(temp_dir, mpk_name)
            print(f"--> [IO] Đang lưu file tạm: {mpk_path}", flush=True)
            mpk.save(mpk_path)
            
            target_font_name = "normal.ttf" 
            font_path = os.path.join(temp_dir, target_font_name)
            font.save(font_path)
            
            output_mpk_path = os.path.join(temp_dir, f"Patched_{mpk_name}")
            
            # Gọi hàm Patch
            success, msg = LauncherPatcher.patch(mpk_path, output_mpk_path, target_font_name)
            
            if success:
                import zipfile
                zip_filename = "WWM_Launcher_Patch.zip"
                zip_path = os.path.join(temp_dir, zip_filename)
                
                print("--> [ZIP] Đang nén file...", flush=True)
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(output_mpk_path, arcname="Resources.mpk")
                    zipf.write(font_path, arcname="Engine/Content/Fonts/normal.ttf")
                    
                    # Thêm các file assets nếu có
                    ASSETS_DIR = os.path.join(os.path.dirname(__file__), 'patch-font', 'assets')
                    if os.path.exists(ASSETS_DIR):
                        for filename in ['Fonts.xml', 'title.ttf', 'art.ttf']:
                            file_src = os.path.join(ASSETS_DIR, filename)
                            if os.path.exists(file_src):
                                zipf.write(file_src, arcname=f"Engine/Content/Fonts/{filename}")
                
                # Giảm số lượt dùng thử nếu là người dùng thường
                if not current_user.is_donor:
                    current_user.free_trials -= 1
                    db.session.commit()
                
                print("--> [DONE] Xử lý xong, đang gửi file về client.", flush=True)
                return send_file(zip_path, as_attachment=True, download_name=zip_filename)
            else:
                print(f"--> [FAIL] Lỗi logic: {msg}", flush=True)
                flash(msg, 'danger')
                return redirect(request.url)
                
        except Exception as e:
            import traceback
            traceback.print_exc()
            flash(f'Lỗi Server: {str(e)}', 'danger')
            return redirect(request.url)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except: pass
    
    return render_template('patch_font_launcher.html', 
                          is_vip=current_user.is_donor,
                          free_trials=current_user.free_trials)

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
