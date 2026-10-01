
# -*- coding: utf-8 -*-
"""审查方独立探针 v2：修正霍夫曼表构造 + 增加"引用了未定义表"用例。"""
import io, os, struct, sys
sys.path.insert(0, r'C:\Users\WONG Tsun Ming\Desktop\欧莱雅黑客松\worktrees\covenia-batch-08-repair-1\backend\src')
sys.stdout.reconfigure(encoding='utf-8')
def seg(m, body): return bytes([0xFF, m]) + struct.pack('>H', len(body)+2) + body
def sof0(w,h,comps):
    b = bytes([8]) + struct.pack('>HH', h, w) + bytes([len(comps)])
    for cid,tq in comps: b += bytes([cid, 0x11, tq])
    return seg(0xC0, b)
def dqt(tables):
    b = b''
    for tid, data in tables: b += bytes([tid]) + bytes(data)
    return seg(0xDB, b)
def dht(tables):
    b = b''
    for cls, tid, counts, syms in tables:
        b += bytes([(cls<<4)|tid]) + bytes(counts) + bytes(syms)
    return seg(0xC4, b)
def sos(comps):
    b = bytes([len(comps)])
    for cid,td in comps: b += bytes([cid, td])
    return seg(0xDA, b + bytes([0x00,0x3F,0x00]))
STD_Q = [16]*64
# 合法最简表：DC 表 id0（1 个长度1的码，符号 0）；AC 表 id0（1 个码，符号 0）
DC_COUNTS = [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]; DC_SYMS=[0]
AC_COUNTS = [1,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]; AC_SYMS=[0]
def build(with_dqt=True, with_dht=True, scan_dc=0):
    p = [b'\xFF\xD8', sof0(8,8,[(1,0)])]
    if with_dqt: p.append(dqt([(0, STD_Q)]))
    if with_dht: p.append(dht([(0,0,DC_COUNTS,DC_SYMS),(1,0,AC_COUNTS,AC_SYMS)]))
    p.append(sos([(1, (scan_dc << 4) | 0)]))
    p.append(bytes([0x00]) + b'\xFF\xD9')
    return b''.join(p)
from covenia_b.images.resolver import _probe_jpeg, ImageContentRejected
print('=== 审查方独立探针 v2 ===')
ok = True
for label, payload, expect in (
    ('完整 JPEG（DQT+DHT 齐全）',        build(True, True),            True),
    ('缺 DQT（量化表缺失）',             build(False, True),           False),
    ('缺 DHT（霍夫曼表缺失）',           build(True, False),           False),
    ('扫描引用未定义的 DC 表 id=2',      build(True, True, scan_dc=2), False),
):
    try:
        w,h = _probe_jpeg(payload); got, passed = '通过 (%dx%d)' % (w,h), expect
    except ImageContentRejected as e:
        got, passed = '拒绝 [%s]' % getattr(e,'code','?'), (not expect)
    except Exception as e:
        got, passed = '%s: %s' % (type(e).__name__, str(e)[:50]), False
    print('  %-32s 期望 %-4s 实际 %-30s %s' % (label, '通过' if expect else '拒绝', got, '✓' if passed else '✗'))
    ok = ok and passed
print()
print('=== 判定 ===')
print('  完整 JPEG 被接受      :', ok)
print('  缺 DQT 被拒绝         :', ok)
print('  缺 DHT 被拒绝         :', ok)
print('  引用未定义表被拒绝    :', ok)
print('  → B08-F01 修复', '验证通过 ✓' if ok else '未通过 ✗')
