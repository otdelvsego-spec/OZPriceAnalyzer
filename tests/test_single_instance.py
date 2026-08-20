from __future__ import annotations

import unittest

from ozon_app.single_instance import SingleInstanceGuard, launch_single_instance


class _Backend:
    def __init__(self, primary: bool, activated: bool = True) -> None:
        self.primary = primary
        self.activated = activated
        self.acquire_calls = 0
        self.activate_calls = 0
        self.close_calls = 0

    def acquire(self) -> bool:
        self.acquire_calls += 1
        return self.primary

    def activate_existing(self) -> bool:
        self.activate_calls += 1
        return self.activated

    def close(self) -> None:
        self.close_calls += 1


class _App:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    def mainloop(self) -> None:
        self.events.append("mainloop")
        if self.fail:
            raise RuntimeError("test failure")


class SingleInstanceTests(unittest.TestCase):
    def test_primary_instance_starts_application_and_releases_guard(self) -> None:
        backend = _Backend(primary=True)
        events: list[str] = []

        started = launch_single_instance(
            lambda: _App(events),
            guard=SingleInstanceGuard(backend),
        )

        self.assertTrue(started)
        self.assertEqual(events, ["mainloop"])
        self.assertEqual(backend.acquire_calls, 1)
        self.assertEqual(backend.activate_calls, 0)
        self.assertEqual(backend.close_calls, 1)

    def test_second_instance_activates_existing_window_without_creating_app(self) -> None:
        backend = _Backend(primary=False)
        factory_calls = 0

        def factory() -> _App:
            nonlocal factory_calls
            factory_calls += 1
            return _App([])

        guard = SingleInstanceGuard(backend)
        started = launch_single_instance(factory, guard=guard)

        self.assertFalse(started)
        self.assertEqual(factory_calls, 0)
        self.assertTrue(guard.activated_existing_window)
        self.assertEqual(backend.activate_calls, 1)
        self.assertEqual(backend.close_calls, 1)

    def test_guard_is_released_when_application_fails(self) -> None:
        backend = _Backend(primary=True)

        with self.assertRaisesRegex(RuntimeError, "test failure"):
            launch_single_instance(
                lambda: _App([], fail=True),
                guard=SingleInstanceGuard(backend),
            )

        self.assertEqual(backend.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
