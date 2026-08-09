# Databricks notebook source
# MAGIC %md
# MAGIC # AI Stock Market Research Assistant — Capstone Setup Notebook
# MAGIC This notebook initializes the database tables, loads the initial company profiles and stock news, runs the vector embedding pipeline, and spins up the Streamlit dashboard on your Databricks Cluster.
# MAGIC 
# MAGIC ---
# MAGIC ### Step 1: Install Dependencies
# MAGIC We install the requirements defined in our project. This includes `sentence-transformers` for embedding generation and `streamlit` for the visual dashboard.

# COMMAND SOURCE CELL
# MAGIC %pip install -r requirements.txt

# COMMAND SOURCE CELL
# MAGIC %md
# MAGIC ### Step 2: Configure Environment Variables
# MAGIC Set your Google Gemini API Key and Lakebase (PostgreSQL) details below. If you leave `LAKEBASE_URL` empty, the application will automatically fall back to SQLite, allowing it to run out-of-the-box on your Free Tier cluster!

# COMMAND SOURCE CELL
import os

# Set your Gemini API Key here for the agent chat:
os.environ["GEMINI_API_KEY"] = "YOUR_GEMINI_API_KEY_HERE"

# Optional: Add your PostgreSQL connection URL. Leave empty for SQLite fallback.
os.environ["LAKEBASE_URL"] = ""

# COMMAND SOURCE CELL
# MAGIC %md
# MAGIC ### Step 3: Run Database Migrations & Initial Data Ingestion
# MAGIC This script loads `schema.sql`, creates the 8 tables, inserts seed records, fetches recent stock news from the Massive Stocks API, chunks the documents, and runs the vectorization pipeline.

# COMMAND SOURCE CELL
# MAGIC %sh python run_setup.py

# COMMAND SOURCE CELL
# MAGIC %md
# MAGIC ### Step 4: Verify Embeddings & Semantic Search
# MAGIC Let's test if the embeddings were generated properly by performing a semantic concept search over the company filings.

# COMMAND SOURCE CELL
import sys
sys.path.append(os.path.abspath("."))
from mcp_server.financial_broker import FinancialBroker

# Conceptual search query
query = "companies facing supply chain risks or component shortages"
results = FinancialBroker.semantic_company_search(query)

print("Semantic Search Results:")
for r in results.get("results", []):
    print(f"- {r['name']} ({r['ticker']}) - Similarity: {r['similarity']:.2%}")
    print(f"  Filing Excerpt: {r['filings'][:120]}...\n")

# COMMAND SOURCE CELL
# MAGIC %md
# MAGIC ### Step 5: Start the Flask REST API (Day 2 Pattern)
# MAGIC Run the Flask background process to listen for Sync and Search calls.

# COMMAND SOURCE CELL
# MAGIC %sh
# MAGIC nohup python app.py > flask.log 2>&1 &
# MAGIC sleep 3
# MAGIC curl http://localhost:5000/healthz

# COMMAND SOURCE CELL
# MAGIC %md
# MAGIC ### Step 6: Deploy Streamlit Dashboard on Databricks
# MAGIC Run the dashboard in the background. If you are on Databricks, the cell below will print the proxy URL to access the live dashboard interface.

# COMMAND SOURCE CELL
import subprocess
import time

# Start Streamlit on port 8080 (standard Databricks App proxy port)
process = subprocess.Popen(
    ["streamlit", "run", "dashboard/app.py", "--server.port", "8080", "--server.address", "0.0.0.0"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE
)

# Wait for it to spin up
time.sleep(5)

# Generate proxy URL link for Databricks UI
try:
    ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    browser_host = ctx.browserHostName().get()
    cluster_id = ctx.clusterId().get()
    # Construct the driver proxy URL
    proxy_url = f"https://{browser_host}/driver-proxy/o/0/{cluster_id}/8080/"
    print("----------------------------------------------------------------")
    print(f"👉 CLICK HERE TO OPEN DASHBOARD: {proxy_url}")
    print("----------------------------------------------------------------")
except Exception:
    print("Running locally. Open your browser at http://localhost:8080")
