import hashlib
import html
import json
import random
import secrets as pysecrets
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

# ====================== الإعدادات ======================
RESULTS_SHEET_ID = "1l5QPU0VU0JMMLYjKTSCDdOqe0uX5ceiBtAEUKXeSl8k"
QUESTIONS_SHEET_ID = "1n_erWCal8TKgsc2muduRm-uREMlZMTvdVZQfbq4AJic"
QUESTIONS_TAB = "MCQ"
TZ = ZoneInfo("Asia/Baghdad")
LETTERS = ["A", "B", "C", "D"]

st.set_page_config(page_title="HIHT Alsaiegh Quiz", page_icon="🧪", layout="centered")
st.markdown(
    """
<style>
.stApp {direction: rtl;}
div[role="radiogroup"], .ltr {direction: ltr; text-align: left;}
.ltr {margin: 6px 0 2px 0; font-size: 1.05rem;}
</style>
""",
    unsafe_allow_html=True,
)


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


@st.cache_data(ttl=300)
def load_questions():
    url = (
        f"https://docs.google.com/spreadsheets/d/{QUESTIONS_SHEET_ID}"
        f"/gviz/tq?tqx=out:csv&sheet={QUESTIONS_TAB}"
    )
    df = pd.read_csv(url, dtype=str).fillna("")
    df.columns = [c.strip() for c in df.columns]
    df = df[df["Question"].str.strip() != ""].copy()
    df["Correct"] = df["Correct"].str.strip().str.upper()
    df["qid"] = df["Question"].apply(
        lambda q: hashlib.md5(q.strip().encode()).hexdigest()[:8]
    )
    return df.reset_index(drop=True)


# ====================== الحسابات ======================
def hash_pw(pw, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", pw.encode(), bytes.fromhex(salt_hex), 200_000
    ).hex()


def register(username, pw):
    ws = users_ws()
    existing = [u.strip().lower() for u in ws.col_values(1)[1:]]
    if username.lower() in existing:
        return False, "هذا الاسم مستخدم، اختر اسمًا آخر."
    salt = pysecrets.token_hex(16)
    ws.append_row(
        [username, salt, hash_pw(pw, salt), datetime.now(TZ).strftime("%Y-%m-%d %H:%M")],
        value_input_option="RAW",
    )
    return True, ""


def login(username, pw):
    for r in users_ws().get_all_records():
        if str(r["Username"]).strip().lower() == username.lower():
            if hash_pw(pw, str(r["Salt"])) == str(r["Hash"]):
                return str(r["Username"]).strip()
            return None
    return None


# ====================== حفظ النتائج ======================
def save_result(name, subject, lecture, score, total, answers):
    ts = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    pct = round(score / total * 100, 1)
    get_book().sheet1.append_row(
        [ts, name, subject, lecture, score, total, pct,
         json.dumps(answers, ensure_ascii=False)],
        value_input_option="RAW",
    )


# ====================== شاشة الدخول ======================
def gate():
    st.title("🧪 HIHT Alsaiegh Quiz")
    st.caption("اختبارات MCQ تفاعلية")
    t_guest, t_login, t_reg = st.tabs(["ضيف", "تسجيل الدخول", "حساب جديد"])

    with t_guest:
        st.write("ادخل كضيف: تصل نتيجتك للمشرف لكن لا يُحفظ لك سجل.")
        name = st.text_input("اسمك", key="guest_name")
        if st.button("ابدأ كضيف", type="primary"):
            if name.strip():
                st.session_state.user = {"name": f"ضيف - {name.strip()}", "account": False}
                st.rerun()
            else:
                st.warning("اكتب اسمك أولًا.")

    with t_login:
        u = st.text_input("اسم المستخدم", key="login_u")
        p = st.text_input("كلمة المرور", type="password", key="login_p")
        if st.button("دخول", type="primary"):
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
        u = st.text_input("اسم المستخدم (اسمك الحقيقي يفضل)", key="reg_u")
        p = st.text_input("كلمة المرور (4 أحرف فأكثر)", type="password", key="reg_p")
        if st.button("إنشاء الحساب", type="primary"):
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


# ====================== صفحة الاختبار ======================
def reset_quiz():
    for k in list(st.session_state.keys()):
        if k.startswith("q_") or k in ("quiz", "result"):
            del st.session_state[k]


