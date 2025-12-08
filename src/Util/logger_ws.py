import os

import aiohttp

LOG_TOKEN_USER = os.environ.get("LOG_TOKEN_USER")
LOG_TOKEN_REALM = os.environ.get("LOG_TOKEN_REALM")


async def logger(payload: dict, realm: str, collection: str):
    url = 'https://log.arz.ai'
    headers = {
        'X-token-user': LOG_TOKEN_USER,
        'X-token-realm': LOG_TOKEN_REALM
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url + f'/log/{realm}/{collection}',
                               headers=headers,
                               json={'data': payload}) as res:
            if res.status != 202:
                print(res)
