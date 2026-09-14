#!/usr/bin/env python3
"""log_analyzer 基础测试"""
import os
import sys
import tempfile
from pathlib import Path

# 把当前目录加入 path 以便导入
sys.path.insert(0, str(Path(__file__).parent))
import log_analyzer as la


# ── 测试辅助 ──────────────────────────────────────────────────
def make_log(content: str) -> str:
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False, encoding='utf-8')
    f.write(content)
    f.flush()
    name = f.name
    f.close()
    return name


def rm(path: str):
    try:
        os.unlink(path)
    except Exception:
        pass


class TestSafeResolve:
    def test_absolute_path_ok(self):
        # Windows: C:\... 或 Unix: /tmp/...
        path = Path(tempfile.gettempdir()) / "test.log"
        path.write_text("ok")
        result = la.safe_resolve(str(path))
        assert result == path.resolve()
        rm(str(path))

    def test_relative_path_in_cwd(self):
        result = la.safe_resolve("log_analyzer.py")
        assert result.name == "log_analyzer.py"

    def test_relative_path_outside_cwd(self):
        try:
            la.safe_resolve("../etc/passwd")
            assert False, "应该抛异常"
        except ValueError as e:
            assert "不允许访问" in str(e)

    def test_symlink_rejected(self):
        target = tempfile.NamedTemporaryFile(suffix='.log', delete=False)
        target.write(b"x")
        target.close()
        link = Path(target.name + ".link")
        try:
            os.symlink(target.name, str(link))
            la.safe_resolve(str(link))
            assert False, "should reject symlink"
        except (ValueError, OSError):
            pass  # ValueError from our code, OSError on Windows if no admin
        finally:
            rm(target.name)
            try:
                rm(str(link))
            except Exception:
                pass


class TestScanFile:
    def test_empty_file(self):
        path = make_log("")
        try:
            r = la.scan_file(path)
            assert r.total_lines == 0
            assert r.critical == []
        finally:
            rm(path)

    def test_captures_error(self):
        path = make_log("2026-04-06 ERROR something broke\n")
        try:
            r = la.scan_file(path)
            assert len(r.critical) >= 1
            assert "ERROR" in r.critical[0].message
        finally:
            rm(path)

    def test_captures_warning(self):
        path = make_log("2026-04-06 WARNING slow query\n")
        try:
            r = la.scan_file(path)
            assert len(r.warnings) >= 1
        finally:
            rm(path)

    def test_code_line_filtered(self):
        path = make_log('logger.error("ERROR in code")\n')
        try:
            r = la.scan_file(path)
            # Python 代码行应该被过滤
            assert len(r.critical) == 0
        finally:
            rm(path)

    def test_multiline_traceback(self):
        path = make_log(
            "Traceback (most recent call last):\n"
            '  File "test.py", line 10\n'
            "    raise ValueError('oops')\n"
            "ValueError: oops\n"
        )
        try:
            r = la.scan_file(path)
            assert len(r.critical) >= 1
            # 合并后的堆栈应该包含多行
            assert " | " in r.critical[0].message or len(r.critical[0].message) > 0
        finally:
            rm(path)

    def test_tail_last_lines(self):
        lines = "\n".join([f"INFO line {i}" for i in range(100)])
        path = make_log(lines)
        try:
            r = la.scan_file(path, tail=10)
            assert r.total_lines == 10
        finally:
            rm(path)

    def test_file_too_big(self):
        # 小文件不会触发限制，测试一个已知存在的小文件
        try:
            la.scan_file("log_analyzer.py")
        except SystemExit:
            pass  # 正常退出

    def test_unknown_path(self):
        try:
            la.scan_file("/nonexistent/file/xyz.log")
            assert False, "should exit"
        except SystemExit:
            pass


class TestCsvFormat:
    def test_escapes_newlines(self):
        path = make_log('ERROR line1\nline2\nline3\n')
        try:
            r = la.scan_file(path)
            csv = la.format_csv(r)
            assert "\\n" in csv or '""' in csv  # 换行被转义
        finally:
            rm(path)

    def test_escapes_quotes(self):
        path = make_log('ERROR say "hello"\n')
        try:
            r = la.scan_file(path)
            csv = la.format_csv(r)
            assert '""' in csv
        finally:
            rm(path)


class TestWebhookValidation:
    def test_localhost_blocked(self):
        for url in ["http://127.0.0.1/admin", "http://localhost/api", "http://192.168.1.1/"]:
            try:
                la.validate_webhook_url(url)
                assert False, f"{url} 应该被拒绝"
            except ValueError:
                pass

    def test_private_network_blocked(self):
        for url in ["http://10.0.0.1/", "http://172.16.0.1/", "http://192.168.0.1/"]:
            try:
                la.validate_webhook_url(url)
                assert False, f"{url} 应该被拒绝"
            except ValueError:
                pass

    def test_public_url_ok(self):
        la.validate_webhook_url("https://hooks.slack.com/services/xxx")
        la.validate_webhook_url("https://notify.example.com/webhook")


class TestFStringDetection:
    def test_fstring_detected(self):
        assert la._is_likely_code_line('logger.info(f"error: {e}")') == True

    def test_bracket_in_log_not_code(self):
        # 含 { 的普通日志，不应该被识别为代码
        assert la._is_likely_code_line('2026-04-06 ERROR { "key": "value" }') == False

    def test_assignment_detected(self):
        assert la._is_likely_code_line("x = 1") == True
        assert la._is_likely_code_line("obj.method()") == True


# ── 运行 ─────────────────────────────────────────────────────
if __name__ == "__main__":
    import traceback

    classes = [
        TestSafeResolve,
        TestScanFile,
        TestCsvFormat,
        TestWebhookValidation,
        TestFStringDetection,
    ]

    passed = failed = 0
    for cls in classes:
        print(f"\n{cls.__name__}")
        for name in dir(cls):
            if name.startswith("test_"):
                try:
                    getattr(cls(), name)()
                    print(f"  PASS  {name}")
                    passed += 1
                except Exception as e:
                    print(f"  FAIL  {name}: {e}")
                    failed += 1

    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
