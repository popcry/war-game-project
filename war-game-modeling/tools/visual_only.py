"""Static HTTP server that opens the 3D visual viewer directly.

런처/시뮬레이션을 거치지 않고 results/simulation.csv를 바로 3D로 보여준다.
서버는 프로젝트 루트(war-game-modeling)를 정적으로 서빙한다.

사용:
    python tools/visual_only.py                # 자동으로 브라우저 열기
    python tools/visual_only.py --port 8090    # 포트 지정
    python tools/visual_only.py --no-open      # 브라우저 자동 오픈 끄기
"""
from __future__ import annotations

import argparse
import http.server
import os
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # Hide noisy per-request logs; keep errors.
        if args and isinstance(args[1], str) and args[1].startswith(("4", "5")):
            super().log_message(fmt, *args)


def _ensure_assets() -> None:
    required = [
        REPO_ROOT / "visual" / "index.html",
        REPO_ROOT / "results" / "simulation.csv",
    ]
    missing = [str(p.relative_to(REPO_ROOT)) for p in required if not p.exists()]
    if missing:
        print(f"[visual_only] 필수 파일이 없습니다: {missing}", file=sys.stderr)
        print(f"[visual_only] 먼저 시뮬레이션을 1회 실행해 results/simulation.csv를 생성하세요.", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="3D 비주얼 뷰어를 바로 띄운다")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-open", action="store_true", help="브라우저 자동 오픈 끄기")
    args = parser.parse_args()

    _ensure_assets()
    os.chdir(REPO_ROOT)

    url = f"http://127.0.0.1:{args.port}/visual/"
    handler = QuietHandler

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", args.port), handler) as httpd:
        print(f"[visual_only] Serving {REPO_ROOT}")
        print(f"[visual_only] Open: {url}")
        if not args.no_open:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[visual_only] stopped.")


if __name__ == "__main__":
    main()
