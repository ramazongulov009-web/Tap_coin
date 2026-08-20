from flask import Flask, jsonify, request

app = Flask(__name__)


@app.route("/")
def home():
    return "Tap Coin Server is running!"


@app.route("/api/test")
def test():
    return jsonify({
        "status": "ok",
        "message": "Tap Coin API works"
    })


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=10000
    )