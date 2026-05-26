import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from mcp.server.fastmcp import FastMCP
from tools.ssl_pinning_hash_generator import generate_ssl_pin as _generate_ssl_pin

mcp = FastMCP("ssl-pinning-agent")


@mcp.tool()
def generate_ssl_pin(cert_input: str) -> dict:
    """
    Generates the SHA-256 SPKI hash of an SSL/TLS certificate for Android/iOS SSL pinning.

    Args:
        cert_input: One of — HTTPS URL to fetch the cert from, absolute file path
                    to a .pem/.der file, or a raw PEM certificate string.

    Returns a dict with 'sha256_hash' (base64 string ready for network_security_config.xml
    or Info.plist), or 'error' if something went wrong.
    """
    return _generate_ssl_pin(cert_input)


if __name__ == "__main__":
    # MCP_TRANSPORT=streamable-http  → Claude Code, Cursor, newer MCP clients
    # MCP_TRANSPORT=sse (default)    → Continue.dev, older MCP clients
    transport = os.environ.get("MCP_TRANSPORT", "sse")
    mcp.run(transport=transport)
