import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

# Load biến môi trường (cho chạy Local)
load_dotenv()

app = Flask(__name__)

# --- CẤU HÌNH BẢO MẬT & DATABASE ---
# 1. Secret Key (Lấy từ biến môi trường, fallback key test)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev_key_khong_an_toan_123')

# 2. Database URI (Xử lý PostgreSQL trên Render)
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # Fix lỗi dialect của Render (Render trả về postgres:// nhưng SQLAlchemy cần postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # Fallback chạy local bằng SQLite nếu chưa cấu hình
    print("⚠️ Không tìm thấy DATABASE_URL, đang chạy chế độ SQLite (Local)")
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db'

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
    balance = db.Column(db.Integer, default=0) # Số dư ví
    free_trials = db.Column(db.Integer, default=2) # Lượt miễn phí

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- CẤU HÌNH SHEET ---
SHEET_URL = os.environ.get('SHEET_URL')

def get_data():
    if not SHEET_URL:
        return []
    try:
        df = pd.read_csv(SHEET_URL, dtype=str)
        df.columns = df.columns.str.lower().str.strip()
        df = df.dropna(subset=['platform'])
        df = df.fillna("")
        return df.to_dict('records')
    except Exception as e:
        print(f"Lỗi đọc Sheet: {e}")
        return []

# --- ROUTES ---

@app.route('/')
def home():
    versions = get_data()
    return render_template('index.html', versions=versions)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('font_tool'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Check user tồn tại
        existing_user = User.query.filter_by(username=username).first()
        if existing_user:
            flash('Tên đăng nhập đã tồn tại. Vui lòng chọn tên khác.', 'danger')
            return redirect(url_for('register'))
            
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, password=hashed_password)
        
        try:
            db.session.add(user)
            db.session.commit()
            flash('Tạo tài khoản thành công! Bạn được tặng 2 lượt dùng thử.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Lỗi hệ thống: {e}', 'danger')
            
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
            flash('Sai tên đăng nhập hoặc mật khẩu.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('Đã đăng xuất thành công.', 'info')
    return redirect(url_for('home'))

@app.route('/tools/font-editor', methods=['GET', 'POST'])
def font_tool():
    return render_template('font_tool.html')

@app.route('/process-font', methods=['POST'])
def process_font():
    # 1. Khách vãng lai (QR Code)
    if not current_user.is_authenticated:
        payment_code = request.form.get('payment_code')
        # Logic check mã (Cần thay bằng check thật hoặc API ngân hàng)
        if payment_code and payment_code.upper() == "DEMO10K": 
            flash('Thanh toán QR thành công! Đang xử lý font...', 'success')
            # [Place logic tạo font ở đây]
        else:
            flash('Mã giao dịch không đúng.', 'danger')
    
    # 2. Thành viên (Trừ ví)
    else:
        cost = 5000
        if current_user.free_trials > 0:
            current_user.free_trials -= 1
            db.session.commit()
            flash(f'Đã dùng 1 lượt miễn phí. Còn lại: {current_user.free_trials}', 'success')
            # [Place logic tạo font ở đây]
        elif current_user.balance >= cost:
            current_user.balance -= cost
            db.session.commit()
            flash(f'Đã trừ {cost}đ. Số dư mới: {current_user.balance}đ', 'success')
            # [Place logic tạo font ở đây]
        else:
            flash('Số dư không đủ (Cần 5.000đ). Vui lòng nạp thêm.', 'warning')
            return redirect(url_for('profile'))
            
    return redirect(url_for('font_tool'))

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

@app.route('/deposit', methods=['POST'])
@login_required
def deposit():
    # Logic nạp tiền demo
    code = request.form.get('deposit_code')
    if code and code.upper() == "NAP50K":
        current_user.balance += 50000
        db.session.commit()
        flash('Nạp thành công 50.000đ!', 'success')
    else:
        flash('Mã nạp không hợp lệ.', 'danger')
    return redirect(url_for('profile'))

if __name__ == '__main__':
    # Tự động tạo bảng Database nếu chưa có (Chạy lần đầu)
    with app.app_context():
        db.create_all()
    app.run(debug=True)
