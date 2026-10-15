import base64
import hashlib
import html
import json
import random
import re
import secrets as pysecrets
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# ====================== الإعدادات ======================
RESULTS_SHEET_ID = "1l5QPU0VU0JMMLYjKTSCDdOqe0uX5ceiBtAEUKXeSl8k"
QUESTIONS_SHEET_ID = "1n_erWCal8TKgsc2muduRm-uREMlZMTvdVZQfbq4AJic"
QUESTIONS_TAB = "MCQ"
APP_TITLE = "HIHT Alsaiegh Quiz"
APP_SUBTITLE = "منصة الاختبارات التفاعلية"
TZ = ZoneInfo("Asia/Baghdad")
BASE = Path(__file__).parent
LETTERS = ["A", "B", "C", "D"]
ALL = "__ALL__"
PALETTE = [("#6C5CE7", "#a29bfe"), ("#00b894", "#55efc4"), ("#e17055", "#fab1a0"),
           ("#0984e3", "#74b9ff"), ("#e84393", "#fd79a8"), ("#f39c12", "#fdcb6e"),
           ("#00cec9", "#81ecec")]
EMOJIS = ["🧬", "🧪", "💉", "🩸", "🔬", "🧫", "⚗️", "🦠", "💊"]
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "webp": "image/webp", "svg": "image/svg+xml"}

