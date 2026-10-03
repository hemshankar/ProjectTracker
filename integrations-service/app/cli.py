"""Bootstrap helpers: python -m app.cli hash-password | gen-keys"""
import getpass
import secrets
import sys

from cryptography.fernet import Fernet

from .services.admin_auth_service import hash_password


def main(argv: list) -> int:
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "hash-password":
        pw = argv[2] if len(argv) > 2 else getpass.getpass("Admin password: ")
        print(f"ADMIN_PASSWORD_HASH={hash_password(pw)}")
    elif cmd == "gen-keys":
        print(f"SECRETS_ENCRYPTION_KEY={Fernet.generate_key().decode()}")
        print(f"ADMIN_SESSION_SECRET={secrets.token_hex(32)}")
    else:
        print("usage: python -m app.cli hash-password [password] | gen-keys")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
