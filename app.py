import os
import time
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


# =========================
# DATABASE
# =========================

def get_db():
    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id BIGINT PRIMARY KEY,

            username TEXT DEFAULT '',
            first_name TEXT DEFAULT '',

            balance DOUBLE PRECISION DEFAULT 0,
            energy DOUBLE PRECISION DEFAULT 1000,
            max_energy DOUBLE PRECISION DEFAULT 1000,

            xp DOUBLE PRECISION DEFAULT 0,
            taps BIGINT DEFAULT 0,

            tap_power DOUBLE PRECISION DEFAULT 1,

            bot_level INTEGER DEFAULT 0,
            mining_rate DOUBLE PRECISION DEFAULT 0,

            last_mining DOUBLE PRECISION DEFAULT 0,
            last_update DOUBLE PRECISION DEFAULT 0,

            created_at DOUBLE PRECISION DEFAULT 0
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


init_db()


# =========================
# GET / CREATE PLAYER
# =========================

def get_or_create_player(user_id, username="", first_name=""):

    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)

    cur.execute(
        "SELECT * FROM players WHERE user_id = %s",
        (user_id,)
    )

    player = cur.fetchone()

    if not player:

        now = time.time()

        cur.execute("""
            INSERT INTO players
            (
                user_id,
                username,
                first_name,
                balance,
                energy,
                max_energy,
                xp,
                taps,
                tap_power,
                bot_level,
                mining_rate,
                last_mining,
                last_update,
                created_at
            )
            VALUES
            (
                %s,%s,%s,
                0,1000,1000,
                0,0,1,
                0,0,
                %s,%s,%s
            )
            RETURNING *
        """, (
            user_id,
            username,
            first_name,
            now,
            now,
            now
        ))

        player = cur.fetchone()

        conn.commit()

    cur.close()
    conn.close()

    return player


# =========================
# PASSIVE SYSTEM
# =========================

def process_passive(player):

    now = time.time()

    last_update = float(
        player["last_update"] or now
    )

    last_mining = float(
        player["last_mining"] or now
    )

    elapsed = max(
        0,
        now - last_mining
    )

    mining_reward = (
        elapsed / 3600
    ) * float(player["mining_rate"])

    # =====================
    # MINING
    # =====================

    if mining_reward > 0:
        player["balance"] += mining_reward

    player["last_mining"] = now

    # =====================
    # ENERGY REGEN
    # 1 energy / 3 sec
    # =====================

    energy_elapsed = max(
        0,
        now - last_update
    )

    energy_add = energy_elapsed / 3

    player["energy"] = min(
        float(player["max_energy"]),
        float(player["energy"]) + energy_add
    )

    # =====================
    # AUTO BOT
    # =====================

    bot_level = int(
        player["bot_level"]
    )

    if bot_level > 0:

        bot_interval = {
            1: 1.0,
            2: 0.5,
            3: 0.25
        }.get(
            bot_level,
            0.25
        )

        bot_taps = int(
            elapsed / bot_interval
        )

        if bot_taps > 0:

            possible_taps = min(
                bot_taps,
                int(player["energy"])
            )

            if possible_taps > 0:

                reward = (
                    possible_taps *
                    float(player["tap_power"])
                )

                player["balance"] += reward
                player["xp"] += reward
                player["taps"] += possible_taps
                player["energy"] -= possible_taps

    player["last_update"] = now

    return player


# =========================
# SAVE PLAYER
# =========================

