from flask import Flask, render_template, request, redirect, url_for, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import pandas as pd
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'khoa_bi_mat_cua_ban_123456' # Đổi cái này nhé
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///site.db' # Database file
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

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

# --- CẤU HÌNH SHEET (CODE CŨ) ---
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSn30TYj3B8mmJAPGzmChZjuykpUKB5wumrcoMEJ1TmnXknl4-bYd6cD7m78KREZt65v5snH2uXMqiR/pub?output=csv"

def get_data():
    try:
        df = pd.read_csv(SHEET_URL, dtype=str)
        df.columns = df.columns.str.lower().str.strip()
        df = df.dropna(subset=['platform'])
        df = df.fillna("")
        return df.to_dict('records')
    except: return []

# --- ROUTE TRANG CHỦ (GIỮ NGUYÊN) ---
@app.route('/')
def home():
    versions = get_data()
    return render_template('index.html', versions=versions)

# --- ROUTE AUTHENTICATION ---
@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated: return redirect(url_for('font_tool'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        user = User(username=username, password=hashed_password)
        try:
            db.session.add(user)
            db.session.commit()
            flash('Tạo tài khoản thành công! Bạn được tặng 2 lượt dùng thử.', 'success')
            return redirect(url_for('login'))
        except:
            flash('Tên đăng nhập đã tồn tại.', 'danger')
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
    return redirect(url_for('home'))

# --- ROUTE TOOL TẠO FONT (LOGIC MỚI) ---
@app.route('/tools/font-editor', methods=['GET', 'POST'])
def font_tool():
    return render_template('font_tool.html')

@app.route('/process-font', methods=['POST'])
def process_font():
    # 1. Xử lý cho người dùng Vãng lai (Thanh toán QR - 10k)
    if not current_user.is_authenticated:
        payment_code = request.form.get('payment_code')
        # Ở đây bạn cần logic check mã giao dịch thật. 
        # Demo: Nếu nhập "DEMO10K" thì cho qua.
        if payment_code == "DEMO10K": 
            flash('Thanh toán QR thành công! Đang tạo font...', 'success')
            # Gọi hàm xử lý font ở đây...
            return redirect(url_for('font_tool'))
        else:
            flash('Mã giao dịch không đúng hoặc chưa thanh toán.', 'danger')
            return redirect(url_for('font_tool'))

    # 2. Xử lý cho Thành viên (Trừ ví - 5k)
    else:
        cost = 5000
        if current_user.free_trials > 0:
            current_user.free_trials -= 1
            db.session.commit()
            flash(f'Sử dụng lượt miễn phí. Còn lại: {current_user.free_trials}', 'success')
            # Gọi hàm xử lý font ở đây...
        elif current_user.balance >= cost:
            current_user.balance -= cost
            db.session.commit()
            flash(f'Đã trừ {cost}đ. Số dư mới: {current_user.balance}đ', 'success')
            # Gọi hàm xử lý font ở đây...
        else:
            flash('Số dư không đủ. Vui lòng nạp thêm tiền.', 'warning')
            return redirect(url_for('profile'))
            
    return redirect(url_for('font_tool'))

# --- ROUTE PROFILE & NẠP TIỀN ---
@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html')

@app.route('/deposit', methods=['POST'])
@login_required
def deposit():
    # Demo nạp tiền: Người dùng nhập mã, Admin duyệt tay hoặc Auto
    # Demo: Nhập "NAP50K" được cộng 50k
    code = request.form.get('deposit_code')
    if code == "NAP50K":
        current_user.balance += 50000
        db.session.commit()
        flash('Nạp thành công 50.000đ!', 'success')
    else:
        flash('Mã nạp không hợp lệ hoặc đang chờ duyệt.', 'warning')
    return redirect(url_for('profile'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all() # Tạo database nếu chưa có
    app.run(debug=True)
