import random
import secrets
import numpy as np
import hashlib
import base64


def pad(value: str, max_length: int) -> str:
    """
    Complete the binary string with zeros at the right if max_length is bigger the return a substring

    :param value: Binary string
    :param max_length: Max length
    :return: String with the length of max_length
    """
    if len(value) > max_length:
        return value[:max_length]

    return '0' * (max_length - len(value)) + value


def crp_kg(bites_length: int) -> str:
    """
    Generate a random binary string with the bite length specific

    :param bites_length: Length of the random binary string
    :return: random binary string
    """
    b = random.getrandbits(bites_length)
    b = np.binary_repr(b)
    b = pad(b, bites_length)
    return b


def cph_generator(params_keys: list[int]) -> str:
    """
    Generate a binary string with all elements to be stored

    :param params_keys: List of values to be encrypted and stored
    :return: Binary string
    """
    tk = ''
    for i in params_keys:
        b = crp_kg(i)
        tk += b
    return tk


def xor(x, y):
    return '1' if x != y else '0'


def generate_hashcode(k):
    dg = hashlib.sha256(k.encode()).digest()
    return format(int.from_bytes(dg, 'big'), 'b')


def cypher_x_encode(random_key: int | None,
                    check_sum: int | None,
                    padding: int | bool | None,
                    params_keys: list[int],
                    params_data: list[int]) -> tuple[str, int | None]:
    """
    Generate Base64 code from int type data.

    If **random_key** is None or zero, the token generated always will be the same, this is util
    to generate URL with an image ID or another data that doesn't matter if the content is visible,
    also the token generated will have fewer characters.

    If **check_sum** is None or zero, then the values can be edited by the user and will accept any
    token if it has a compatible format with the **params_keys**. If the token is compatible and was
    deserialized, and the **random_key** is not Null or zero, the decrypted value will be an unexpected
    value from 0-2^key_value but if both are None or zero the token will be just the **params_data** in
    base64.

    The **padding** is not implemented yet

    :param random_key: (Optional) Bytes length for the random key, the Base64 code will be different each time.
    :param check_sum: (Optional) The Base64 will check the integrity before decoded, max value 256 (SHA256).
    :param padding: Not implemented yet.
    :param params_keys: List with the byte length for each data.
    :param params_data: List with the ints to be encoded.
    :return: Base64 string coded to be used as URL.
    """

    if check_sum is not None and check_sum > 256:
        return "", None

    binary_randomkey_string = ''
    raw_seed_int = None
    binary_params_string = ''

    # Generate a binary string with all params
    for _i, _t in zip(params_keys, params_data):
        binary_params_string += pad(format(_t, 'b'), _i)

    # Generate the binary random key string
    if random_key is not None and random_key != 0:
        raw_seed_int = secrets.randbits(random_key)
        # Initialize the native python random generator with the raw_seed_int
        random.seed(raw_seed_int)
        binary_randomkey_string = pad(format(raw_seed_int, 'b'), random_key)
        z = zip(
            cph_generator(params_keys),  # Generate a binary string with the keys
            binary_params_string
        )
        # Apply the xor operation to the binary_params_string with the binary string of the keys
        binary_params_string = ''.join([xor(k, d) for k, d in z])
    else:
        random_key = 0

    if check_sum is None:
        check_sum = 0

    # Generate a fix_length
    sm = check_sum + random_key + sum(params_keys)
    fix_length = sm % 24
    if fix_length != 0:
        fix_length = 24 - fix_length

    dg = ''
    if check_sum != 0:
        check_sum = check_sum
        dg = generate_hashcode(binary_randomkey_string +
                               binary_params_string +
                               ''.join([str(x) for x in params_keys]))
        if check_sum > len(dg):
            dg = pad(dg, 256)
        dg = dg[:check_sum]

    dg = pad(dg, check_sum + fix_length)
    res = binary_randomkey_string + dg + binary_params_string

    key = b''
    for _i in range(0, len(res), 8):
        key += int(res[_i:_i + 8], 2).to_bytes(1, 'big')

    b64 = base64.b64encode(key, altchars=b'_-')

    return b64.decode('utf-8'), raw_seed_int


def cypher_x_decode(random_key: int | None,
                    check_sum: int | None,
                    padding: int | bool | None,
                    params_keys: list[int],
                    encoded: str) -> tuple[list[int], int | None]:
    """
    Decode a Base64 encoded with 'cph_encode',
    All params must be the same as the used in the encoded method.

    :param random_key: (Optional) Bytes length for the random key, the Base64 code will be different each time.
    :param check_sum: (Optional) The Base64 will check the integrity before decode.
    :param padding: Not implemented yet.
    :param params_keys: List with the byte length for each data.
    :param encoded: Base64 encoded
    :return: List of int with the data decoded
    """
    if check_sum is not None and check_sum > 256:
        return [0], None

    d = base64.b64decode(encoded, altchars=b'_-')
    res = ''.join(['{:08d}'.format(int(format(i, 'b')))[-8:] for i in d])

    tk = ''
    s = ''
    raw_seed = None
    if random_key is not None and random_key != 0:
        raw_seed = int(res[:random_key], 2)
        t = res[random_key:]
        random.seed(raw_seed)
        s = pad(format(raw_seed, 'b'), random_key)
        tk = ''.join([crp_kg(x) for x in params_keys])
    else:
        random_key = 0
        t = res

    if check_sum is not None and check_sum != 0:
        sm = check_sum + random_key + sum(params_keys)
    else:
        sm = random_key + sum(params_keys)
        check_sum = 0

    fix_length = sm % 24
    if fix_length != 0:
        fix_length = 24 - fix_length

    if check_sum != 0:
        hs = t[fix_length:check_sum + fix_length]
        t = t[check_sum + fix_length:]

        k = s + t + ''.join([str(x) for x in params_keys])
        m = hashlib.sha256()
        m.update(k.encode())
        dg = m.digest()
        dg = format(int.from_bytes(dg, 'big'), 'b')

        while len(dg) < 256:
            dg = '0' + dg
        dg = dg[:check_sum]

        if dg != hs:
            return [0], None
    else:
        t = t[:fix_length]

    if random_key != 0:
        rk = ''.join(['1' if k != d else '0' for k, d in zip(tk, t)])
    else:
        rk = t

    res = []
    t = rk
    for i in params_keys:
        res.append(int(t[:i], 2))
        t = t[i:]

    return res, raw_seed
