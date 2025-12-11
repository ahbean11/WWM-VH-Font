import streamlit as st
import pandas as pd
import requests

# --- CẤU HÌNH TRANG (Phải để đầu tiên) ---
st.set_page_config(
    page_title="WWM Việt Hóa Download",
    page_icon="⚔️",
    layout="centered"
)

# --- CSS ẨN GIAO DIỆN (HEADER, FOOTER, MENU) ---
hide_ui_style = """
<style>
    /* Ẩn Main Menu (Hamburger ở góc phải) */
    #MainMenu {visibility: hidden;}
    /* Ẩn Footer (Dòng Hosted with Streamlit) */
    footer {visibility: hidden;}
    /* Ẩn Header (Thanh màu trên cùng) */
    header {visibility: hidden;}
    /* Ẩn nút Deploy */
    .stDeployButton {display:none;}
    /* Ẩn liên kết GitHub */
    a[href^="https://github.com"] {display: none !important;}
    /* Ẩn nút Viewer Badge */
    div[data-testid="stStatusWidget"] {visibility: hidden;}
</style>
"""
st.markdown(hide_ui_style, unsafe_allow_html=True)

# --- CẤU HÌNH DATABASE (GOOGLE SHEETS) ---
# Link CSV Google Sheet của bạn
SHEET_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vSn30TYj3B8mmJAPGzmChZjuykpUKB5wumrcoMEJ1TmnXknl4-bYd6cD7m78KREZt65v5snH2uXMqiR/pub?output=csv"

# Hàm load dữ liệu (Cache 60 giây)
@st.cache_data(ttl=60)
def load_data():
    try:
        # Đọc CSV, ép kiểu tất cả về string
        df = pd.read_csv(SHEET_URL, dtype=str)
        # Chuẩn hóa tên cột
        df.columns = df.columns.str.lower().str.strip()
        # Xóa dòng trống platform
        df = df.dropna(subset=['platform'])
        # Điền chuỗi rỗng vào ô trống
        df = df.fillna("")
        return df
    except Exception as e:
        print(f"Lỗi load data: {e}")
        return pd.DataFrame()

def main():
    st.title("⚔️ Tải Bản Việt Hóa - Where Winds Meet")
    st.info('ℹ️ Lưu ý: Đây là các phiên bản việt hoá mình tổng hợp từ cộng đồng. Vui lòng chọn bản phù hợp nhất.')

    # --- PHẦN 1: CHỌN PHIÊN BẢN GAME ---
    st.header("1. Chọn phiên bản game của bạn")
    
    game_type = st.selectbox(
        "Bạn đang chơi game trên nền tảng nào?",
        ("Client NPH (Launcher)", "Steam", "Epic Games")
    )

    selected_platform_key = ""

    if game_type == "Client NPH (Launcher)":
        st.subheader("1.1 Chọn loại Client")
        client_ver = st.radio(
            "Máy bạn đang cài bản nào?",
            ("Phiên bản Standard (Tiêu chuẩn)", "Phiên bản Lite (Nhẹ)"),
            horizontal=True
        )
        if client_ver == "Phiên bản Standard (Tiêu chuẩn)":
            selected_platform_key = "Standard"
        else:
            selected_platform_key = "Lite"
    elif game_type == "Steam":
        selected_platform_key = "Steam"
    elif game_type == "Epic Games":
        selected_platform_key = "Epic"

    # --- PHẦN 2: HIỂN THỊ LINK DOWNLOAD ---
    st.divider()
    st.header(f"2. Danh sách tải về ({selected_platform_key})")
    
    df = load_data()
    
    if not df.empty:
        # Lọc dữ liệu theo Platform
        filtered_df = df[df['platform'].str.strip() == selected_platform_key]

        if not filtered_df.empty:
            st.success(f"🎉 Tìm thấy **{len(filtered_df)}** bản việt hóa:")
            
            for index, row in filtered_df.iterrows():
                # Lấy dữ liệu an toàn
                ver_name = row.get('version_name', 'Không tên').strip()
                link_raw = row.get('link', '').strip()
                note = row.get('note', '').strip()

                with st.container(border=True):
                    c1, c2 = st.columns([3, 1.2])
                    
                    with c1:
                        st.subheader(f"📦 {ver_name}")
                        if note:
                            st.info(f"💡 {note}")
                        else:
                            st.caption("Chưa có ghi chú.")
                            
                    with c2:
                        st.write("") 
                        st.write("")
                        
                        # LOGIC XỬ LÝ LINK
                        if link_raw.lower().startswith('http'):
                            st.link_button(
                                label="⬇️ TẢI VỀ MÁY", 
                                url=link_raw, 
                                type="primary", 
                                use_container_width=True
                            )
                        else:
                            display_text = link_raw if link_raw else "Đang cập nhật"
                            st.button(
                                label=f"🚫 {display_text}", 
                                disabled=True, 
                                use_container_width=True,
                                key=f"btn_disable_{index}"
                            )
        else:
            st.warning(f"😔 Hiện chưa có link tải nào cho phiên bản **{selected_platform_key}**.")
    else:
        st.error("Không kết nối được với danh sách link (Google Sheet).")

    # --- PHẦN 3: HƯỚNG DẪN SỬ DỤNG ---
    st.divider()
    st.header("3. Hướng dẫn cài đặt")
    
    with st.container(border=True):
        st.markdown("""
        **Bước 1: Chọn đúng phiên bản**
        - Chọn đúng link tải ở **Mục 2** tương ứng với phiên bản game bạn đang chơi.
        
        **Bước 2: Giải nén**
        - Sử dụng **WinRAR** để giải nén file ZIP vừa tải về.
        - Sau khi giải nén, bạn sẽ thấy thư mục (Ví dụ: `Client_wwm_standard`).
        
        **Bước 3: Tìm thư mục dữ liệu**
        - Mở thư mục vừa giải nén ra.
        - Bên trong sẽ thấy thư mục tên là `wwm_standard` (hoặc `wwm_lite`...).
        
        **Bước 4: Cài đặt vào Game**
        - Mở thư mục cài đặt game gốc trên máy tính.
        - **Copy** thư mục `wwm_standard` (từ Bước 3).
        - **Paste (Dán)** đè vào thư mục cài đặt game.
        - ⚠️ **QUAN TRỌNG:** Chọn **"Replace the files in the destination" (Ghi đè)**.
        """)

    st.divider()
    st.caption("Admin liên tục cập nhật link mới. F5 để làm mới danh sách.")

if __name__ == "__main__":
    main()