def quiz_page(df):
    user = st.session_state.user

    # ---- عرض النتيجة ----
    if "result" in st.session_state:
        res = st.session_state.result
        st.success(f"نتيجتك: {res['score']} / {res['total']}  ({res['pct']}%)")
        if res.get("saved"):
            st.caption("✅ تم إرسال النتيجة.")
        else:
            st.warning("تعذر حفظ النتيجة في الجدول، التقط صورة لها وأرسلها للمشرف.")
        wrong = [r for r in res["review"] if not r["ok"]]
        if wrong:
            st.subheader(f"مراجعة الأخطاء ({len(wrong)})")
            for r in wrong:
                with st.expander(r["q"][:80]):
                    st.markdown(f'<div class="ltr">{html.escape(r["q"])}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="ltr">❌ إجابتك: {html.escape(r["chosen_text"])}</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="ltr">✅ الصحيحة: {html.escape(r["correct_text"])}</div>', unsafe_allow_html=True)
        else:
            st.balloons()
        if st.button("اختبار جديد", type="primary"):
            reset_quiz()
            st.rerun()
        return

    # ---- إعداد الاختبار ----
    if "quiz" not in st.session_state:
        st.header("ابدأ اختبارًا")
        subject = st.selectbox("المادة", sorted(df["Subject"].unique()))
        lectures = sorted(df[df["Subject"] == subject]["Lecture"].unique())
        lecture = st.selectbox("المحاضرة", lectures)
        pool = df[(df["Subject"] == subject) & (df["Lecture"] == lecture)]
        n_all = len(pool)
        choice = st.radio(
            "عدد الأسئلة",
            [f"الكل ({n_all})"] + [str(n) for n in (10, 20) if n < n_all],
            horizontal=True,
        )
        n = n_all if choice.startswith("الكل") else int(choice)
        if st.button("ابدأ", type="primary"):
            ids = list(pool["qid"])
            random.shuffle(ids)
            st.session_state.quiz = {"ids": ids[:n], "subject": subject, "lecture": lecture}
            st.rerun()
        return

    # ---- أسئلة الاختبار ----
    quiz = st.session_state.quiz
    qmap = df.set_index("qid").to_dict("index")
    st.header(f"{quiz['subject']} — {quiz['lecture']}")
    with st.form("quiz_form"):
        for i, qid in enumerate(quiz["ids"], 1):
            row = qmap[qid]
            st.markdown(
                f'<div class="ltr"><b>{i}. {html.escape(row["Question"])}</b></div>',
                unsafe_allow_html=True,
            )
            letters = [L for L in LETTERS if row[f"Option{L}"].strip()]
            st.radio(
                "اختر", letters, index=None, key=f"q_{qid}",
                format_func=lambda L, r=row: f"{L}) {r['Option' + L]}",
                label_visibility="collapsed",
            )
            st.divider()
        submitted = st.form_submit_button("إنهاء وإرسال", type="primary")

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
        except Exception as e:
            saved = False
            st.session_state.save_error = str(e)
        st.session_state.result = {
            "score": score, "total": total,
            "pct": round(score / total * 100, 1),
            "review": review, "saved": saved,
        }
        del st.session_state["quiz"]
        st.rerun()


# ====================== صفحة السجل والتحليل ======================
def history_page(df):
    user = st.session_state.user
    st.header("📊 سجلي")
    try:
        rows = [r for r in get_book().sheet1.get_all_records()
                if str(r.get("Name", "")).strip() == user["name"]]
    except Exception as e:
        st.error(f"تعذر تحميل السجل: {e}")
        return
    if not rows:
        st.info("لا توجد اختبارات سابقة بعد.")
        return

    qmap = df.set_index("qid").to_dict("index")
    hist = pd.DataFrame(rows)[["Timestamp", "Lecture", "Score", "Total", "Percentage"]]
    c1, c2, c3 = st.columns(3)
    c1.metric("عدد الاختبارات", len(hist))
    c2.metric("المتوسط", f"{hist['Percentage'].astype(float).mean():.1f}%")
    c3.metric("أفضل نتيجة", f"{hist['Percentage'].astype(float).max():.1f}%")
    st.line_chart(hist["Percentage"].astype(float), height=180)

    # ---- نقاط الضعف ----
    wrong, seen = Counter(), Counter()
    for r in rows:
        try:
            ans = json.loads(r["Answers"])
        except Exception:
            continue
        for qid, (chosen, correct) in ans.items():
            seen[qid] += 1
            if chosen != correct:
                wrong[qid] += 1
    weak = [(q, w) for q, w in wrong.most_common(10) if q in qmap]
    st.subheader("🎯 الأسئلة التي تخطئ فيها أكثر")
    if weak:
        for qid, w in weak:
            r = qmap[qid]
            with st.expander(f"أخطأت {w} من {seen[qid]} — {r['Question'][:60]}"):
                st.markdown(f'<div class="ltr">{html.escape(r["Question"])}</div>', unsafe_allow_html=True)
                st.markdown(
                    f'<div class="ltr">✅ {r["Correct"]}) {html.escape(r["Option" + r["Correct"]])}</div>',
                    unsafe_allow_html=True)
    else:
        st.success("لا أخطاء مسجلة، ممتاز!")

    # ---- مراجعة اختبار محدد ----
    st.subheader("🔍 مراجعة اختبار سابق")
    labels = [f"{r['Timestamp']} — {r['Lecture']} — {r['Score']}/{r['Total']}" for r in rows]
    idx = st.selectbox("اختر الاختبار", range(len(rows)),
                       format_func=lambda i: labels[i], index=len(rows) - 1)
    try:
        ans = json.loads(rows[idx]["Answers"])
    except Exception:
        st.warning("لا توجد تفاصيل لهذا الاختبار.")
        return
    for n, (qid, (chosen, correct)) in enumerate(ans.items(), 1):
        if qid not in qmap:
            continue
        r = qmap[qid]
        icon = "✅" if chosen == correct else "❌"
        with st.expander(f"{icon} {n}. {r['Question'][:60]}"):
            st.markdown(f'<div class="ltr">{html.escape(r["Question"])}</div>', unsafe_allow_html=True)
            if chosen != correct:
                ct = f"{chosen}) {r['Option' + chosen]}" if chosen else "بدون إجابة"
                st.markdown(f'<div class="ltr">❌ إجابتك: {html.escape(ct)}</div>', unsafe_allow_html=True)
            st.markdown(
                f'<div class="ltr">✅ {correct}) {html.escape(r["Option" + correct])}</div>',
                unsafe_allow_html=True)


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
with st.sidebar:
    st.write(f"👤 {user['name']}")
    pages = ["📝 اختبار"] + (["📊 سجلي"] if user["account"] else [])
    page = st.radio("القائمة", pages)
    if st.button("خروج"):
        st.session_state.clear()
        st.rerun()

if page.startswith("📝"):
    quiz_page(questions)
else:
    history_page(questions)
