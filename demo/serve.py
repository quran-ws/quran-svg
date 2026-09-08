#!/usr/bin/env python3
"""Serve the repo so the demo can read the mushaf folders, and open it.

    python3 demo/serve.py            # http://127.0.0.1:8000/demo/
    python3 demo/serve.py --port 9000 --no-open

If the port is already serving something else -- 8000 is a popular default and easy to have
occupied -- the next free one is used and printed, rather than failing with an address-in-use
traceback or, worse, appearing to work while another server answers on that port.
"""

import argparse
import functools
import http.server
import os
import socketserver
import threading
import webbrowser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):        # one line per page, not per byte
        if "GET" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    handler = functools.partial(Handler, directory=ROOT)
    socketserver.TCPServer.allow_reuse_address = True
    httpd, port = None, args.port
    for candidate in range(args.port, args.port + 20):
        try:
            httpd = socketserver.ThreadingTCPServer(("127.0.0.1", candidate), handler)
            port = candidate
            break
        except OSError:
            continue
    if httpd is None:
        raise SystemExit("no free port in %d-%d" % (args.port, args.port + 19))
    if port != args.port:
        print("port %d is in use by something else; serving on %d instead"
              % (args.port, port))
    with httpd:
        url = "http://127.0.0.1:%d/demo/" % port
        print("serving %s at %s   (ctrl-c to stop)" % (ROOT, url))
        if not args.no_open:
            threading.Timer(0.5, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
