from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
import requests
import socket


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """Contract tests must never contact a speech API, even on regression."""
    def blocked(*args, **kwargs):
        raise AssertionError("Network access is forbidden in offline voice tests")

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)


@dataclass
class FakeResponse:
    status_code: int = 200
    content: bytes = b"audio"
    payload: Any = None
    text: str = ""

    def json(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload if self.payload is not None else {}


@pytest.fixture
def fake_response():
    return FakeResponse()
