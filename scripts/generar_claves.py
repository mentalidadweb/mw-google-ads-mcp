#!/usr/bin/env python3
"""Imprime tres claves aleatorias seguras para el despliegue en Railway.

Uso:
    python scripts/generar_claves.py

Las claves de cifrado usan el formato Fernet (32 bytes en base64 URL safe), que
el servidor acepta directamente. La clave JWT usa 48 bytes aleatorios.
No guardes la salida en el repositorio: cópiala directo en Railway > Variables.
"""

import base64
import secrets


def _fernet_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def main() -> None:
    print(f"GOOGLE_ADS_MCP_JWT_SIGNING_KEY={secrets.token_urlsafe(48)}")
    print(f"GOOGLE_ADS_MCP_STORAGE_ENCRYPTION_KEY={_fernet_key()}")
    print(f"GOOGLE_ADS_MCP_AUDIT_STORAGE_ENCRYPTION_KEY={_fernet_key()}")


if __name__ == "__main__":
    main()
