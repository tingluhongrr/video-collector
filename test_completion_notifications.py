"""Mock-only lifecycle tests: no test sends a real Windows notification."""

import ctypes
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import completion_notifications as notifications


class FakeRoot:
    def __init__(self):
        self.jobs = {}
        self.cancelled = []
        self.unbound = []
        self._job_id = 0
        self.destroy_handler = None

    def bind(self, sequence, handler, add=None):
        self.destroy_handler = handler
        return "destroy-binding"

    def unbind(self, sequence, binding):
        self.unbound.append((sequence, binding))

    def winfo_id(self):
        return 0x123456789 if ctypes.sizeof(ctypes.c_void_p) == 8 else 123

    def after(self, delay, callback):
        self._job_id += 1
        job = f"job-{self._job_id}"
        self.jobs[job] = (delay, callback)
        return job

    def after_cancel(self, job):
        self.cancelled.append(job)
        self.jobs.pop(job, None)

    def fire(self, job):
        _, callback = self.jobs.pop(job)
        callback()


class FakeWindowsAPI:
    def __init__(self):
        self.calls = []
        self.loaded = []
        self.destroyed = []
        self.failed_commands = set()
        self.icon = 987
        self.owned = True

    def root_handle(self, tk_handle):
        return tk_handle

    def load_icon(self, path):
        self.loaded.append(path)
        return self.icon, self.owned

    def notify(self, command, data):
        self.calls.append((command, notifications._NOTIFYICONDATAW.from_buffer_copy(data)))
        return command not in self.failed_commands

    def destroy_icon(self, icon):
        self.destroyed.append(icon)