st.set_page_config(page_title=APP_TITLE, page_icon="🧪", layout="centered")
st.markdown(
    """
<style>
@import url('https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;700&display=swap');
.stApp, .stApp p, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp label,
.stApp button, .stApp input, .stApp [data-testid="stMarkdownContainer"] {
  font-family: 'Cairo', sans-serif;
}
.stApp {direction: rtl;}
#MainMenu, footer, header[data-testid="stHeader"] {display: none;}
.block-container {padding-top: 1.4rem; padding-bottom: 3rem; max-width: 720px;}
.ltr {direction: ltr; text-align: left;}
div[role="radiogroup"] {direction: ltr; text-align: left;}

.hero {position: relative; overflow: hidden; color: #fff; padding: 20px 22px;
  border-radius: 24px; margin-bottom: 14px;
  background: linear-gradient(135deg,#4834d4,#6C5CE7 55%,#a29bfe);
  box-shadow: 0 10px 26px rgba(108,92,231,.30);}
.hero::before {content:""; position:absolute; width:190px; height:190px; border-radius:50%;
  background: rgba(255,255,255,.10); top:-70px; left:-50px;}
.hero::after {content:""; position:absolute; width:110px; height:110px; border-radius:50%;
  background: rgba(255,255,255,.08); bottom:-45px; right:30%;}
.hero-in {display:flex; gap:14px; align-items:center; position:relative; z-index:1;}
.hero-logo {width:64px; height:64px; border-radius:18px; background:#fff; object-fit:contain;
  padding:6px; flex-shrink:0; box-shadow: 0 4px 12px rgba(0,0,0,.18);}
.hero-emoji {display:flex; align-items:center; justify-content:center; font-size:32px;}
.hero-t {font-size:1.3rem; font-weight:700; line-height:1.2; direction:ltr; text-align:right;}
.hero-s {opacity:.92; font-size:.92rem; margin-top:3px;}

.row {display:flex; gap:14px; align-items:center; padding: 2px 0 4px 0;}
.ico {width:54px; height:54px; border-radius:16px; display:flex; align-items:center;
  justify-content:center; font-size:26px; font-weight:700; color:#fff; flex-shrink:0;}
.ico-img {width:54px; height:54px; border-radius:16px; object-fit:cover; flex-shrink:0;}
.ttl {font-weight:700; font-size:1.05rem; line-height:1.35;}
.meta {opacity:.65; font-size:.85rem; margin-top:2px;}
.chip {display:inline-block; padding:1px 10px; border-radius:999px; font-size:.76rem;
  font-weight:700; margin-inline-start:6px;}
.c-ok {background:rgba(0,184,148,.18); color:#00a383;}
.c-mid {background:rgba(243,156,18,.2); color:#d68910;}
.c-low {background:rgba(225,112,85,.2); color:#d9534f;}
.c-new {background:rgba(128,128,128,.18);}

.cover {height:150px; border-radius:22px; background-size:cover; background-position:center;
  display:flex; flex-direction:column; justify-content:flex-end; padding:16px; color:#fff;
  margin: 6px 0 12px 0; box-shadow: 0 8px 22px rgba(0,0,0,.15);}
.cover-t {font-size:1.35rem; font-weight:700; text-shadow: 0 2px 8px rgba(0,0,0,.4);}
.cover-m {opacity:.92; font-size:.88rem;}

.avatar {width:64px; height:64px; border-radius:50%; display:flex; align-items:center;
  justify-content:center; font-size:1.7rem; font-weight:700; color:#fff; flex-shrink:0;
  background: linear-gradient(135deg,#6C5CE7,#a29bfe);}

.srow {margin: 6px 0 12px 0;}
.srow-h {display:flex; justify-content:space-between; align-items:baseline; gap:8px;}
.srow-h b {font-size:1rem;}
.bar {height:8px; border-radius:999px; background: rgba(128,128,128,.2); margin-top:5px; overflow:hidden;}
.bar i {display:block; height:100%; border-radius:999px;}

.stApp [data-testid="stBaseButton-primary"], .stApp button[kind="primary"] {
  background: linear-gradient(135deg,#6C5CE7,#8e7cff); border: 0; border-radius: 14px; color:#fff;}
.stApp [data-testid="stBaseButton-secondary"], .stApp button[kind="secondary"] {border-radius: 14px;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 18px;}

.st-key-nav div[role="radiogroup"] {direction: rtl; gap: 8px;}
.st-key-nav div[role="radiogroup"] label {background: rgba(128,128,128,.14);
  padding: 6px 20px; border-radius: 999px; cursor: pointer;}
.st-key-nav div[role="radiogroup"] label > :not(:last-child) {display: none !important;}
.st-key-nav div[role="radiogroup"] label:has(input:checked) {background:#6C5CE7;}
.st-key-nav div[role="radiogroup"] label:has(input:checked) p {color:#fff !important;}

.st-key-quiz_form div[role="radiogroup"] label {background: rgba(128,128,128,.09);
  padding: 9px 12px; border-radius: 12px; margin-bottom: 6px; width: 100%;}
.st-key-quiz_form div[role="radiogroup"] label:has(input:checked) {
  background: rgba(108,92,231,.22); outline: 2px solid #6C5CE7;}

.ring {position: relative; width: 150px; height: 150px; margin: 6px auto 4px auto;}
.ring-bg {position:absolute; inset:0; border-radius:50%;
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 14px), #000 calc(100% - 13px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 14px), #000 calc(100% - 13px));}
.ring-txt {position:absolute; inset:0; display:flex; flex-direction:column;
  align-items:center; justify-content:center;}
.ring-p {font-size: 2rem; font-weight: 700; line-height: 1;}
.ring-s {opacity:.65; font-size:.85rem; margin-top: 4px;}
.msg {text-align:center; font-size:1.1rem; font-weight:700; margin-bottom: 10px;}
</style>
""",
    unsafe_allow_html=True,
)


# ====================== أدوات مساعدة ======================
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


@st.cache_data
def file_data_uri(path_str):
    p = Path(path_str)
    ext = p.suffix.lower().lstrip(".")
    return f"data:{MIME.get(ext, 'image/png')};base64," + base64.b64encode(p.read_bytes()).decode()


def find_image(*parts, stem):
    folder = BASE.joinpath(*parts) if parts else BASE
    for ext in ("png", "jpg", "jpeg", "webp", "svg"):
        p = folder / f"{stem}.{ext}"
        if p.exists():
            return file_data_uri(str(p))
    return None


def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def subject_img(subj):
    return find_image("images", stem=slug(subj))


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


# ====================== الاتصال بـ Google Sheets ======================
@st.cache_resource
def get_book():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"],
    )
    return gspread.authorize(creds).open_by_key(RESULTS_SHEET_ID)


