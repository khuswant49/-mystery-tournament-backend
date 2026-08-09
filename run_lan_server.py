"""
Standalone entry point for the LAN fallback server -- built into a single
.exe via PyInstaller (see backend/README.md's "Build a standalone .exe"
section) so it can run on any Windows laptop with zero setup: no Python, no
pip install, no manually editing a .env file. Double-click it and it prints
the LAN address and admin PIN to give out, then just runs.
"""
import os
import secrets
import socket
import sys


def _persistent_dir():
    # Next to the actual .exe (or this script, when run normally in dev) --
    # NOT PyInstaller's temporary extraction directory for bundled
    # resources, which is wiped the moment the process exits. The config
    # file and the SQLite DB both need to survive between runs.
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _load_or_create_config(base_dir):
    config_path = os.path.join(base_dir, "lan_server_config.txt")
    config = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()

    changed = False
    if not config.get("ADMIN_PIN"):
        config["ADMIN_PIN"] = "".join(secrets.choice("0123456789") for _ in range(6))
        changed = True
    if not config.get("COOKIE_SECRET"):
        config["COOKIE_SECRET"] = secrets.token_hex(32)
        changed = True

    if changed:
        with open(config_path, "w") as f:
            f.write("# Mystery Tournament LAN server config -- auto-generated on first run.\n")
            f.write("# Delete this file to get a fresh random PIN next time.\n")
            f.write("ADMIN_PIN={}\n".format(config["ADMIN_PIN"]))
            f.write("COOKIE_SECRET={}\n".format(config["COOKIE_SECRET"]))

    return config


def _detect_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    base_dir = _persistent_dir()
    config = _load_or_create_config(base_dir)

    # Must happen BEFORE importing app.main -- app.config reads these from
    # os.environ at import time, not lazily.
    os.environ["ADMIN_PIN"] = config["ADMIN_PIN"]
    os.environ["COOKIE_SECRET"] = config["COOKIE_SECRET"]
    os.environ.setdefault("CORS_ORIGINS", "*")
    db_path = os.path.join(base_dir, "local.db").replace("\\", "/")
    os.environ["DATABASE_URL"] = "sqlite:///" + db_path

    import uvicorn
    from app.main import app

    ip = _detect_lan_ip()
    port = 8000

    print("=" * 64)
    print("MYSTERY TOURNAMENT -- LAN SERVER")
    print("=" * 64)
    print("Admin dashboard : http://{}:{}/admin/".format(ip, port))
    print("Admin PIN       : {}".format(config["ADMIN_PIN"]))
    print("Give this address to players' games and the cloud")
    print("dashboard's Backend Mode page:")
    print("    http://{}:{}".format(ip, port))
    print()
    print("Keep this window open -- closing it stops the server.")
    print("=" * 64)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback

        traceback.print_exc()
    finally:
        input("\nPress Enter to close this window...")
