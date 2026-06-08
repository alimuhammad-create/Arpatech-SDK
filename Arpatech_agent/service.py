import os
from dotenv import load_dotenv
from os import environ, path
from msal import PublicClientApplication
import logging
from copilot_service import CopilotService

from microsoft_agents.copilotstudio.client import ConnectionSettings, CopilotClient

logger = logging.getLogger(__name__)


from msal_cache_plugin import get_msal_token_cache
from config import McsConnectionSettings

load_dotenv(path.join(path.dirname(__file__), ".env"))
mcs_connection_settings = McsConnectionSettings()

PATH_TO_BIN = environ.get("TOKEN_CACHE_PATH")
if PATH_TO_BIN:
    BIN_DIR = os.path.join(PATH_TO_BIN, "bin")
else:
    BIN_DIR = None


def acquire_token(mcs_settings: McsConnectionSettings, cache_path: str) -> str:
    cache = get_msal_token_cache(cache_path)
    app = PublicClientApplication(
        mcs_settings.app_client_id,
        authority=f"https://login.microsoftonline.com/{mcs_settings.tenant_id}",
        token_cache=cache,
    )

    token_scopes = ["https://api.powerplatform.com/.default"]

    accounts = app.get_accounts()

    if accounts:
        logger.info("[Auth] Cached account found. Trying silent acquisition...")
        chosen = accounts[0]
        result = app.acquire_token_silent(scopes=token_scopes, account=chosen)
        if result and "access_token" in result:
            logger.info("[Auth] Silent authentication succeeded.")
            return result["access_token"]
        else:
            logger.info("[Auth] Silent authentication failed.")
    logger.info("[Auth] Starting Device Flow Login...")
    flow = app.initiate_device_flow(scopes=token_scopes)
    if "user_code" not in flow:
        raise RuntimeError("Failed to initiate device code flow")    
    print("\n" + "=" * 60)
    print(f"[Device Login] Open this URL: {flow['verification_uri']}")
    print(f"[Device Login] Enter Code:    {flow['user_code']}")
    print("=" * 60 + "\n")
    result =  app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        logger.info("[Auth] Manual authentication successful.")
        return result["access_token"]
    else:
        print(result.get("error"))
        print(result.get("error_description"))
        print(result.get("correlation_id"))  # You may need this when reporting a bug
        raise RuntimeError("Authentication with the Public AgentApplication failed")


def create_mcs_client(connection_settings: ConnectionSettings) -> CopilotClient:
    token = acquire_token(
        connection_settings,
        environ.get("PATH_TO_BIN")
        or path.join(path.dirname(__file__), "bin/token_cache.bin"),
    )
    return CopilotClient(connection_settings, token)

def get_copilot_client() -> CopilotClient:
    if not os.path.exists(BIN_DIR):
        logger.warning(f"[Setup] '{BIN_DIR}' folder not found. Creating it...")
        os.makedirs(BIN_DIR, exist_ok=True)
    cache_path = os.path.join(BIN_DIR, "token_cache.bin")
    token_cache_env_path = cache_path
    try:
        token =  acquire_token(mcs_connection_settings, token_cache_env_path)
        logger.info("[Setup] Token acquired successfully.")
        return CopilotClient(mcs_connection_settings, token)
    except Exception as e:
        logger.error(f"[Setup] Failed to acquire token: {e}")
        raise e
    
copilot_client = get_copilot_client()
copilot_service = CopilotService(copilot_client)


