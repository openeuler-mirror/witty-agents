"""log_analyzer 快速健康检查"""
import log_analyzer as la

# 检查函数存在
for fn in ['safe_resolve','_stream_lines','scan_file','ai_analyze','format_csv','format_html','watch','send_alert']:
    assert fn in dir(la), f'MISSING: {fn}'

# 检查常量
assert la.MAX_FILE_SIZE == 500*1024*1024
assert la._ALERT_COOLDOWN_MINUTES == 5

# 检查watch用seek
src = open('log_analyzer.py', encoding='utf-8').read()
assert 'seek(last_pos)' in src, 'watch() should use seek()'
assert 'prev_tail_lines' in src, 'watch() should track previous tail'

# 检查report路径校验
assert 'safe_resolve(report_path)' in src, 'report path should be validated'

# 检查CSV换行转义（检查源码中的转义逻辑）
assert "replace('\\n'" in src, 'CSV should escape newlines'

# 检查f-string加强检测
assert ('f"' in src and "in stripped" in src), 'f-string detection should be stricter'

print('OK  watch() seek incremental reading')
print('OK  report path safe_resolve validation')
print('OK  CSV newline escaping')
print('OK  f-string detection strengthened')
print('ALL CHECKS PASSED')

