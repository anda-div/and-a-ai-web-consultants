"""clarity_heatmap_capture の --login-plain まわりを確かめる。

ブラウザは起動しない。引数の組み合わせと、プロファイル使用中の判定だけを見る。
CIには Playwright を入れていないため、読み込みだけ差し替える。
"""

import io
import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

if "playwright" not in sys.modules:
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        fake = types.ModuleType("playwright.sync_api")
        fake.sync_playwright = None
        sys.modules["playwright"] = types.ModuleType("playwright")
        sys.modules["playwright.sync_api"] = fake

import clarity_heatmap_capture as cap  # noqa: E402


def parse_fails(argv) -> bool:
    try:
        with redirect_stderr(io.StringIO()):
            cap.parse_args(argv)
    except SystemExit:
        return True
    return False


class 引数(unittest.TestCase):
    def test_login_plainはプロジェクト指定なしで通る(self):
        args = cap.parse_args(["--login-plain"])
        self.assertTrue(args.login_plain)
        self.assertFalse(args.login)

    def test_loginとlogin_plainは同時に指定できない(self):
        self.assertTrue(parse_fails(["--login", "--login-plain"]))

    def test_撮影には引き続きプロジェクト指定が要る(self):
        self.assertTrue(parse_fails([]))

    def test_login_plainはchannelと併用できない(self):
        # 撮影と同じ版のChromiumで開くことが前提のため
        with tempfile.TemporaryDirectory() as d:
            args = cap.parse_args(["--login-plain", "--channel", "chrome", "--profile", d])
            with self.assertRaises(SystemExit):
                cap.login_plain(args)


class プロファイル使用中の判定(unittest.TestCase):
    def test_空のプロファイルは使用中ではない(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(cap.profile_in_use(Path(d)))

    @unittest.skipUnless(sys.platform == "win32", "Windows の lockfile 判定")
    def test_異常終了で残っただけのlockfileは使用中ではない(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "lockfile").write_bytes(b"")
            self.assertFalse(cap.profile_in_use(Path(d)))

    @unittest.skipIf(sys.platform == "win32", "Windows 以外の SingletonLock 判定")
    def test_SingletonLockがあれば使用中(self):
        with tempfile.TemporaryDirectory() as d:
            os.symlink("host-12345", Path(d) / "SingletonLock")
            self.assertTrue(cap.profile_in_use(Path(d)))


if __name__ == "__main__":
    unittest.main(verbosity=2)
