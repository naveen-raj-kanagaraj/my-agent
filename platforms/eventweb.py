"""Public, read-only live dashboard for the tracked event (only public YouTube numbers, nothing about users).

Runs on its own port (EVENT_WEB_PORT, default 8092, this computer only) so the owner dashboard on 8090 is never
exposed. core/tunnel.py gives it a public https link that opens on any device.
"""
import logging
import os

from flask import Flask, Response, jsonify

from core import eventpage

PORT = int(os.getenv("EVENT_WEB_PORT", "8092"))
app = Flask(__name__)


@app.after_request
def _headers(resp):
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Robots-Tag"] = "noindex, nofollow"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


@app.route("/")
def index():
    return Response(eventpage.build_html(live=True), mimetype="text/html")


@app.route("/data")
def data():
    return jsonify(eventpage.data())


@app.route("/robots.txt")
def robots():
    return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


def run():
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print(f"Event dashboard: http://localhost:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False, use_reloader=False, threaded=True)
