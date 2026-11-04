"""Tests must not contact live providers or require real credentials."""

import socket

import pytest


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def local_only_connect(sock, address):
        # Windows asyncio uses loopback sockets to wake its own event loop.
        if isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1"):
            return original_connect(sock, address)
        raise AssertionError("External network access is disabled in automated tests")

    def local_only_connection(address, *args, **kwargs):
        if address[0] in ("127.0.0.1", "::1"):
            return original_create_connection(address, *args, **kwargs)
        raise AssertionError("External network access is disabled in automated tests")

    monkeypatch.setattr(socket.socket, "connect", local_only_connect)
    monkeypatch.setattr(socket, "create_connection", local_only_connection)
