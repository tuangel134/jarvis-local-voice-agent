#!/usr/bin/env python3
from __future__ import annotations

import argparse

from jarvis.web.app import run


def main() -> None:
    parser = argparse.ArgumentParser(description='Run the Jarvis Reactive Web UI')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=7070)
    parser.add_argument('--open-browser', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()

    open_browser = args.open_browser and not args.no_browser
    run(host=args.host, port=args.port, open_browser=open_browser)


if __name__ == '__main__':
    main()