def save_player(player):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE players SET

            balance = %s,
            energy = %s,
            max_energy = %s,

            xp = %s,
            taps = %s,

            tap_power = %s,

            bot_level = %s,
            mining_rate = %s,

            last_mining = %s,
            last_update = %s,

            username = %s,
            first_name = %s

        WHERE user_id = %s
    """, (

        player["balance"],
        player["energy"],
        player["max_energy"],

        player["xp"],
        player["taps"],

        player["tap_power"],

        player["bot_level"],
        player["mining_rate"],

        player["last_mining"],
        player["last_update"],

        player["username"],
        player["first_name"],

        player["user_id"]
    ))

    conn.commit()
    cur.close()
    conn.close()


# =========================
# HOME
# =========================

@app.route("/")
def home():

    return jsonify({
        "message": "Tap Coin API works",
        "status": "ok"
    })


# =========================
# GET PLAYER
# =========================

@app.route("/api/player", methods=["GET"])
def player():

    user_id = request.args.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    try:
        user_id = int(user_id)
    except:
        return jsonify({
            "error": "invalid user_id"
        }), 400

    username = request.args.get(
        "username",
        ""
    )

    first_name = request.args.get(
        "first_name",
        ""
    )

    player = get_or_create_player(
        user_id,
        username,
        first_name
    )

    player = process_passive(player)

    save_player(player)

    return jsonify(dict(player))


# =========================
# TAP
# =========================

@app.route("/api/tap", methods=["POST"])
def tap():

    data = request.get_json() or {}

    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    player = get_or_create_player(
        int(user_id)
    )

    player = process_passive(player)

    fingers = int(
        data.get("fingers", 1)
    )

    fingers = max(
        1,
        min(fingers, 10)
    )

    if player["energy"] < 1:

        save_player(player)

        return jsonify({
            "error": "No Energy",
            "player": dict(player)
        }), 400

    possible = min(
        fingers,
        int(player["energy"])
    )

    reward = (
        possible *
        float(player["tap_power"])
    )

    player["balance"] += reward
    player["xp"] += reward
    player["taps"] += possible
    player["energy"] -= possible

    save_player(player)

    return jsonify({
        "reward": reward,
        "player": dict(player)
    })


# =========================
# BUY BOT
# =========================

@app.route("/api/bot/buy", methods=["POST"])
def buy_bot():

    data = request.get_json() or {}

    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    player = get_or_create_player(
        int(user_id)
    )

    player = process_passive(player)

    level = int(
        player["bot_level"]
    )

    prices = {
        0: 5000,
        1: 15000,
        2: 50000
    }

    if level >= 3:

        return jsonify({
            "error": "Maximum bot level",
            "player": dict(player)
        }), 400

    price = prices[level]

    if player["balance"] < price:

        return jsonify({
            "error": "Not enough balance",
            "price": price,
            "player": dict(player)
        }), 400

    player["balance"] -= price
    player["bot_level"] += 1

    save_player(player)

    return jsonify({
        "success": True,
        "price": price,
        "player": dict(player)
    })


# =========================
# BUY MINER
# =========================

@app.route("/api/mining/buy", methods=["POST"])
def buy_mining():

    data = request.get_json() or {}

    user_id = data.get("user_id")
    miner = int(
        data.get("miner", 1)
    )

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    miners = {

        1: {
            "price": 10000,
            "rate": 100
        },

        2: {
            "price": 50000,
            "rate": 600
        },

        3: {
            "price": 250000,
            "rate": 3000
        },

        4: {
            "price": 1000000,
            "rate": 15000
        }

    }

    if miner not in miners:

        return jsonify({
            "error": "Invalid miner"
        }), 400

    player = get_or_create_player(
        int(user_id)
    )

    player = process_passive(player)

    price = miners[miner]["price"]
    rate = miners[miner]["rate"]

    if player["balance"] < price:

        return jsonify({
            "error": "Not enough balance",
            "price": price,
            "player": dict(player)
        }), 400

    player["balance"] -= price

    player["mining_rate"] += rate

    save_player(player)

    return jsonify({
        "success": True,
        "miner": miner,
        "rate": rate,
        "player": dict(player)
    })


# =========================
# POWER UPGRADE
# =========================

@app.route("/api/power", methods=["POST"])
def power():

    data = request.get_json() or {}

    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    player = get_or_create_player(
        int(user_id)
    )

    player = process_passive(player)

    price = 2000 * float(
        player["tap_power"]
    )

    if player["balance"] < price:

        return jsonify({
            "error": "Not enough balance",
            "price": price,
            "player": dict(player)
        }), 400

    player["balance"] -= price
    player["tap_power"] += 1

    save_player(player)

    return jsonify({
        "success": True,
        "player": dict(player)
    })


# =========================
# ENERGY UPGRADE
# =========================

@app.route("/api/energy-upgrade", methods=["POST"])
def energy_upgrade():

    data = request.get_json() or {}

    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    player = get_or_create_player(
        int(user_id)
    )

    player = process_passive(player)

    price = 3000 * (
        float(player["max_energy"]) / 1000
    )

    if player["balance"] < price:

        return jsonify({
            "error": "Not enough balance",
            "price": price,
            "player": dict(player)
        }), 400

    player["balance"] -= price

    player["max_energy"] += 500
    player["energy"] += 500

    save_player(player)

    return jsonify({
        "success": True,
        "player": dict(player)
    })


# =========================
# SAVE
# =========================

@app.route("/api/save", methods=["POST"])
def save():

    data = request.get_json() or {}

    user_id = data.get("user_id")

    if not user_id:
        return jsonify({
            "error": "user_id required"
        }), 400

    player = get_or_create_player(
        int(user_id)
    )

    player = process_passive(player)

    save_player(player)

    return jsonify({
        "success": True,
        "player": dict(player)
    })


# =========================
# HEALTH
# =========================

@app.route("/health")
def health():

    return jsonify({
        "status": "healthy"
    })


# =========================
# START
# =========================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )