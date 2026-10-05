# -*- coding: utf-8 -*-
import json, sys
sys.path.insert(0, r'C:/v27/v/backend/src')
sys.stdout.reconfigure(encoding='utf-8')
from covenia_b.main import create_app

app = create_app()
print('=== 标准1：恰好四个业务 POST 路由 ===')
posts = []
for r in app.routes:
    m = getattr(r, 'methods', None)
    if m and 'POST' in m:
        posts.append((sorted(m), getattr(r,'path','?'), getattr(r,'name','?')))
print('  POST 路由数:', len(posts))
for m, p, n in posts: print('    %-8s %-30s %s' % (','.join(m), p, n))
expect = {'/api/cases/analyze','/api/actions/evaluate','/api/resolutions/approve','/api/events/shipment'}
got = {p for _,p,_ in posts}
print('  期望集合:', sorted(expect))
print('  实际集合:', sorted(got))
print('  完全一致:', got == expect)
print()
print('=== 全部路由（含非 POST）===') 
for r in app.routes:
    print('    %-16s %s' % (','.join(sorted(getattr(r,'methods',[]) or [])), getattr(r,'path','?')))
print('  路由总数:', len(app.routes))
print()
print('=== 标准1附：无文档路由 ===') 
print('  docs_url  :', app.docs_url)
print('  redoc_url :', app.redoc_url)
print('  openapi_url:', app.openapi_url)
print('  三者皆 None:', app.docs_url is None and app.redoc_url is None and app.openapi_url is None)
print()
print('=== 标准3：CORS 与请求 ID ===')
mw = [type(m).__name__ for m in app.user_middleware]
print('  中间件:', mw)
for m in app.user_middleware:
    if 'CORS' in str(m):
        import re
        s = str(m)
        origins = re.findall(r"'(https?://[^']+)'", s)
        print('  CORS 允许的 origin:', sorted(set(origins)))
        print('  含 127.0.0.1:4173:', 'http://127.0.0.1:4173' in s)
        print('  含 localhost Origin:', 'http://localhost:' in s)
        print('  允许方法:', re.findall(r"'(GET|POST|OPTIONS|PUT|DELETE)'", s))
print()
print('=== 标准1附：无第五业务接口（health/reset/query）===') 
bad = [p for _,p,_ in posts if any(k in p.lower() for k in ('health','reset','query','ping','status'))]
print('  可疑第五接口:', bad or '无 ✓')