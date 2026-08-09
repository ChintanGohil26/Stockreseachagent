import os
import sys
import getpass
from dotenv import load_dotenv

def prompt_and_deploy_secrets():
    """
    Interactively prompts the user for secrets in the terminal or notebook prompt,
    writes them to a local .env file, and deploys them to a secure Databricks Secret Scope.
    """
    print("====================================================================")
    print("🔒 Secure API & Lakebase Credentials Configurator")
    print("====================================================================\n")

    # Prompt user securely
    print("Please enter your Google Gemini API Key (input will be hidden):")
    gemini_key = getpass.getpass("Gemini API Key: ").strip()

    print("\nPlease enter your Lakebase PostgreSQL Connection URL (input will be hidden):")
    print("Format: postgresql://username:password@host:port/database")
    lakebase_url = getpass.getpass("Lakebase URL: ").strip()

    print("\nPlease enter your Massive Stocks API Key (optional - press Enter to skip):")
    massive_key = getpass.getpass("Massive API Key: ").strip()

    # 1. Write to local .env file
    env_content = f"""# ====================================================================
# Auto-generated Credentials Configuration
# ====================================================================
GEMINI_API_KEY={gemini_key}
LAKEBASE_URL={lakebase_url}
MASSIVE_STOCKS_API_KEY={massive_key}
"""
    try:
        with open(".env", "w") as f:
            f.write(env_content)
        print("\n✅ Successfully created local .env file.")
    except Exception as e:
        print(f"\n❌ Error writing local .env file: {e}")

    # 2. Upload to Databricks Secrets Scope
    try:
        from databricks.sdk import WorkspaceClient
        print("\nConnecting to Databricks Workspace Client...")
        w = WorkspaceClient()
        print(f"Connected to workspace: {w.config.host}")

        scope_name = "financial_agent_scope"
        print(f"Ensuring secret scope '{scope_name}' exists...")
        try:
            w.secrets.create_scope(scope=scope_name)
            print(f"Created scope '{scope_name}'.")
        except Exception as e:
            if "RESOURCE_ALREADY_EXISTS" in str(e):
                print(f"Scope '{scope_name}' already exists.")
            else:
                raise e

        # Upload keys
        if gemini_key:
            w.secrets.put_secret(scope=scope_name, key="gemini-api-key", string_value=gemini_key)
            print("🔑 Uploaded: gemini-api-key")
        if lakebase_url:
            w.secrets.put_secret(scope=scope_name, key="lakebase-url", string_value=lakebase_url)
            print("🔑 Uploaded: lakebase-url")
        if massive_key:
            w.secrets.put_secret(scope=scope_name, key="massive-api-key", string_value=massive_key)
            print("🔑 Uploaded: massive-api-key")

        print("\n🚀 All credentials uploaded to your Databricks Secret Scope successfully!")
        print("Your notebooks and apps can now retrieve these credentials securely.")
        
    except ImportError:
        print("\n⚠️  databricks-sdk is not installed. Secrets were only saved to the local .env file.")
        print("To deploy to Databricks Secrets, run 'pip install databricks-sdk' and execute this script again.")
    except Exception as e:
        print(f"\n⚠️  Saved to .env, but could not deploy to Databricks Secrets: {e}")
        print("This is normal if you are running locally without Databricks authentication configured.")

if __name__ == "__main__":
    prompt_and_deploy_secrets()
