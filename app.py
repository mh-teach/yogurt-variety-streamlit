import os, random, time
from datetime import datetime, timezone

import streamlit as st
import psycopg

# -----------------------------
# Setup
# -----------------------------
st.set_page_config(page_title="Yogurt Study", layout="centered")

# Six flavors (image can be German; labels shown here are English)
FLAVORS = ["Vanilla", "Strawberry", "Banana", "Blueberry", "Apricot", "Coffee"]

def classify_variety(choices: list[str]) -> str:
    """Low: one flavor three times; Medium: one flavor twice; High: three different flavors."""
    u = len(set(choices))
    return "Low" if u == 1 else ("Medium" if u == 2 else "High")

@st.cache_resource
def get_conn():
    db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL missing in Streamlit secrets or environment variables.")
    # One connection per worker
    return psycopg.connect(db_url, autocommit=True)

def init_db():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS yogurt_variety (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            participant_id TEXT NOT NULL,
            condition TEXT NOT NULL,      -- "sequential" or "simultaneous"
            choices TEXT[] NOT NULL,      -- 3 items, repeats allowed
            variety TEXT NOT NULL         -- Low/Medium/High
        );
        """)
init_db()

def safe_insert(row: dict, retries: int = 6):
    """Retry inserts to survive brief DB/network spikes when many students submit at once."""
    conn = get_conn()
    for a in range(retries):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO yogurt_variety (created_at, participant_id, condition, choices, variety)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (row["created_at"], row["participant_id"], row["condition"], row["choices"], row["variety"])
                )
            return
        except Exception:
            if a == retries - 1:
                raise
            time.sleep(0.2 * (2 ** a))

# -----------------------------
# Session state
# -----------------------------
if "pid" not in st.session_state:
    st.session_state.pid = f"p_{random.randint(100000, 999999)}"

if "condition" not in st.session_state:
    # Random assignment on first load
    st.session_state.condition = random.choice(["sequential", "simultaneous"])

if "done" not in st.session_state:
    st.session_state.done = False

st.title("Purchase Quantity, Purchase Timing, and Variety-Seeking Behaviour")

# Show German image strip if present in repo
if os.path.exists("Bild1.png"):
    st.image("Bild1.png", use_container_width=True)

if st.session_state.done:
    st.success("Thank you — your choices were recorded.")
    st.stop()

# -----------------------------
# Instructions (English, weeks)
# -----------------------------
if st.session_state.condition == "sequential":
    st.write(
        "Imagine you are purchasing three cups of yogurt.\n\n"
        "In this task, you are asked to choose **one yogurt each week**, for **three consecutive weeks**. "
        "After making your choice for a week, assume you consume it, and then on the following week you again "
        "choose one yogurt from the **same set**. This is repeated a third time."
    )
    st.write("**Which yogurt would you choose each week, for three weeks?**")

    with st.form("seq"):
        w1 = st.selectbox("Week 1", FLAVORS, index=0)
        w2 = st.selectbox("Week 2", FLAVORS, index=1)
        w3 = st.selectbox("Week 3", FLAVORS, index=2)
        submit = st.form_submit_button("Submit")

        if submit:
            choices = [w1, w2, w3]
            safe_insert({
                "created_at": datetime.now(timezone.utc),
                "participant_id": st.session_state.pid,
                "condition": "sequential",
                "choices": choices,
                "variety": classify_variety(choices),
            })
            st.session_state.done = True
            st.rerun()

else:
    st.write(
        "Imagine you are purchasing three cups of yogurt.\n\n"
        "In this task, you are asked to choose **three yogurts at the same time**, "
        "to be consumed over **three weeks** (one per week). "
        "You may select the same yogurt more than once."
    )
    st.write("**Which three yogurts would you choose (at the same time)?**")

    with st.form("sim"):
        # Allow repeats: use three dropdowns (NOT multiselect)
        s1 = st.selectbox("Yogurt 1", FLAVORS, index=0, key="s1")
        s2 = st.selectbox("Yogurt 2", FLAVORS, index=1, key="s2")
        s3 = st.selectbox("Yogurt 3", FLAVORS, index=2, key="s3")
        submit = st.form_submit_button("Submit")

        if submit:
            choices = [s1, s2, s3]
            safe_insert({
                "created_at": datetime.now(timezone.utc),
                "participant_id": st.session_state.pid,
                "condition": "simultaneous",
                "choices": choices,
                "variety": classify_variety(choices),
            })
            st.session_state.done = True
            st.rerun()
