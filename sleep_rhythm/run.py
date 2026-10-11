"""Local launcher: python run.py. Production: python run.py --production."""
import argparse
import os
import socket
import sys
import threading
import webbrowser
from wsgiref.simple_server import make_server, WSGIRequestHandler, WSGIServer
from sleepapp.server import application


class QuietHandler(WSGIRequestHandler):
    def log_message(self, format, *args):
        pass


class LocalServer(WSGIServer):
    # On Windows SO_REUSEADDR lets a second program (for example an older copy
    # that is still running) bind the same port and take its connections, so it
    # stays off there, as in socket.create_server(); restarting works without it.
    allow_reuse_address = os.name != "nt"


def lan_addresses():
    """IPv4 addresses that phones on the same Wi-Fi may use to reach this computer."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))  # route lookup only: a UDP connect sends nothing
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        found += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    out = []
    for ip in found:
        if not ip.startswith(("127.", "0.", "169.254.")) and ip not in out:
            out.append(ip)
    return out


def main():
    parser = argparse.ArgumentParser(description="리듬 수면 관리 앱")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("포트는 1~65535입니다.")
    everywhere = args.host in ("0.0.0.0", "")
    url = f"http://{'127.0.0.1' if everywhere else args.host}:{args.port}"
    if args.production:
        print(f"리듬 실행 주소: {url}", flush=True)
        try:
            from waitress import serve
        except ImportError:
            parser.error("배포 서버에는 python -m pip install -r requirements.txt 를 먼저 실행하세요.")
        serve(application, host=args.host, port=args.port, threads=4,
              max_request_body_size=524288, inbuf_overflow=1048576,
              outbuf_overflow=1048576, channel_timeout=30, ident="Rhythm")
        return
    try:
        httpd = make_server(args.host, args.port, application,
                            server_class=LocalServer, handler_class=QuietHandler)
    except OSError as err:
        other = 8001 if args.port != 8001 else 8002
        sys.exit(f"서버를 열 수 없습니다: {err}\n"
                 f"- 리듬 실행 창(예전 버전 포함)이 이미 켜져 있으면 그 창을 닫고 다시 실행하세요.\n"
                 f"- 다른 프로그램이 {args.port}번 포트를 쓰고 있으면 python run.py --port {other} 처럼 다른 포트를 쓰세요.")
    lines = [f"리듬 실행 주소: {url}"]
    if everywhere:
        phones = lan_addresses()
        if phones:
            lines.append(f"같은 Wi-Fi의 휴대폰에서 열 주소: http://{phones[0]}:{args.port}")
            lines += [f"  (열리지 않으면 이 주소도 시도: http://{ip}:{args.port})" for ip in phones[1:3]]
        else:
            lines.append("휴대폰에서 열 주소를 찾지 못했습니다. Wi-Fi 연결을 확인하세요.")
    lines.append("종료: Ctrl+C 또는 이 창 닫기. 기록은 사용 중인 브라우저에 보관됩니다.")
    print("\n".join(lines), flush=True)
    try:
        if not args.no_browser:
            timer = threading.Timer(.7, lambda: webbrowser.open(url))
            timer.daemon = True
            timer.start()
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n종료했습니다.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
