import os
import re
import shutil
import tempfile
import traceback
import zipfile
import sys
from datetime import datetime
# Thêm jsonify vào import
from flask import Flask, render_template, request, send_file, flash, redirect, jsonify

app = Flask(__name__)
app.secret_key = "test_key_123"

ASSETS_DIR = os.path.join(os.getcwd(), 'assets') 

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
                return False, "File này CÓ VẺ ĐÃ ĐƯỢC PATCH RỒI (Tìm thấy 'normal.ttf' hoặc 'NormalFont'). Vui lòng dùng file gốc chưa sửa."
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

@app.route('/')
def index():
    return render_template('test.html')

@app.route('/test-patch', methods=['POST'])
def test_patch():
    # Kiểm tra file
    if 'mpk_file' not in request.files or 'font_file' not in request.files:
        return jsonify({'error': 'Thiếu file upload!'}), 400
        
    mpk = request.files['mpk_file']
    font = request.files['font_file']
    
    if mpk.filename == '':
        return jsonify({'error': 'Chưa chọn file MPK!'}), 400

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
            zip_filename = "WWM_Patch_Full.zip"
            zip_path = os.path.join(temp_dir, zip_filename)
            
            print("--> [ZIP] Đang nén file...", flush=True)
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                zipf.write(output_mpk_path, arcname="Resources.mpk")
                zipf.write(font_path, arcname="Engine/Content/Fonts/normal.ttf")
                if os.path.exists(ASSETS_DIR):
                    for filename in ['Fonts.xml', 'title.ttf', 'art.ttf']:
                        file_src = os.path.join(ASSETS_DIR, filename)
                        if os.path.exists(file_src):
                            zipf.write(file_src, arcname=f"Engine/Content/Fonts/{filename}")

            print("--> [DONE] Xử lý xong, đang gửi file về client.", flush=True)
            return send_file(zip_path, as_attachment=True, download_name=zip_filename)
        else:
            print(f"--> [FAIL] Lỗi logic: {msg}", flush=True)
            return jsonify({'error': msg}), 400
            
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': f"Lỗi Server: {str(e)}"}), 500
    finally:
        if temp_dir and os.path.exists(temp_dir):
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except: pass

if __name__ == '__main__':
    app.run(debug=True, port=5000)