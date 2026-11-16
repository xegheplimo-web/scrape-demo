"""Site adapters: one module per supported site, picked by domain."""

import importlib
from urllib.parse import urlparse

ADAPTERS = {
    "books.toscrape.com": "sites.books",
}


def get_adapter(url: str):
    """Return the adapter module for *url*'s domain, or None."""
    host = urlparse(url).netloc.lower()
    for domain, module_name in ADAPTERS.items():
        if host == domain or host.endswith("." + domain):
            return importlib.import_module(module_name)
    return None
