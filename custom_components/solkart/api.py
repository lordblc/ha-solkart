"""Async client for the Solkart solar-forecast API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from .const import API_BASE_URL, REQUEST_TIMEOUT, USER_AGENT

_LOGGER = logging.getLogger(__name__)


class SolkartError(Exception):
    """Base error for the Solkart API client."""


class SolkartAuthError(SolkartError):
    """Raised when the API key is missing, invalid or lacks access."""


class SolkartRateLimitError(SolkartError):
    """Raised when the API quota / rate limit has been exceeded (HTTP 429)."""


class SolkartConnectionError(SolkartError):
    """Raised for network problems or unexpected server responses."""


class SolkartApiClient:
    """Thin async wrapper around the Solkart forecast API.

    The client deliberately holds no Home Assistant references so it can be
    exercised standalone (see the repo's smoke-test script).
    """

    def __init__(self, api_key: str, session: aiohttp.ClientSession) -> None:
        """Initialise the client with an API key and a shared aiohttp session."""
        self._api_key = api_key
        self._session = session

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        }

    async def forecast(
        self,
        *,
        latitude: float,
        longitude: float,
        arrays: list[dict[str, Any]],
        performance_ratio: float | None = None,
        daily: bool = False,
        extended: bool = False,
    ) -> dict[str, Any]:
        """Request a PV forecast for one or more arrays.

        ``arrays`` is a list of dicts with the keys ``name``, ``kwp``,
        ``tilt_deg`` and ``azimuth_deg``. Returns the decoded JSON body.
        """
        payload: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "arrays": arrays,
        }
        if performance_ratio is not None:
            payload["performance_ratio"] = performance_ratio
        if daily:
            payload["daily"] = True
        if extended:
            payload["extended"] = True

        return await self._request("POST", "/api/forecast", json=payload)

    async def validate(self, *, latitude: float, longitude: float) -> None:
        """Validate connectivity and the API key.

        Issues one minimal forecast request. Raises :class:`SolkartAuthError`
        for bad credentials and :class:`SolkartConnectionError` otherwise.
        """
        await self.forecast(
            latitude=latitude,
            longitude=longitude,
            arrays=[
                {"name": "Test", "kwp": 1.0, "tilt_deg": 30, "azimuth_deg": 180}
            ],
        )

    async def _request(
        self, method: str, path: str, *, json: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        url = f"{API_BASE_URL}{path}"
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                response = await self._session.request(
                    method, url, headers=self._headers, json=json
                )
        except asyncio.TimeoutError as err:
            raise SolkartConnectionError(
                f"Timeout connecting to Solkart API at {url}"
            ) from err
        except aiohttp.ClientError as err:
            raise SolkartConnectionError(
                f"Error connecting to Solkart API: {err}"
            ) from err

        if response.status in (401, 403):
            raise SolkartAuthError(
                f"Solkart API rejected the API key (HTTP {response.status})"
            )
        if response.status == 429:
            raise SolkartRateLimitError(
                "Solkart API rate limit reached (HTTP 429); increase the "
                "update interval in the integration options"
            )
        if response.status >= 400:
            text = await _safe_text(response)
            raise SolkartConnectionError(
                f"Unexpected Solkart API response (HTTP {response.status}): {text}"
            )

        try:
            data = await response.json()
        except (aiohttp.ContentTypeError, ValueError) as err:
            raise SolkartConnectionError(
                "Solkart API returned a non-JSON response"
            ) from err

        if not isinstance(data, dict):
            raise SolkartConnectionError(
                "Solkart API returned an unexpected payload shape"
            )
        return data


async def _safe_text(response: aiohttp.ClientResponse) -> str:
    """Return a short snippet of a response body for error messages."""
    try:
        text = await response.text()
    except Exception:  # noqa: BLE001 - best effort for logging only
        return "<unreadable body>"
    return text[:200]
