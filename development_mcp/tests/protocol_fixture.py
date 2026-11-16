"""Synthetic stdio server, used only by protocol tests. Never reads environment/DB."""
import logging
import sys

from development_mcp.server import create_server
from development_mcp.service import Service
from .helpers import MemoryDatabase, NoNER, fixture

if __name__ == '__main__':
    logging.disable(sys.maxsize)
    create_server(Service(MemoryDatabase(fixture()), NoNER(), 'synthetic-protocol-test-secret-123456')).run(transport='stdio')
