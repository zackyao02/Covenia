# -*- coding: utf-8 -*-
import os, subprocess, sys, textwrap
sys.stdout.reconfigure(encoding='utf-8')
V = r'C:/v30/v'
SCAN = V + '/tools/verification/check_no_case_branches.py'
PY = r'C:/v30/venv/Scripts/python.exe'
BODY = textwrap.dedent('''
    def decide(entry):
        if entry.file_name.endswith("_gift.png"):
            return {"decision": "ALLOW", "rule_id": "E0_NO_RULE_MATCHED"}
        return {"decision": "HUMAN_REVIEW", "rule_id": "H1"}
    ''')
PLACES = [
  ('covenia_b 顶层', os.path.join(V,'backend','src','covenia_b','probe_top.py')),
  ('services/', os.path.join(V,'backend','src','covenia_b','services','probe_svc.py')),
  ('rules/', os.path.join(V,'backend','src','covenia_b','rules','probe_rules.py')),
  ('evidence/', os.path.join(V,'backend','src','covenia_b','evidence','probe_ev.py')),
]
for label, p in PLACES:
    if not os.path.isdir(os.path.dirname(p)):
        print('%-14s 目录不存在，跳过' % label); continue
    open(p,'w',encoding='utf-8',newline='\n').write(BODY)
    try:
        r = subprocess.run([PY, SCAN, '--strict'], cwd=V, capture_output=True, text=True, encoding='utf-8', errors='replace')
        out = (r.stdout or '')
        last = [l for l in out.splitlines() if 'no-case-branches-v1' in l]
        rel = os.path.relpath(p, V).replace(os.sep,'/')
        hits = [l for l in out.splitlines() if 'probe' in l.lower() and 'ok ' not in l]
        print('%-14s exit=%d | %s' % (label, r.returncode, (last[0].strip()[:78] if last else '')))
        for h in hits[:2]: print('      → %s' % h.strip()[:130])
    finally:
        if os.path.exists(p): os.remove(p)
print()
print('=== 还原 ===')
r2 = subprocess.run([PY, SCAN, '--strict'], cwd=V, capture_output=True, text=True, encoding='utf-8', errors='replace')
print('  exit:', r2.returncode, '|', (r2.stdout or '').strip().splitlines()[-1][:80])
o = subprocess.run(['git','-C',V,'status','--short'],capture_output=True).stdout.decode('utf-8','replace')
print('  git:', o.strip() or '（干净）')