import os
from datetime import datetime, timezone

import psycopg2
from flask import Flask, jsonify, request

app = Flask(__name__)


# =========================
# DATABASE
# =========================

DATABASE_URL = os.environ.get("DATABASE_URL")


def get_db():
    if not DATABASE_URL:
        raise Exception("DATABASE_URL is not configured")

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

            mining_rate DOUBLE PRECISION DEFAULT 0,
            mining_last_claim TIMESTAMP WITH TIME ZONE,

            autobot_level INTEGER DEFAULT 0,
            autobot_last_claim TIMESTAMP WITH TIME ZONE,

            tap_power INTEGER DEFAULT 1,
            total_taps INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    cur.close()
    conn.close()


# =========================
# TIME
# =========================

def now():
    return datetime.now(timezone.utc)


# =========================
# USER
# =========================

def get_or_create_user(telegram_id, username="Guest"):

    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            telegram_id,
            username,
            balance,
            mining_rate,
            mining_last_claim,
            autobot_level,
            autobot_last_claim,
            tap_power,
            total_taps
        FROM users
        WHERE telegram_id = %s
    """, (telegram_id,))

    user = cur.fetchone()

    if not user:

        current = now()

        cur.execute("""
            INSERT INTO users (
                telegram_id,
                username,
                balance,
                mining_last_claim,
                autobot_last_claim
            )
            VALUES (%s, %s, 0, %s, %s)
            RETURNING
                id,
                telegram_id,
                username,
                balance,
                mining_rate,
                mining_last_claim,
                autobot_level,
                autobot_last_claim,
                tap_power,
                total_taps
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


# =========================
# PASSIVE REWARDS
# =========================

def calculate_passive(user):

    (
        user_id,
        telegram_id,
        username,
        balance,
        mining_rate,
        mining_last_claim,
        autobot_level,
        autobot_last_claim,
        tap_power,
        total_taps
    ) = user

    current = now()

    mining_reward = 0
    autobot_reward = 0

    # -------------------------
    # MINING
    # -------------------------

    if mining_rate > 0 and mining_last_claim:

        seconds = (
            current - mining_last_claim
        ).total_seconds()

        if seconds > 0:

            mining_reward = (
                seconds / 3600
            ) * mining_rate

            mining_last_claim = current

    # -------------------------
    # AUTOBOT
    # -------------------------

    if autobot_level > 0 and autobot_last_claim:

        seconds = (
            current - autobot_last_claim
        ).total_seconds()

        if seconds > 0:

            # Bot speed
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

            autobot_last_claim = current

    total_reward = (
        mining_reward +
        autobot_reward
    )

    if total_reward > 0:

        balance += total_reward

    return (
        balance,
        mining_last_claim,
        autobot_last_claim,
        mining_reward,
        autobot_reward
    )


# =========================
# HOME
# =========================

@app.route("/")
def home():

    return """
    <h2>Tap Coin Server</h2>
    <p>Server is running.</p>
    """


# =========================
# TEST
# =========================

@app.route("/api/test")
def api_test():

    return jsonify({
        "status": "ok",
        "message": "Tap Coin API works"
    })


# =========================
# USER STATE
# =========================

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

    user = get_or_create_user(
        telegram_id,
        username
    )

    (
        balance,
        mining_last_claim,
        autobot_last_claim,
        mining_reward,
        autobot_reward
    ) = calculate_passive(user)

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
        balance,
        mining_last_claim,
        autobot_last_claim,
        telegram_id
    ))

    conn.commit()

    cur.close()
    conn.close()

    return jsonify({

        "telegram_id": telegram_id,

        "username": username,

        "balance": balance,

        "mining_rate": user[4],

        "autobot_level": user[6],

        "tap_power": user[8],

        "total_taps": user[9],

        "offline_mining": mining_reward,

        "offline_autobot": autobot_reward
    })


# =========================
# RUN
# =========================

if __name__ == "__main__":

    init_db()

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                10000
            )
        )
    )