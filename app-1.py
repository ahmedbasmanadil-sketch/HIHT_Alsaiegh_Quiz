import base64
import hashlib
import html
import io
import itertools
import json
import random
import re
import secrets as pysecrets
from collections import Counter
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

import gspread
import extra_streamlit_components as stx
import pandas as pd
import streamlit as st
import google.generativeai as genai
from google.oauth2.service_account import Credentials
from PIL import Image, ImageOps

# ====================== الإعدادات ======================
RESULTS_SHEET_ID = "1l5QPU0VU0JMMLYjKTSCDdOqe0uX5ceiBtAEUKXeSl8k"
QUESTIONS_SHEET_ID = "1n_erWCal8TKgsc2muduRm-uREMlZMTvdVZQfbq4AJic"
QUESTIONS_TAB = "MCQ"
APP_TITLE = "HIHT Quiz"
CREATOR = "Ahmed Basman"
ADMIN_USERS = ["ahmed basman"]          # أسماء المشرفين (بحروف صغيرة)
TZ = ZoneInfo("Asia/Baghdad")
LETTERS = ["A", "B", "C", "D"]
ALL = "__ALL__"
GUEST_PREFIX = "ضيف - "
SEMESTERS = ["First Semester", "Second Semester"]
PALETTE = [("#6C5CE7", "#a29bfe"), ("#00b894", "#55efc4"), ("#e17055", "#fab1a0"),
           ("#0984e3", "#74b9ff"), ("#e84393", "#fd79a8"), ("#f39c12", "#fdcb6e"),
           ("#00cec9", "#81ecec")]
EMOJIS = ["🧬", "🧪", "💉", "🩸", "🔬", "🧫", "⚗️", "🦠", "💊"]
MAX_CELL = 44000   # حد خلية Google Sheets ~50000 حرف


# ====================== الاتصال بـ Google Sheets ======================
@st.cache_resource(show_spinner=False)
def get_book():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds).open_by_key(RESULTS_SHEET_ID)


@st.cache_resource(show_spinner=False)
def users_ws():
    book = get_book()
    try:
        ws = book.worksheet("Users")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Users", rows=300, cols=6)
        ws.append_row(["Username", "Salt", "Hash", "Created", "Avatar", "RememberToken"])
        return ws
    if ws.col_count < 6:
        ws.add_cols(6 - ws.col_count)
    head = ws.row_values(1)
    if len(head) < 5 or head[4] != "Avatar":
        ws.update(range_name="E1", values=[["Avatar"]], raw=True)
    if len(head) < 6 or head[5] != "RememberToken":
        ws.update(range_name="F1", values=[["RememberToken"]], raw=True)
    return ws


@st.cache_resource(show_spinner=False)
def materials_ws():
    book = get_book()
    try:
        ws = book.worksheet("Materials")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Materials", rows=200, cols=4)
        ws.append_row(["OriginalSubject", "Subject", "Semester", "Active"])
    return ws


@st.cache_resource(show_spinner=False)
def question_bank_ws():
    book = get_book()
    try:
        ws = book.worksheet("QuestionBank")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("QuestionBank", rows=2000, cols=9)
        ws.append_row(["Semester", "Subject", "Lecture", "Question", "OptionA", "OptionB", "OptionC", "OptionD", "Correct"])
    return ws


@st.cache_data(ttl=60, show_spinner=False)
def load_materials():
    try:
        rows = materials_ws().get_all_records()
        return [r for r in rows if str(r.get("Subject", "")).strip() and str(r.get("Active", "1")).strip().lower() not in ("0", "false", "no", "inactive")]
    except Exception:
        return []


def save_material(original, name, semester, active="1"):
    ws = materials_ws()
    rows = ws.get_all_records()
    for i, row in enumerate(rows, start=2):
        if str(row.get("OriginalSubject", "")).strip() == original:
            ws.update(range_name=f"A{i}:D{i}", values=[[original, name, semester, active]], raw=True)
            load_materials.clear()
            load_questions.clear()
            return
    ws.append_row([original, name, semester, active], value_input_option="RAW")
    load_materials.clear()
    load_questions.clear()


def delete_material_mapping(original):
    """Remove the selected material's metadata row without deleting source questions or results."""
    ws = materials_ws()
    rows = ws.get_all_records()
    removed = 0
    for i, row in reversed(list(enumerate(rows, start=2))):
        if str(row.get("OriginalSubject", "")).strip() == original:
            ws.delete_rows(i)
            removed += 1
    load_materials.clear()
    load_questions.clear()
    return removed


def local_question_rows():
    try:
        rows = question_bank_ws().get_all_records()
        return [r for r in rows if str(r.get("Question", "")).strip()]
    except Exception:
        return []


@st.cache_resource(show_spinner=False)
def drafts_ws():
    book = get_book()
    try:
        return book.worksheet("Drafts")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Drafts", rows=500, cols=4)
        ws.append_row(["Username", "Quiz", "Answers", "Updated"])
        return ws


