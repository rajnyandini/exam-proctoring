"""Raspberry Pi HTTP client module.

Sends authenticated proctoring state notifications to the Raspberry Pi 3 Model B
agent over the local network. Isolates network failures so MacBook video processing
remains real-time and uninterrupted even if the Pi is offline or unconfigured.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
import requests

logger = logging.getLogger(__name__)


@dataclass
class PiClientStatus:
    enabled: bool
    online: bool
    base_url: str
    last_response: Optional[str] = None
    last_error: Optional[str] = None


class RaspberryPiClient:
    """Non-blocking, resilient client for the Raspberry Pi proctoring agent."""

    def __init__(
        self,
        base_url: str = "http://raspberrypi.local:5050",
        shared_token: str = "",
        timeout_sec: float = 2.0,
        enabled: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.shared_token = shared_token
        self.timeout_sec = timeout_sec
        self.enabled = enabled

        self._session = requests.Session()
        self._is_online = False
        self._last_error: Optional[str] = None
        self._last_response: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        """Construct authentication headers using the shared secret."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "MacBookProctoringSystem/1.0",
        }
        if self.shared_token:
            headers["Authorization"] = f"Bearer {self.shared_token}"
            headers["X-Proctor-Auth"] = self.shared_token
        return headers

    def check_health(self) -> bool:
        """Query the Pi agent health-check endpoint."""
        if not self.enabled:
            self._is_online = False
            return False

        url = f"{self.base_url}/health"
        try:
            resp = self._session.get(url, timeout=self.timeout_sec)
            if resp.status_code == 200:
                self._is_online = True
                self._last_error = None
                self._last_response = resp.text
                return True
            else:
                self._is_online = False
                self._last_error = f"Health check returned HTTP {resp.status_code}"
                return False
        except requests.exceptions.RequestException as e:
            self._is_online = False
            self._last_error = f"Pi unreachable: {e}"
            logger.debug(f"Pi health check failed: {self._last_error}")
            return False

    def notify_status(
        self,
        status: str,
        event_type: str = "NORMAL",
        face_count: int = 1,
        explanation: str = "Candidate present and monitored.",
        timestamp: Optional[str] = None,
    ) -> bool:
        """Send authenticated status payload to the Raspberry Pi.

        status: 'NORMAL' | 'ALERT'
        event_type: 'NORMAL' | 'FACE_ABSENT' | 'MULTIPLE_FACES' | 'CAMERA_ERROR'
        """
        if not self.enabled:
            logger.debug("Pi integration disabled. Skipping status transmission.")
            return True

        if not timestamp:
            from datetime import datetime, timezone
            timestamp = datetime.now(timezone.utc).astimezone().isoformat()

        url = f"{self.base_url}/status"
        payload: Dict[str, Any] = {
            "status": status,
            "event_type": event_type,
            "face_count": face_count,
            "explanation": explanation,
            "timestamp": timestamp,
        }

        try:
            resp = self._session.post(
                url,
                json=payload,
                headers=self._get_headers(),
                timeout=self.timeout_sec,
            )
            if resp.status_code == 200:
                self._is_online = True
                self._last_error = None
                self._last_response = resp.text
                logger.info(f"Notified Pi: status={status}, event={event_type}")
                return True
            elif resp.status_code in (401, 403):
                self._last_error = f"Authentication rejected by Pi: HTTP {resp.status_code}"
                logger.error(self._last_error)
                return False
            else:
                self._last_error = f"Pi responded with HTTP {resp.status_code}: {resp.text}"
                logger.warning(self._last_error)
                return False
        except requests.exceptions.RequestException as e:
            self._is_online = False
            self._last_error = f"Pi connection failed: {e}"
            logger.debug(f"Could not reach Pi: {self._last_error}")
            return False

    def get_status(self) -> PiClientStatus:
        """Return diagnostic client telemetry."""
        return PiClientStatus(
            enabled=self.enabled,
            online=self._is_online,
            base_url=self.base_url,
            last_response=self._last_response,
            last_error=self._last_error,
        )