class DesktopNotifierTests(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.api = FakeWindowsAPI()
        self.platform_patch = patch.object(notifications.sys, "platform", "win32")
        self.factory_patch = patch.object(notifications, "_WindowsAPI", return_value=self.api)
        self.platform_patch.start()
        self.factory = self.factory_patch.start()
        self.addCleanup(self.platform_patch.stop)
        self.addCleanup(self.factory_patch.stop)
        self.notifier = notifications.DesktopNotifier(self.root, "assets/video-collector.ico")
        self.addCleanup(self.notifier.close)

    def commands(self):
        return [command for command, _ in self.api.calls]

    def test_show_uses_owned_app_icon_and_quiet_time_notification(self):
        self.assertTrue(self.notifier.show("视频采集器 · 下载完成", "成功 5 个，失败 1 个"))
        self.assertEqual(self.commands(), [0, 4, 1])
        added, version, info = [data for _, data in self.api.calls]
        self.assertEqual(added.hWnd, self.root.winfo_id())
        self.assertEqual(added.szTip, "视频采集器")
        self.assertEqual(added.hIcon, self.api.icon)
        self.assertEqual(added.cbSize, ctypes.sizeof(notifications._NOTIFYICONDATAW))
        self.assertEqual(added.uFlags, notifications.NIF_ICON | notifications.NIF_TIP)
        self.assertEqual(version.uVersion, 4)
        self.assertEqual(info.szInfoTitle, "视频采集器 · 下载完成")
        self.assertEqual(info.szInfo, "成功 5 个，失败 1 个")
        self.assertEqual(info.uFlags, notifications.NIF_INFO)
        self.assertEqual(info.dwInfoFlags, notifications.NIIF_INFO | notifications.NIIF_RESPECT_QUIET_TIME)
        self.assertEqual(self.api.destroyed, [])
        self.assertEqual(len(self.root.jobs), 1)
        self.assertEqual(next(iter(self.root.jobs.values()))[0], 30_000)

    def test_repeated_show_reuses_icon_and_stale_timer_cannot_remove_it(self):
        self.assertTrue(self.notifier.show("完成", "第一批"))
        first_job = self.notifier._cleanup_job
        stale_callback = self.root.jobs[first_job][1]
        self.assertTrue(self.notifier.show("完成", "第二批"))
        self.assertEqual(self.commands(), [0, 4, 1, 1])
        self.assertEqual(len(self.api.loaded), 1)
        self.assertIn(first_job, self.root.cancelled)
        stale_callback()
        self.assertTrue(self.notifier._active)
        self.assertEqual(self.api.destroyed, [])
        self.root.fire(self.notifier._cleanup_job)
        self.assertEqual(self.commands(), [0, 4, 1, 1, 2])
        self.assertEqual(self.api.destroyed, [987])
        self.assertEqual(self.root.jobs, {})
        self.assertTrue(self.notifier.show("完成", "第三批"))
        self.assertEqual(self.commands()[-3:], [0, 4, 1])
        self.assertEqual(len(self.api.loaded), 2)

    def test_close_is_idempotent_and_stops_future_requests(self):
        self.notifier.show("完成", "成功 1 个")
        job = self.notifier._cleanup_job
        self.notifier.close()
        self.notifier.close()
        self.assertFalse(self.notifier.show("完成", "不会再显示"))
        self.assertEqual(self.commands(), [0, 4, 1, 2])
        self.assertEqual(self.api.destroyed, [987])
        self.assertIn(job, self.root.cancelled)
        self.assertEqual(self.root.unbound, [("<Destroy>", "destroy-binding")])

    def test_root_destroy_cleans_up_but_child_destroy_does_not(self):
        self.notifier.show("完成", "成功 1 个")
        self.root.destroy_handler(SimpleNamespace(widget=object()))
        self.assertFalse(self.notifier._closed)
        self.root.destroy_handler(SimpleNamespace(widget=self.root))
        self.assertTrue(self.notifier._closed)
        self.assertEqual(self.commands()[-1], notifications.NIM_DELETE)
        self.assertEqual(self.api.destroyed, [987])

    def test_add_failure_frees_icon_and_can_retry(self):
        self.api.failed_commands.add(notifications.NIM_ADD)
        self.assertFalse(self.notifier.show("完成", "失败"))
        self.assertEqual(self.commands(), [0])
        self.assertEqual(self.api.destroyed, [987])
        self.assertEqual(self.root.jobs, {})
        self.api.failed_commands.clear()
        self.assertTrue(self.notifier.show("完成", "重试"))

    def test_modify_failure_removes_icon_and_pending_cleanup(self):
        self.notifier.show("完成", "第一批")
        job = self.notifier._cleanup_job
        self.api.failed_commands.add(notifications.NIM_MODIFY)
        self.assertFalse(self.notifier.show("完成", "第二批"))
        self.assertEqual(self.commands(), [0, 4, 1, 1, 2])
        self.assertEqual(self.api.destroyed, [987])
        self.assertIn(job, self.root.cancelled)
        self.assertEqual(self.root.jobs, {})

    def test_version_failure_does_not_prevent_notification(self):
        self.api.failed_commands.add(notifications.NIM_SETVERSION)
        self.assertTrue(self.notifier.show("完成", "成功"))
        self.assertEqual(self.commands(), [0, 4, 1])

    def test_shared_system_icon_is_not_destroyed(self):
        self.api.owned = False
        self.assertTrue(self.notifier.show("完成", "成功"))
        self.notifier.close()
        self.assertEqual(self.commands()[-1], notifications.NIM_DELETE)
        self.assertEqual(self.api.destroyed, [])

    def test_missing_icon_returns_false_without_notification(self):
        self.api.icon = 0
        self.assertFalse(self.notifier.show("完成", "成功"))
        self.assertEqual(self.commands(), [])
        self.assertEqual(self.root.jobs, {})

    def test_unavailable_api_and_non_windows_are_safe(self):
        with patch.object(notifications, "_WindowsAPI", side_effect=OSError("DLL unavailable")):
            self.assertFalse(self.notifier.show("完成", "成功"))
        with patch.object(notifications.sys, "platform", "linux"):
            self.assertFalse(self.notifier.show("完成", "成功"))
        self.factory.assert_not_called()
        self.assertEqual(self.commands(), [])

    def test_tk_timer_failure_removes_temporary_icon(self):
        with patch.object(self.root, "after", side_effect=RuntimeError("root gone")):
            self.assertFalse(self.notifier.show("完成", "成功"))
        self.assertEqual(self.commands(), [0, 4, 1, 2])
        self.assertEqual(self.api.destroyed, [987])

    def test_cleanup_api_errors_never_escape(self):
        self.notifier.show("完成", "成功")
        with patch.object(self.api, "notify", side_effect=OSError("shell gone")), \
                patch.object(self.api, "destroy_icon", side_effect=OSError("icon gone")), \
                patch.object(self.root, "after_cancel", side_effect=RuntimeError("root gone")), \
                patch.object(self.root, "unbind", side_effect=RuntimeError("root gone")):
            self.notifier.close()
        self.assertTrue(self.notifier._closed)
        self.assertFalse(self.notifier._active)
        self.assertEqual(self.notifier._icon, 0)

    def test_long_unicode_text_is_safely_truncated_for_wchar_buffers(self):
        self.assertTrue(self.notifier.show("标题" + "😀" * 100, "文字\0" + "😀" * 200))
        info = self.api.calls[-1][1]
        self.assertLessEqual(len(info.szInfoTitle.encode("utf-16-le")), 63 * 2)
        self.assertLessEqual(len(info.szInfo.encode("utf-16-le")), 255 * 2)
        self.assertNotIn("\0", info.szInfo)
        self.assertTrue(info.szInfo.startswith("文字"))

    @unittest.skipUnless(sys.platform == "win32", "native Windows ABI")
    def test_notifyicondata_has_correct_windows_layout(self):
        structure = notifications._NOTIFYICONDATAW
        self.assertEqual(ctypes.sizeof(ctypes.c_wchar), 2)
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            self.assertEqual(ctypes.sizeof(structure), 976)
            self.assertEqual(structure.hWnd.offset, 8)
            self.assertEqual(structure.szInfo.offset, 304)
            self.assertEqual(structure.hBalloonIcon.offset, 968)
        else:
            self.assertEqual(ctypes.sizeof(structure), 956)
            self.assertEqual(structure.hWnd.offset, 4)
            self.assertEqual(structure.szInfo.offset, 288)
            self.assertEqual(structure.hBalloonIcon.offset, 952)


if __name__ == "__main__":
    unittest.main()
