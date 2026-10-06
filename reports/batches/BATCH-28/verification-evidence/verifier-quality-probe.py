import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')
V = r'C:/v28/v'
BASE = os.path.join(V, 'reports', 'batches', 'BATCH-28')
def find(obj, key, depth=0):
    if depth > 7: return None
    if isinstance(obj, dict):
        if key in obj: return obj[key]
        for v in obj.values():
            r = find(v, key, depth+1)
            if r is not None: return r
    elif isinstance(obj, list):
        for v in obj[:5]:
            r = find(v, key, depth+1)
            if r is not None: return r
    return None
D = os.path.join(BASE, 'live')
runs = [('第1次', D)] + [('第%d次'%i, os.path.join(BASE,'verifier-live','run-%d'%i)) for i in range(2,7)]
print('%-8s %-8s %-8s %-10s %-12s %s' % ('运行','obs数','trace数','IMAGE trace','cached','revision'))
allok = True
for label, d in runs:
    p = os.path.join(d, 'model-output.redacted.json')
    if not os.path.exists(p):
        print('%-8s 【无 model-output：%s】' % (label, d)); allok=False; continue
    j = json.load(open(p, encoding='utf-8'))
    obs = find(j, 'observations')
    tr  = find(j, 'source_trace')
    cached = find(j, 'cached_result')
    rev = find(j, 'model_revision')
    n_obs = len(obs) if isinstance(obs, list) else -1
    n_tr = len(tr) if isinstance(tr, list) else -1
    n_img = len([t for t in (tr or []) if isinstance(t,dict) and str(t.get('source_type'))=='IMAGE'])
    ok = (n_obs >= 3 and n_tr >= 4 and n_img >= 1 and cached is False)
    allok = allok and ok
    print('%-8s %-8d %-8d %-10d %-12s %s  %s' % (label, n_obs, n_tr, n_img, str(cached), str(rev)[:26], '✓' if ok else '✗'))
print()
print('=== 结论 ===')
print('  6/6 通过 且 每次保留图片观察（IMAGE trace ≥1）:', allok)
print()
print('=== 我的第一次运行是否改动了他们的 live/ 目录 ===')
import subprocess
o = subprocess.run(['git','-C',V,'status','--short'],capture_output=True).stdout.decode('utf-8','replace')
lines = [l for l in o.splitlines() if l.strip()]
print('  改动条数:', len(lines))
for l in lines[:12]: print('   ', l[:110])