import os, random, time
from datetime import datetime, timezone

import streamlit as st
import psycopg
import pandas as pd
import matplotlib.pyplot as plt

# -----------------------------
# Page setup
# -----------------------------
st.set_page_config(page_title="Yogurt Study", layout="centered")

# -----------------------------
# Constants
# -----------------------------
FLAVORS = ["Vanilla", "Strawberry", "Banana", "Blueberry", "Apricot", "Coffee"]
PLACEHOLDER = "— select —"
OPTIONS = [PLACEHOLDER] + FLAVORS

SHOW_RESULTS_TO_STUDENTS = True

# -----------------------------
# Helper functions
# -----------------------------
def classify_variety(choices):
    u = len(set(choices))
    return "Low" if u == 1 else ("Medium" if u == 2 else "High")

@st.cache_resource
def get_conn():
    db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL missing")
    return psycopg.connect(db_url, autocommit=True, sslmode="require")

def init_db():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS yogurt_variety (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL,
            participant_id TEXT NOT NULL,
            condition TEXT NOT NULL,
            choices TEXT[] NOT NULL,
            variety TEXT NOT NULL
        );
        """)

def safe_insert(row, retries=6):
    conn = get_conn()
    for i in range(retries):
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO yogurt_variety
                    (created_at, participant_id, condition, choices, variety)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (row["created_at"], row["participant_id"],
                     row["condition"], row["choices"], row["variety"])
                )
            return
        except Exception:
            if i == retries - 1:
                raise
            time.sleep(0.2 * (2 ** i))

def fetch_counts():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT condition, variety, COUNT(*) AS n
            FROM yogurt_variety
            GROUP BY condition, variety
        """)
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["condition", "variety", "n"])

def plot_stacked(df):
    label_map = {
        "Low": "Low (3x same)",
        "Medium": "Medium (2x same)",
        "High": "High (3 different)",
    }

    order_var = ["Low", "Medium", "High"]
    order_cond = ["sequential", "simultaneous"]

    if df.empty:
        st.info("No data yet.")
        return

    for c in order_cond:
        for v in order_var:
            if not ((df.condition == c) & (df.variety == v)).any():
                df = pd.concat(
                    [df, pd.DataFrame([{"condition": c, "variety": v, "n": 0}])],
                    ignore_index=True
                )

    pivot = (
        df.pivot_table(index="condition", columns="variety", values="n", aggfunc="sum")
        .reindex(order_cond)
        .reindex(columns=order_var)
        .fillna(0)
    )

    perc = pivot.div(pivot.sum(axis=1).replace(0, 1), axis=0) * 100

    fig, ax = plt.subplots()
    bottom = None

    for v in order_var:
        ax.bar(
            perc.index,
            perc[v],
            bottom=bottom,
            label=label_map[v],
        )
        bottom = perc[v] if bottom is None else bottom + perc[v]

    ax.set_ylim(0, 100)
    ax.set_ylabel("%")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Sequential\nChoices", "Simultaneous\nChoices"])
    ax.set_title("Amount of Variety Selected")
    ax.legend(loc="upper right")

    for i, cond in enumerate(order_cond):
        cum = 0
        for v in order_var:
            val = perc.loc[cond, v]
            if val >= 6:
                ax.text(i, cum + val / 2, f"{val:.0f}%", ha="center", va="center")
            cum += val

    st.pyplot(fig)

def reset_data():
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("DELETE FROM yogurt_variety;")

# -----------------------------
# Init DB
# -----------------------------
init_db()

# -----------------------------
# Session state
# -----------------------------
if "pid" not in st.session_state:
    st.session_state.pid = f"p_{random.randint(100000, 999999)}"
if "condition" not in st.session_state:
    st.session_state.condition = random.choice(["sequential", "simultaneous"])
if "done" not in st.session_state:
    st.session_state.done = False

admin = st.query_params.get("admin") == "1"

# -----------------------------
# UI
# -----------------------------
if os.path.exists("Bild1.png"):
    st.image("Bild1.png", use_container_width=True)

# ----- Admin block -----
if admin:
    st.markdown("### Live results")
    plot_stacked(fetch_counts())

    st.markdown("### Admin controls")
    confirm = st.checkbox("I understand this will permanently delete ALL data.")
    if st.button("🗑️ Reset data", disabled=not confirm):
        reset_data()
        st.success("All data deleted.")
        st.rerun()

    st.markdown("---")

# ----- Done screen -----
if st.session_state.done:
    st.success("Thank you — your choices were recorded.")

    if SHOW_RESULTS_TO_STUDENTS or admin:
        with st.expander("See results so far", expanded=True):
            plot_stacked(fetch_counts())

    st.stop()

# ----- Experiment -----
if st.session_state.condition == "sequential":
    st.write(
        "Imagine you are purchasing three cups of yogurt.\n\n"
        "You choose **one yogurt each week**, for **three consecutive weeks**. "
        "After each choice, assume you consume it. "
        "Each week you choose again from the same set."
    )
    st.write("**Which yogurt would you choose each week?**")

    with st.form("seq"):
        w1 = st.selectbox("Week 1", OPTIONS)
        w2 = st.selectbox("Week 2", OPTIONS)
        w3 = st.selectbox("Week 3", OPTIONS)
        submit = st.form_submit_button("Submit")

        if submit:
            choices = [w1, w2, w3]
            if PLACEHOLDER in choices:
                st.error("Please select a yogurt for all three weeks.")
                st.stop()

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
        "You choose **three yogurts at the same time**, "
        "to be consumed over **three weeks** (one per week). "
        "You may choose the same yogurt more than once."
    )
    st.write("**Which three yogurts would you choose?**")

    with st.form("sim"):
        s1 = st.selectbox("Yogurt 1", OPTIONS)
        s2 = st.selectbox("Yogurt 2", OPTIONS)
        s3 = st.selectbox("Yogurt 3", OPTIONS)
        submit = st.form_submit_button("Submit")

        if submit:
            choices = [s1, s2, s3]
            if PLACEHOLDER in choices:
                st.error("Please select all three yogurts.")
                st.stop()

            safe_insert({
                "created_at": datetime.now(timezone.utc),
                "participant_id": st.session_state.pid,
                "condition": "simultaneous",
                "choices": choices,
                "variety": classify_variety(choices),
            })
            st.session_state.done = True
            st.rerun()
