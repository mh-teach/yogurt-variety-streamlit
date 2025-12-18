import os, random, time
from datetime import datetime, timezone

import streamlit as st
import psycopg
import pandas as pd
import matplotlib.pyplot as plt

# -----------------------------
# Setup
# -----------------------------
st.set_page_config(page_title="Yogurt Study", layout="centered")

FLAVORS = ["Vanilla", "Strawberry", "Banana", "Blueberry", "Apricot", "Coffee"]
PLACEHOLDER = "— select —"
OPTIONS = [PLACEHOLDER] + FLAVORS

SHOW_RESULTS_TO_STUDENTS = True  # set False if you want only admin to see the chart

def classify_variety(choices: list[str]) -> str:
    """Low: one flavor three times; Medium: one flavor twice; High: three different flavors."""
    u = len(set(choices))
    return "Low" if u == 1 else ("Medium" if u == 2 else "High")

@st.cache_resource
def get_conn():
    db_url = st.secrets.get("DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL missing in Streamlit secrets or environment variables.")
    # Force SSL (helps with Supabase in cloud environments)
    return psycopg.connect(db_url, autocommit=True, sslmode="require")

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

def fetch_counts() -> pd.DataFrame:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT condition, variety, COUNT(*) AS n
            FROM yogurt_variety
            GROUP BY condition, variety
        """)
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["condition", "variety", "n"])

def plot_stacked(df: pd.DataFrame):
    order_var = ["Low", "Medium", "High"]
    order_cond = ["sequential", "simultaneous"]

    if df.empty:
        st.info("No data yet.")
        return

    # ensure all cells exist
    for c in order_cond:
        for v in order_var:
            if not ((df["condition"] == c) & (df["variety"] == v)).any():
                df = pd.concat([df, pd.DataFrame([{"condition": c, "variety": v, "n": 0}])], ignore_index=True)

    pivot = (
        df.pivot_table(index="condition", columns="variety", values="n", aggfunc="sum")
        .reindex(order_cond)
        .reindex(columns=order_var)
        .fillna(0)
    )

    totals = pivot.sum(axis=1).replace(0, 1)
    perc = pivot.div(totals, axis=0) * 100

    fig, ax = plt.subplots()
    bottom = None
    for v in order_var:
        ax.bar(perc.index, perc[v], bottom=bottom, label=v)
        bottom = perc[v] if bottom is None else bottom + perc[v]

    ax.set_ylim(0, 100)
    ax.set_ylabel("%")
    ax.set_title("Amount of Variety Selected for Sequential Consumption (Yogurt)")
    ax.set_xticks([0, 1])
    ax.set_xticklabels(["Sequential\nChoices", "Simultaneous\nChoices"])
    ax.legend(loc="upper right")

    # % labels inside segments (only if large enough)
    cum = perc[order_var].cumsum(axis=1)
    starts = cum.shift(axis=1, fill_value=0)
    for i, cond in enumerate(order_cond):
        for v in order_var:
            val = float(perc.loc[cond, v])
            if val >= 6:
                y = float(starts.loc[cond, v] + val / 2)
                ax.text(i, y, f"{val:.0f}%", ha="center", va="center", fontsize=10)

    st.pyplot(fig)

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

# German image strip if present
if os.path.exists("Bild1.png"):
    st.image("Bild1.png", use_container_width=True)

# Optional: admin can always see live results at top
if admin:
    st.markdown("### Live results")
    plot_stacked(fetch_counts())
    st.markdown("---")

# -----------------------------
# Done screen (optionally show chart)
# -----------------------------
if st.session_state.done:
    st.success("Thank you — your choices were recorded.")

    if SHOW_RESULTS_TO_STUDENTS or admin:
        with st.expander("See results so far", expanded=True):
            plot_stacked(fetch_counts())

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
        w1 = st.selectbox("Week 1", OPTIONS, index=0)
        w2 = st.selectbox("Week 2", OPTIONS, index=0)
        w3 = st.selectbox("Week 3", OPTIONS, index=0)
        submit = st.form_submit_button("Submit")

        if submit:
            choices = [w1, w2, w3]
            if PLACEHOLDER in choices:
                st.error("Please make a selection for Week 1, Week 2, and Week 3.")
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
        "In this task, you are asked to choose **three yogurts at the same time**, "
        "to be consumed over **three weeks** (one per week). "
        "You may select the same yogurt more than once."
    )
    st.write("**Which three yogurts would you choose (at the same time)?**")

    with st.form("sim"):
        s1 = st.selectbox("Yogurt 1", OPTIONS, index=0, key="s1")
        s2 = st.selectbox("Yogurt 2", OPTIONS, index=0, key="s2")
        s3 = st.selectbox("Yogurt 3", OPTIONS, index=0, key="s3")
        submit = st.form_submit_button("Submit")

        if submit:
            choices = [s1, s2, s3]
            if PLACEHOLDER in choices:
                st.error("Please select Yogurt 1, Yogurt 2, and Yogurt 3.")
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
