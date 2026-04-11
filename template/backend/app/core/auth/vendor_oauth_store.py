# ============================================================
# Per-user vendor OAuth token store (Pattern 2)
#
# This module solves the "external MCP" auth problem:
# External vendor MCPs (GitHub, Salesforce, etc.) have their own OAuth identity
# systems and will never accept an Entra OBO token.  The user must explicitly
# authorize your application with the vendor, and the resulting access token
# must be stored per-user and forwarded on every request to that vendor's MCP.
#
# Flow:
#   1. User clicks "Connect <Vendor>" in the frontend.
#   2. Backend redirects to the vendor's OAuth authorization URL.
#   3. Vendor redirects back to /api/auth/<vendor>/callback with a code.
#   4. Backend exchanges code -> access_token and stores it here (keyed by oid).
#   5. When the agent builds tools for that vendor's MCP:
#      - retrieve_token(user_oid) -> token
#      - pass token as Bearer to the vendor MCP's httpx.AsyncClient
#
# Security notes:
#   - Tokens are stored in Cosmos DB in the same database as conversations.
#   - Partition key = user_oid  (each user's data is isolated).
#   - The container is NOT accessible from the MCP servers — only the backend reads it.
#   - Tokens should be encrypted at rest (Cosmos DB encrypts at rest by default in Azure).
#   - Rotate tokens on expiry; refresh tokens (if issued) should be stored alongside.
#
# CORE SERVICE -- do not add vendor-specific logic here.
# ============================================================

import logging
from datetime import datetime, timezone

from azure.cosmos import PartitionKey
from azure.cosmos.aio import CosmosClient

from app.config import Settings

logger = logging.getLogger(__name__)

# Cosmos container name for vendor OAuth tokens
_CONTAINER_NAME = "vendor-oauth-tokens"


class VendorOAuthStore:
    """Generic per-user OAuth token store backed by Azure Cosmos DB.

    Each document stores one vendor's OAuth token for one user.
    Documents are partitioned by ``user_oid`` for efficient per-user lookups.

    Document schema::

        {
            "id": "<user_oid>-<vendor>",
            "user_oid": "<oid from Entra>",
            "vendor": "github" | "salesforce" | ...,
            "access_token": "...",
            "refresh_token": "...",     # optional, vendor-specific
            "scope": "public_repo ...", # scopes granted by user
            "stored_at": "ISO8601",
            "expires_at": "ISO8601",    # null if token does not expire
        }
    """

    def __init__(self, settings: Settings, vendor: str) -> None:
        self._settings = settings
        self._vendor = vendor
        self._client: CosmosClient | None = None
        self._container = None

    async def initialize(self) -> None:
        """Connect to Cosmos DB and ensure the vendor-oauth-tokens container exists."""
        from azure.identity.aio import DefaultAzureCredential

        credential = (
            self._settings.azure_cosmos_key
            if self._settings.azure_cosmos_key
            else DefaultAzureCredential(
                managed_identity_client_id=self._settings.azure_client_id or None
            )
        )
        self._client = CosmosClient(self._settings.azure_cosmos_endpoint, credential=credential)
        db = self._client.get_database_client(self._settings.azure_cosmos_database_name)
        self._container = await db.create_container_if_not_exists(
            id=_CONTAINER_NAME,
            partition_key=PartitionKey(path="/user_oid"),
        )

    async def close(self) -> None:
        if self._client:
            await self._client.close()
            self._client = None

    async def store_token(
        self,
        user_oid: str,
        access_token: str,
        scope: str = "",
        refresh_token: str = "",
        expires_at: str | None = None,
    ) -> None:
        """Upsert the OAuth token for a user + vendor pair."""
        if self._container is None:
            await self.initialize()
        doc = {
            "id": f"{user_oid}-{self._vendor}",
            "user_oid": user_oid,
            "vendor": self._vendor,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "scope": scope,
            "stored_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at,
        }
        await self._container.upsert_item(doc)
        logger.info("Stored %s OAuth token for user %s", self._vendor, user_oid)

    async def retrieve_token(self, user_oid: str) -> str | None:
        """Return the stored access token, or None if not connected."""
        if self._container is None:
            await self.initialize()
        try:
            doc = await self._container.read_item(
                item=f"{user_oid}-{self._vendor}",
                partition_key=user_oid,
            )
            return doc.get("access_token")
        except Exception:
            return None

    async def delete_token(self, user_oid: str) -> None:
        """Remove the stored token (user disconnects the integration)."""
        if self._container is None:
            await self.initialize()
        try:
            await self._container.delete_item(
                item=f"{user_oid}-{self._vendor}",
                partition_key=user_oid,
            )
            logger.info("Deleted %s OAuth token for user %s", self._vendor, user_oid)
        except Exception:
            pass

    async def is_connected(self, user_oid: str) -> bool:
        """Return True if the user has a stored token for this vendor."""
        return await self.retrieve_token(user_oid) is not None


class GitHubTokenStore(VendorOAuthStore):
    """Cosmos-backed store for per-user GitHub OAuth access tokens.

    GitHub OAuth App tokens do not expire by default.
    GitHub App installation tokens expire after 1 hour (not used here).
    """

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, vendor="github")
