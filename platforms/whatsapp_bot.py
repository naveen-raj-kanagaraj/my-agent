import os
from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
from core.agent import chat
from core.memory import Memory
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
memory = Memory()


@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    from_number = request.form.get("From", "")
    body = request.form.get("Body", "").strip()
    resp = MessagingResponse()

    user_id = from_number.replace("whatsapp:", "")
    if user_id != os.getenv("MY_WHATSAPP_NUMBER", "").replace("whatsapp:", ""):
        return str(resp)

    if not body:
        return str(resp)

    if body.lower() == "!clear":
        memory.clear(user_id, "whatsapp")
        resp.message("Memory cleared.")
        return str(resp)

    response_text = chat(user_id, "whatsapp", body)
    resp.message(response_text)
    return str(resp)


@app.route("/", methods=["GET"])
def index():
    return "Agent running", 200


def run_whatsapp():
    print("WhatsApp: running on port 5001")
    app.run(host="127.0.0.1", port=5001, debug=False, use_reloader=False)