def save_draft(username, quiz, answers):
    ws = drafts_ws()
    records = ws.get_all_records()
    for i, row in enumerate(records, start=2):
        if str(row.get("Username", "")) == username:
            ws.update(range_name=f"B{i}:D{i}", values=[[json.dumps(quiz, ensure_ascii=False), json.dumps(answers, ensure_ascii=False), datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")]], raw=True)
            return
    ws.append_row([username, json.dumps(quiz, ensure_ascii=False), json.dumps(answers, ensure_ascii=False), datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")], value_input_option="RAW")


def get_draft(username):
    try:
        for row in drafts_ws().get_all_records():
            if str(row.get("Username", "")) == username and row.get("Quiz"):
                return json.loads(row["Quiz"]), json.loads(row.get("Answers") or "{}")
    except Exception:
        return None
    return None


def delete_draft(username):
    try:
        ws = drafts_ws()
        for i, row in enumerate(ws.get_all_records(), start=2):
            if str(row.get("Username", "")) == username:
                ws.delete_rows(i)
                return
    except Exception:
        pass


@st.cache_resource(show_spinner=False)
def assets_ws():
    book = get_book()
    try:
        return book.worksheet("Assets")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Assets", rows=60, cols=2)
        ws.append_row(["Key", "Data"])
        return ws


@st.cache_data(ttl=300, show_spinner=False)
def load_assets():
    rows = assets_ws().get_all_values()[1:]
    return {r[0]: r[1] for r in rows if len(r) > 1 and r[0]}


def safe_assets():
    try:
        return load_assets()
    except Exception:
        return {}


def set_asset(key, data):
    ws = assets_ws()
    keys = ws.col_values(1)
    if key in keys:
        ws.update(range_name=f"B{keys.index(key) + 1}", values=[[data]], raw=True)
    else:
        ws.append_row([key, data], value_input_option="RAW")
    load_assets.clear()


def del_asset(key):
    ws = assets_ws()
    keys = ws.col_values(1)
    if key in keys:
        ws.delete_rows(keys.index(key) + 1)
    load_assets.clear()


def fresh_users():
    return users_ws().get_all_records(numericise_ignore=["all"])


@st.cache_data(ttl=45, show_spinner=False)
def users_table():
    return fresh_users()


@st.cache_data(ttl=300, show_spinner=False)
def load_questions():
    url = (
        f"https://docs.google.com/spreadsheets/d/{QUESTIONS_SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={QUESTIONS_TAB}"
    )
    df = pd.read_csv(url, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    required = ["Question", "Subject", "Lecture", "Correct", "OptionA", "OptionB", "OptionC", "OptionD"]
    for c in required:
        if c not in df.columns:
            df[c] = ""
    if "Semester" not in df.columns:
        df["Semester"] = "First Semester"
    df = df[df["Question"].astype(str).str.strip() != ""].copy()

    local = local_question_rows()
    if local:
        local_df = pd.DataFrame(local).fillna("")
        for c in ["Semester", "Subject", "Lecture", "Question", "Correct", "OptionA", "OptionB", "OptionC", "OptionD"]:
            if c not in local_df.columns:
                local_df[c] = ""
        df = pd.concat([df, local_df[required + ["Semester"]]], ignore_index=True)

    for c in ("Subject", "Lecture", "Correct", "Semester"):
        df[c] = df[c].astype(str).str.strip()
    df["Correct"] = df["Correct"].str.upper()

    # Materials metadata can rename subjects or move them between semesters without editing source files.
    material_rows = load_materials()
    overrides = {str(r.get("OriginalSubject", "")).strip(): r for r in material_rows}
    if overrides:
        original_subjects = df["Subject"].copy()
        for original, row in overrides.items():
            mask = original_subjects == original
            if mask.any():
                df.loc[mask, "Subject"] = str(row.get("Subject", original)).strip() or original
                df.loc[mask, "Semester"] = str(row.get("Semester", "First Semester")).strip() or "First Semester"
        # A subject introduced from the manager is represented even before questions are uploaded.
        for original, row in overrides.items():
            display = str(row.get("Subject", original)).strip()
            if display and display not in set(df["Subject"]):
                df = pd.concat([df, pd.DataFrame([{"Question":"", "Subject":display, "Lecture":"", "Correct":"", "OptionA":"", "OptionB":"", "OptionC":"", "OptionD":"", "Semester":row.get("Semester", "First Semester")}])], ignore_index=True)
        df = df[df["Question"].astype(str).str.strip() != ""].copy()

    # Preserve legacy IDs for unique question texts, but disambiguate repeated
    # question text across subjects/lectures/semesters to prevent history crashes.
    base_qid = df["Question"].apply(lambda q: hashlib.md5(str(q).strip().encode("utf-8")).hexdigest()[:8])
    duplicate_text = df["Question"].astype(str).str.strip().duplicated(keep=False)
    df["qid"] = base_qid
    if duplicate_text.any():
        for idx in df.index[duplicate_text]:
            row = df.loc[idx]
            identity = "|".join(str(row.get(k, "")).strip() for k in ["Subject", "Lecture", "Semester", "Question"])
            df.at[idx, "qid"] = hashlib.md5(identity.encode("utf-8")).hexdigest()[:12]
    def sem_of(v):
        t = str(v).strip().lower()
        return 2 if ("second" in t or t == "2" or "ثان" in t) else 1
    df["SemN"] = df["Semester"].apply(sem_of)
    return df.reset_index(drop=True)


def delete_question_bank_rows(subject=None, lecture=None, semester=None):
    """Delete imported question rows from the app-managed QuestionBank only."""
    ws = question_bank_ws()
    values = ws.get_all_values()
    if len(values) <= 1:
        return 0
    headers = [str(v).strip() for v in values[0]]
    pos = {h: i for i, h in enumerate(headers)}
    delete_indices = []
    for row_num, row in enumerate(values[1:], start=2):
        def cell(field):
            i = pos.get(field)
            return str(row[i]).strip() if i is not None and i < len(row) else ""
        if subject is not None and cell("Subject") != subject:
            continue
        if lecture is not None and cell("Lecture") != lecture:
            continue
        if semester is not None and cell("Semester") != semester:
            continue
        delete_indices.append(row_num)
    for row_num in reversed(delete_indices):
        ws.delete_rows(row_num)
    load_questions.clear()
    return len(delete_indices)


def persist_csv_questions(uploaded_file, subject, lecture, semester):
    # CSV files exported from Excel may use UTF-8, UTF-8 with BOM, or legacy
    # Arabic Windows encodings (especially Windows-1256). Read bytes first so
    # an encoding mismatch does not abort the import before column validation.
    file_bytes = uploaded_file.getvalue()
    decoded_text = None
    decode_errors = []
    encodings = ["utf-8-sig", "cp1256", "cp1252", "latin1"]
    # UTF-16 exports normally have a BOM; only try UTF-16 first when present.
    if file_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings.insert(0, "utf-16")
    for encoding in encodings:
        try:
            decoded_text = file_bytes.decode(encoding)
            break
        except UnicodeDecodeError as exc:
            decode_errors.append(f"{encoding}: {exc}")
    if decoded_text is None:
        raise ValueError("تعذرت قراءة ترميز الملف. احفظه بصيغة CSV UTF-8 ثم أعد المحاولة.")
    try:
        filename = str(getattr(uploaded_file, "name", "")).lower()
        if filename.endswith((".xlsx", ".xls")):
            uploaded_file.seek(0)
            raw = pd.read_excel(io.BytesIO(file_bytes), dtype=str).fillna("")
        else:
            raw = pd.read_csv(io.StringIO(decoded_text), dtype=str).fillna("")
    except Exception as exc:
        raise ValueError(f"تعذر تحليل الملف. تحقق من سلامة CSV أو Excel وأسماء الأعمدة: {exc}") from exc
    raw.columns = [str(c).strip().lstrip("\ufeff") for c in raw.columns]
    # Accept common column naming variants while keeping the import predictable.
    aliases = {
        "Question": ["Question", "question", "السؤال", "نص السؤال"],
        "OptionA": ["OptionA", "A", "Option A", "الخيار A", "الخيار الأول"],
        "OptionB": ["OptionB", "B", "Option B", "الخيار B", "الخيار الثاني"],
        "OptionC": ["OptionC", "C", "Option C", "الخيار C", "الخيار الثالث"],
        "OptionD": ["OptionD", "D", "Option D", "الخيار D", "الخيار الرابع"],
        "Correct": ["Correct", "correct", "Answer", "answer", "الإجابة الصحيحة", "الإجابة"],
        "Lecture": ["Lecture", "lecture", "Chapter", "الفصل", "المحاضرة"],
        "Semester": ["Semester", "semester", "الفصل الدراسي"]
    }
    rename = {}
    for target, options in aliases.items():
        found = next((c for c in options if c in raw.columns), None)
        if found:
            rename[found] = target
    raw = raw.rename(columns=rename)
    if "Question" not in raw.columns:
        raise ValueError("لم أجد عمود السؤال. استخدم Question أو السؤال.")
    for c in ["OptionA", "OptionB", "OptionC", "OptionD", "Correct"]:
        if c not in raw.columns:
            raise ValueError(f"العمود المطلوب غير موجود: {c}")
    if "Lecture" not in raw.columns:
        raw["Lecture"] = lecture
    if "Semester" not in raw.columns:
        raw["Semester"] = semester
    raw = raw[raw["Question"].astype(str).str.strip() != ""].copy()
    raw["Correct"] = raw["Correct"].astype(str).str.strip().str.upper().str.replace(r"^([A-D]).*$", r"\1", regex=True)
    bad = sorted(set(raw[~raw["Correct"].isin(LETTERS)]["Correct"]))
    if bad:
        raise ValueError("قِيَم الإجابة الصحيحة يجب أن تكون A أو B أو C أو D. القيم غير الصحيحة: " + ", ".join(bad[:8]))
    rows = []
    for _, r in raw.iterrows():
        rows.append([semester, subject, str(r.get("Lecture", lecture)).strip() or lecture,
                     str(r["Question"]).strip(), str(r["OptionA"]).strip(), str(r["OptionB"]).strip(),
                     str(r["OptionC"]).strip(), str(r["OptionD"]).strip(), str(r["Correct"]).strip()])
    if rows:
        question_bank_ws().append_rows(rows, value_input_option="RAW")
    load_questions.clear()
    return len(rows)


@st.cache_data(ttl=20, show_spinner=False)
def all_results():
    try:
        return get_book().sheet1.get_all_records()
    except Exception:
        return []


def my_rows(name):
    return [r for r in all_results() if str(r.get("Name", "")).strip() == name]


def delete_result_rows(subject=None, name=None, lecture=None):
    """Delete matching result rows from the results worksheet, preserving its header."""
    ws = get_book().sheet1
    values = ws.get_all_values()
    if not values:
        return 0
    headers = [str(x).strip() for x in values[0]]
    positions = {h: i for i, h in enumerate(headers)}
    removed = []
    for sheet_row, row in enumerate(values[1:], start=2):
        def cell(field):
            idx = positions.get(field)
            return str(row[idx]).strip() if idx is not None and idx < len(row) else ""
        if subject is not None and cell("Subject") != subject:
            continue
        if name is not None and cell("Name") != name:
            continue
        if lecture is not None and cell("Lecture") != lecture:
            continue
        removed.append(sheet_row)
    for row_num in reversed(removed):
        ws.delete_rows(row_num)
    all_results.clear()
    return len(removed)


# ====================== الصفحة والمظهر ======================
def _page_icon():
    try:
        uri = safe_assets().get("logo")
        if uri:
            return Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    except Exception:
        pass
    return "🧪"


st.set_page_config(page_title=APP_TITLE, page_icon=_page_icon(), layout="centered")


def chem_svg(stroke, op):
    g = (f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="420" viewBox="0 0 420 420">'
         f'<g fill="none" stroke="{stroke}" stroke-opacity="{op}" stroke-width="2.2" '
         f'stroke-linecap="round" stroke-linejoin="round">')
    # دورق
    g += ('<g transform="translate(70 80) rotate(-12)"><path d="M-10 -42h20v28l26 48q7 14 -9 14h-54q-16 0 -9 -14l26 -48z"/>'
          '<path d="M-28 28h56"/><circle cx="-6" cy="38" r="3"/><circle cx="9" cy="34" r="2"/></g>')
    # أنبوب اختبار
    g += ('<g transform="translate(335 70) rotate(25)"><path d="M-9 -40v66a9 9 0 0 0 18 0v-66"/>'
          '<path d="M-13 -40h26"/><path d="M-9 8h18"/></g>')
    # حلقة بنزين
    g += ('<g transform="translate(210 205)"><path d="M26 0L13 22.5L-13 22.5L-26 0L-13 -22.5L13 -22.5z"/>'
          '<path d="M17 0L8.5 14.7M-8.5 14.7L-17 0M-8.5 -14.7L8.5 -14.7"/><path d="M26 0h22"/>'
          '<circle cx="54" cy="0" r="5"/></g>')
    # جزيء
    g += ('<g transform="translate(335 305)"><circle cx="0" cy="0" r="7"/><circle cx="38" cy="-20" r="5"/>'
          '<circle cx="40" cy="26" r="6"/><circle cx="-30" cy="22" r="5"/>'
          '<path d="M6 -3L33 -17M6 4L34 22M-5 5L-26 19"/></g>')
    # DNA
    g += ('<g transform="translate(70 245) rotate(14)"><path d="M0 0C28 15 28 45 0 60S-28 105 0 120"/>'
          '<path d="M0 0C-28 15 -28 45 0 60S28 105 0 120"/>'
          '<path d="M-16 14h32M-21 30h42M-16 46h32M-16 74h32M-21 90h42M-16 106h32"/></g>')
    # دورق صغير
    g += ('<g transform="translate(250 330) rotate(10) scale(.6)"><path d="M-10 -42h20v28l26 48q7 14 -9 14h-54q-16 0 -9 -14l26 -48z"/>'
          '<path d="M-28 28h56"/></g>')
    # حلقة صغيرة
    g += '<g transform="translate(160 350) scale(.55)"><path d="M26 0L13 22.5L-13 22.5L-26 0L-13 -22.5L13 -22.5z"/></g>'
    # فقاعات وعلامات
    g += ('<circle cx="190" cy="60" r="6"/><circle cx="212" cy="96" r="3.5"/><circle cx="150" cy="150" r="4.5"/>'
          '<circle cx="380" cy="175" r="5"/><circle cx="25" cy="385" r="5"/><circle cx="300" cy="160" r="3"/>'
          '<path d="M250 40v14M243 47h14M110 400v12M104 406h12M390 250v12M384 256h12"/>')
    return g + "</g></svg>"


def svg_url(stroke, op):
    return 'url("data:image/svg+xml,' + quote(chem_svg(stroke, op), safe="") + '")'


CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');
.stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp label,
.stApp button, .stApp input, .stApp [data-testid="stMarkdownContainer"] {font-family:'Cairo',sans-serif;}
.stApp {direction: rtl;}
#MainMenu, footer, header[data-testid="stHeader"] {display:none;}
html {background:#efeaff;}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {background: transparent !important;}
.stApp {
  background-color:#efeaff !important;
  background-image: __L1__, __L2__, linear-gradient(160deg,#f6f3ff 0%,#e4eeff 52%,#efe6ff 100%) !important;
  background-size: 520px 520px, 340px 340px, cover !important;
  background-position: 0 0, 130px 90px, center !important;
  background-attachment: fixed !important;
  animation: drift 140s linear infinite;
}
@keyframes drift {to {background-position: 520px 520px, -210px 430px, center;}}
@media (prefers-reduced-motion: reduce) {.stApp {animation: none;}}
@media (prefers-color-scheme: dark) {
  html {background:#14112e;}
  .stApp {
    background-color:#14112e !important;
    background-image: __D1__, __D2__, linear-gradient(160deg,#1a1640 0%,#14112e 55%,#201a4a 100%) !important;
  }
}
.block-container {padding-top:1.4rem; padding-bottom:3rem; max-width:1120px;}
div[class*="st-key-card_"] [data-testid="stRadio"] div[role="radiogroup"] {display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:10px;}
div[class*="st-key-card_"] [data-testid="stRadio"] div[role="radiogroup"] label {min-height:54px; display:flex; align-items:center; border:1px solid rgba(108,92,231,.18); box-shadow:0 3px 10px rgba(72,52,212,.05); transition:all .15s ease;}
div[class*="st-key-card_"] [data-testid="stRadio"] div[role="radiogroup"] label:hover {border-color:#6C5CE7; transform:translateY(-1px);}
@media(max-width:560px){div[class*="st-key-card_"] [data-testid="stRadio"] div[role="radiogroup"]{grid-template-columns:1fr;}}
.welcome {min-height:68vh; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center; color:#fff; padding:38px 24px; border-radius:28px; background:radial-gradient(circle at 80% 10%,rgba(255,255,255,.2),transparent 30%),linear-gradient(135deg,#35228f,#6C5CE7 55%,#a29bfe); box-shadow:0 20px 60px rgba(72,52,212,.25);}
.welcome h1 {font-size:clamp(2rem,5vw,4rem); direction:ltr; margin:14px 0 8px;}
.welcome p {font-size:1.1rem; opacity:.92;}
.welcome .created {margin-top:24px; opacity:.75; direction:ltr;}
.ltr {direction:ltr; text-align:left;}
div[role="radiogroup"] {direction:ltr; text-align:left;}

div[class*="st-key-card_"] {background: rgba(255,255,255,.80); backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px); border: 1px solid rgba(108,92,231,.16) !important;
  box-shadow: 0 6px 20px rgba(72,52,212,.08); border-radius: 18px;}
[data-testid="stExpander"] {background: rgba(255,255,255,.72); border-radius: 14px;}
@media (prefers-color-scheme: dark) {
  div[class*="st-key-card_"] {background: rgba(34,28,76,.72); border-color: rgba(162,155,254,.20) !important;
    box-shadow: 0 6px 20px rgba(0,0,0,.25);}
  [data-testid="stExpander"] {background: rgba(34,28,76,.6);}
}

.hero {position:relative; overflow:hidden; color:#fff; padding:20px 22px; border-radius:24px;
  margin-bottom:14px; background: linear-gradient(135deg,#4834d4,#6C5CE7 55%,#a29bfe);
  box-shadow: 0 10px 26px rgba(108,92,231,.30);}
.hero::before {content:""; position:absolute; width:190px; height:190px; border-radius:50%;
  background:rgba(255,255,255,.10); top:-70px; left:-50px;}
.hero::after {content:""; position:absolute; width:110px; height:110px; border-radius:50%;
  background:rgba(255,255,255,.08); bottom:-45px; right:30%;}
.hero-in {display:flex; gap:14px; align-items:center; position:relative; z-index:1;}
.hero-logo-wrap {width:72px; height:72px; border-radius:50%; display:flex; align-items:center; justify-content:center; background:rgba(255,255,255,.96); padding:4px; box-shadow:0 4px 14px rgba(0,0,0,.20); flex-shrink:0; overflow:hidden;}\n.hero-logo {width:64px; height:64px; border-radius:18px; background:#fff; object-fit:contain;
  padding:6px; flex-shrink:0; box-shadow:0 4px 12px rgba(0,0,0,.18);}
.hero-emoji {display:flex; align-items:center; justify-content:center; font-size:32px;}
.hero-t {font-size:1.35rem; font-weight:700; line-height:1.2; direction:ltr; text-align:right;}
.hero-s {opacity:.95; font-size:.95rem; margin-top:3px;}
.hero-c {opacity:.75; font-size:.78rem; margin-top:2px; direction:ltr; text-align:right;}

.row {display:flex; gap:14px; align-items:center; padding:2px 0 4px 0;}
.ico {width:54px; height:54px; border-radius:16px; display:flex; align-items:center;
  justify-content:center; font-size:26px; font-weight:700; color:#fff; flex-shrink:0;}
.ico-img {width:54px; height:54px; border-radius:16px; object-fit:cover; flex-shrink:0;}
.ttl {font-weight:700; font-size:1.05rem; line-height:1.35;}
.meta {opacity:.68; font-size:.85rem; margin-top:2px;}
.chip {display:inline-block; padding:1px 10px; border-radius:999px; font-size:.76rem;
  font-weight:700; margin-inline-start:6px;}
.c-ok {background:rgba(0,184,148,.18); color:#00a383;}
.c-mid {background:rgba(243,156,18,.2); color:#d68910;}
.c-low {background:rgba(225,112,85,.2); color:#d9534f;}
.c-new {background:rgba(128,128,128,.18);}

.cover {position:relative; height:190px; border-radius:22px; background-size:cover; background-position:center;
  display:flex; flex-direction:column; justify-content:flex-end; padding:16px; color:#fff;
  margin:6px 0 12px 0; box-shadow:0 8px 22px rgba(0,0,0,.15); isolation:isolate; overflow:hidden;}
.cover-img {position:absolute; inset:0; width:100%; height:100%; object-fit:cover; border-radius:22px; z-index:0;}
.cover::after {content:""; position:absolute; inset:0; border-radius:22px; background:linear-gradient(to top,rgba(0,0,0,.74),rgba(0,0,0,.04)); z-index:1; pointer-events:none;}
.cover-t {font-size:1.35rem; font-weight:700; text-shadow:0 2px 8px rgba(0,0,0,.4); position:relative; z-index:2;}
.cover-m {opacity:.92; font-size:.88rem; position:relative; z-index:2;}
.cover.cover-full {height:auto; min-height:0; padding:0; display:block; background:#262044;}
.cover-full .cover-img {position:relative; inset:auto; display:block; width:100%; height:auto; max-height:680px; object-fit:contain; border-radius:0; z-index:0;}
.cover-full::after {border-radius:22px;}
.cover-full .cover-t, .cover-full .cover-m {position:absolute; right:16px; z-index:2;}
.cover-full .cover-t {bottom:42px;}
.cover-full .cover-m {bottom:14px;}

.avatar {width:64px; height:64px; border-radius:50%; display:flex; align-items:center;
  justify-content:center; font-size:1.7rem; font-weight:700; color:#fff; flex-shrink:0;
  background:linear-gradient(135deg,#6C5CE7,#a29bfe); object-fit:cover;}

.srow {margin:6px 0 12px 0;}
.srow-h {display:flex; justify-content:space-between; align-items:baseline; gap:8px;}
.srow-h b {font-size:1rem;}
.bar {position:relative; height:8px; border-radius:999px; background:rgba(128,128,128,.2); margin-top:6px;}
.bar i {display:block; height:100%; border-radius:999px;}
.bar s {position:absolute; top:-3px; width:3px; height:14px; border-radius:2px; background:#636e72;}
.foot {text-align:center; opacity:.55; font-size:.78rem; margin-top:26px; direction:ltr;}

.stApp [data-testid="stBaseButton-primary"], .stApp button[kind="primary"] {
  background:linear-gradient(135deg,#6C5CE7,#8e7cff); border:0; border-radius:14px; color:#fff;}
.stApp [data-testid="stBaseButton-secondary"], .stApp button[kind="secondary"] {border-radius:14px;}

.st-key-nav div[role="radiogroup"], .st-key-sem div[role="radiogroup"] {direction:rtl; gap:8px;}
.st-key-nav div[role="radiogroup"] label, .st-key-sem div[role="radiogroup"] label {
  background:rgba(128,128,128,.16); padding:6px 20px; border-radius:999px; cursor:pointer;}
.st-key-nav div[role="radiogroup"] label > :not(:last-child),
.st-key-sem div[role="radiogroup"] label > :not(:last-child) {display:none !important;}
.st-key-nav div[role="radiogroup"] label:has(input:checked),
.st-key-sem div[role="radiogroup"] label:has(input:checked) {background:#6C5CE7;}
.st-key-nav div[role="radiogroup"] label:has(input:checked) p,
.st-key-sem div[role="radiogroup"] label:has(input:checked) p {color:#fff !important;}

div[class*="st-key-card_"] [data-testid="stRadio"] div[role="radiogroup"] label {background:rgba(128,128,128,.10);
  padding:9px 12px; border-radius:12px; margin-bottom:6px; width:100%;}
div[class*="st-key-card_"] [data-testid="stRadio"] div[role="radiogroup"] label:has(input:checked) {
  background:rgba(108,92,231,.22); outline:2px solid #6C5CE7;}

.ring {position:relative; width:150px; height:150px; margin:6px auto 4px auto;}
.ring-bg {position:absolute; inset:0; border-radius:50%;
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 14px), #000 calc(100% - 13px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 14px), #000 calc(100% - 13px));}
.ring-txt {position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center;}
.ring-p {font-size:2rem; font-weight:700; line-height:1;}
.ring-s {opacity:.65; font-size:.85rem; margin-top:4px;}
.msg {text-align:center; font-size:1.1rem; font-weight:700; margin-bottom:10px;}
</style>
"""
st.markdown(
    CSS.replace("__L1__", svg_url("#5b47d6", 0.13)).replace("__L2__", svg_url("#8e7cff", 0.17))
       .replace("__D1__", svg_url("#8e7cff", 0.14)).replace("__D2__", svg_url("#c4b8ff", 0.10)),
    unsafe_allow_html=True,
)


# ====================== أدوات مساعدة ======================
_box_n = itertools.count()


def box():
    return st.container(border=True, key=f"card_{next(_box_n)}")


def esc(s):
    return html.escape(str(s))


def nat_key(s):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


def pick(name, seq):
    return seq[int(hashlib.md5(name.encode()).hexdigest(), 16) % len(seq)]


def pct_color(p):
    return "#00b894" if p >= 75 else "#f39c12" if p >= 50 else "#e17055"


def chip_for(best):
    if best is None:
        return '<span class="chip c-new">جديد</span>'
    cls = "c-ok" if best >= 75 else "c-mid" if best >= 50 else "c-low"
    return f'<span class="chip {cls}">أفضل: {best:g}%</span>'


def card(icon, c1, c2, title, meta, chip="", img=None):
    ico = (f'<img class="ico-img" src="{img}">' if img else
           f'<div class="ico" style="background:linear-gradient(135deg,{c1},{c2})">{icon}</div>')
    return (f'<div class="row">{ico}<div><div class="ttl">{esc(title)}{chip}</div>'
            f'<div class="meta">{esc(meta)}</div></div></div>')


def go(view, **kw):
    st.session_state.view = view
    for k, v in kw.items():
        st.session_state[k] = v
    st.rerun()


def is_admin(name):
    extra = []
    try:
        extra = [str(x).lower() for x in st.secrets.get("admins", [])]
    except Exception:
        pass
    return name.strip().lower() in ADMIN_USERS + extra


def prep_image(file, kind):
    """يصغّر الصورة ويحوّلها إلى data-URI يناسب خلية Google Sheets."""
    img = ImageOps.exif_transpose(Image.open(file))
    plans = {
        "avatar": [(128, 80), (112, 70), (96, 60)],
        "cover": [(1200, 78), (1000, 72), (800, 66), (640, 58), (480, 50)],
        "logo": [(220, 0), (170, 0), (130, 0), (100, 0)],
    }[kind]
    for size, q in plans:
        buf = io.BytesIO()
        if kind == "avatar":
            im = ImageOps.fit(img.convert("RGB"), (size, size))
            im.save(buf, "JPEG", quality=q, optimize=True)
            mime = "image/jpeg"
        elif kind == "cover":
            # Preserve the full image instead of cropping it to a banner ratio.
            im = img.convert("RGB")
            im.thumbnail((size, int(size * 0.65)), Image.Resampling.LANCZOS)
            im.save(buf, "JPEG", quality=q, optimize=True)
            mime = "image/jpeg"
        else:
            im = img.convert("RGBA")
            im.thumbnail((size, size))
            im.save(buf, "PNG", optimize=True)
            if len(buf.getvalue()) * 4 // 3 > MAX_CELL:
                buf = io.BytesIO()
                im.quantize(colors=96, method=Image.FASTOCTREE).save(buf, "PNG", optimize=True)
            mime = "image/png"
        uri = f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()
        if len(uri) < MAX_CELL:
            return uri
    raise ValueError("الصورة كبيرة جدًا، جرّب صورة أخرى.")


# ====================== الحسابات ======================
def hash_pw(pw, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000).hex()


def find_user(name, records=None):
    for i, r in enumerate(records if records is not None else fresh_users(), start=2):
        if str(r["Username"]).strip().lower() == name.strip().lower():
            return i, r
    return None, None


def name_problem(new, ignore=None):
    new = new.strip()
    if not new or len(new) > 30:
        return "الاسم مطلوب (حتى 30 حرفًا)."
    if new.startswith("ضيف"):
        return "لا يمكن أن يبدأ الاسم بكلمة ضيف."
    for r in fresh_users():
        n = str(r["Username"]).strip().lower()
        if n == new.lower() and n != (ignore or "").lower():
            return "هذا الاسم مستخدم، اختر اسمًا آخر."
    return ""


def register(username, pw):
    msg = name_problem(username)
    if msg:
        return False, msg
    salt = pysecrets.token_hex(16)
    users_ws().append_row(
        [username.strip(), salt, hash_pw(pw, salt), datetime.now(TZ).strftime("%Y-%m-%d"), ""],
        value_input_option="RAW",
    )
    users_table.clear()
    return True, ""


def login(username, pw):
    i, r = find_user(username)
    if r and hash_pw(pw, str(r["Salt"])) == str(r["Hash"]):
        return str(r["Username"]).strip()
    return None


def set_remember_token(username, token):
    i, row = find_user(username)
    if row:
        users_ws().update(range_name=f"F{i}", values=[[token]], raw=True)
        users_table.clear()


def login_by_token(token):
    if not token:
        return None
    for row in users_table():
        if token and secrets_compare(str(row.get("RememberToken", "")), token):
            return str(row.get("Username", "")).strip()
    return None


def secrets_compare(a, b):
    import hmac
    return hmac.compare_digest(str(a), str(b))


def set_password(i, new):
    salt = pysecrets.token_hex(16)
    users_ws().update(range_name=f"B{i}:C{i}", values=[[salt, hash_pw(new, salt)]], raw=True)
    users_ws().update(range_name=f"F{i}", values=[[""]], raw=True)
    users_table.clear()


def change_password(username, old, new):
    i, r = find_user(username)
    if not r:
        return False, "الحساب غير موجود."
    if hash_pw(old, str(r["Salt"])) != str(r["Hash"]):
        return False, "كلمة المرور الحالية غير صحيحة."
    set_password(i, new)
    return True, ""


def rename_user(old, new):
    new = new.strip()
    msg = name_problem(new, ignore=old)
    if msg:
        return False, msg
    i, r = find_user(old)
    if not r:
        return False, "الحساب غير موجود."
    users_ws().update(range_name=f"A{i}", values=[[new]], raw=True)
    rs = get_book().sheet1
    col = rs.col_values(2)
    out = [[new if v.strip() == old else v] for v in col]
    rs.update(range_name=f"B1:B{len(col)}", values=out, raw=True)
    users_table.clear()
    all_results.clear()
    return True, ""


def set_avatar(username, uri):
    i, r = find_user(username)
    if r:
        users_ws().update(range_name=f"E{i}", values=[[uri]], raw=True)
        users_table.clear()


def delete_user(username):
    i, r = find_user(username)
    if r:
        users_ws().delete_rows(i)
        users_table.clear()


def user_row(name):
    for r in users_table():
        if str(r["Username"]).strip().lower() == name.strip().lower():
            return r
    return {}


def save_result(name, subject, lecture, score, total, answers):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    pct = round(score / total * 100, 1)
    get_book().sheet1.append_row(
        [ts, name, subject, lecture, score, total, pct, json.dumps(answers, ensure_ascii=False)],
        value_input_option="RAW",
    )
    all_results.clear()


# ====================== مكونات الواجهة ======================
def hero(sub):
    logo = safe_assets().get("logo")
    img = (f'<div class="hero-logo-wrap"><img class="hero-logo" src="{logo}" alt="شعار المعهد"></div>' if logo
           else '<div class="hero-logo-wrap"><div class="hero-logo hero-emoji">🧪</div></div>')
    st.markdown(
        f'<div class="hero"><div class="hero-in">{img}<div>'
        f'<div class="hero-t">{esc(APP_TITLE)}</div><div class="hero-s">{esc(sub)}</div>'
        f'<div class="hero-c">Created by {esc(CREATOR)}</div></div></div></div>',
        unsafe_allow_html=True,
    )


def back_button(label, view, **kw):
    if st.button(f"→ {label}"):
        go(view, **kw)


def bars(df_g, label_col, peer=None, extra=None):
    out = ""
    for _, r in df_g.iterrows():
        lab = r[label_col]
        avg, best, n = round(float(r["mean"]), 1), float(r["max"]), int(r["count"])
        meta = f"{n} اختبار · أفضل {best:g}%"
        mark = ""
        if extra and lab in extra:
            meta += f" · {extra[lab]}"
        if peer and lab in peer:
            pv = round(float(peer[lab]), 1)
            meta += f" · متوسط الزملاء {pv:g}%"
            mark = f'<s style="right:{min(pv, 99)}%"></s>'
        out += (
            f'<div class="srow"><div class="srow-h"><span class="ttl">{esc(lab)}</span>'
            f'<b style="color:{pct_color(avg)}">{avg:g}%</b></div>'
            f'<div class="meta">{meta}</div>'
            f'<div class="bar"><i style="width:{min(avg, 100)}%;background:{pct_color(avg)}"></i>{mark}</div></div>'
        )
    return out


def gate():
    hero("اختبارات تفاعلية لمراجعة المحاضرات")
    if st.session_state.pop("kicked", False):
        st.warning("تم إيقاف هذا الحساب أو حذفه. تواصل مع المشرف.")
    t_guest, t_login, t_reg = st.tabs(["ضيف", "تسجيل الدخول", "حساب جديد"])

    with t_guest:
        st.caption("تصل نتيجتك للمشرف، لكن لا يُحفظ لك سجل.")
        name = st.text_input("اسمك", key="guest_name")
        if st.button("ابدأ كضيف", type="primary", use_container_width=True):
            if name.strip():
                st.session_state.user = {"name": f"{GUEST_PREFIX}{name.strip()}", "account": False}
                st.rerun()
            else:
                st.warning("اكتب اسمك أولًا.")

    with t_login:
        u = st.text_input("اسم المستخدم", key="login_u")
        p = st.text_input("كلمة المرور", type="password", key="login_p")
        remember = st.checkbox("تذكرني (إبقاء الحساب مسجلًا على هذا الجهاز)", key="remember_me")
        if st.button("دخول", type="primary", use_container_width=True):
            try:
                found = login(u.strip(), p)
            except Exception as e:
                st.error(f"تعذر الاتصال: {e}")
                found = None
            if found:
                if remember:
                    token = pysecrets.token_urlsafe(32)
                    try:
                        set_remember_token(found, token)
                        cookie_manager.set("hiht_remember", token, expires_at=datetime.now(TZ).replace(year=datetime.now(TZ).year + 1))
                    except Exception as e:
                        st.warning(f"تم تسجيل الدخول، لكن تعذر تفعيل تذكرني: {e}")
                st.session_state.user = {"name": found, "account": True}
                st.rerun()
            else:
                st.error("اسم المستخدم أو كلمة المرور غير صحيحة.")
        if st.button("نسيت كلمة السر؟", use_container_width=True):
            st.info("راسل المشرف لتغيير الرمز.")

    with t_reg:
        st.caption("الحساب يحفظ سجل اختباراتك ويحلل نقاط ضعفك.")
        u = st.text_input("اسم المستخدم (يفضل اسمك الحقيقي)", key="reg_u")
        p = st.text_input("كلمة المرور (4 أحرف فأكثر)", type="password", key="reg_p")
        if st.button("إنشاء الحساب", type="primary", use_container_width=True):
            if not u.strip() or len(p) < 4:
                st.warning("أكمل الاسم وكلمة مرور من 4 أحرف على الأقل.")
            else:
                try:
                    ok, msg = register(u.strip(), p)
                except Exception as e:
                    ok, msg = False, f"تعذر الاتصال: {e}"
                if ok:
                    st.session_state.user = {"name": u.strip(), "account": True}
                    st.rerun()
                else:
                    st.error(msg)


# ====================== الرئيسية: الفصول والمواد ======================
def home_view(df):
    user = st.session_state.user
    counts = Counter()
    if user["account"]:
        for r in my_rows(user["name"]):
            counts[r["Subject"]] += 1

    with st.container(key="sem"):
        sem = st.radio("sem", SEMESTERS, horizontal=True, label_visibility="collapsed")
    sem_n = SEMESTERS.index(sem) + 1
    sdf = df[df["SemN"] == sem_n]
    material_names = [str(r.get("Subject", "")).strip() for r in load_materials()
                      if (2 if "second" in str(r.get("Semester", "")).lower() or "2" == str(r.get("Semester", "")).strip() or "ثان" in str(r.get("Semester", "")) else 1) == sem_n]
    subjects = sorted(set(sdf["Subject"].unique()).union(material_names), key=nat_key)
    if not subjects:
        st.info("لا توجد مواد في هذا الفصل بعد، يمكنك إضافتها من لوحة المشرف.")
        return
    assets = safe_assets()
    cols = st.columns(2)
    for i, subj in enumerate(subjects):
        sub_df = sdf[sdf["Subject"] == subj]
        c1, c2 = pick(subj, PALETTE)
        chip = f'<span class="chip c-new">{counts[subj]} اختبار</span>' if counts[subj] else ""
        with cols[i % 2]:
            with box():
                st.markdown(
                    card(pick(subj, EMOJIS), c1, c2, subj,
                         f"{sub_df['Lecture'].nunique()} محاضرات · {len(sub_df)} سؤال",
                         chip, assets.get(f"subj:{subj}")),
                    unsafe_allow_html=True,
                )
                if st.button("فتح", key=f"subj_{sem_n}_{i}", use_container_width=True):
                    go("subject", subject=subj)


# ====================== المادة: المحاضرات ======================
def subject_view(df):
    user = st.session_state.user
    subj = st.session_state.subject
    sub_df = df[df["Subject"] == subj]
    c1, c2 = pick(subj, PALETTE)
    back_button("المواد", "home")

    img = safe_assets().get(f"subj:{subj}")
    bg = f"background-image:linear-gradient(135deg,{c1},{c2});"
    cover_img = f'<img class="cover-img" src="{img}" alt="غلاف {esc(subj)}">' if img else ""
    cover_class = "cover cover-full" if img else "cover"
    st.markdown(
        f'<div class="{cover_class}" style="{bg}">{cover_img}<div class="cover-t">'
        f'{"" if img else pick(subj, EMOJIS) + " "}{esc(subj)}</div>'
        f'<div class="cover-m">{sub_df["Lecture"].nunique()} محاضرات · {len(sub_df)} سؤال</div></div>',
        unsafe_allow_html=True,
    )
    if sub_df.empty:
        st.info("أُضيفت هذه المادة، لكن لا توجد أسئلة لها بعد. يمكنك رفع ملف CSV من لوحة المشرف.")
        return

    best = {}
    if user["account"]:
        for r in my_rows(user["name"]):
            if r["Subject"] == subj:
                p = float(r["Percentage"] or 0)
                best[r["Lecture"]] = max(best.get(r["Lecture"], 0), p)

    with box():
        st.markdown(
            card("🎲", "#2d3436", "#636e72", "اختبار شامل",
                 f"أسئلة عشوائية من كل المحاضرات · {len(sub_df)} سؤال"),
            unsafe_allow_html=True,
        )
        if st.button("ابدأ", key="lec_all", use_container_width=True):
            go("setup", lecture=ALL)

    for i, lec in enumerate(sorted(sub_df["Lecture"].unique(), key=nat_key)):
        n_q = int((sub_df["Lecture"] == lec).sum())
        num = re.search(r"\d+", lec)
        with box():
            st.markdown(
                card(num.group(0) if num else "📄", c1, c2, lec, f"{n_q} سؤال",
                     chip_for(best.get(lec)) if user["account"] else ""),
                unsafe_allow_html=True,
            )
            if st.button("ابدأ", key=f"lec_{i}", use_container_width=True, type="primary"):
                go("setup", lecture=lec)


# ====================== إعداد الاختبار ======================
def setup_view(df):
    subj, lec = st.session_state.subject, st.session_state.lecture
    pool = df[df["Subject"] == subj]
    if lec != ALL:
        pool = pool[pool["Lecture"] == lec]
    back_button("رجوع", "subject")
    st.subheader(f"{subj} — {'اختبار شامل' if lec == ALL else lec}")
    if st.session_state.user.get("account"):
        st.caption(f"متوفر {len(pool)} سؤال. يتم ترتيب الأسئلة عشوائيًا.")
    else:
        st.caption(f"متوفر {len(pool)} سؤال. تظهر الأسئلة بترتيبها الأصلي.")

    options = [n for n in (10, 20, 30) if n < len(pool)]
    labels = [str(n) for n in options] + [f"الكل ({len(pool)})"]
    choice = st.radio("عدد الأسئلة", labels, horizontal=True, index=len(labels) - 1)
    n = len(pool) if choice.startswith("الكل") else int(choice)

    if st.button("🚀 ابدأ الاختبار", type="primary", use_container_width=True):
        ids = list(pool["qid"])
        if st.session_state.user.get("account"):
            random.shuffle(ids)
        for k in [k for k in st.session_state if k.startswith("q_")]:
            del st.session_state[k]
        quiz = {"ids": ids[:n], "subject": subj,
                "lecture": "كل المحاضرات" if lec == ALL else lec}
        st.session_state.quiz = quiz
        st.session_state.quiz_answers = {}
        go("quiz", quiz=quiz)


# ====================== الاختبار ======================
def quiz_view(df):
    user = st.session_state.user
    quiz = st.session_state.get("quiz")
    if not quiz:
        go("home")
    qmap = df.drop_duplicates(subset=["qid"], keep="last").set_index("qid").to_dict("index")

    c_back, c_title = st.columns([1, 4])
    with c_back:
        if st.button("↩️ إلغاء", use_container_width=True):
            if user.get("account"):
                try:
                    delete_draft(user["name"])
                except Exception:
                    pass
            st.session_state.quiz = None
            st.session_state.quiz_answers = {}
            go("subject")
    with c_title:
        st.subheader(f"{quiz['subject']} — {quiz['lecture']}")

    st.caption(f"{len(quiz['ids'])} سؤال · إجاباتك تبقى محفوظة أثناء التنقل داخل الاختبار؛ اضغط إنهاء عند الاكتمال.")
    answers_state = st.session_state.setdefault("quiz_answers", {})
    for i, qid in enumerate(quiz["ids"], 1):
        row = qmap[qid]
        with box():
            st.markdown(f'<div class="ltr"><b>{i}. {esc(row["Question"])}</b></div>', unsafe_allow_html=True)
            letters = [L for L in LETTERS if str(row.get(f"Option{L}", "")).strip()]
            old = answers_state.get(qid, "")
            default_idx = letters.index(old) if old in letters else None
            chosen = st.radio("اختر الإجابة", letters, index=default_idx, key=f"q_{qid}",
                              format_func=lambda L, r=row: f"{L}) {r['Option' + L]}",
                              label_visibility="collapsed")
            if chosen:
                answers_state[qid] = chosen
    answered = sum(1 for qid in quiz["ids"] if answers_state.get(qid))
    if user.get("account"):
        try:
            save_draft(user["name"], quiz, answers_state)
        except Exception:
            pass
    st.progress(answered / max(len(quiz["ids"]), 1), text=f"أجبت عن {answered} من {len(quiz['ids'])} سؤال")
    if st.button("✅ إنهاء وإرسال", type="primary", use_container_width=True):
        answers, review, score = {}, [], 0
        for qid in quiz["ids"]:
            row = qmap[qid]
            chosen = answers_state.get(qid, "") or ""
            correct = row["Correct"]
            ok = chosen == correct
            score += ok
            answers[qid] = [chosen, correct]
            review.append({"q": row["Question"], "ok": ok,
                "chosen_text": f"{chosen}) {row['Option' + chosen]}" if chosen else "بدون إجابة",
                "correct_text": f"{correct}) {row['Option' + correct]}"})
        total = len(quiz["ids"])
        if user.get("account"):
            delete_draft(user["name"])
        saved = True
        try:
            save_result(user["name"], quiz["subject"], quiz["lecture"], score, total, answers)
        except Exception:
            saved = False
        go("result", result={"score": score, "total": total,
             "pct": round(score / total * 100, 1), "review": review, "saved": saved}, quiz=None, quiz_answers={})# ====================== النتيجة ======================
def result_view():
    res = st.session_state.get("result")
    if not res:
        go("home")
    pct = res["pct"]
    msg = ("ممتاز 🌟" if pct >= 85 else "جيد جدًا 👏" if pct >= 70
           else "جيد، راجع الأخطاء 💪" if pct >= 50 else "تحتاج مراجعة أكثر 📚")
    st.markdown(
        f'<div class="ring"><div class="ring-bg" style="background:conic-gradient({pct_color(pct)} {pct}%, rgba(128,128,128,.22) 0)"></div>'
        f'<div class="ring-txt"><div class="ring-p">{pct:g}%</div>'
        f'<div class="ring-s">{res["score"]} / {res["total"]}</div></div></div>'
        f'<div class="msg">{msg}</div>',
        unsafe_allow_html=True,
    )
    if res.get("saved"):
        st.caption("✅ تم إرسال نتيجتك.")
    else:
        st.warning("تعذر حفظ النتيجة في الجدول. التقط صورة لها وأرسلها للمشرف.")

    wrong = [r for r in res["review"] if not r["ok"]]
    if wrong:
        st.subheader(f"مراجعة الأخطاء ({len(wrong)})")
        for r in wrong:
            with st.expander(r["q"][:70]):
                st.markdown(f'<div class="ltr">{esc(r["q"])}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="ltr">❌ إجابتك: {esc(r["chosen_text"])}</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="ltr">✅ الصحيحة: {esc(r["correct_text"])}</div>', unsafe_allow_html=True)
    else:
        st.balloons()

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🔁 اختبار جديد", type="primary", use_container_width=True):
            go("subject", result=None)
    with c2:
        if st.button("🏠 الرئيسية", use_container_width=True):
            go("home", result=None)

def ai_analyze_lecture(user_name, subject, lecture, attempts_df, wrong_texts):
    """توليد تقرير AI عبر Gemini بناءً على محاولات متعددة."""
    try:
        genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
        model = genai.GenerativeModel('gemini-3.0-flash')

        attempts_lines = []
        for i, (_, row) in enumerate(attempts_df.iterrows(), 1):
            attempts_lines.append(f"المحاولة {i}: {row['Score']}/{row['Total']} ({row['Percentage']}%)")

        wrong_section = chr(10).join(wrong_texts) if wrong_texts else "لا توجد أخطاء متكررة"

        prompt = f"""أنت مدرّس جامعي مختص. حلل أداء الطالب التالي وقدم تقريراً بالعربية.

المعلومات:
- الطالب: {user_name}
- المادة: {subject}
- المحاضرة: {lecture}
- عدد المحاولات: {len(attempts_df)}

سجل المحاولات:
{chr(10).join(attempts_lines)}

الأسئلة المتكررة في الخطأ:
{wrong_section}

اكتب تقريراً مختصراً (200-300 كلمة) يشمل:
1. ملخص الأداء: هل هناك تحسن من محاولة لأخرى؟
2. نقاط القوة
3. نقاط الضعف المتكررة
4. توصيات محددة قابلة للتطبيق
5. كلمة تشجيعية

استخدم تنسيق Markdown مع عناوين وقوائم نقطية."""

        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"⚠️ تعذر توليد التقرير: {e}"
               
# ====================== السجل (يُستخدم للطالب وللمشرف) ======================
def lecture_panel(lsel, qmap, kp, peer, subj="", lec=""):
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("الاختبارات", len(lsel))
    c2.metric("المتوسط", f"{lsel['Percentage'].mean():.1f}%")
    c3.metric("الأفضل", f"{lsel['Percentage'].max():.1f}%")
    c4.metric("الزملاء", f"{peer:.1f}%" if peer is not None else "—")
    if len(lsel) > 1:
        st.line_chart(pd.DataFrame({"النسبة %": lsel["Percentage"].tolist()}), height=150)

    wrong, seen = Counter(), Counter()
    for a in lsel["Answers"]:
        try:
            ans = json.loads(a)
        except Exception:
            continue
        for qid, (chosen, correct) in ans.items():
            seen[qid] += 1
            if chosen != correct:
                wrong[qid] += 1
    weak = [(q, w) for q, w in wrong.most_common(10) if q in qmap]
    st.markdown("🎯 أكثر الأسئلة خطأً في هذه المحاضرة")
    if weak:
        for qid, w in weak:
            r = qmap[qid]
            with st.expander(f"أخطأت {w} من {seen[qid]} — {r['Question'][:55]}"):
                st.markdown(f'<div class="ltr">{esc(r["Question"])}</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="ltr">✅ {r["Correct"]}) {esc(r["Option" + r["Correct"]])}</div>',
                    unsafe_allow_html=True)
    else:
        st.success("لا أخطاء مسجلة، ممتاز!")

    st.markdown("🔍 مراجعة اختبار سابق")
    recs = lsel.to_dict("records")
    labels = [f"{r['Timestamp']} — {r['Score']}/{r['Total']}" for r in recs]
    choice = st.selectbox("اختر اختبارًا لعرض تفاصيله", ["— اختر اختبارًا —"] + list(range(len(recs))),
                          format_func=lambda i: i if isinstance(i, str) else labels[i],
                          index=0, key=f"{kp}_rev")
    if isinstance(choice, int):
        try:
            ans = json.loads(recs[choice]["Answers"])
        except Exception:
            st.warning("لا توجد تفاصيل لهذا الاختبار.")
            ans = None
        if ans:
            qorder = {qid: i for i, qid in enumerate(qmap.keys())}
            ordered_answers = sorted(ans.items(), key=lambda item: qorder.get(item[0], 10**9))
            for n, (qid, (chosen, correct)) in enumerate(ordered_answers, 1):
                if qid not in qmap:
                    continue
                r = qmap[qid]
                with st.expander(f"{'✅' if chosen == correct else '❌'} {n}. {r['Question'][:55]}"):
                    st.markdown(f'<div class="ltr">{esc(r["Question"])}</div>', unsafe_allow_html=True)
                    if chosen != correct:
                        ct = f"{chosen}) {r['Option' + chosen]}" if chosen else "بدون إجابة"
                        st.markdown(f'<div class="ltr">❌ إجابتك: {esc(ct)}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="ltr">✅ {correct}) {esc(r["Option" + correct])}</div>',
                                unsafe_allow_html=True)
    else:
        st.caption("لن تظهر تفاصيل أي اختبار حتى تختار اختبارًا من القائمة.")

    st.divider()
    st.subheader("🤖 التحليل الذكي (AI)")
    if len(lsel) >= 3:
        st.caption(f"سيقوم Gemini بتحليل أدائك خلال {len(lsel)} محاولات.")
        report_key = f"ai_report_{kp}"
        if st.button("📊 توليد التقرير", type="primary", use_container_width=True, key=f"ai_btn_{kp}"):
            with st.spinner("جاري التحليل عبر Gemini..."):
                user_name = st.session_state.user["name"]
                wrong_texts = [f"- {qmap[qid]['Question']} (أخطأ {w} مرة)"
                               for qid, w in weak[:10] if qid in qmap]
                report = ai_analyze_lecture(user_name, subj, lec, lsel, wrong_texts)
                st.session_state[report_key] = report
        if st.session_state.get(report_key):
            st.markdown(st.session_state[report_key])
            if st.button("🗑️ حذف التقرير", key=f"del_ai_{kp}", use_container_width=True):
                       del st.session_state[report_key]
        st.rerun()
    else:
        remaining = 3 - len(lsel)
        st.info(f"💡 يحتاج التحليل إلى 3 محاولات على الأقل. تحتاج {remaining} محاولة إضافية.")

def history_section(df, rows, kp):
    if not rows:
        st.info("لا توجد اختبارات سابقة بعد.")
        return
    # Older sheets can contain repeated question text, which historically made
    # qid non-unique. Keep a safe mapping instead of crashing the admin history.
    qmap = df.drop_duplicates(subset=["qid"], keep="last").set_index("qid").to_dict("index")
    rdf = pd.DataFrame(rows)
    rdf["Percentage"] = pd.to_numeric(rdf["Percentage"], errors="coerce").fillna(0)
    allr = pd.DataFrame(all_results())
    allr["Percentage"] = pd.to_numeric(allr["Percentage"], errors="coerce").fillna(0)
    peer_s = allr.groupby("Subject")["Percentage"].mean().to_dict()
    peer_l = allr.groupby(["Subject", "Lecture"])["Percentage"].mean().to_dict()

    subjects = sorted(rdf["Subject"].unique(), key=nat_key)
    subj = st.selectbox("المادة", ["كل المواد"] + subjects, key=f"{kp}_subj")
    sel = rdf if subj == "كل المواد" else rdf[rdf["Subject"] == subj]

    c1, c2, c3 = st.columns(3)
    c1.metric("الاختبارات", len(sel))
    c2.metric("المتوسط", f"{sel['Percentage'].mean():.1f}%")
    c3.metric("الأفضل", f"{sel['Percentage'].max():.1f}%")
    if len(sel) > 1:
        st.line_chart(pd.DataFrame({"النسبة %": sel["Percentage"].tolist()}), height=160)

    if subj == "كل المواد":
        g = rdf.groupby("Subject")["Percentage"].agg(["count", "mean", "max"]).reset_index()
        g = g.sort_values("Subject", key=lambda s: s.map(nat_key))
        st.subheader("📚 أداؤك في كل مادة")
        with box():
            st.markdown(bars(g, "Subject", peer=peer_s), unsafe_allow_html=True)
        st.caption("العلامة الرمادية على الشريط = متوسط الزملاء. اختر مادة لترى كل محاضرة بتفاصيلها.")
        return

    g = sel.groupby("Lecture")["Percentage"].agg(["count", "mean", "max"]).reset_index()
    g = g.sort_values("Lecture", key=lambda s: s.map(nat_key))
    peer_lec = {lec: peer_l.get((subj, lec)) for lec in g["Lecture"]}
    peer_lec = {k: v for k, v in peer_lec.items() if v is not None}
    with box():
        st.markdown(bars(g, "Lecture", peer=peer_lec), unsafe_allow_html=True)

    st.subheader("🗂️ تفاصيل كل محاضرة")
    lectures = list(g["Lecture"])
    for tab, lec in zip(st.tabs(lectures), lectures):
        with tab:
            lsel = sel[sel["Lecture"] == lec]
            lecture_panel(lsel, qmap, f"{kp}_{subj}_{lec}", peer_l.get((subj, lec)), subj=subj, lec=lec)

# ====================== حسابي ======================
def avatar_html(row, name, size=64):
    uri = (row or {}).get("Avatar", "")
    if uri:
        return f'<img class="avatar" style="width:{size}px;height:{size}px" src="{uri}">'
    return (f'<div class="avatar" style="width:{size}px;height:{size}px;font-size:{size // 2}px">'
            f'{esc(name[:1].upper())}</div>')


def account_view(df):
    user = st.session_state.user
    name = user["name"]
    urow = user_row(name)
    rows = my_rows(name)
    pcts = [float(r["Percentage"] or 0) for r in rows]
    since = str(urow.get("Created", ""))[:10]
    with box():
        st.markdown(
            f'<div class="row">{avatar_html(urow, name)}'
            f'<div><div class="ttl" style="font-size:1.2rem">{esc(name)}'
            + ('<span class="chip c-mid">مشرف</span>' if is_admin(name) else "")
            + f'</div><div class="meta">{"عضو منذ " + since if since else "حساب مسجل"}</div>'
            f'<div style="margin-top:6px"><span class="chip c-new" style="margin:0">{len(rows)} اختبار</span>'
            + (f'<span class="chip c-ok">المتوسط {sum(pcts) / len(pcts):.0f}%</span>' if pcts else "")
            + "</div></div></div>",
            unsafe_allow_html=True,
        )

    t_hist, t_set = st.tabs(["📊 سجلي", "⚙️ الإعدادات"])
    with t_hist:
        history_section(df, rows, "me")

    with t_set:
        st.subheader("صورة الحساب")
        up = st.file_uploader("اختر صورة", type=["png", "jpg", "jpeg", "webp"], key="av_up")
        b1, b2 = st.columns(2)
        if b1.button("حفظ الصورة", type="primary", use_container_width=True, disabled=up is None):
            try:
                set_avatar(name, prep_image(up, "avatar"))
                st.rerun()
            except Exception as e:
                st.error(f"تعذر حفظ الصورة: {e}")
        if b2.button("إزالة الصورة", use_container_width=True, disabled=not urow.get("Avatar")):
            set_avatar(name, "")
            st.rerun()

        st.divider()
        st.subheader("تغيير الاسم")
        if is_admin(name):
            st.caption("حساب المشرف لا يغيّر اسمه حتى لا تفقد الصلاحية.")
        else:
            new_name = st.text_input("الاسم الجديد", value=name, key="new_name")
            if st.button("حفظ الاسم", use_container_width=True):
                if new_name.strip() == name:
                    st.info("لم يتغير شيء.")
                else:
                    try:
                        ok, msg = rename_user(name, new_name)
                    except Exception as e:
                        ok, msg = False, f"تعذر الاتصال: {e}"
                    if ok:
                        st.session_state.user["name"] = new_name.strip()
                        st.rerun()
                    else:
                        st.error(msg)

        st.divider()
        st.subheader("تغيير كلمة المرور")
        with st.form("pw_form", clear_on_submit=True):
            old = st.text_input("كلمة المرور الحالية", type="password")
            new = st.text_input("كلمة المرور الجديدة (4 أحرف فأكثر)", type="password")
            new2 = st.text_input("أعد كتابة الجديدة", type="password")
            ok = st.form_submit_button("حفظ", type="primary", use_container_width=True)
        if ok:
            if len(new) < 4:
                st.warning("كلمة المرور الجديدة قصيرة (4 أحرف على الأقل).")
            elif new != new2:
                st.warning("كلمتا المرور الجديدتان غير متطابقتين.")
            else:
                try:
                    done, msg = change_password(name, old, new)
                except Exception as e:
                    done, msg = False, f"تعذر الاتصال: {e}"
                if done:
                    st.success("تم تغيير كلمة المرور ✅")
                else:
                    st.error(msg)
        st.divider()
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            try:
                i, row = find_user(name)
                if row:
                    set_remember_token(name, "")
                if cookie_manager:
                    cookie_manager.delete("hiht_remember")
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()


# ====================== لوحة المشرف ======================
def admin_view(df):
    t_over, t_users, t_materials, t_csv, t_img, t_cleanup = st.tabs(["📈 نظرة عامة", "👥 المستخدمون", "📚 إدارة المواد", "📄 استيراد CSV/Excel", "🖼️ الصور", "🧹 حذف النتائج"])
    allr = pd.DataFrame(all_results())
    if not allr.empty:
        allr["Percentage"] = pd.to_numeric(allr["Percentage"], errors="coerce").fillna(0)
    accounts = users_table()
    guests = sorted({str(n) for n in allr["Name"] if str(n).startswith(GUEST_PREFIX)}) if not allr.empty else []

    with t_over:
        k1, k2 = st.columns(2)
        k1.metric("الحسابات المسجلة", len(accounts))
        k2.metric("الضيوف", len(guests))
        k3, k4 = st.columns(2)
        k3.metric("إجمالي الاختبارات", len(allr))
        k4.metric("المتوسط العام", f"{allr['Percentage'].mean():.1f}%" if not allr.empty else "—")
        if allr.empty:
            st.info("لا توجد نتائج بعد.")
        else:
            st.subheader("⚖️ مقارنة المواد")
            g = allr.groupby("Subject")["Percentage"].agg(["count", "mean", "max"]).reset_index()
            ppl = allr.groupby("Subject")["Name"].nunique().to_dict()
            with box():
                st.markdown(bars(g, "Subject", extra={k: f"{v} مشارك" for k, v in ppl.items()}),
                            unsafe_allow_html=True)
            subj = st.selectbox("تفصيل مادة", sorted(allr["Subject"].unique(), key=nat_key), key="adm_ov_subj")
            gl = allr[allr["Subject"] == subj].groupby("Lecture")["Percentage"].agg(["count", "mean", "max"]).reset_index()
            gl = gl.sort_values("Lecture", key=lambda s: s.map(nat_key))
            pl = allr[allr["Subject"] == subj].groupby("Lecture")["Name"].nunique().to_dict()
            with box():
                st.markdown(bars(gl, "Lecture", extra={k: f"{v} مشارك" for k, v in pl.items()}),
                            unsafe_allow_html=True)
            st.subheader("🧮 متوسط كل مستخدم في كل مادة")
            piv = allr.pivot_table(index="Name", columns="Subject", values="Percentage", aggfunc="mean").round(1)
            st.dataframe(piv, use_container_width=True)

    with t_users:
        recs = []
        for u in accounts:
            n = str(u["Username"]).strip()
            mine = allr[allr["Name"] == n] if not allr.empty else pd.DataFrame()
            recs.append({
                "المستخدم": n, "الانضمام": str(u.get("Created", ""))[:10],
                "الاختبارات": len(mine),
                "المتوسط %": round(mine["Percentage"].mean(), 1) if len(mine) else None,
                "آخر نشاط": mine["Timestamp"].max() if len(mine) else "",
                "صورة": "✓" if u.get("Avatar") else "",
            })
        st.subheader(f"الحسابات ({len(recs)})")
        if recs:
            st.dataframe(pd.DataFrame(recs), use_container_width=True, hide_index=True)
        if guests:
            with st.expander(f"الضيوف ({len(guests)})"):
                grec = []
                for gname in guests:
                    mine = allr[allr["Name"] == gname]
                    grec.append({"الضيف": gname.replace(GUEST_PREFIX, ""), "الاختبارات": len(mine),
                                 "المتوسط %": round(mine["Percentage"].mean(), 1),
                                 "آخر نشاط": mine["Timestamp"].max()})
                st.dataframe(pd.DataFrame(grec), use_container_width=True, hide_index=True)

        st.subheader("🔎 عرض مستخدم")
        names = [str(u["Username"]).strip() for u in accounts] + guests
        if not names:
            return
        who = st.selectbox("اختر مستخدمًا", names, key="adm_user")
        urow = user_row(who)
        with box():
            st.markdown(
                f'<div class="row">{avatar_html(urow, who.replace(GUEST_PREFIX, ""), 56)}'
                f'<div><div class="ttl">{esc(who)}</div>'
                f'<div class="meta">{"عضو منذ " + str(urow.get("Created", ""))[:10] if urow else "ضيف (بدون حساب)"}</div></div></div>',
                unsafe_allow_html=True)
        history_section(df, my_rows(who), f"adm_{who}")

        if urow and not is_admin(who):
            with st.expander("⚙️ إدارة هذا الحساب"):
                tmp = st.text_input("كلمة مرور جديدة للمستخدم", type="password", key=f"adm_pw_{who}")
                if st.button("إعادة تعيين كلمة المرور", key=f"adm_rst_{who}"):
                    if len(tmp) < 4:
                        st.warning("4 أحرف على الأقل.")
                    else:
                        i, r = find_user(who)
                        if r:
                            set_password(i, tmp)
                            st.success("تم التغيير. أبلغ المستخدم بكلمته الجديدة.")
                st.divider()
                sure = st.checkbox("أؤكد حذف هذا الحساب (لن يتمكن من الدخول، وتبقى نتائجه في الجدول)",
                                   key=f"adm_ok_{who}")
                if st.button("🗑️ حذف الحساب", disabled=not sure, key=f"adm_del_{who}"):
                    delete_user(who)
                    st.success("تم حذف الحساب.")
                    st.rerun()

    with t_materials:
        st.subheader("إضافة مادة أو تعديلها")
        st.caption("تُحفظ الإعدادات في Google Sheets. إعادة تسمية مادة هنا لا تعدّل ملف الأسئلة الأصلي، بل تُطبّق اسم العرض والفصل داخل الموقع.")
        current = load_materials()
        existing = sorted(set(df["Subject"].unique()).union(str(r.get("Subject", "")) for r in current), key=nat_key)
        mode = st.radio("الإجراء", ["إضافة مادة", "تعديل مادة"], horizontal=True, key="mat_mode")
        if mode == "تعديل مادة" and existing:
            selected = st.selectbox("المادة", existing, key="mat_selected")
            matched = next((r for r in current if str(r.get("Subject", "")).strip() == selected), None)
            original = str(matched.get("OriginalSubject", selected)) if matched else selected
            default_name = selected
            default_sem = str(matched.get("Semester", "First Semester")) if matched else ("Second Semester" if (not df[df["Subject"] == selected].empty and int(df[df["Subject"] == selected]["SemN"].iloc[0]) == 2) else "First Semester")
        else:
            selected = ""
            original = ""
            default_name = ""
            default_sem = "First Semester"
        with st.form("material_form"):
            original_input = st.text_input("المادة الأصلية (لربطها بأسئلتها الحالية)", value=original,
                                           help="للمادة الموجودة، اترك الاسم الأصلي كما هو. للمادة الجديدة، استخدم اسم المادة الجديد.")
            display_name = st.text_input("اسم المادة الظاهر للمستخدم", value=default_name)
            semester = st.selectbox("الفصل الدراسي", SEMESTERS, index=1 if "second" in default_sem.lower() or default_sem == "2" or "ثان" in default_sem else 0)
            active = st.checkbox("إظهار المادة في الموقع", value=True)
            save_mat = st.form_submit_button("حفظ المادة", type="primary", use_container_width=True)
        if save_mat:
            if not original_input.strip() or not display_name.strip():
                st.error("أدخل اسم المادة الأصلية واسم العرض.")
            else:
                try:
                    save_material(original_input.strip(), display_name.strip(), semester, "1" if active else "0")
                    st.success("تم حفظ إعدادات المادة.")
                    st.rerun()
                except Exception as e:
                    st.error(f"تعذر حفظ المادة: {e}")
        if current:
            st.divider()
            st.markdown("**المواد المسجلة في إعدادات الموقع**")
            st.dataframe(pd.DataFrame(current), use_container_width=True, hide_index=True)
            st.markdown("**حذف مادة تجريبية أو إزالة إعداداتها**")
            st.caption("هذا يحذف سجل المادة من ورقة Materials فقط، ولا يحذف أسئلة المصدر الأصلي أو نتائج الاختبارات. لحذف الأسئلة المستوردة أيضًا استخدم تبويب حذف النتائج.")
            deletable = sorted({str(r.get("Subject", "")).strip(): str(r.get("OriginalSubject", "")).strip() for r in current if str(r.get("Subject", "")).strip()}.items(), key=lambda x: nat_key(x[0]))
            if deletable:
                labels = [f"{name} — المصدر: {orig}" for name, orig in deletable]
                chosen_label = st.selectbox("المادة التي تريد إزالة إعداداتها", labels, key="delete_material_mapping_select")
                chosen_name, chosen_original = deletable[labels.index(chosen_label)]
                confirm_material_delete = st.checkbox(f"أؤكد إزالة إعدادات مادة {chosen_name}", key="confirm_delete_material_mapping")
                if st.button("🗑️ حذف إعدادات المادة", disabled=not confirm_material_delete, key="delete_material_mapping_button"):
                    try:
                        removed = delete_material_mapping(chosen_original)
                        # Also remove the custom cover image for the displayed subject.
                        del_asset(f"subj:{chosen_name}")
                        st.success(f"تمت إزالة {removed} من سجلات إعدادات المادة. لم تُحذف الأسئلة الأصلية أو النتائج.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"تعذر حذف إعدادات المادة: {exc}")

    with t_csv:
        st.subheader("تحويل CSV أو Excel إلى أسئلة اختبار")
        st.markdown("ارفع ملف CSV أو Excel يحتوي على الأعمدة `Question`, `OptionA`, `OptionB`, `OptionC`, `OptionD`, `Correct`. يمكن أيضًا استخدام أسماء عربية مثل `السؤال` و`الإجابة الصحيحة`. قيمة `Correct` تكون A أو B أو C أو D.")
        csv_subject = st.text_input("اسم المادة", key="csv_subject")
        csv_lecture = st.text_input("اسم المحاضرة / الفصل", key="csv_lecture", value="Lecture 1")
        csv_semester = st.selectbox("الفصل الدراسي", SEMESTERS, key="csv_semester")
        csv_file = st.file_uploader("ملف الأسئلة CSV أو Excel", type=["csv", "xlsx", "xls"], key="csv_file")
        if st.button("استيراد الأسئلة", type="primary", disabled=(csv_file is None or not csv_subject.strip() or not csv_lecture.strip()), use_container_width=True):
            try:
                count = persist_csv_questions(csv_file, csv_subject.strip(), csv_lecture.strip(), csv_semester)
                save_material(csv_subject.strip(), csv_subject.strip(), csv_semester, "1")
                st.success(f"تم استيراد {count} سؤالًا. ستدخل في الاختبارات والتصحيح وسجل النتائج كالمعتاد.")
                st.rerun()
            except Exception as e:
                st.error(f"تعذر استيراد الملف: {e}")
        st.caption("الاستيراد يضيف الأسئلة ولا يحذف الأسئلة السابقة. افحص أسماء الأعمدة ومفاتيح الإجابة قبل الرفع.")

    with t_cleanup:
        st.subheader("حذف أسئلة استوردتها بالخطأ")
        st.caption("هذا القسم يحذف الأسئلة التي أُضيفت عبر استيراد CSV/Excel إلى ورقة QuestionBank فقط، ولا يحذف أسئلة المصدر الأصلي MCQ.")
        local_rows = local_question_rows()
        if local_rows:
            local_df = pd.DataFrame(local_rows).fillna("")
            for col in ["Semester", "Subject", "Lecture"]:
                if col not in local_df.columns:
                    local_df[col] = ""
            sem_choices = sorted(local_df["Semester"].astype(str).str.strip().unique(), key=nat_key)
            del_sem = st.selectbox("الفصل الدراسي للأسئلة المستوردة", sem_choices, key="del_q_sem")
            subject_choices = sorted(local_df[local_df["Semester"].astype(str).str.strip() == del_sem]["Subject"].astype(str).str.strip().unique(), key=nat_key)
            del_subject = st.selectbox("المادة", subject_choices, key="del_q_subject") if subject_choices else None
            lecture_choices = sorted(local_df[(local_df["Semester"].astype(str).str.strip() == del_sem) & (local_df["Subject"].astype(str).str.strip() == del_subject)]["Lecture"].astype(str).str.strip().unique(), key=nat_key) if del_subject else []
            del_lecture_mode = st.radio("نطاق حذف الأسئلة", ["المادة كاملة في هذا الفصل", "محاضرة محددة فقط"], horizontal=True, key="del_q_scope")
            del_lecture = st.selectbox("المحاضرة", lecture_choices, key="del_q_lecture") if del_lecture_mode == "محاضرة محددة فقط" and lecture_choices else None
            preview = local_df[(local_df["Semester"].astype(str).str.strip() == del_sem) & (local_df["Subject"].astype(str).str.strip() == del_subject)]
            if del_lecture_mode == "محاضرة محددة فقط" and del_lecture is not None:
                preview = preview[preview["Lecture"].astype(str).str.strip() == del_lecture]
            st.warning(f"سيتم حذف {len(preview)} سؤالًا من بنك الأسئلة المحلي. هذا لا يحذف نتائج الاختبارات السابقة.")
            confirm_q_delete = st.checkbox("أؤكد حذف هذه الأسئلة نهائيًا", key="del_q_confirm")
            if st.button("🗑️ حذف الأسئلة المحددة", disabled=not confirm_q_delete or not del_subject, key="del_q_btn"):
                try:
                    removed_q = delete_question_bank_rows(subject=del_subject, lecture=del_lecture if del_lecture_mode == "محاضرة محددة فقط" else None, semester=del_sem)
                    st.success(f"تم حذف {removed_q} سؤالًا من بنك الأسئلة المحلي.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"تعذر حذف الأسئلة: {exc}")
        else:
            st.info("لا توجد أسئلة مستوردة في QuestionBank.")

        st.divider()
        st.subheader("حذف أو تصفير نتائج الاختبارات")
        st.warning("الحذف نهائي من سجل النتائج. اختر نطاقًا محددًا وراجع الاختيار قبل التأكيد.")
        cleanup_scope = st.radio("ما الذي تريد حذفه؟",
            ["اختبارات مستخدم محدد", "نتائج مادة كاملة", "اختبار/محاضرة لمستخدم محدد", "كل النتائج"],
            key="cleanup_scope")
        all_names = sorted({str(r.get("Name", "")).strip() for r in allr.to_dict("records") if str(r.get("Name", "")).strip()}) if not allr.empty else []
        all_subjects = sorted({str(r.get("Subject", "")).strip() for r in allr.to_dict("records") if str(r.get("Subject", "")).strip()}) if not allr.empty else []
        chosen_name = None
        chosen_subject = None
        chosen_lecture = None
        if cleanup_scope in ["اختبارات مستخدم محدد", "اختبار/محاضرة لمستخدم محدد"]:
            if all_names:
                chosen_name = st.selectbox("المستخدم", all_names, key="cleanup_name")
            else:
                st.info("لا توجد نتائج لحذفها.")
        if cleanup_scope in ["نتائج مادة كاملة", "اختبار/محاضرة لمستخدم محدد"]:
            if all_subjects:
                chosen_subject = st.selectbox("المادة", all_subjects, key="cleanup_subject")
        if cleanup_scope == "اختبار/محاضرة لمستخدم محدد" and chosen_name and chosen_subject:
            lectures = sorted({str(r.get("Lecture", "")).strip() for r in allr.to_dict("records")
                               if str(r.get("Name", "")).strip() == chosen_name and str(r.get("Subject", "")).strip() == chosen_subject},
                              key=nat_key)
            if lectures:
                chosen_lecture = st.selectbox("الاختبار / المحاضرة", lectures, key="cleanup_lecture")
        confirm_cleanup = st.checkbox("أؤكد أنني أريد حذف النتائج المحددة نهائيًا", key="cleanup_confirm")
        if st.button("🗑️ حذف النتائج المحددة", type="primary", disabled=not confirm_cleanup, key="cleanup_delete"):
            try:
                if cleanup_scope == "اختبارات مستخدم محدد":
                    removed = delete_result_rows(name=chosen_name)
                elif cleanup_scope == "نتائج مادة كاملة":
                    removed = delete_result_rows(subject=chosen_subject)
                elif cleanup_scope == "اختبار/محاضرة لمستخدم محدد":
                    removed = delete_result_rows(name=chosen_name, subject=chosen_subject, lecture=chosen_lecture)
                else:
                    removed = delete_result_rows()
                st.success(f"تم حذف {removed} نتيجة.")
                st.rerun()
            except Exception as exc:
                st.error(f"تعذر حذف النتائج: {exc}")

    with t_img:
        assets = safe_assets()
        st.subheader("شعار المعهد")
        st.caption("يظهر في أعلى الموقع وكأيقونة التبويب.")
        if assets.get("logo"):
            st.markdown(f'<img class="hero-logo" style="border:1px solid #ddd" src="{assets["logo"]}">',
                        unsafe_allow_html=True)
        up = st.file_uploader("ارفع الشعار", type=["png", "jpg", "jpeg", "webp"], key="logo_up")
        c1, c2 = st.columns(2)
        if c1.button("حفظ الشعار", type="primary", disabled=up is None, use_container_width=True):
            try:
                set_asset("logo", prep_image(up, "logo"))
                st.rerun()
            except Exception as e:
                st.error(f"تعذر الحفظ: {e}")
        if c2.button("حذف الشعار", disabled="logo" not in assets, use_container_width=True):
            del_asset("logo")
            st.rerun()

        st.divider()
        st.subheader("صور المواد")
        all_subject_names = sorted(set(df["Subject"].unique()).union(str(r.get("Subject", "")) for r in load_materials()), key=nat_key)
        subj = st.selectbox("المادة", all_subject_names, key="img_subj")
        key = f"subj:{subj}"
        if assets.get(key):
            st.markdown(f'<img style="width:100%;border-radius:16px" src="{assets[key]}">',
                        unsafe_allow_html=True)
        up2 = st.file_uploader("ارفع صورة المادة", type=["png", "jpg", "jpeg", "webp"], key="subj_up")
        d1, d2 = st.columns(2)
        if d1.button("حفظ صورة المادة", type="primary", disabled=up2 is None, use_container_width=True):
            try:
                set_asset(key, prep_image(up2, "cover"))
                st.rerun()
            except Exception as e:
                st.error(f"تعذر الحفظ: {e}")
        if d2.button("حذف صورة المادة", disabled=key not in assets, use_container_width=True):
            del_asset(key)
            st.rerun()


# ====================== التشغيل ======================
# Persistent browser cookie for the optional "remember me" feature.
try:
    cookie_manager = stx.CookieManager(key="hiht_cookie_manager")
    cookie_token = cookie_manager.get("hiht_remember")
except Exception:
    cookie_manager = None
    cookie_token = None

if "user" not in st.session_state and cookie_token:
    try:
        remembered = login_by_token(cookie_token)
        if remembered:
            st.session_state.user = {"name": remembered, "account": True}
    except Exception:
        pass

if "welcome_seen" not in st.session_state and "user" not in st.session_state:
    logo = safe_assets().get("logo")
    logo_html = f'<img src="{logo}" style="width:120px;height:120px;object-fit:contain;background:#fff;border-radius:24px;padding:10px;box-shadow:0 6px 20px rgba(0,0,0,.25);margin-bottom:14px;">' if logo else '<div style="font-size:4rem">🧪</div>'
    st.markdown(f'<div class="welcome">{logo_html}<h1>{esc(APP_TITLE)}</h1><p>اختبارات تفاعلية لمراجعة المحاضرات</p><div class="created">Created by {esc(CREATOR)}</div></div>', unsafe_allow_html=True)
    if st.button("دخول", type="primary", use_container_width=True):
        st.session_state.welcome_seen = True
        st.rerun()
    st.stop()

if "user" not in st.session_state:
    gate()
    st.stop()

try:
    questions = load_questions()
except Exception as e:
    st.error(f"تعذر تحميل الأسئلة: {e}")
    st.stop()

user = st.session_state.user
if user["account"]:
    try:
        known = {str(r["Username"]).strip().lower() for r in users_table()}
        if known and user["name"].lower() not in known:
            st.session_state.clear()
            st.session_state["kicked"] = True
            st.rerun()
    except Exception:
        pass

if user.get("account") and not st.session_state.get("quiz"):
    try:
        draft = get_draft(user["name"])
        if draft:
            st.session_state.quiz, st.session_state.quiz_answers = draft
            st.session_state.view = "quiz"
    except Exception:
        pass

st.session_state.setdefault("view", "home")
hero(f"أهلًا {user['name'].replace(GUEST_PREFIX, '')} 👋")

tab = "🏠 الرئيسية"
if user["account"]:
    tabs_list = ["🏠 الرئيسية", "👤 حسابي"] + (["🛠️ المشرف"] if is_admin(user["name"]) else [])
    with st.container(key="nav"):
        tab = st.radio("nav", tabs_list, horizontal=True, label_visibility="collapsed")

if tab.startswith("👤"):
    account_view(questions)
elif tab.startswith("🛠️"):
    admin_view(questions)
else:
    view = st.session_state.view
    if view == "subject":
        subject_view(questions)
    elif view == "setup":
        setup_view(questions)
    elif view == "quiz":
        quiz_view(questions)
    elif view == "result":
        result_view()
    else:
        home_view(questions)

if not user["account"]:
    st.write("")
    if st.button("🚪 خروج"):
        st.session_state.clear()
        st.rerun()

st.markdown(f'<div class="foot">{esc(APP_TITLE)} · Created by {esc(CREATOR)}</div>',
            unsafe_allow_html=True)
