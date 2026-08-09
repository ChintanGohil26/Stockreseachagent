import os
import requests
import time
import datetime
from dotenv import load_dotenv

# Load local environment variables
load_dotenv()

class MassiveClient:
    """
    Thin wrapper client for interacting with the Massive Stocks API,
    matching the authentication and pagination patterns from the bootcamp.
    """
    def __init__(self):
        self.scope = os.getenv("MASSIVE_SECRET_SCOPE", "massive")
        self.key = os.getenv("MASSIVE_SECRET_KEY", "api-key")
        self.base_url = os.getenv("MASSIVE_API_BASE_URL", "https://api.massive.com")
        self.session = requests.Session()
        self.api_key = self._resolve_api_key()

        # Configure session header
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            })
            self.is_sandbox = False
        else:
            print("No Massive Stocks API key resolved. Running in Sandbox / Mock mode.")
            self.is_sandbox = True

    def _resolve_api_key(self):
        """
        Attempts to resolve the API key.
        1. Checks environment variables (local/fallback).
        2. Checks Databricks Secrets scope.
        """
        # Try local environment variable first
        env_key = os.getenv("MASSIVE_STOCKS_API_KEY") or os.getenv("MASSIVE_API_KEY")
        if env_key:
            return env_key

        # Try Databricks SDK secrets
        try:
            from databricks.sdk import WorkspaceClient
            w = WorkspaceClient()
            try:
                return w.secrets.get_secret(scope="financial_agent_scope", key="massive-api-key").value
            except Exception:
                return w.secrets.get_secret(scope=self.scope, key=self.key).value
        except Exception:
            return None

    def get(self, path, params=None):
        """
        Performs a GET request. If in sandbox mode, redirects to simulated response.
        """
        if self.is_sandbox:
            return self._simulated_get(path, params)

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        response = self.session.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path, json_data=None):
        """
        Performs a POST request.
        """
        if self.is_sandbox:
            return {"status": "success", "message": "Simulated POST successful"}

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        response = self.session.post(url, json=json_data)
        response.raise_for_status()
        return response.json()

    def paginated_get(self, path, params=None, page_size=100):
        """
        Generator method handling cursor-based pagination.
        """
        if params is None:
            params = {}
        params["limit"] = page_size

        next_cursor = None
        while True:
            if next_cursor:
                params["cursor"] = next_cursor

            data = self.get(path, params=params)
            
            # Sandbox returns everything at once
            if self.is_sandbox:
                yield data
                break

            yield data

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break

    # --- Sandbox / Mock Mocking Engine ---
    def _simulated_get(self, path, params=None):
        """
        Generates rich, realistic financial data when running in sandbox mode.
        """
        path = path.strip("/")
        params = params or {}
        ticker = params.get("ticker", "AAPL").upper()
        tickers = params.get("tickers", "").upper().split(",")
        if not tickers or tickers == [""]:
            tickers = [ticker]

        if "quote" in path:
            # Get latest quote
            quotes = []
            for t in tickers:
                base_price = self._get_mock_base_price(t)
                quotes.append({
                    "ticker": t,
                    "price": round(base_price + (time.time() % 2) - 1.0, 2),
                    "open": base_price,
                    "high": round(base_price * 1.02, 2),
                    "low": round(base_price * 0.98, 2),
                    "close": round(base_price * 1.005, 2),
                    "volume": int(1000000 + (time.time() % 500000)),
                    "timestamp": datetime.datetime.now().isoformat()
                })
            return quotes if len(quotes) > 1 else quotes[0]

        elif "historical" in path or "snapshots" in path:
            # Historical daily ticks
            history = []
            days = int(params.get("days", 30))
            base_price = self._get_mock_base_price(ticker)
            
            for i in range(days, 0, -1):
                dt = datetime.datetime.now() - datetime.timedelta(days=i)
                # Skip weekends
                if dt.weekday() >= 5:
                    continue
                # Add some random walk variation
                change = (np.sin(i / 3.0) * 0.02) + ((i % 5 - 2) * 0.005)
                price = round(base_price * (1 + change), 2)
                history.append({
                    "ticker": ticker,
                    "timestamp": dt.strftime("%Y-%m-%d"),
                    "open": round(price * 0.99, 2),
                    "high": round(price * 1.015, 2),
                    "low": round(price * 0.985, 2),
                    "close": price,
                    "volume": int(1500000 + (i * 10000))
                })
            return {"ticker": ticker, "data": history}

        elif "news" in path:
            # Return news articles related to tickers
            articles = []
            for t in tickers:
                articles.extend(self._get_mock_news(t))
            return {"articles": articles}

        elif "fundamentals" in path or "companies" in path:
            # Company profiles / fundamentals
            companies_data = []
            for t in tickers:
                companies_data.append(self._get_mock_company_profile(t))
            return companies_data if len(companies_data) > 1 else companies_data[0]

        return {"error": "Endpoint not found in sandbox"}

    def _get_mock_base_price(self, ticker):
        bases = {"AAPL": 175.0, "MSFT": 420.0, "GOOGL": 150.0, "NVDA": 850.0, "AMZN": 180.0}
        return bases.get(ticker, 100.0)

    def _get_mock_company_profile(self, ticker):
        profiles = {
            "AAPL": {
                "ticker": "AAPL",
                "name": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "profile_text": "Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide. The company is heavily exposed to supply chain risks, global consumer sentiment, and regulatory investigations into app store fees.",
                "filings_excerpt": "Form 10-K: Our products and services are highly complex and depend on specialized component suppliers. Any bottleneck in hardware supply chains, particularly in microchips or regional assembly delays, will adversely impact gross margins.",
                "earnings_summary": "Q2 2026 Earnings: Record service revenues of $25.2 billion offset slight declines in iPhone hardware sales. Management expressed optimism regarding consumer on-device AI adoption, but analysts raised concerns about capital expenditures."
            },
            "MSFT": {
                "ticker": "MSFT",
                "name": "Microsoft Corporation",
                "sector": "Technology",
                "industry": "Software - Infrastructure",
                "profile_text": "Microsoft Corporation develops, licenses, and supports software, services, devices, and solutions worldwide. The company is a leader in Enterprise Cloud services (Azure) and Generative AI services through its partnership with OpenAI.",
                "filings_excerpt": "Form 10-K: We compete in rapidly evolving markets. Our success depends heavily on capital investments in global AI infrastructure and data centers, which are subject to energy grid capacity limits and high interest rates.",
                "earnings_summary": "Q2 2026 Earnings: Azure grew 31% year-over-year. Capital expenditure spiked to $15 billion for data center capacity, impacting free cash flow expectations, but positioning MSFT as a core cloud infrastructure driver."
            },
            "GOOGL": {
                "ticker": "GOOGL",
                "name": "Alphabet Inc.",
                "sector": "Communication Services",
                "industry": "Internet Content & Information",
                "profile_text": "Alphabet Inc. offers Google Search, Google Maps, YouTube, Google Play, and Google Cloud services. The company's business model relies on advertising revenues, cloud subscriptions, and expanding AI search features.",
                "filings_excerpt": "Form 10-K: Antitrust litigation regarding search distribution agreements poses a material risk to our core monetization strategies. Additionally, user transition to AI chat answers may alter traditional search ad impressions.",
                "earnings_summary": "Q2 2026 Earnings: Search ad revenue remains strong, showing 12% growth. Google Cloud operating margins expanded significantly, hitting 10%. The CEO highlighted progress in Gemini model training efficiencies."
            }
        }
        return profiles.get(ticker, {
            "ticker": ticker,
            "name": f"{ticker} Corp",
            "sector": "Financials",
            "industry": "Asset Management",
            "profile_text": f"{ticker} is a publicly traded company. Operates in retail financial markets and is subject to fluctuating interest rates and macroeconomic cycles.",
            "filings_excerpt": f"Form 10-K: High interest rates have increased borrowing costs, depressing consumer demand in our primary asset division.",
            "earnings_summary": f"Latest Earnings: Revenues remained flat. The company announced restructuring to reduce overhead in response to regional banking pressures."
        })

    def _get_mock_news(self, ticker):
        return [
            {
                "id": f"news_{ticker}_1",
                "ticker": ticker,
                "headline": f"Why {ticker} shares are fluctuating amidst macroeconomic shifts",
                "content": f"Shares of {ticker} experienced volatility today as investors parsed comments from the Federal Reserve regarding interest rates. As a major player in its sector, {ticker} is sensitive to borrow costs, which affect its capital investment plans and consumer demand metrics. Analysts remain divided on long-term implications.",
                "published_at": (datetime.datetime.now() - datetime.timedelta(hours=4)).isoformat()
            },
            {
                "id": f"news_{ticker}_2",
                "ticker": ticker,
                "headline": f"Industry report flags potential headwinds for {ticker}",
                "content": f"A new regulatory review has raised questions about antitrust compliance in the {ticker} product suite. The report suggests that dominant platforms face rising scrutiny, which could lead to structural constraints or fee reductions in the coming quarters.",
                "published_at": (datetime.datetime.now() - datetime.timedelta(days=2)).isoformat()
            }
        ]