def users_ws():
    book = get_book()
    try:
        return book.worksheet("Users")
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet("Users", rows=200, cols=4)
        ws.append_row(["Username", "Salt", "Hash", "Created"])
        return ws


def user_records():
    return users_ws().get_all_records(numericise_ignore=["all"])


@st.cache_data(ttl=300)
def load_questions():
    url = (
        f"https://docs.google.com/spreadsheets/d/{QUESTIONS_SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={QUESTIONS_TAB}"
    )
    df = pd.read_csv(url, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    df = df[df["Question"].str.strip() != ""].copy()
    for c in ("Subject", "Lecture", "Correct"):
        df[c] = df[c].str.strip()
    df["Correct"] = df["Correct"].str.upper()
    df["qid"] = df["Question"].apply(lambda q: hashlib.md5(q.strip().encode()).hexdigest()[:8])
    return df.reset_index(drop=True)


@st.cache_data(ttl=20)
def all_results():
    try:
        return get_book().sheet1.get_all_records()
    except Exception:
        return []


def my_rows(name):
    return [r for r in all_results() if str(r.get("Name", "")).strip() == name]


# ====================== الحسابات ======================
def hash_pw(pw, salt_hex):
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000).hex()


def register(username, pw):
    ws = users_ws()
    existing = [u.strip().lower() for u in ws.col_values(1)[1:]]
    if username.lower() in existing:
        return False, "هذا الاسم مستخدم، اختر اسمًا آخر."
    salt = pysecrets.token_hex(16)
    ws.append_row(
        [username, salt, hash_pw(pw, salt), datetime.now(TZ).strftime("%Y-%m-%d")],
        value_input_option="RAW",
    )
    return True, ""


def login(username, pw):
    for r in user_records():
        if str(r["Username"]).strip().lower() == username.lower():
            if hash_pw(pw, str(r["Salt"])) == str(r["Hash"]):
                return str(r["Username"]).strip()
            return None
    return None


def change_password(username, old, new):
    ws = users_ws()
    for i, r in enumerate(user_records(), start=2):
        if str(r["Username"]).strip().lower() == username.lower():
            if hash_pw(old, str(r["Salt"])) != str(r["Hash"]):
                return False, "كلمة المرور الحالية غير صحيحة."
            salt = pysecrets.token_hex(16)
            ws.update(range_name=f"B{i}:C{i}", values=[[salt, hash_pw(new, salt)]], raw=True)
            return True, ""
    return False, "الحساب غير موجود."


