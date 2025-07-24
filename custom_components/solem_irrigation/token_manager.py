"""Token management for Solem Irrigation integration."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .solem_api import SolemAPI, AuthenticationError

_LOGGER = logging.getLogger(__name__)


class SolemTokenManager:
    """Manages OAuth tokens for Solem API."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Initialize token manager."""
        self.hass = hass
        self.config_entry = config_entry
        self.store = Store(hass, 1, f"solem_tokens_{config_entry.entry_id}")
        
        self._tokens: Dict[str, str] = {}
        self._token_expiry: Dict[str, datetime] = {}
        self._refresh_buffer = timedelta(minutes=5)
        self._refresh_task: Optional[asyncio.Task] = None
        self._refresh_lock = asyncio.Lock()

    async def load_tokens(self) -> None:
        """Load tokens from storage."""
        try:
            stored_data = await self.store.async_load() or {}
            self._tokens = stored_data.get("tokens", {})
            
            # Parse expiry times
            for token_type, expiry_str in stored_data.get("expiry", {}).items():
                if expiry_str:
                    try:
                        self._token_expiry[token_type] = datetime.fromisoformat(expiry_str)
                    except ValueError:
                        _LOGGER.warning("Invalid expiry format for %s: %s", token_type, expiry_str)
            
            _LOGGER.debug("Loaded tokens: %s", list(self._tokens.keys()))
            
        except Exception as e:
            _LOGGER.warning("Failed to load stored tokens: %s", e)

    async def save_tokens(self) -> None:
        """Save tokens to storage."""
        try:
            expiry_strings = {
                token_type: expiry.isoformat() if expiry else None
                for token_type, expiry in self._token_expiry.items()
            }
            
            await self.store.async_save({
                "tokens": self._tokens,
                "expiry": expiry_strings,
                "updated": dt_util.utcnow().isoformat()
            })
            
            _LOGGER.debug("Saved tokens to storage")
            
        except Exception as e:
            _LOGGER.error("Failed to save tokens: %s", e)

    async def ensure_valid_tokens(self, api: SolemAPI) -> None:
        """Ensure we have valid tokens, refresh if needed."""
        async with self._refresh_lock:
            # Check app token first
            if await self._needs_refresh("app_token"):
                await self._refresh_app_token(api)
            
            # Then check user token
            if await self._needs_refresh("user_token"):
                await self._refresh_user_token(api)

    async def force_refresh(self, api: SolemAPI) -> None:
        """Force refresh of all tokens."""
        async with self._refresh_lock:
            _LOGGER.info("Forcing token refresh")
            try:
                await self._refresh_app_token(api)
                await self._refresh_user_token(api)
            except Exception as e:
                _LOGGER.error("Failed to force refresh tokens: %s", e)
                raise

    async def _needs_refresh(self, token_type: str) -> bool:
        """Check if token needs refresh."""
        if token_type not in self._tokens:
            _LOGGER.debug("Token %s not found, needs refresh", token_type)
            return True
        
        expiry = self._token_expiry.get(token_type)
        if not expiry:
            _LOGGER.debug("No expiry info for %s, needs refresh", token_type)
            return True
        
        # Refresh if within buffer time of expiry
        needs_refresh = dt_util.utcnow() + self._refresh_buffer >= expiry
        if needs_refresh:
            _LOGGER.debug("Token %s expires soon (%s), needs refresh", token_type, expiry)
        
        return needs_refresh

    async def _refresh_app_token(self, api: SolemAPI) -> None:
        """Refresh application token."""
        _LOGGER.debug("Refreshing app token")
        try:
            token = await api.get_app_token()
            self._tokens["app_token"] = token
            
            # OAuth2 tokens typically expire in 1-24 hours, assume 23 hours for safety
            self._token_expiry["app_token"] = dt_util.utcnow() + timedelta(hours=23)
            
            # Update API instance
            api._app_token = token
            
            await self.save_tokens()
            _LOGGER.info("App token refreshed successfully")
            
        except Exception as e:
            _LOGGER.error("Failed to refresh app token: %s", e)
            raise AuthenticationError(f"Failed to refresh app token: {e}") from e

    async def _refresh_user_token(self, api: SolemAPI) -> None:
        """Refresh user token by re-authenticating."""
        _LOGGER.debug("Refreshing user token")
        try:
            # Get credentials from config
            username = self.config_entry.data[CONF_USERNAME]
            password = self.config_entry.data[CONF_PASSWORD]
            
            success = await api.login(username, password)
            if success and api._user_token:
                self._tokens["user_token"] = api._user_token
                
                # Assume user tokens expire in 23 hours
                self._token_expiry["user_token"] = dt_util.utcnow() + timedelta(hours=23)
                
                await self.save_tokens()
                _LOGGER.info("User token refreshed successfully")
            else:
                raise AuthenticationError("Login failed during token refresh")
                
        except AuthenticationError:
            raise
        except Exception as e:
            _LOGGER.error("Failed to refresh user token: %s", e)
            raise AuthenticationError(f"Failed to refresh user token: {e}") from e

    def schedule_refresh_check(self) -> None:
        """Schedule periodic token validity checks."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
        
        # Calculate next check time
        next_check_delay = self._get_next_check_delay()
        
        _LOGGER.debug("Scheduling next token check in %d seconds", next_check_delay)
        
        self._refresh_task = self.hass.async_call_later(
            next_check_delay,
            self._periodic_refresh_check
        )

    def _get_next_check_delay(self) -> int:
        """Calculate delay until next token check."""
        now = dt_util.utcnow()
        earliest_expiry = None
        
        for expiry in self._token_expiry.values():
            if expiry and (earliest_expiry is None or expiry < earliest_expiry):
                earliest_expiry = expiry
        
        if earliest_expiry:
            # Check 15 minutes before earliest expiry, but at least in 5 minutes
            check_time = earliest_expiry - timedelta(minutes=15)
            delay = max((check_time - now).total_seconds(), 300)  # Minimum 5 minutes
            return min(int(delay), 3600)  # Maximum 1 hour
        else:
            # No expiry info, check in 30 minutes
            return 1800

    async def _periodic_refresh_check(self, now=None) -> None:
        """Periodic check called by Home Assistant scheduler."""
        _LOGGER.debug("Performing periodic token check")
        try:
            # Get the coordinator to trigger a refresh if tokens need updating
            # This will call ensure_valid_tokens during the next update
            domain_data = self.hass.data.get("solem_irrigation", {})
            for entry_data in domain_data.values():
                if isinstance(entry_data, dict) and "coordinator" in entry_data:
                    coordinator = entry_data["coordinator"]
                    if coordinator.token_manager is self:
                        # Request refresh which will trigger token check
                        await coordinator.async_request_refresh()
                        break
                        
        except Exception as e:
            _LOGGER.error("Error during periodic token check: %s", e)
        finally:
            # Schedule next check
            self.schedule_refresh_check()

    def cancel_refresh_task(self) -> None:
        """Cancel the refresh task."""
        if self._refresh_task and not self._refresh_task.done():
            self._refresh_task.cancel()
            _LOGGER.debug("Cancelled token refresh task")

    async def clear_tokens(self) -> None:
        """Clear all stored tokens (for re-auth)."""
        _LOGGER.info("Clearing all stored tokens")
        self._tokens.clear()
        self._token_expiry.clear()
        try:
            await self.store.async_remove()
        except Exception as e:
            _LOGGER.warning("Failed to remove token storage: %s", e)

    def get_token_status(self) -> Dict[str, dict]:
        """Get current token status for diagnostics."""
        now = dt_util.utcnow()
        status = {}
        
        for token_type in ["app_token", "user_token"]:
            expiry = self._token_expiry.get(token_type)
            has_token = token_type in self._tokens
            
            if expiry and has_token:
                remaining = expiry - now
                status[token_type] = {
                    "expires_at": expiry.isoformat(),
                    "expires_in_seconds": int(remaining.total_seconds()),
                    "is_valid": remaining > self._refresh_buffer,
                    "needs_refresh": remaining <= self._refresh_buffer
                }
            else:
                status[token_type] = {
                    "expires_at": None,
                    "is_valid": has_token,
                    "needs_refresh": True,
                    "has_token": has_token
                }
        
        return status

    def restore_tokens_to_api(self, api: SolemAPI) -> None:
        """Restore stored tokens to API instance."""
        if "app_token" in self._tokens:
            api._app_token = self._tokens["app_token"]
            _LOGGER.debug("Restored app token to API")
        
        if "user_token" in self._tokens:
            api._user_token = self._tokens["user_token"]
            _LOGGER.debug("Restored user token to API")