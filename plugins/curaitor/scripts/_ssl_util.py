"""SSL trust-store helpers for curaitor scripts.

Python 3.14's SSL verification is strict about malformed basicConstraints
extensions in the system keychain. Using certifi's CA bundle sidesteps local
trust-store quirks — including residual certificates from TLS-intercepting
proxies like Netskope even when the proxy is disabled.

Two helpers are provided:

- `install_certifi_env()` for scripts using `requests` (sets SSL_CERT_FILE and
  REQUESTS_CA_BUNDLE env vars if not already set).
- `build_ssl_context()` for scripts using `urllib.request` directly (returns
  an `ssl.SSLContext` backed by certifi, falling back to the system default).

Both are no-ops if certifi is not installed.
"""

import os
import ssl


def install_certifi_env():
    """Point requests/urllib env vars at certifi's CA bundle.

    No-op if SSL_CERT_FILE and REQUESTS_CA_BUNDLE are already set, or if
    certifi is not importable.
    """
    if os.environ.get('SSL_CERT_FILE') and os.environ.get('REQUESTS_CA_BUNDLE'):
        return
    try:
        import certifi
        bundle = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', bundle)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', bundle)
    except ImportError:
        pass


def build_ssl_context():
    """Return an SSLContext using certifi's CA bundle, or the system default."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()
