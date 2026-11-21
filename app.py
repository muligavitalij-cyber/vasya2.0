import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

def add_cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

@app.after_request
def after_request(resp):
    return add_cors(resp)

@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return add_cors(app.make_response(("", 204)))

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return jsonify({"error": {"message": "Не задано GEMINI_API_KEY у Render"}}), 500

    data = request.get_json(silent=True) or {}
    model = data.get("model", "gemini-3.8-flash")
    payload = {
        "systemInstruction": data.get("systemInstruction"),
        "contents": data.get("contents", []),
    }

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    try:
        r = requests.post(
            url,
            params={"key": api_key},
            json=payload,
            timeout=60,
        )
        return jsonify(r.json()), r.status_code
    except Exception as e:
        return jsonify({"error": {"message": str(e)}}), 500

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
