from flask import Flask, render_template
import pandas as pd

app = Flask(__name__)

# --- CẤU HÌNH ---
# Thay link CSV Google Sheet của bạn vào đây
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSn30TYj3B8mmJAPGzmChZjuykpUKB5wumrcoMEJ1TmnXknl4-bYd6cD7m78KREZt65v5snH2uXMqiR/pub?output=csv"

def get_data():
    try:
        # Đọc dữ liệu từ Google Sheet
        df = pd.read_csv(SHEET_URL, dtype=str)
        
        # Chuẩn hóa dữ liệu
        df.columns = df.columns.str.lower().str.strip()
        df = df.dropna(subset=['platform'])
        df = df.fillna("")
        
        # Chuyển thành danh sách Dictionary để dễ xử lý bên HTML
        # Kết quả: [{'platform': 'Steam', 'version_name': 'v1', ...}, {...}]
        return df.to_dict('records')
    except Exception as e:
        print(f"Lỗi đọc dữ liệu: {e}")
        return []

@app.route('/')
def home():
    # Lấy dữ liệu mới nhất mỗi khi người dùng tải trang
    versions = get_data()
    return render_template('index.html', versions=versions)

if __name__ == '__main__':
    app.run(debug=True)
