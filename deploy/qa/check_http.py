"""Verify the public QA route, including the files required by Django admin."""
import argparse
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


CHECKS = (
    ("/admin/login/", {"text/html"}),
    ("/static/admin/css/base.css", {"text/css"}),
    ("/static/admin/js/core.js", {"text/javascript", "application/javascript"}),
)


def check(base_url):
    for path, expected_types in CHECKS:
        with urlopen(base_url.rstrip("/") + path, timeout=10) as response:
            content_type = response.headers.get_content_type()
            if response.status != 200 or content_type not in expected_types:
                raise ValueError(f"{path}: HTTP {response.status}, Content-Type {content_type}")
            if not response.read(1):
                raise ValueError(f"{path}: empty response")
        print(f"OK {path} ({content_type})", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--attempts", type=int, default=60)
    args = parser.parse_args()
    parts = urlsplit(args.base_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password or parts.path not in {"", "/"} or parts.query or parts.fragment:
        parser.error("base_url must be an HTTP(S) origin without credentials or path")
    if args.attempts < 1:
        parser.error("attempts must be positive")
    for attempt in range(1, args.attempts + 1):
        try:
            check(args.base_url)
            return
        except (URLError, ValueError, TimeoutError, OSError) as exc:
            print(f"Attempt {attempt}/{args.attempts}: {exc}", flush=True)
            if attempt == args.attempts:
                raise SystemExit("QA HTTP check failed") from exc
            time.sleep(2)


if __name__ == "__main__":
    main()
