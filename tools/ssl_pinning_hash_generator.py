# tools/ssl_pinning_hash_generator.py
#
# Tool implementation: given a certificate (URL, file path, or PEM string),
# computes the SHA-256 SPKI hash used for Android/iOS SSL certificate pinning.
#
# SPKI (Subject Public Key Info) pinning hashes the public key rather than the
# full certificate. This means the pin survives certificate renewals as long as
# the server doesn't rotate its key pair — making it the recommended pinning approach.

import subprocess
import tempfile
import os
import ssl
import socket
import base64


def generate_ssl_pin(cert_input: str) -> dict:
    """
    Accepts:
      - HTTPS URL   → fetches the live certificate from the server
      - File path   → reads a .pem or .der file from disk
      - PEM string  → uses the certificate text directly

    Returns the SHA-256 SPKI hash as a base64 string, ready to embed in
    Android's network_security_config.xml or iOS's Info.plist.
    """
    pem_data = _resolve_input(cert_input)

    # Write PEM to a temp file because the openssl CLI operates on files.
    # We clean it up in the finally block regardless of success or failure.
    with tempfile.NamedTemporaryFile(suffix=".pem", delete=False, mode='w') as f:
        f.write(pem_data)
        tmp_path = f.name

    try:
        # OpenSSL pipeline to compute the SHA-256 SPKI hash:
        #
        #   x509 -pubkey -noout      → extract the public key from the certificate
        #   pkey -pubin -outform der → convert to DER binary (this is the SPKI structure)
        #   dgst -sha256 -binary     → SHA-256 hash of the raw DER bytes
        #   enc -base64              → base64-encode for use in config files
        #
        # Using the openssl CLI (via subprocess) avoids adding a third-party
        # cryptography library dependency. openssl is pre-installed on macOS and Linux.
        result = subprocess.run(
            f"openssl x509 -in {tmp_path} -pubkey -noout "
            f"| openssl pkey -pubin -outform der "
            f"| openssl dgst -sha256 -binary "
            f"| openssl enc -base64",
            shell=True, capture_output=True, text=True
        )
        if result.returncode != 0:
            return {"error": result.stderr.strip()}

        return {"sha256_hash": result.stdout.strip()}
    finally:
        os.unlink(tmp_path)


def _resolve_input(cert_input: str) -> str:
    """
    Normalises any supported input type into a PEM string.
    The three input types let the tool work flexibly from the CLI, CI pipelines,
    or automated workflows without requiring a separate download step.
    """
    cert_input = cert_input.strip()

    # Raw PEM — already in the right format, use as-is.
    if cert_input.startswith("-----BEGIN"):
        return cert_input

    # HTTPS URL — fetch the live certificate directly at the TLS handshake level.
    if cert_input.startswith("https://"):
        hostname = cert_input.replace("https://", "").split("/")[0]

        ctx = ssl.create_default_context()
        # Disable certificate verification so we can fetch even self-signed or
        # expired certs. We're not validating trust here — just extracting the
        # public key for the developer to pin.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        # SSLContext.wrap_socket() is the correct modern API (ssl.wrap_socket()
        # is deprecated and doesn't support server_hostname, which is required
        # for SNI — standard for servers hosting multiple domains on one IP).
        # server_hostname tells the server which certificate to present.
        with ctx.wrap_socket(
            socket.create_connection((hostname, 443)),
            server_hostname=hostname
        ) as s:
            # getpeercert(binary_form=True) returns the raw DER-encoded cert bytes
            # from the TLS handshake — no HTTP request is made.
            der = s.getpeercert(binary_form=True)

        # Convert DER to PEM so the openssl CLI can read it.
        pem = "-----BEGIN CERTIFICATE-----\n"
        pem += base64.encodebytes(der).decode()
        pem += "-----END CERTIFICATE-----\n"
        return pem

    # File path — read PEM or DER file from disk.
    if os.path.exists(cert_input):
        with open(cert_input, 'r') as f:
            return f.read()

    raise ValueError(f"Cannot resolve input: {cert_input}")
