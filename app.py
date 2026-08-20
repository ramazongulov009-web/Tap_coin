import os
from datetime import datetime, timezone

import psycopg2
from flask import Flask, jsonify, request

app = Flask(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")


# =========================================================
# DATABASE
# =========================================================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg2.connect(DATABASE_URL)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username TEXT DEFAULT 'Guest',

            balance DOUBLE PRECISION DEFAULT 0,
            energy DOUBLE PRECISION DEFAULT 1000,
            max_energy DOUBLE PRECISION DEFAULT 1000,

            xp DOUBLE PRECISION DEFAULT 0,
            total_taps BIGINT DEFAULT 0,

            tap_power INTEGER DEFAULT 1,

            autobot_level INTEGER DEFAULT 0,
            autobot_last_claim TIMESTAMP WITH TIME ZONE,

            mining_rate DOUBLE PRECISION DEFAULT 0,
            mining_last_claim TIMESTAMP WITH TIME ZONE,

            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# =========================================================
# TIME
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


# =========================================================
# USER
# =========================================================

def create_user(telegram_id, username):
    current = utc_now()

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        INSERT INTO users (
            telegram_id,
            username,
            balance,
            energy,
            max_energy,
            xp,
            total_taps,
            tap_power,
            autobot_level,
            autobot_last_claim,
            mining_rate,
            mining_last_claim
        )
        VALUES (
            %s, %s, 0, 1000, 1000, 0, 0, 1,
            0, %s, 0, %s
        )
        ON CONFLICT (telegram_id)
        DO UPDATE SET username = EXCLUDED.username
        RETURNING *
    """, (
        telegram_id,
        username,
        current,
        current
    ))

    user = cur.fetchone()

    conn.commit()
    cur.close()
    conn.close()

    return user


def get_user(telegram_id, username="Guest"):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT *
        FROM users
        WHERE telegram_id = %s
    """, (telegram_id,))

    user = cur.fetchone()

    cur.close()
    conn.close()

    if not user:
        return create_user(
            telegram_id,
            username
        )

    return user


# =========================================================
# PASSIVE REWARDS
# =========================================================

def calculate_passive(user):
    """
    Mining + AutoBot-ро барои вақти гузашта ҳисоб мекунад.
    Mini App баста бошад ҳам кор мекунад.
    """

    (
        user_id,
        telegram_id,
        username,
        balance,
        energy,
        max_energy,
        xp,
        total_taps,
        tap_power,
        autobot_level,
        autobot_last_claim,
        mining_rate,
        mining_last_claim,
        created_at
    ) = user

    current = utc_now()

    mining_reward = 0
    autobot_reward = 0

    # -----------------------------------------------------
    # MINING
    # -----------------------------------------------------

    if mining_rate > 0 and mining_last_claim:

        seconds = (
            current - mining_last_claim
        ).total_seconds()

        if seconds > 0:

            # Maximum offline mining = 24 hours
            seconds = min(
                seconds,
                24 * 60 * 60
            )

            mining_reward = (
                seconds / 3600
            ) * mining_rate

            balance += mining_reward

            mining_last_claim = current

    else:
        mining_last_claim = current

    # -----------------------------------------------------
    # AUTOBOT
    # -----------------------------------------------------

    if autobot_level > 0 and autobot_last_claim:

        seconds = (
            current - autobot_last_claim
        ).total_seconds()

        if seconds > 0:

            # Maximum offline AutoBot = 24 hours
            seconds = min(
                seconds,
                24 * 60 * 60
            )

            if autobot_level == 1:
                taps_per_second = 1

            elif autobot_level == 2:
                taps_per_second = 2

            else:
                taps_per_second = 4

            autobot_reward = (
                seconds *
                taps_per_second *
                tap_power
            )

            balance += autobot_reward

            autobot_last_claim = current

    else:
        autobot_last_claim = current

    return {
        "balance": balance,
        "mining_reward": mining_reward,
        "autobot_reward": autobot_reward,
        "mining_last_claim": mining_last_claim,
        "autobot_last_claim": autobot_last_claim
    }


