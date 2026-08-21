import streamlit as st
from streamlit_calendar import calendar
import datetime
import pandas as pd
import sqlite3
import google.generativeai as genai
from PIL import Image
import json
import re

# ---------------------------------------------------------
# 1. 앱 기본 설정, CSS 모바일 최적화 및 세션 초기화
# ---------------------------------------------------------
st.set_page_config(page_title="Protein Lens", page_icon="🥗", layout="wide")

# 모바일 한 화면에 맞추기 위한 여백 및 글자 크기 조정 CSS
st.markdown("""
    <style>
    /* 전체 여백 최소화 */
    .block-container {
        padding-top: 1rem !important;
        padding-bottom: 0.5rem !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
    /* 모바일 반응형 제목 크기 */
    @media (max-width: 600px) {
        h1, h2 {
            font-size: 1.4rem !important;
            margin-bottom: 0.2rem !important;
        }
    }
    </style>
""", unsafe_allow_html=True)

if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ""
if 'selected_date' not in st.session_state:
    st.session_state['selected_date'] = None

# URL 쿼리 파라미터를 통한 자동 로그인 검사
query_params = st.query_params
if "user" in query_params and not st.session_state['logged_in']:
    st.session_state['logged_in'] = True
    st.session_state['username'] = query_params["user"]

# Streamlit Secrets에서 서버 API 키 자동 로드
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except:
    GEMINI_API_KEY = ""

# ---------------------------------------------------------
# 2. 데이터베이스 셋업 (SQLite)
# ---------------------------------------------------------
def init_db():
    conn = sqlite3.connect('protein_lens.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS goals (username TEXT, target_kcal REAL, target_protein REAL, target_fat REAL, target_sugar REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS meals 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, date TEXT, meal_type TEXT, 
                  food_name TEXT, quantity REAL, kcal REAL, protein REAL, fat REAL, sugar REAL)''')
    conn.commit()
    return conn

conn = init_db()

# --- 허용 날짜 계산 함수 ---
def get_allowed_dates():
    KST = datetime.timezone(datetime.timedelta(hours=9))
    now = datetime.datetime.now(KST)
    today_str = now.strftime("%Y-%m-%d")
    yesterday_str = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    
    allowed_dates = [today_str]
    if now.hour < 3:
        allowed_dates.append(yesterday_str)
    return allowed_dates

# ---------------------------------------------------------
# 3. AI 분석 함수 (gemini-3.6-flash 고정)
# ---------------------------------------------------------
def clean_json_string(raw_string):
    raw_string = raw_string.strip()
    if raw_string.startswith("```json"):
        raw_string = raw_string[7:]
    if raw_string.startswith("```"):
        raw_string = raw_string[3:]
    if raw_string.endswith("```"):
        raw_string = raw_string[:-3]
    return raw_string.strip()

def analyze_food_image(image, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3.6-flash') 
    
    prompt = """
    당신은 영양 분석 전문가입니다. 이 사진을 분석하여 다음 2단계 규칙에 따라 영양 성분을 알려주세요.
    1단계: 사진에 '영양 성분표(라벨)'가 있다면 라벨의 글자를 읽어서 칼로리, 단백질, 지방, 당류를 정확히 추출하세요.
    2단계: 만약 라벨이 없다면, 사진 속 음식의 종류와 양을 인식하여 해당 음식의 평균적인 칼로리, 단백질, 지방, 당류를 추정하세요.
    
    반드시 아래 JSON 형식으로만 대답하세요. 다른 설명이나 마크다운 기호는 절대 넣지 마세요:
    {"food_name": "음식명(간단히)", "kcal": 0, "protein": 0, "fat": 0, "sugar": 0}
    """
    response = model.generate_content([prompt, image])
    cleaned_json = clean_json_string(response.text)
    return json.loads(cleaned_json)

def analyze_food_text(food_name, quantity, api_key):
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel('gemini-3.6-flash')
    
    prompt = f"""
    당신은 영양학자입니다. 사용자가 '{food_name}'을(를) {quantity}개(또는 인분) 섭취했습니다. 
    인터넷에 알려진 이 제품 또는 음식의 실제 1개(1인분) 평균 영양성분을 찾은 뒤, 
    섭취 수량({quantity})을 곱하여 **최종 총 영양성분**을 계산해주세요.
    
    반드시 아래 JSON 형식으로만 대답하세요. 다른 설명이나 마크다운 기호는 절대 넣지 마세요:
    {{"kcal": 0, "protein": 0, "fat": 0, "sugar": 0}}
    """
    response = model.generate_content(prompt)
    cleaned_json = clean_json_string(response.text)
    return json.loads(cleaned_json)

# ---------------------------------------------------------
# 4. 각 페이지별 화면 렌더링 함수들
# ---------------------------------------------------------

def view_login():
    st.title("🥗 Protein Lens 로그인")
    tab1, tab2 = st.tabs(["로그인", "회원가입"])
    
    with tab1:
        login_id = st.text_input("아이디", key="login_id")
        login_pw = st.text_input("비밀번호", type="password", key="login_pw")
        auto_login = st.checkbox("자동 로그인 유지 (이 브라우저에서 유지)")
        
        if st.button("로그인"):
            if not login_id.strip() or not login_pw.strip():
                st.warning("아이디와 비밀번호를 모두 입력해주세요.")
            else:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username=? AND password=?", (login_id.strip(), login_pw.strip()))
                if c.fetchone():
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = login_id.strip()
                    
                    if auto_login:
                        st.query_params["user"] = login_id.strip()
                    
                    st.success("로그인 성공!")
                    st.rerun()
                else:
                    st.error("아이디나 비밀번호가 틀렸습니다.")
                
    with tab2:
        reg_id = st.text_input("새 아이디", key="reg_id_input")
        reg_pw = st.text_input("새 비밀번호", type="password", key="reg_pw_input")
        
        if st.button("가입하기"):
            reg_id_clean = reg_id.strip()
            reg_pw_clean = reg_pw.strip()
            
            if not reg_id_clean or not reg_pw_clean:
                st.warning("아이디와 비밀번호를 모두 입력해주세요.")
            else:
                c = conn.cursor()
                c.execute("SELECT * FROM users WHERE username=?", (reg_id_clean,))
                if c.fetchone():
                    st.error("이미 존재하는 아이디입니다.")
                else:
                    try:
                        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (reg_id_clean, reg_pw_clean))
                        c.execute("INSERT INTO goals (username, target_kcal, target_protein, target_fat, target_sugar) VALUES (?, 2000, 100, 50, 30)", (reg_id_clean,))
                        conn.commit()
                        st.success(f"🎉 회원가입 성공! '{reg_id_clean}'님, 로그인 탭으로 이동하여 로그인해주세요.")
                    except Exception as e:
                        conn.rollback()
                        st.error(f"회원가입 처리 중 오류 발생: {e}")

def view_calendar():
    st.sidebar.title(f"👋 {st.session_state['username']}님 환영합니다!")

    c = conn.cursor()
    c.execute("SELECT target_kcal, target_protein, target_fat, target_sugar FROM goals WHERE username=?", (st.session_state['username'],))
    goal = c.fetchone()
    if not goal:
        c.execute("INSERT INTO goals VALUES (?, 2000, 100, 50, 30)", (st.session_state['username'],))
        conn.commit()
        goal = (2000.0, 100.0, 50.0, 30.0)
    
    st.sidebar.subheader("🎯 나의 하루 목표")
    with st.sidebar.form("goal_form"):
        target_kcal = st.number_input("목표 칼로리 (kcal)", value=float(goal[0]))
        target_protein = st.number_input("목표 단백질 (g)", value=float(goal[1]))
        target_fat = st.number_input("목표 지방 (g)", value=float(goal[2]))
        target_sugar = st.number_input("목표 당류 (g)", value=float(goal[3]))
        if st.form_submit_button("목표 저장"):
            c.execute("UPDATE goals SET target_kcal=?, target_protein=?, target_fat=?, target_sugar=? WHERE username=?",
                      (target_kcal, target_protein, target_fat, target_sugar, st.session_state['username']))
            conn.commit()
            st.success("목표가 업데이트 되었습니다!")
            st.rerun()

    st.sidebar.divider()
    if st.sidebar.button("🚪 로그아웃", type="primary"):
        st.session_state['logged_in'] = False
        st.session_state['username'] = ""
        st.session_state['selected_date'] = None
        st.query_params.clear()
        st.rerun()

    # 모바일용 컴팩트 헤더 적용
    st.markdown("<h2 style='margin-top:-10px; margin-bottom: 2px;'>📅 프로틴 렌즈 다이어리</h2>", unsafe_allow_html=True)
    
    allowed_dates = get_allowed_dates()
    if len(allowed_dates) > 1:
        st.caption("🌙 현재 새벽 시간입니다. 어제/오늘 날짜 식단 기록이 가능합니다.")
    else:
        st.caption("📌 오늘 날짜만 식단 기록 및 수정이 가능합니다.")

    c.execute("SELECT date, SUM(kcal), SUM(protein) FROM meals WHERE username=? GROUP BY date", (st.session_state['username'],))
    daily_records = c.fetchall()
    
    calendar_events = []
    for record in daily_records:
        date_record, total_kcal, total_protein = record
        if total_kcal <= goal[0] and total_protein >= goal[1]:
            color = "#28a745"
            title = "목표 달성!"
        else:
            color = "#dc3545"
            title = "목표 미달성"
            
        calendar_events.append({"title": title, "start": date_record, "color": color})

    # 모바일 한 화면에 쏙 들어오도록 높이(height) 및 CSS 반응형 조정
    calendar_options = {
        "headerToolbar": {"left": "prev,next today", "center": "title", "right": ""},
        "initialView": "dayGridMonth",
        "buttonText": {"today": "오늘"},
        "selectable": True,
        "height": 380,  # 모바일 화면 높이에 맞춘 고정 높이
    }
    
    custom_css = """
        .fc { font-size: 0.75rem !important; }
        .fc-toolbar-title { font-size: 1.0rem !important; }
        .fc-button { padding: 0.15rem 0.3rem !important; font-size: 0.75rem !important; }
        .fc-col-header-cell-cushion { padding: 1px !important; color: #ffffff !important; }
        .fc-daygrid-day-number { color: #ffffff !important; font-weight: bold; padding: 2px !important; }
        .fc-daygrid-day-frame { min-height: 42px !important; }
        .fc-event-title { font-size: 0.65rem !important; font-weight: bold; }
    """
    
    cal_result = calendar(events=calendar_events, options=calendar_options, custom_css=custom_css)
    
    if cal_result.get("dateClick"):
        raw_date = cal_result["dateClick"]["date"]
        if "T" in raw_date:
            try:
                dt_utc = datetime.datetime.strptime(raw_date[:19], "%Y-%m-%dT%H:%M:%S")
                dt_kst = dt_utc + datetime.timedelta(hours=9)
                clicked_date_str = dt_kst.strftime("%Y-%m-%d")
            except:
                clicked_date_str = raw_date[:10]
        else:
            clicked_date_str = raw_date[:10]
        
        if clicked_date_str in allowed_dates:
            st.session_state['selected_date'] = clicked_date_str
            st.switch_page(page_detail)
        else:
            st.error(f"❌ {clicked_date_str} 날짜는 현재 기록하거나 수정할 수 없습니다.")

def view_detail():
    date_str = st.session_state.get('selected_date')
    
    if not date_str:
        st.warning("선택된 날짜가 없습니다.")
        if st.button("⬅️ 달력으로 돌아가기"):
            st.switch_page(page_calendar)
        return

    if st.button("⬅️ 달력으로 돌아가기"):
        st.session_state['selected_date'] = None
        st.switch_page(page_calendar)
        
    date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    weekdays = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]
    weekday_str = weekdays[date_obj.weekday()]
    
    st.title(f"🍽️ {date_str} ({weekday_str}) 식단 기록")
    
    tabs = st.tabs(["아침", "점심", "저녁", "간식"])
    meal_types = ["아침", "점심", "저녁", "간식"]
    
    for i, tab in enumerate(tabs):
        with tab:
            meal_type = meal_types[i]
            st.subheader(f"{meal_type} 기록하기")
            
            input_mode = st.radio(
                "입력 방식", 
                ["📷 스마트폰 카메라", "🖼️ 사진 업로드", "✍️ 텍스트 입력 (AI 자동계산)"], 
                horizontal=True, 
                key=f"radio_{meal_type}"
            )
            
            uploaded_image = None
            
            if input_mode == "📷 스마트폰 카메라":
                camera_photo = st.camera_input("음식 사진 찍기", key=f"cam_{meal_type}")
                if camera_photo:
                    uploaded_image = Image.open(camera_photo)
            
            elif input_mode == "🖼️ 사진 업로드":
                file_photo = st.file_uploader(f"{meal_type} 음식 사진 업로드", type=["jpg", "png", "jpeg"], key=f"file_{meal_type}")
                if file_photo:
                    uploaded_image = Image.open(file_photo)

            if uploaded_image is not None:
                st.image(uploaded_image, width=300)
                if st.button(f"{meal_type} 사진으로 분석하기", key=f"btn_analyze_{meal_type}"):
                    if not GEMINI_API_KEY:
                        st.error("서버에 API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
                    else:
                        with st.spinner("AI가 이미지를 꼼꼼히 분석 중입니다..."):
                            try:
                                result = analyze_food_image(uploaded_image, GEMINI_API_KEY)
                                c = conn.cursor()
                                c.execute("INSERT INTO meals (username, date, meal_type, food_name, quantity, kcal, protein, fat, sugar) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                          (st.session_state['username'], date_str, meal_type, result['food_name'], 1.0, result['kcal'], result['protein'], result['fat'], result['sugar']))
                                conn.commit()
                                st.success("사진 분석 및 저장 완료!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"분석 중 오류가 발생했습니다. (에러: {e})")

            elif input_mode == "✍️ 텍스트 입력 (AI 자동계산)":
                if f'num_rows_{meal_type}' not in st.session_state:
                    st.session_state[f'num_rows_{meal_type}'] = 1

                if st.button("➕ 음식 입력 칸 추가", key=f"add_row_{meal_type}"):
                    st.session_state[f'num_rows_{meal_type}'] += 1
                    st.rerun()

                with st.form(f"form_{meal_type}"):
                    st.caption("음식 이름과 수량을 적으면 실제 AI가 영양성분을 분석하여 저장합니다.")
                    food_names = []
                    quantities = []
                    for r in range(st.session_state[f'num_rows_{meal_type}']):
                        col1, col2 = st.columns([3, 1])
                        fn = col1.text_input(f"음식 이름 {r+1}", placeholder="예: 베지밀 고단백 두유", key=f"fn_{meal_type}_{r}")
                        q = col2.number_input(f"수량 {r+1} (개/인분)", min_value=0.5, value=1.0, step=0.5, key=f"q_{meal_type}_{r}")
                        food_names.append(fn)
                        quantities.append(q)
                    
                    if st.form_submit_button("일괄 AI 계산 및 저장하기"):
                        if not GEMINI_API_KEY:
                            st.error("서버에 API 키가 설정되지 않았습니다. 관리자에게 문의하세요.")
                        else:
                            added_count = 0
                            c = conn.cursor()
                            with st.spinner("AI가 음식 정보를 검색하고 영양 성분을 계산 중입니다..."):
                                try:
                                    for fn, q in zip(food_names, quantities):
                                        if fn.strip() != "":
                                            result = analyze_food_text(fn, q, GEMINI_API_KEY)
                                            c.execute("INSERT INTO meals (username, date, meal_type, food_name, quantity, kcal, protein, fat, sugar) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                                      (st.session_state['username'], date_str, meal_type, fn, q, result.get('kcal', 0), result.get('protein', 0), result.get('fat', 0), result.get('sugar', 0)))
                                            added_count += 1
                                    if added_count > 0:
                                        conn.commit()
                                        st.success(f"총 {added_count}개의 음식이 성공적으로 기록되었습니다!")
                                        st.session_state[f'num_rows_{meal_type}'] = 1
                                        st.rerun()
                                    else:
                                        st.warning("입력된 음식이 없습니다.")
                                except Exception as e:
                                    st.error(f"분석 중 오류가 발생했습니다. (에러: {e})")

    st.divider()
    st.subheader(f"📊 오늘 섭취 기록 및 편집")
    c = conn.cursor()
    c.execute("SELECT id, meal_type, food_name, quantity, kcal, protein, fat, sugar FROM meals WHERE username=? AND date=?", (st.session_state['username'], date_str))
    records = c.fetchall()
    
    if records:
        df = pd.DataFrame(records, columns=["ID", "끼니", "음식", "수량", "칼로리", "단백질", "지방", "당류"])
        st.info("💡 표의 내용을 더블클릭하여 직접 숫자를 수정하거나 지울 수 있습니다. 변경 후 반드시 저장 버튼을 누르세요.")
        
        edited_df = st.data_editor(
            df,
            column_config={
                "ID": None, 
                "끼니": st.column_config.SelectboxColumn("끼니", options=["아침", "점심", "저녁", "간식"], required=True),
                "음식": st.column_config.TextColumn("음식", required=True),
            },
            disabled=["ID"],
            num_rows="dynamic",
            use_container_width=True,
            key="daily_meals_editor"
        )
        
        if st.button("💾 변경사항 DB에 완전 저장하기", type="primary"):
            changes = st.session_state["daily_meals_editor"]
            for row_idx in changes.get("deleted_rows", []):
                del_id = int(df.iloc[row_idx]["ID"])
                c.execute("DELETE FROM meals WHERE id=?", (del_id,))
                
            for row_idx, col_changes in changes.get("edited_rows", {}).items():
                edit_id = int(df.iloc[row_idx]["ID"])
                for col_name, new_val in col_changes.items():
                    db_col_map = {"끼니":"meal_type", "음식":"food_name", "수량":"quantity", "칼로리":"kcal", "단백질":"protein", "지방":"fat", "당류":"sugar"}
                    db_col = db_col_map[col_name]
                    c.execute(f"UPDATE meals SET {db_col}=? WHERE id=?", (new_val, edit_id))
                    
            for added in changes.get("added_rows", []):
                meal_type = added.get("끼니", "간식")
                food_name = added.get("음식", "새 음식")
                quantity = added.get("수량", 1.0)
                kcal = added.get("칼로리", 0.0)
                protein = added.get("단백질", 0.0)
                fat = added.get("지방", 0.0)
                sugar = added.get("당류", 0.0)
                c.execute("INSERT INTO meals (username, date, meal_type, food_name, quantity, kcal, protein, fat, sugar) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (st.session_state['username'], date_str, meal_type, food_name, quantity, kcal, protein, fat, sugar))
                          
            conn.commit()
            st.success("변경사항이 성공적으로 저장되었습니다!")
            st.rerun()

        for col in ["칼로리", "단백질", "지방", "당류"]:
            edited_df[col] = pd.to_numeric(edited_df[col], errors='coerce').fillna(0)
            
        totals = edited_df[["칼로리", "단백질", "지방", "당류"]].sum()
        c.execute("SELECT target_kcal, target_protein, target_fat, target_sugar FROM goals WHERE username=?", (st.session_state['username'],))
        goals = c.fetchone()
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("총 칼로리", f"{totals['칼로리']:.1f} kcal", f"{(totals['칼로리'] - goals[0]):.1f} kcal (목표대비)", delta_color="inverse")
        col2.metric("총 단백질", f"{totals['단백질']:.1f} g", f"{(totals['단백질'] - goals[1]):.1f} g (목표대비)")
        col3.metric("총 지방", f"{totals['지방']:.1f} g", f"{(totals['지방'] - goals[2]):.1f} g")
        col4.metric("총 당류", f"{totals['당류']:.1f} g", f"{(totals['당류'] - goals[3]):.1f} g", delta_color="inverse")
    else:
        st.info("아직 기록된 식단이 없습니다.")

# ---------------------------------------------------------
# 5. 라우팅
# ---------------------------------------------------------

page_login = st.Page(view_login, title="로그인", url_path="login")
page_calendar = st.Page(view_calendar, title="달력", url_path="calendar", default=True)
page_detail = st.Page(view_detail, title="식단 기록", url_path="detail")

if not st.session_state.get('logged_in', False):
    pg = st.navigation([page_login], position="hidden")
else:
    pg = st.navigation([page_calendar, page_detail], position="hidden")

pg.run()