import os
# Fix OpenSSL FIPS self-test failure inside Databricks sandbox
os.environ.pop("OPENSSL_FORCE_FIPS_MODE", None)

import sys
import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import datetime
from dotenv import load_dotenv

# Ensure parent directory and root directory are on path to import lakebase, massive_client, and agent
sys.path.append(os.getcwd())
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from lakebase import get_connection, USE_POSTGRES, sqlite_cosine_similarity
from agent import FinancialAgent
from massive_client import MassiveClient

# Load env variables
load_dotenv()

# Set page config
st.set_page_config(
    page_title="AI Stock Market Research Assistant",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium dark styling
st.markdown("""
<style>
    /* Dark Theme Styles */
    .stApp {
        background-color: #0e1117;
        color: #e2e8f0;
    }
    .metric-card {
        background-color: #1b2230;
        border: 1px solid #2d3748;
        padding: 20px;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.2);
    }
    .card-header {
        color: #3182ce;
        font-size: 1.1rem;
        font-weight: 600;
        margin-bottom: 8px;
    }
    .card-value {
        font-size: 2rem;
        font-weight: bold;
        color: #ffffff;
    }
    .card-subtitle {
        color: #a0aec0;
        font-size: 0.85rem;
    }
</style>
""", unsafe_allow_html=True)

# Helper function to trigger sync via Flask or directly
def trigger_sync(tickers, limit):
    try:
        # Try calling the local Flask REST API (Day 2 pattern)
        res = requests.post("http://localhost:5000/stocks/sync", json={"tickers": tickers, "limit": limit})
        if res.status_code == 200:
            return res.json(), None
    except Exception:
        pass
    
    # Fallback to direct python call if Flask API is not running
    try:
        # Run sync logic directly using the Massive Stock Client
        from massive_client import MassiveClient
        massive = MassiveClient()
        synced_companies = 0
        synced_news = 0
        synced_prices = 0
        
        with get_connection() as conn:
            cursor = conn.cursor()
            for ticker in tickers:
                profile = massive.get("companies", {"tickers": ticker})
                if profile:
                    if USE_POSTGRES:
                        cursor.execute("""
                            INSERT INTO companies (ticker, name, sector, industry, profile_text, filings_excerpt, earnings_summary)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (ticker) DO UPDATE SET
                                name = EXCLUDED.name, sector = EXCLUDED.sector, industry = EXCLUDED.industry,
                                profile_text = EXCLUDED.profile_text, filings_excerpt = EXCLUDED.filings_excerpt, earnings_summary = EXCLUDED.earnings_summary;
                        """, (profile["ticker"], profile["name"], profile.get("sector"), profile.get("industry"), profile.get("profile_text"), profile.get("filings_excerpt"), profile.get("earnings_summary")))
                    else:
                        cursor.execute("""
                            INSERT INTO companies (ticker, name, sector, industry, profile_text, filings_excerpt, earnings_summary)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            ON CONFLICT(ticker) DO UPDATE SET
                                name=excluded.name, sector=excluded.sector, industry=excluded.industry,
                                profile_text=excluded.profile_text, filings_excerpt=excluded.filings_excerpt, earnings_summary=excluded.earnings_summary;
                        """, (profile["ticker"], profile["name"], profile.get("sector"), profile.get("industry"), profile.get("profile_text"), profile.get("filings_excerpt"), profile.get("earnings_summary")))
                    synced_companies += 1

                # Price history
                hist = massive.get("historical", {"ticker": ticker, "days": 30})
                if hist and "data" in hist:
                    for snapshot in hist["data"]:
                        if USE_POSTGRES:
                            cursor.execute("""
                                INSERT INTO price_snapshots (ticker, timestamp, open, high, low, close, volume)
                                VALUES (%s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (ticker, timestamp) DO UPDATE SET
                                    open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume;
                            """, (snapshot["ticker"], snapshot["timestamp"], snapshot["open"], snapshot["high"], snapshot["low"], snapshot["close"], snapshot["volume"]))
                        else:
                            cursor.execute("""
                                INSERT INTO price_snapshots (ticker, timestamp, open, high, low, close, volume)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(ticker, timestamp) DO UPDATE SET
                                    open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, volume=excluded.volume;
                            """, (snapshot["ticker"], snapshot["timestamp"], snapshot["open"], snapshot["high"], snapshot["low"], snapshot["close"], snapshot["volume"]))
                        synced_prices += 1

            # Sync news
            news_response = massive.get("news", {"tickers": ",".join(tickers), "limit": limit})
            if news_response and "articles" in news_response:
                for art in news_response["articles"]:
                    if USE_POSTGRES:
                        cursor.execute("""
                            INSERT INTO news_articles (id, ticker, headline, content, published_at)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (id) DO UPDATE SET
                                ticker = EXCLUDED.ticker, headline = EXCLUDED.headline, content = EXCLUDED.content, published_at = EXCLUDED.published_at;
                        """, (art["id"], art.get("ticker", "AAPL"), art["headline"], art["content"], art["published_at"]))
                    else:
                        cursor.execute("""
                            INSERT INTO news_articles (id, ticker, headline, content, published_at)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(id) DO UPDATE SET
                                ticker=excluded.ticker, headline=excluded.headline, content=excluded.content, published_at=excluded.published_at;
                        """, (art["id"], art.get("ticker", "AAPL"), art["headline"], art["content"], art["published_at"]))
                    synced_news += 1
                    
        return {
            "status": "success (direct)",
            "synced_companies": synced_companies,
            "synced_prices": synced_prices,
            "synced_news": synced_news
        }, None
    except Exception as e:
        return None, str(e)

# Sidebar config
st.sidebar.title("📈 Control Panel")
st.sidebar.write("Configure connection details & sync raw data.")

# Sync section in sidebar
st.sidebar.subheader("📥 Ingest Stock Data")
tickers_to_sync = st.sidebar.text_input("Tickers (comma separated)", "AAPL,MSFT,GOOGL")
news_limit = st.sidebar.slider("News Ingest Limit", 5, 20, 10)

if st.sidebar.button("Run Data Ingestion Pipeline"):
    tickers_list = [t.upper().strip() for t in tickers_to_sync.split(",") if t.strip()]
    if tickers_list:
        with st.sidebar.spinner("Syncing with Massive Stocks API..."):
            res, err = trigger_sync(tickers_list, news_limit)
            if err:
                st.sidebar.error(f"Sync failed: {err}")
            else:
                st.sidebar.success(f"Ingested data: {res.get('synced_companies')} profiles, {res.get('synced_news')} articles.")
                st.sidebar.info("Tip: Run the embedding pipeline from the terminal or Databricks notebook to vectorize this news content.")
    else:
        st.sidebar.warning("Please provide valid tickers.")

# Main app title
st.title("AI Stock Market Research Assistant")
st.markdown("---")

# Navigation tabs
tab_wl, tab_search, tab_agent, tab_analytics = st.tabs([
    "📊 Watchlist & Analytics", 
    "🔍 Semantic Context Search", 
    "🤖 AI Research Copilot",
    "📁 Audit Analytics"
])

# ==========================================
# TAB 1: WATCHLIST & ANALYTICS
# ==========================================
with tab_wl:
    st.header("Your Stock Watchlist")
    
    # 1. Fetch Watchlist from Database
    watchlist_tickers = []
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT wt.ticker, wt.notes, wt.added_at 
                FROM watchlist_tickers wt
                JOIN watchlists w ON w.id = wt.watchlist_id
            """)
            watchlist_tickers = cursor.fetchall()
    except Exception as e:
        st.error(f"Could not load watchlist: {e}")

    # Watchlist Add/Remove Form
    col_add, col_rem = st.columns(2)
    with col_add:
        with st.form("add_ticker_form"):
            st.subheader("Add Stock Ticker")
            new_t = st.text_input("Ticker Symbol (e.g. NVDA)", "").upper().strip()
            add_sub = st.form_submit_button("Add Ticker")
            if add_sub and new_t:
                from mcp_server.financial_broker import FinancialBroker
                res = FinancialBroker.manage_watchlist("add", new_t)
                st.toast(res.get("message", "Status updated"), icon="✅")
                st.rerun()

    with col_rem:
        with st.form("remove_ticker_form"):
            st.subheader("Remove Stock Ticker")
            rem_t = st.text_input("Ticker Symbol (e.g. AAPL)", "").upper().strip()
            rem_sub = st.form_submit_button("Remove Ticker")
            if rem_sub and rem_t:
                from mcp_server.financial_broker import FinancialBroker
                res = FinancialBroker.manage_watchlist("remove", rem_t)
                st.toast(res.get("message", "Status updated"), icon="🗑️")
                st.rerun()

    # Display watchlist table
    if watchlist_tickers:
        df_wl = pd.DataFrame(watchlist_tickers)
        # Handle dict format vs tuple depending on cursor
        if not df_wl.empty and 0 in df_wl.columns:
            df_wl.columns = ["Ticker", "Notes", "Added At"]
        else:
            df_wl = df_wl.rename(columns={"ticker": "Ticker", "notes": "Notes", "added_at": "Added At"})
            
        st.dataframe(df_wl, use_container_width=True)

        # Watchlist Updates Section (Notable price changes > 1.5%)
        st.subheader("🚨 Watchlist Alerts")
        with st.spinner("Checking price deviations..."):
            from mcp_server.financial_broker import FinancialBroker
            updates_res = FinancialBroker.check_watchlist_updates()
            updates = updates_res.get("updates", [])
            if isinstance(updates, list) and len(updates) > 0:
                for upd in updates:
                    if upd["severity"] == "HIGH":
                        st.error(f"**{upd['ticker']}**: Price is ${upd['price']:.2f} ({upd['change_pct']} from open). {upd['message']}")
                    else:
                        st.info(f"**{upd['ticker']}**: Price is ${upd['price']:.2f} ({upd['change_pct']} from open). {upd['message']}")
            else:
                st.success("No significant watchlist alerts today.")

        # Price history chart
        st.subheader("📈 Stock Price Action Chart")
        selected_ticker = st.selectbox("Select ticker to chart", df_wl["Ticker"].tolist())
        
        # Load historical price data
        try:
            with get_connection() as conn:
                cursor = conn.cursor()
                if USE_POSTGRES:
                    cursor.execute("""
                        SELECT timestamp, open, high, low, close, volume 
                        FROM price_snapshots 
                        WHERE ticker = %s 
                        ORDER BY timestamp ASC
                    """, (selected_ticker,))
                else:
                    cursor.execute("""
                        SELECT timestamp, open, high, low, close, volume 
                        FROM price_snapshots 
                        WHERE ticker = ? 
                        ORDER BY timestamp ASC
                    """, (selected_ticker,))
                hist_rows = cursor.fetchall()
            
            if hist_rows:
                df_hist = pd.DataFrame(hist_rows)
                if 0 in df_hist.columns:
                    df_hist.columns = ["Timestamp", "Open", "High", "Low", "Close", "Volume"]
                else:
                    df_hist = df_hist.rename(columns={
                        "timestamp": "Timestamp", "open": "Open", "high": "High",
                        "low": "Low", "close": "Close", "volume": "Volume"
                    })
                df_hist["Timestamp"] = pd.to_datetime(df_hist["Timestamp"])
                
                fig = px.line(
                    df_hist, x="Timestamp", y="Close", 
                    title=f"{selected_ticker} Historical Close Price",
                    color_discrete_sequence=["#3182ce"]
                )
                fig.update_layout(
                    paper_bgcolor="#1a202c",
                    plot_bgcolor="#1a202c",
                    font_color="#e2e8f0"
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.warning(f"No price snapshots found in database for {selected_ticker}. Use the sidebar to ingest stock data first.")
        except Exception as e:
            st.error(f"Could not load chart: {e}")
    else:
        st.info("Watchlist is currently empty. Add tickers above to start monitoring.")

# ==========================================
# TAB 2: SEMANTIC CONTEXT SEARCH
# ==========================================
with tab_search:
    st.header("Semantic Context Engineering Search")
    st.write("Query company filings, profile summaries, and news conceptually rather than by simple ticker match.")

    search_query = st.text_input("Enter semantic concept query (e.g. 'supply chain microchip risks')", "")
    search_k = st.slider("Results Count (Top K)", 1, 10, 3)

    if st.button("Run Concept Search"):
        if search_query:
            with st.spinner("Searching vectorized embeddings database..."):
                from mcp_server.financial_broker import FinancialBroker
                results = FinancialBroker.semantic_company_search(search_query)
                matches = results.get("results", [])
                
                if matches:
                    st.success(f"Found {len(matches)} matching company documents:")
                    for m in matches:
                        with st.container():
                            st.markdown(f"### {m['name']} ({m['ticker']}) — Similarity: **{m['similarity']:.2%}**")
                            st.markdown(f"**Sector**: {m['sector']} | **Industry**: {m['industry']}")
                            
                            # Layout two columns for Profile and Filings
                            col_p, col_f = st.columns(2)
                            with col_p:
                                st.info(f"**Profile Summary**:\n{m['profile']}")
                            with col_f:
                                st.warning(f"**Filing Excerpt (10-K)**:\n{m['filings']}")
                            st.markdown("---")
                else:
                    st.info("No matching embedded documents found. Make sure you have run the embedding pipeline `notebooks/ingest_ticker_news_embeddings.py`.")
        else:
            st.warning("Please type a search query first.")

# ==========================================
# TAB 3: AI RESEARCH COPILOT
# ==========================================
with tab_agent:
    st.header("Financial Agent Conversation Console")
    st.write("Discuss stock performance, perform comparisons, search contexts, and generate & save reports.")

    # Initialize chat history
    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat Input
    if prompt := st.chat_input("Ask the analyst agent... (e.g. 'Compare Apple and Microsoft performance')"):
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Run agent
        with st.chat_message("assistant"):
            agent = FinancialAgent()
            with st.spinner("Agent is reasoning..."):
                response_text, thoughts = agent.run_query(prompt)
            
            # Show thought process in an expander
            if thoughts:
                with st.expander("💭 View Agent Tool Call Chain Logs"):
                    for thought in thoughts:
                        st.code(thought)

            # Display final message
            st.markdown(response_text)
            st.session_state.messages.append({"role": "assistant", "content": response_text})

# ==========================================
# TAB 4: AUDIT ANALYTICS (CDF / LOGS)
# ==========================================
with tab_analytics:
    st.header("Application Audit Trails & Change Logs")
    st.write("Track the simulated Change Data Feed (CDF) mapping LLM tool executions and database transactions.")

    if st.button("Refresh Audit Logs"):
        st.rerun()

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, user_id, action_type, details, created_at FROM analytics_log ORDER BY created_at DESC LIMIT 50")
            log_rows = cursor.fetchall()
            
        if log_rows:
            df_logs = pd.DataFrame(log_rows)
            if 0 in df_logs.columns:
                df_logs.columns = ["Log ID", "User ID", "Action", "Details", "Logged At"]
            else:
                df_logs = df_logs.rename(columns={
                    "id": "Log ID", "user_id": "User ID", "action_type": "Action",
                    "details": "Details", "created_at": "Logged At"
                })
            
            # Summary Metrics
            c1, c2 = st.columns(2)
            with c1:
                st.metric("Total Logged Actions", len(df_logs))
            with c2:
                st.metric("Unique Actions Tracked", df_logs["Action"].nunique())

            st.dataframe(df_logs, use_container_width=True)
        else:
            st.info("No audit logs found. Interact with the chatbot agent or watchlist settings to generate logs.")
    except Exception as e:
        st.error(f"Could not load logs: {e}")
