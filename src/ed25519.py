"""纯 Python Ed25519 参考实现（改写自 djb 等人的公开域参考代码）。

只实现本项目所需：由 32 字节种子生成公钥、对消息签名。
正确性由 tests/test_ed25519.py 中的 RFC 8032 官方测试向量保证；
选纯标准库是为了 SCF 云函数零依赖打包（cryptography 等三方库打包复杂）。
"""

import hashlib

q = 2**255 - 19
l = 2**252 + 27742317777372353535851937790883648493
d = -121665 * pow(121666, q - 2, q) % q
I = pow(2, (q - 1) // 4, q)


def _sha512(m):
    return hashlib.sha512(m).digest()


def _xrecover(y):
    xx = (y * y - 1) * pow(d * y * y + 1, q - 2, q)
    x = pow(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = x * I % q
    if x % 2 != 0:
        x = q - x
    return x


By = 4 * pow(5, q - 2, q)
Bx = _xrecover(By)
B = (Bx % q, By % q)


def _edwards_add(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * pow(1 + d * x1 * x2 * y1 * y2, q - 2, q)
    y3 = (y1 * y2 + x1 * x2) * pow(1 - d * x1 * x2 * y1 * y2, q - 2, q)
    return (x3 % q, y3 % q)


def _scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = _scalarmult(P, e // 2)
    Q = _edwards_add(Q, Q)
    if e & 1:
        Q = _edwards_add(Q, P)
    return Q


def _encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(32))


def _secret_expand(seed):
    h = _sha512(seed)
    a = 2**254 + sum(2**i * ((h[i // 8] >> (i % 8)) & 1) for i in range(3, 254))
    return h, a


def publickey(seed):
    """由 32 字节种子生成 32 字节公钥。"""
    _, a = _secret_expand(seed)
    return _encodepoint(_scalarmult(B, a))


def sign(message, seed):
    """返回 message 的 64 字节 Ed25519 签名。"""
    h, a = _secret_expand(seed)
    pk = _encodepoint(_scalarmult(B, a))
    r = int.from_bytes(_sha512(h[32:64] + message), "little") % l
    R = _encodepoint(_scalarmult(B, r))
    k = int.from_bytes(_sha512(R + pk + message), "little") % l
    s = (r + k * a) % l
    return R + s.to_bytes(32, "little")
