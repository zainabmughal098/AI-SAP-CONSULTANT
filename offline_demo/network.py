"""Process-local outbound guard installed before offline application imports.

Not an OS security sandbox against arbitrary native code or other processes.
No provider SDK, subprocess or native encoder is invoked by this application.
"""

import socket


def install():
    if getattr(socket, "_sap_offline_guard", False):
        return
    connect = socket.socket.connect
    connect_ex = socket.socket.connect_ex
    getaddrinfo = socket.getaddrinfo
    sendto = socket.socket.sendto

    def check(address):
        if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
            raise PermissionError("TEST_ONLY offline mode blocks external networking")

    def local_connect(sock, address):
        check(address)
        return connect(sock, address)

    def local_connect_ex(sock, address):
        check(address)
        return connect_ex(sock, address)

    def local_dns(host, *args, **kwargs):
        if host not in ("127.0.0.1", "::1", None):
            raise PermissionError("TEST_ONLY offline mode blocks external DNS")
        return getaddrinfo(host, *args, **kwargs)

    def local_sendto(sock, data, *args):
        check(args[-1])
        return sendto(sock, data, *args)

    socket.socket.connect = local_connect
    socket.socket.connect_ex = local_connect_ex
    socket.getaddrinfo = local_dns
    socket.socket.sendto = local_sendto
    socket._sap_offline_guard = True