def save_passive(
    telegram_id,
    result
):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET
            balance = %s,
            mining_last_claim = %s,
            autobot_last_claim = %s
        WHERE telegram_id = %s
    """, (
        result["balance"],
        result["mining_last_claim"],
        result["autobot_last_claim"],
        telegram_id
    ))

    conn.commit()

    cur.close()
    conn.close()


# =========================================================
# STATE
# =========================================================

@app.route("/api/state", methods=["GET"])
def state():

    telegram_id = request.args.get(
        "telegram_id",
        type=int
    )

    username = request.args.get(
        "username",
        "Guest"
    )

    if not telegram_id:
        return jsonify({
            "error": "telegram_id required"
        }), 400

    user = get_user(
        telegram_id,
        username
    )

    result = calculate_passive(user)

    save_passive(
        telegram_id,
        result
    )

    user = get_user(
        telegram_id,
        username
    )

    (
        user_id,
        telegram_id,
        username,
        balance,
        energy,
        max_energy,
        xp,
        total_taps,
        tap_power,
        autobot_level,
        autobot_last_claim,
        mining_rate,
        mining_last_claim,
        created_at
    ) = user

    return jsonify({
        "telegram_id": telegram_id,
        "username": username,

        "balance": balance,

        "energy": energy,
        "max_energy": max_energy,

        "xp": xp,
        "total_taps": total_taps,

        "tap_power": tap_power,

        "autobot_level": autobot_level,
        "mining_rate": mining_rate,

        "offline_mining": result["mining_reward"],
        "offline_autobot": result["autobot_reward"]
    })


# =========================================================
# TAP
# =========================================================

@app.route("/api/tap", methods=["POST"])
def tap():

    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = data.get(
        "telegram_id"
    )

    username = data.get(
        "username",
        "Guest"
    )

    fingers = int(
        data.get(
            "fingers",
            1
        )
    )

    if not telegram_id:
        return jsonify({
            "error": "telegram_id required"
        }), 400

    fingers = max(
        1,
        min(fingers, 5)
    )

    user = get_user(
        telegram_id,
        username
    )

    passive = calculate_passive(
        user
    )

    balance = passive["balance"]

    energy = user[4]
    max_energy = user[5]
    xp = user[6]
    total_taps = user[7]
    tap_power = user[8]

    if energy <= 0:

        return jsonify({
            "error": "No Energy"
        }), 400

    used = min(
        fingers,
        int(energy)
    )

    reward = (
        tap_power *
        used
    )

    balance += reward
    xp += reward
    energy -= used
    total_taps += used

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET
            balance = %s,
            energy = %s,
            xp = %s,
            total_taps = %s,
            mining_last_claim = %s,
            autobot_last_claim = %s
        WHERE telegram_id = %s
    """, (
        balance,
        energy,
        xp,
        total_taps,
        passive["mining_last_claim"],
        passive["autobot_last_claim"],
        telegram_id
    ))

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "ok": True,
        "reward": reward,
        "balance": balance,
        "energy": energy,
        "xp": xp,
        "total_taps": total_taps
    })


# =========================================================
# BUY MINER
# =========================================================

@app.route("/api/mining/buy", methods=["POST"])
def buy_mining():

    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = data.get(
        "telegram_id"
    )

    miner = int(
        data.get(
            "miner",
            1
        )
    )

    if not telegram_id:
        return jsonify({
            "error": "telegram_id required"
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

    price = miners[miner]["price"]
    rate = miners[miner]["rate"]

    user = get_user(
        telegram_id
    )

    passive = calculate_passive(
        user
    )

    balance = passive["balance"]
    mining_rate = user[11]

    if balance < price:

        return jsonify({
            "error":
                f"Need {price} R"
        }), 400

    balance -= price
    mining_rate += rate

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET
            balance = %s,
            mining_rate = %s,
            mining_last_claim = %s,
            autobot_last_claim = %s
        WHERE telegram_id = %s
    """, (
        balance,
        mining_rate,
        passive["mining_last_claim"],
        passive["autobot_last_claim"],
        telegram_id
    ))

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "ok": True,
        "balance": balance,
        "mining_rate": mining_rate
    })


# =========================================================
# BUY AUTOBOT
# =========================================================

@app.route("/api/autobot/buy", methods=["POST"])
def buy_autobot():

    data = request.get_json(
        silent=True
    ) or {}

    telegram_id = data.get(
        "telegram_id"
    )

    if not telegram_id:
        return jsonify({
            "error": "telegram_id required"
        }), 400

    user = get_user(
        telegram_id
    )

    passive = calculate_passive(
        user
    )

    balance = passive["balance"]
    bot_level = user[9]

    prices = {
        1: 5000,
        2: 15000,
        3: 50000
    }

    next_level = (
        bot_level + 1
    )

    if next_level not in prices:

        return jsonify({
            "error": "Maximum level"
        }), 400

    price = prices[next_level]

    if balance < price:

        return jsonify({
            "error":
                f"Need {price} R"
        }), 400

    balance -= price
    bot_level = next_level

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        UPDATE users
        SET
            balance = %s,
            autobot_level = %s,
            mining_last_claim = %s,
            autobot_last_claim = %s
        WHERE telegram_id = %s
    """, (
        balance,
        bot_level,
        passive["mining_last_claim"],
        passive["autobot_last_claim"],
        telegram_id
    ))

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({
        "ok": True,
        "balance": balance,
        "autobot_level": bot_level
    })


# =========================================================
# HEALTH
# =========================================================

@app.route("/")
def home():

    return jsonify({
        "status": "online",
        "service": "Tap Coin API",
        "version": "5.0"
    })


@app.route("/api/test")
def test():

    return jsonify({
        "status": "ok",
        "message": "Tap Coin API works"
    })


# =========================================================
# STARTUP
# =========================================================

# Gunicorn app:app-ро истифода мебарад,
# бинобар ин database-ро ҳангоми import месозем.
try:
    init_db()
except Exception as e:
    print(
        "Database initialization error:",
        e
    )


if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                10000
            )
        )
    )