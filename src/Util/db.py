import json
import secrets
import os

import pymysql
import hashlib
import redis

from src.Util.Models import UserLogin

ip = "192.168.1.90"
# ip = "127.0.0.1"

connectionDB = {
    "host": ip,
    "user": "root",
    "password": os.environ.get("DB_MYSQL_PASSWORD")
}

client = redis.StrictRedis(host=ip,
                           port=6379,
                           db=0,
                           password=os.environ.get("DB_REDIS_PASSWORD"))


def get_connection():
    return pymysql.connect(**connectionDB)


def set_session(key: int, value: str, ex: int, user_hash: str) -> bool:
    # print(key, value, ex)
    with get_connection() as con:
        cur = con.cursor()
        cur.execute(f"SELECT tb_collection_user.id_collection_user FROM auth.tb_collection_user "
                    f"WHERE user_hash = '{user_hash}'")

        res = cur.fetchall()
        if not res:
            return False

        cur.execute("INSERT IGNORE INTO "
                    f"auth.tb_user_session (id_collection_user, user_session_key,"
                    f" user_session_value, user_session_creation) "
                    "VALUES (%s,%s, %s, NOW())",
                    [res[0][0], key, value])
        i = con.insert_id()
        con.commit()
        if i == 0:
            return False
    client.set(hex(key)[2:], value, ex=ex)
    return True


def get_session(key: int) -> UserLogin | None:
    # print('====', hex(key)[2:])
    res = client.get(hex(key)[2:])
    if res:
        res = json.loads(res)
        return UserLogin(user_session=res['user_session'],
                         user_session_length=res['user_session_length'],
                         user_hash=res['user_hash'],
                         user_collection=res['user_collection'])
    return None


def db_validate_session(user_hash: str, user_session: str) -> bool:
    with get_connection() as con:
        cur = con.cursor()
        cur.execute(f'SELECT user_session '
                    f'FROM auth.tb_collection_user '
                    f'WHERE user_hash = "{user_hash}"')
        res = cur.fetchall()
        if res:
            return res[0][0] == user_session
        return False


def db_login(user: str, password: str, collection: str) -> UserLogin | None:
    """
    Will make the login process, the password will be hashed before to call the db
    :param collection:
    :param user: Username
    :param password: Password
    :return: dictionary
    """
    password = hashlib.sha256(password.encode()).hexdigest().upper()
    with get_connection() as con:
        cur = con.cursor()

        cur.execute(f'SELECT tcu.user_session,tcu.user_session_length, tcu.user_hash, tcu.id_collection_user '
                    f'FROM auth.tb_collection_user tcu '
                    f'INNER JOIN auth.tb_collection tc ON tc.id_collection = tcu.id_collection '
                    f'WHERE user_name = "{user}" AND '
                    f'user_password ="{password}" AND '
                    f'collection_hash = "{collection}"')
        res = cur.fetchone()

        if not res:
            return None

        if res:
            return UserLogin(user_session=res[0],
                             user_session_length=res[1],
                             user_hash=res[2],
                             user_collection=collection)
        return None


def db_register(collection: str, user: str, password: str, email=None) -> UserLogin | None:
    password = hashlib.sha256(password.encode()).hexdigest().upper()
    user_hash = secrets.token_hex(32).upper()
    user_session = secrets.token_hex(32).upper()
    user_session_length = 60 * 60 * 24 * 3
    with get_connection() as con:
        cur = con.cursor()
        cur.execute(f"SELECT tb_collection.id_collection FROM auth.tb_collection "
                    f"WHERE collection_hash = '{collection}'")

        res = cur.fetchall()
        if not res:
            return None

        cur.execute("INSERT IGNORE INTO "
                    f"auth.tb_collection_user (id_collection, user_creation, user_name, user_email, user_password,"
                    f" user_hash, user_session, user_session_length) "
                    "VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s)",
                    [res[0][0], user, email, password, user_hash, user_session, user_session_length])
        i = con.insert_id()
        con.commit()
        if i == 0:
            return None
        x = UserLogin(user_session, user_session_length, user_hash, collection, i)
        return x


def db_username_or_email_available(username_or_email: str, collection: str) -> bool:
    """
    will check the availability for the username or email
    :param username_or_email:
    :param collection:
    :return: dictionary
    """
    with get_connection() as con:
        cur = con.cursor()
        cur.execute(f'SELECT "" '
                    f'FROM auth.tb_collection_user '
                    f'INNER JOIN auth.tb_collection '
                    f'WHERE (user_name = "{username_or_email}" OR user_email = "{username_or_email}") AND '
                    f'collection_hash = "{collection}"')

        return len(cur.fetchall()) == 0
