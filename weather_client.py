import requests
import json
import hashlib
import datetime

# National Weather Service (NWS) API Client
# NWS API requires a custom User-Agent header or it will return a 403 Forbidden.
HEADERS = {
    "User-Agent": "(dataexpert-bootcamp-app, contact@dataexpert.io)",
    "Accept": "application/ld+json"
}

# Pre-coded coordinates for common US locations to avoid external geocoding API keys
CITY_COORDINATES = {
    "CHICAGO, IL": (41.8781, -87.6298),
    "CHICAGO": (41.8781, -87.6298),
    "AUSTIN, TX": (30.2672, -97.7431),
    "AUSTIN": (30.2672, -97.7431),
    "NEW YORK, NY": (40.7128, -74.0060),
    "NEW YORK": (40.7128, -74.0060),
    "SEATTLE, WA": (47.6062, -122.3321),
    "SEATTLE": (47.6062, -122.3321),
    "MIAMI, FL": (25.7617, -80.1918),
    "MIAMI": (25.7617, -80.1918),
    "SAN FRANCISCO, CA": (37.7749, -122.4194),
    "SAN FRANCISCO": (37.7749, -122.4194),
    "LOS ANGELES, CA": (34.0522, -118.2437),
    "LOS ANGELES": (34.0522, -118.2437),
    "DENVER, CO": (39.7392, -104.9903),
    "DENVER": (39.7392, -104.9903),
    "BOSTON, MA": (42.3601, -71.0589),
    "BOSTON": (42.3601, -71.0589)
}

class WeatherClient:
    """
    Client for harvesting unstructured forecast and alert narrative text from api.weather.gov,
    normalizing it to a document schema matching Day 2 homework specs.
    """
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def resolve_location(self, location_query):
        """
        Resolves a city name (like 'Chicago, IL') or lat,lon string to numeric (lat, lon).
        """
        query_clean = location_query.upper().strip()
        
        # Check dictionary first
        if query_clean in CITY_COORDINATES:
            return CITY_COORDINATES[query_clean]

        # Check if query is in raw 'lat,lon' format
        try:
            parts = query_clean.split(",")
            if len(parts) == 2:
                lat = float(parts[0].strip())
                lon = float(parts[1].strip())
                return lat, lon
        except Exception:
            pass

        # Default fallback to Chicago if query is unresolvable
        print(f"Warning: Location '{location_query}' could not be resolved. Defaulting to Chicago, IL.")
        return CITY_COORDINATES["CHICAGO, IL"]

    def fetch_nws_endpoints(self, lat, lon):
        """
        Fetches the NWS metadata to retrieve grid points and offices.
        GET /points/{lat},{lon}
        """
        url = f"https://api.weather.gov/points/{lat:.4f},{lon:.4f}"
        res = self.session.get(url, timeout=10)
        res.raise_for_status()
        return res.json()

    def harvest_weather(self, location_name):
        """
        Fetches active alerts and narrative forecasts for a location,
        returning a list of normalized document dictionaries.
        """
        lat, lon = self.resolve_location(location_name)
        documents = []

        try:
            # 1. Fetch gridpoints metadata
            meta = self.fetch_nws_endpoints(lat, lon)
            forecast_url = meta.get("forecast")
            
            # 2. Fetch Multi-day Forecast narrative text
            if forecast_url:
                print(f"Fetching weather forecast from {forecast_url}...")
                fore_res = self.session.get(forecast_url, timeout=10)
                if fore_res.status_code == 200:
                    fore_data = fore_res.json()
                    periods = fore_data.get("periods", [])
                    
                    for period in periods:
                        period_name = period.get("name", "Forecast Period")
                        detailed_forecast = period.get("detailedForecast")
                        if not detailed_forecast:
                            continue
                            
                        # Create stable deduplication ID
                        # Hash of location + period name + start time
                        start_time = period.get("startTime", "")
                        id_raw = f"forecast_{location_name}_{period_name}_{start_time}"
                        doc_id = hashlib.md5(id_raw.encode("utf-8")).hexdigest()

                        documents.append({
                            "id": doc_id,
                            "location": location_name,
                            "source_type": "forecast",
                            "headline": f"Forecast: {period_name}",
                            "narrative_text": f"Detailed Forecast for {period_name}: {detailed_forecast}",
                            "issued_at": start_time or datetime.datetime.now().isoformat(),
                            "payload": json.dumps(period),
                            "synced_at": datetime.datetime.now().isoformat()
                        })

            # 3. Fetch Active Weather Alerts
            alerts_url = f"https://api.weather.gov/alerts/active?point={lat:.4f},{lon:.4f}"
            print(f"Fetching active weather alerts from {alerts_url}...")
            alerts_res = self.session.get(alerts_url, timeout=10)
            if alerts_res.status_code == 200:
                alerts_data = alerts_res.json()
                features = alerts_data.get("features", [])
                
                for feat in features:
                    props = feat.get("properties", {})
                    alert_id = props.get("id") or props.get("@id")
                    if not alert_id:
                        continue
                        
                    event = props.get("event", "Weather Alert")
                    description = props.get("description", "")
                    instruction = props.get("instruction", "")
                    
                    # Combine narrative text
                    narrative = f"Alert: {event}. Description: {description}"
                    if instruction:
                        narrative += f" Instruction: {instruction}"
                        
                    # Create stable deduplication ID
                    doc_id = hashlib.md5(alert_id.encode("utf-8")).hexdigest()

                    documents.append({
                        "id": doc_id,
                        "location": location_name,
                        "source_type": "alert",
                        "headline": event,
                        "narrative_text": narrative,
                        "issued_at": props.get("sent", datetime.datetime.now().isoformat()),
                        "payload": json.dumps(feat),
                        "synced_at": datetime.datetime.now().isoformat()
                    })

        except Exception as e:
            print(f"Error harvesting weather data for {location_name}: {e}")
            # Generate simulated mock weather data if API fails or rate-limits
            print("Falling back to simulated weather data.")
            documents.extend(self._get_mock_weather(location_name))

        return documents

    def _get_mock_weather(self, location_name):
        """
        Fallback simulation generator for offline/rate-limited queries.
        """
        now = datetime.datetime.now()
        id_1 = f"forecast_mock_{location_name}_today"
        id_2 = f"alert_mock_{location_name}_today"
        
        return [
            {
                "id": hashlib.md5(id_1.encode("utf-8")).hexdigest(),
                "location": location_name,
                "source_type": "forecast",
                "headline": "Forecast: Today",
                "narrative_text": f"Detailed Forecast for Today in {location_name}: Mostly sunny, with a high near 78 degrees. Northwest wind around 6 mph. Humidity is expected to stay at 40%. Possible flash flood risk this weekend due to heavy river discharge warnings upstream.",
                "issued_at": now.isoformat(),
                "payload": json.dumps({"temperature": 78, "wind": "6 mph"}),
                "synced_at": now.isoformat()
            },
            {
                "id": hashlib.md5(id_2.encode("utf-8")).hexdigest(),
                "location": location_name,
                "source_type": "alert",
                "headline": "Flash Flood Watch",
                "narrative_text": f"Alert: Flash Flood Watch in effect for {location_name} and surrounding river basins. Description: A slow-moving storm system is expected to dump 2-4 inches of rain this weekend, leading to rising creek levels and river risks. Instruction: Do not cross flooded roadways. Keep updated on local weather broadcasts.",
                "issued_at": now.isoformat(),
                "payload": json.dumps({"severity": "Severe", "urgency": "Immediate"}),
                "synced_at": now.isoformat()
            }
        ]