@st.cache_data(ttl=120)
def joined_date(username):
    try:
        for r in user_records():
            if str(r["Username"]).strip().lower() == username.lower():
                return str(r.get("Created", ""))[:10]
    except Exception:
        pass
    return ""


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
    logo = find_image(stem="logo")
    img = (f'<img class="hero-logo" src="{logo}">' if logo
           else '<div class="hero-logo hero-emoji">🧪</div>')
    st.markdown(
        f'<div class="hero"><div class="hero-in">{img}<div>'
        f'<div class="hero-t">{esc(APP_TITLE)}</div><div class="hero-s">{esc(sub)}</div>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )


def back_button(label, view, **kw):
    if st.button(f"→ {label}"):
        go(view, **kw)


def bars(df_g, label_col):
    """df_g: columns [label_col, count, mean, max] -> HTML bars"""
    out = ""
    for _, r in df_g.iterrows():
        avg, best, n = round(float(r["mean"]), 1), float(r["max"]), int(r["count"])
        out += (
            f'<div class="srow"><div class="srow-h"><span class="ttl">{esc(r[label_col])}</span>'
            f'<b style="color:{pct_color(avg)}">{avg:g}%</b></div>'
            f'<div class="meta">{n} اختبار · أفضل نتيجة {best:g}%</div>'
            f'<div class="bar"><i style="width:{min(avg, 100)}%;background:{pct_color(avg)}"></i></div></div>'
        )
    return out


def gate():
    hero(APP_SUBTITLE)
    t_guest, t_login, t_reg = st.tabs(["ضيف", "تسجيل الدخول", "حساب جديد"])

    with t_guest:
        st.caption("تصل نتيجتك للمشرف، لكن لا يُحفظ لك سجل.")
        name = st.text_input("اسمك", key="guest_name")
        if st.button("ابدأ كضيف", type="primary", use_container_width=True):
            if name.strip():
                st.session_state.user = {"name": f"ضيف - {name.strip()}", "account": False}
                st.rerun()
            else:
                st.warning("اكتب اسمك أولًا.")

    with t_login:
        u = st.text_input("اسم المستخدم", key="login_u")
        p = st.text_input("كلمة المرور", type="password", key="login_p")
        if st.button("دخول", type="primary", use_container_width=True):
            try:
                found = login(u.strip(), p)
            except Exception as e:
                st.error(f"تعذر الاتصال: {e}")
                found = None
            if found:
                st.session_state.user = {"name": found, "account": True}
                st.rerun()
            else:
                st.error("اسم المستخدم أو كلمة المرور غير صحيحة.")

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


# ====================== الرئيسية: المواد ======================
def home_view(df):
    user = st.session_state.user
    counts = Counter()
    if user["account"]:
        for r in my_rows(user["name"]):
            counts[r["Subject"]] += 1

    st.subheader("المواد")
    subjects = sorted(df["Subject"].unique(), key=nat_key)
    cols = st.columns(2)
    for i, subj in enumerate(subjects):
        sub_df = df[df["Subject"] == subj]
        c1, c2 = pick(subj, PALETTE)
        chip = f'<span class="chip c-new">{counts[subj]} اختبار</span>' if counts[subj] else ""
        with cols[i % 2]:
            with st.container(border=True):
                st.markdown(
                    card(pick(subj, EMOJIS), c1, c2, subj,
                         f"{sub_df['Lecture'].nunique()} محاضرات · {len(sub_df)} سؤال",
                         chip, subject_img(subj)),
                    unsafe_allow_html=True,
                )
                if st.button("فتح", key=f"subj_{i}", use_container_width=True):
                    go("subject", subject=subj)


# ====================== المادة: المحاضرات ======================
def subject_view(df):
    user = st.session_state.user
    subj = st.session_state.subject
    sub_df = df[df["Subject"] == subj]
    c1, c2 = pick(subj, PALETTE)
    back_button("المواد", "home")

    img = subject_img(subj)
    bg = (f"linear-gradient(to top, rgba(0,0,0,.70), rgba(0,0,0,.08)), url({img})" if img
          else f"linear-gradient(135deg,{c1},{c2})")
    st.markdown(
        f'<div class="cover" style="background-image:{bg}"><div class="cover-t">'
        f'{"" if img else pick(subj, EMOJIS) + " "}{esc(subj)}</div>'
        f'<div class="cover-m">{sub_df["Lecture"].nunique()} محاضرات · {len(sub_df)} سؤال</div></div>',
        unsafe_allow_html=True,
    )

    best = {}
    if user["account"]:
        for r in my_rows(user["name"]):
            if r["Subject"] == subj:
                p = float(r["Percentage"] or 0)
                best[r["Lecture"]] = max(best.get(r["Lecture"], 0), p)

    with st.container(border=True):
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
        with st.container(border=True):
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
    st.caption(f"متوفر {len(pool)} سؤال. الأسئلة تُخلط عشوائيًا في كل مرة.")

    options = [n for n in (10, 20, 30) if n < len(pool)]
    labels = [str(n) for n in options] + [f"الكل ({len(pool)})"]
    choice = st.radio("عدد الأسئلة", labels, horizontal=True, index=len(labels) - 1)
    n = len(pool) if choice.startswith("الكل") else int(choice)

    if st.button("🚀 ابدأ الاختبار", type="primary", use_container_width=True):
        ids = list(pool["qid"])
        random.shuffle(ids)
        for k in [k for k in st.session_state if k.startswith("q_")]:
            del st.session_state[k]
        go("quiz", quiz={"ids": ids[:n], "subject": subj,
                          "lecture": "كل المحاضرات" if lec == ALL else lec})


# ====================== الاختبار ======================
def quiz_view(df):
    user = st.session_state.user
    quiz = st.session_state.get("quiz")
    if not quiz:
        go("home")
    qmap = df.set_index("qid").to_dict("index")
    st.subheader(f"{quiz['subject']} — {quiz['lecture']}")
    st.caption(f"{len(quiz['ids'])} سؤال · أجب ثم اضغط إنهاء في الأسفل")

    with st.form("quiz_form"):
        for i, qid in enumerate(quiz["ids"], 1):
            row = qmap[qid]
            with st.container(border=True):
                st.markdown(f'<div class="ltr"><b>{i}. {esc(row["Question"])}</b></div>',
                            unsafe_allow_html=True)
                letters = [L for L in LETTERS if row[f"Option{L}"].strip()]
                st.radio("اختر", letters, index=None, key=f"q_{qid}",
                         format_func=lambda L, r=row: f"{L}) {r['Option' + L]}",
                         label_visibility="collapsed")
        submitted = st.form_submit_button("✅ إنهاء وإرسال", type="primary",
                                          use_container_width=True)

    if submitted:
        answers, review, score = {}, [], 0
        for qid in quiz["ids"]:
            row = qmap[qid]
            chosen = st.session_state.get(f"q_{qid}") or ""
            correct = row["Correct"]
            ok = chosen == correct
            score += ok
            answers[qid] = [chosen, correct]
            review.append({
                "q": row["Question"], "ok": ok,
                "chosen_text": f"{chosen}) {row['Option' + chosen]}" if chosen else "بدون إجابة",
                "correct_text": f"{correct}) {row['Option' + correct]}",
            })
        total = len(quiz["ids"])
        saved = True
        try:
            save_result(user["name"], quiz["subject"], quiz["lecture"], score, total, answers)
        except Exception:
            saved = False
        go("result", result={"score": score, "total": total,
                              "pct": round(score / total * 100, 1),
                              "review": review, "saved": saved}, quiz=None)


# ====================== النتيجة ======================
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


# ====================== حسابي ======================
def history_section(df):
    user = st.session_state.user
    rows = my_rows(user["name"])
    if not rows:
        st.info("لا توجد اختبارات سابقة بعد. ابدأ أول اختبار من الرئيسية.")
        return

    qmap = df.set_index("qid").to_dict("index")
    rdf = pd.DataFrame(rows)
    rdf["Percentage"] = pd.to_numeric(rdf["Percentage"], errors="coerce").fillna(0)

    # ---- الفلاتر ----
    f1, f2 = st.columns(2)
    subjects = sorted(rdf["Subject"].unique(), key=nat_key)
    subj = f1.selectbox("المادة", ["كل المواد"] + subjects)
    sel = rdf if subj == "كل المواد" else rdf[rdf["Subject"] == subj]
    lectures = sorted(sel["Lecture"].unique(), key=nat_key)
    lec = f2.selectbox("المحاضرة", ["كل المحاضرات"] + lectures,
                       disabled=(subj == "كل المواد"))
    if subj != "كل المواد" and lec != "كل المحاضرات":
        sel = sel[sel["Lecture"] == lec]

    # ---- ملخص ----
    c1, c2, c3 = st.columns(3)
    c1.metric("الاختبارات", len(sel))
    c2.metric("المتوسط", f"{sel['Percentage'].mean():.1f}%")
    c3.metric("الأفضل", f"{sel['Percentage'].max():.1f}%")
    if len(sel) > 1:
        st.line_chart(pd.DataFrame({"النسبة %": sel["Percentage"].tolist()}), height=170)

    # ---- تفصيل حسب المادة / المحاضرة ----
    if subj == "كل المواد":
        g = rdf.groupby("Subject")["Percentage"].agg(["count", "mean", "max"]).reset_index()
        g = g.sort_values("Subject", key=lambda s: s.map(nat_key))
        st.subheader("📚 أداؤك في كل مادة")
        with st.container(border=True):
            st.markdown(bars(g, "Subject"), unsafe_allow_html=True)
    elif lec == "كل المحاضرات":
        g = sel.groupby("Lecture")["Percentage"].agg(["count", "mean", "max"]).reset_index()
        g = g.sort_values("Lecture", key=lambda s: s.map(nat_key))
        st.subheader("🗂️ أداؤك في كل محاضرة")
        with st.container(border=True):
            st.markdown(bars(g, "Lecture"), unsafe_allow_html=True)

    # ---- نقاط الضعف ----
    wrong, seen = Counter(), Counter()
    for a in sel["Answers"]:
        try:
            ans = json.loads(a)
        except Exception:
            continue
        for qid, (chosen, correct) in ans.items():
            seen[qid] += 1
            if chosen != correct:
                wrong[qid] += 1
    weak = [(q, w) for q, w in wrong.most_common(10) if q in qmap]
    st.subheader("🎯 أكثر الأسئلة خطأً عندك")
    if weak:
        for qid, w in weak:
            r = qmap[qid]
            with st.expander(f"أخطأت {w} من {seen[qid]} — {r['Question'][:55]}"):
                st.markdown(f'<div class="ltr">{esc(r["Question"])}</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="ltr">✅ {r["Correct"]}) {esc(r["Option" + r["Correct"]])}</div>',
                    unsafe_allow_html=True)
    else:
        st.success("لا أخطاء مسجلة في هذا النطاق، ممتاز!")

    # ---- مراجعة اختبار ----
    st.subheader("🔍 مراجعة اختبار سابق")
    recs = sel.to_dict("records")
    labels = [f"{r['Timestamp']} — {r['Lecture']} — {r['Score']}/{r['Total']}" for r in recs]
    idx = st.selectbox("اختر الاختبار", range(len(recs)),
                       format_func=lambda i: labels[i], index=len(recs) - 1)
    try:
        ans = json.loads(recs[idx]["Answers"])
    except Exception:
        st.warning("لا توجد تفاصيل لهذا الاختبار.")
        return
    for n, (qid, (chosen, correct)) in enumerate(ans.items(), 1):
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


def account_view(df):
    user = st.session_state.user
    rows = my_rows(user["name"])
    pcts = [float(r["Percentage"] or 0) for r in rows]
    since = joined_date(user["name"])
    meta = f"عضو منذ {since}" if since else "حساب مسجل"
    with st.container(border=True):
        st.markdown(
            f'<div class="row"><div class="avatar">{esc(user["name"][:1].upper())}</div>'
            f'<div><div class="ttl" style="font-size:1.2rem">{esc(user["name"])}</div>'
            f'<div class="meta">{meta}</div>'
            f'<div style="margin-top:6px"><span class="chip c-new" style="margin:0">{len(rows)} اختبار</span>'
            + (f'<span class="chip c-ok">المتوسط {sum(pcts) / len(pcts):.0f}%</span>' if pcts else "")
            + "</div></div></div>",
            unsafe_allow_html=True,
        )

    t_hist, t_set = st.tabs(["📊 سجلي", "⚙️ الإعدادات"])
    with t_hist:
        history_section(df)
    with t_set:
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
                    done, msg = change_password(user["name"], old, new)
                except Exception as e:
                    done, msg = False, f"تعذر الاتصال: {e}"
                st.success("تم تغيير كلمة المرور ✅") if done else st.error(msg)
        st.divider()
        if st.button("🚪 تسجيل الخروج", use_container_width=True):
            st.session_state.clear()
            st.rerun()


# ====================== التشغيل ======================
if "user" not in st.session_state:
    gate()
    st.stop()

try:
    questions = load_questions()
except Exception as e:
    st.error(f"تعذر تحميل الأسئلة: {e}")
    st.stop()

user = st.session_state.user
st.session_state.setdefault("view", "home")
hero(f"أهلًا {user['name']} 👋")

tab = "🏠 الرئيسية"
if user["account"]:
    with st.container(key="nav"):
        tab = st.radio("nav", ["🏠 الرئيسية", "👤 حسابي"], horizontal=True,
                       label_visibility="collapsed")

if tab.startswith("👤"):
    account_view(questions)
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
