# Weather Intelligence Pipeline (Day 2 Homework)

This module implements a complete unstructured weather data harvesting, vectorization, and semantic search retrieval pipeline.

## 1. Selected Data Source
We chose the **National Weather Service API (api.weather.gov)**:
*   **Why**: It is free, requires no API key, and exposes narrative meteorological forecast text (e.g. `detailedForecast`) and active weather warnings/hazard instructions.
*   **Safety Fallback**: The client has built-in offline simulation mock fallbacks to handle NWS API rate-limiting or network issues during evaluations.

---

## 2. Schema Decisions & Hyperparameters
*   **Tables**:
    *   `weather_documents`: Stores raw narrative forecasts and hazard alerts.
    *   `weather_embeddings`: Stores 384-dimensional vector embeddings keyed to individual chunks.
*   **Chunking Strategy**: A sliding-window chunker with `CHUNK_SIZE = 800` characters and `CHUNK_OVERLAP = 100` characters. This ensures text segments stay within context windows while maintaining spatial coherence.
*   **Embedding Model**: `sentence-transformers/all-MiniLM-L6-v2` (384-dimensional vectors).

---

## 3. End-to-End Pipeline Execution

### Step 1: Migrate the Database
Initialize the new database tables in your Databricks notebook or terminal:
```python
from lakebase import init_db
init_db()
```

### Step 2: Harvest and Sync Data
Call the sync endpoint to fetch weather alerts and detailed forecasts for your target locations (e.g. Chicago, Austin):
```bash
curl -X POST http://localhost:5000/weather/sync \
     -H "Content-Type: application/json" \
     -d '{"locations": ["Chicago, IL", "Austin, TX"]}'
```

### Step 3: Run the Ingestion & Embedding Pipeline
Vectorize the harvested narrative documents by running the batch embedding script:
```bash
python notebooks/ingest_weather_embeddings.py
```
*(In Databricks, run `%run ./notebooks/ingest_weather_embeddings.py` or import it directly).*

### Step 4: Perform Semantic Retrieval
Submit unstructured queries to return the most semantically relevant alerts or forecasts:
```bash
curl -X POST http://localhost:5000/weather/search \
     -H "Content-Type: application/json" \
     -d '{"query": "risk of river flooding this weekend", "top_k": 3}'
```

---

## 4. Known Limitations & Future Improvements
*   **Geocoding Resolution**: Currently uses pre-coded city coordinates to stay offline-friendly. Integrating a lightweight forward geocoder (e.g. Nominatim) would resolve arbitrary address search inputs dynamically.
*   **HNSW Indexing**: Creating an HNSW index on the Postgres `weather_embeddings` table will speed up search queries for high-volume deployments.
