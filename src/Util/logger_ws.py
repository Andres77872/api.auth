import requests

sess = requests.Session()


def logger(payload: dict, realm: str, collection: str):
    url = 'https://log.arz.ai'
    # url = 'http://127.0.0.1:8000'
    headers = sess.headers
    headers['X-token-user'] = '9D8B161E8870DE18203E767F81445CB2CA5A2DA6E997573635DD25F290BAB59E'
    headers['X-token-realm'] = '9CFE23E08EA0DCAAAEA5AA642F3BF7A4A38EBB2F05C053CD0363A8FD87995A41'
    res = sess.put(url + f'/log/{realm}/{collection}', headers=headers, json={'data': payload})
    if res.status_code != 200:
        print(res)
