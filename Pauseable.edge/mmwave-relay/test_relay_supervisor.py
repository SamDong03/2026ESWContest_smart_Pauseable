import io
import signal
import subprocess
import unittest
import sys
from unittest.mock import Mock

from relay_supervisor import stop_children, wait_ready


class SupervisorCleanupTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "linux", "Linux pipe readiness")
    def test_ready_requires_a_complete_remote_handshake(self):
        with subprocess.Popen([sys.executable, "-c",
                               "import sys,time; sys.stderr.write('PAUSEABLE_FIFO_READY\\n'); sys.stderr.flush(); time.sleep(1)"],
                              stderr=subprocess.PIPE) as child:
            wait_ready(child, 2, lambda: False)
            child.terminate()
            child.wait()

    @unittest.skipUnless(sys.platform == "linux", "Linux pipe readiness")
    def test_failed_ssh_cannot_start_a_usb_reader(self):
        with subprocess.Popen([sys.executable, "-c", "raise SystemExit(1)"], stderr=subprocess.PIPE) as child:
            with self.assertRaises(RuntimeError):
                wait_ready(child, 2, lambda: False)
            child.wait()

    def test_relay_is_interrupted_and_reaped_before_ssh_is_closed(self):
        operations = []
        relay = Mock()
        relay.poll.return_value = None
        relay.send_signal.side_effect = lambda sig: operations.append(("relay_signal", sig))
        relay.wait.side_effect = lambda **_: operations.append(("relay_wait",))
        ssh = Mock()
        ssh.poll.return_value = None
        ssh.stdin = io.BytesIO()
        ssh.terminate.side_effect = lambda: operations.append(("ssh_terminate",))
        stop_children(relay, ssh)
        self.assertEqual(operations[:2], [("relay_signal", signal.SIGINT), ("relay_wait",)])
        self.assertTrue(ssh.stdin.closed)
        ssh.wait.assert_called_once()

    def test_dead_children_do_not_get_signalled_again(self):
        relay, ssh = Mock(), Mock()
        relay.poll.return_value = 2
        ssh.poll.return_value = 1
        ssh.stdin = io.BytesIO()
        stop_children(relay, ssh)
        relay.send_signal.assert_not_called()
        ssh.terminate.assert_not_called()

    def test_unresponsive_relay_is_killed_and_reaped(self):
        relay = Mock()
        relay.poll.return_value = None
        relay.wait.side_effect = [subprocess.TimeoutExpired("relay", 3), 0]
        stop_children(relay, None)
        relay.kill.assert_called_once()
        self.assertEqual(relay.wait.call_count, 2)


if __name__ == "__main__":
    unittest.main()
