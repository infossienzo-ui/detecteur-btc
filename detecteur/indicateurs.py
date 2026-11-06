import numpy as np
import pandas as pd


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def rma(x, n):
    return pd.Series(x).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    hausse, baisse = rma(np.clip(d, 0, None), n), rma(np.clip(-d, 0, None), n)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = 100 - 100 / (1 + hausse / baisse)
    r[baisse == 0] = 100.0
    return r


def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return rma(tr, n)
