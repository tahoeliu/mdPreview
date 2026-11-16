"""HTTPS trust for update checks and downloads.

The Python inside the packaged app is built with an OpenSSL whose default certificate
folder is a path on the build machine. On a user's Mac that folder does not exist, so
default verification trusts nothing and every HTTPS request fails. macOS itself ships
a root list at a fixed path; use it explicitly.
"""
import os
import ssl

SYSTEM_ROOTS = '/etc/ssl/cert.pem'


def context():
    if os.path.isfile(SYSTEM_ROOTS):
        return ssl.create_default_context(cafile=SYSTEM_ROOTS)
    return ssl.create_default_context()


def selfcheck():
    """No network: report where roots come from and that some were loaded."""
    stats = context().cert_store_stats()
    return {'roots': SYSTEM_ROOTS if os.path.isfile(SYSTEM_ROOTS) else None, 'count': stats.get('x509_ca', 0)}
