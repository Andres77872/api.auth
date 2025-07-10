import aiohttp


async def logger(payload: dict, realm: str, collection: str):
    url = 'https://log.arz.ai'
    # url = 'http://127.0.0.1:8000'
    headers = {
        'X-token-user': '9D8B161E8870DE18203E767F81445CB2CA5A2DA6E997573635DD25F290BAB59E',
        'X-token-realm': '9CFE23E08EA0DCAAAEA5AA642F3BF7A4A38EBB2F05C053CD0363A8FD87995A41'
    }
    async with aiohttp.ClientSession() as session:
        async with session.put(url + f'/log/{realm}/{collection}',
                               headers=headers,
                               json={'data': payload}) as res:
            if res.status != 202:
                print(res)
