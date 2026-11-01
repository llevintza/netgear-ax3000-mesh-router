#!/usr/bin/env python3
"""Recover {key, value[, flags]} NVRAM default tables from a 32-bit LE ARM ELF.

Usage: python3 -I nvram_defaults.py <elf> [key-regex]
Scans 4-byte aligned words for runs of struct entries whose first field points to an
identifier-like string and second field points to a printable string (or NULL).
Tries stride 8 (key,value) and 12 (key,value,flags). Prints runs of >= 20 entries.
"""
import re
import struct
import sys

path = sys.argv[1]
pat = re.compile(sys.argv[2]) if len(sys.argv) > 2 else None
b = open(path, "rb").read()
assert b[:4] == b"\x7fELF" and b[4] == 1 and b[5] == 1, "need ELF32 LE"
e_phoff, = struct.unpack_from("<I", b, 0x1C)
e_phentsize, e_phnum = struct.unpack_from("<HH", b, 0x2A)
segs = []
for i in range(e_phnum):
    p_type, p_off, p_vaddr, _, p_filesz, _, _, _ = struct.unpack_from("<8I", b, e_phoff + i * e_phentsize)
    if p_type == 1:  # PT_LOAD
        segs.append((p_vaddr, p_off, p_filesz))


def v2o(v):
    for va, off, sz in segs:
        if va <= v < va + sz:
            return off + (v - va)
    return None


KEY = re.compile(rb"[A-Za-z_][A-Za-z0-9_.:\-]{1,63}\Z")
cache = {}


def cstr(v):
    if v in cache:
        return cache[v]
    o = v2o(v)
    r = None
    if o is not None:
        end = b.find(b"\0", o, o + 512)
        if end != -1:
            s = b[o:end]
            if all(32 <= c < 127 for c in s):
                r = s
    cache[v] = r
    return r


def entry(off, stride):
    k, v = struct.unpack_from("<II", b, off)
    ks = cstr(k)
    if ks is None or not KEY.match(ks):
        return None
    if v == 0:
        vs = b""
    else:
        vs = cstr(v)
        if vs is None:
            return None
    return ks.decode(), vs.decode()


best = []
for stride in (8, 12):
    off = 0
    n = len(b) - stride
    while off < n:
        run = []
        o = off
        while o < n:
            e = entry(o, stride)
            if e is None:
                break
            run.append(e)
            o += stride
        if len(run) >= 20:
            best.append((stride, off, run))
            off = o
        else:
            off += 4

for stride, off, run in best:
    print(f"# table @0x{off:x} stride={stride} entries={len(run)}")
    for k, v in run:
        if pat is None or pat.search(k):
            print(f"{k}={v}")
