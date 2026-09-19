"""Concurrent agent stress tests.

Tests high-concurrency contention, lock contention, lease renewal races,
and atomic ledger mutations under thread pressure.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import tempfile
import threading
import unittest

from ship.lifecycle.coordination import CoordinationManager
from ship.lifecycle.events import EventLogger
from ship.lifecycle.ledger import FileLedgerStore


class TestConcurrentStress(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        self.change_id = "stress-change"
        FileLedgerStore.save(self.repo_root, {
            "version": 1,
            "active_change_id": self.change_id,
            "changes": {
                self.change_id: {
                    "turns": [],
                    "blockers": [],
                    "coordination": {"leases": {}, "handoffs": []},
                    "counter": 0,
                }
            },
        })

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_concurrent_ledger_mutations_no_lost_updates(self):
        """Stress: 30 concurrent worker threads increment a ledger counter.
        Guarantees zero lost updates and zero corrupted states under lock contention.
        """
        num_workers = 30
        iterations_per_worker = 5

        def worker_task(worker_id: int):
            for i in range(iterations_per_worker):
                def updater(entry: dict):
                    entry["counter"] = entry.get("counter", 0) + 1
                    entry.setdefault("workers_seen", []).append(f"w{worker_id}_{i}")
                FileLedgerStore.mutate_change(self.repo_root, self.change_id, updater)

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = [executor.submit(worker_task, i) for i in range(num_workers)]
            for f in as_completed(futures):
                f.result()

        ledger = FileLedgerStore.load(self.repo_root)
        ch = ledger["changes"][self.change_id]
        expected_total = num_workers * iterations_per_worker
        self.assertEqual(ch["counter"], expected_total)
        self.assertEqual(len(ch["workers_seen"]), expected_total)

    def test_concurrent_task_claims_race_safety(self):
        """Stress: 20 workers race to claim 4 tasks (5 workers per task).
        Guarantees exactly 4 winners (1 per task) and 16 clean conflict rejections.
        """
        num_tasks = 4
        workers_per_task = 5
        total_workers = num_tasks * workers_per_task
        coord = CoordinationManager(self.repo_root)

        results = []
        lock = threading.Lock()

        def try_claim(task_idx: int, worker_idx: int):
            task_id = f"task-{task_idx:02d}"
            res = coord.claim_task(
                task_id=task_id,
                owner_id=f"worker-{worker_idx}",
                files=[f"src/file_{task_idx}.py"],
                change_id=self.change_id,
            )
            with lock:
                results.append((task_idx, worker_idx, res.success, res.error))

        with ThreadPoolExecutor(max_workers=total_workers) as executor:
            futures = []
            for t in range(num_tasks):
                for w in range(workers_per_task):
                    futures.append(executor.submit(try_claim, t, t * workers_per_task + w))
            for f in as_completed(futures):
                f.result()

        successes = [r for r in results if r[2] is True]
        conflicts = [r for r in results if r[2] is False]

        self.assertEqual(len(successes), num_tasks, "Exactly one winner per task")
        self.assertEqual(len(conflicts), total_workers - num_tasks, "All others receive clean conflicts")

        # Verify winners hold unique task leases
        claimed_tasks = set()
        for t_idx, w_idx, _, _ in successes:
            self.assertNotIn(t_idx, claimed_tasks)
            claimed_tasks.add(t_idx)

    def test_concurrent_event_stream_stress(self):
        """Stress: 20 threads simultaneously emit 10 events each (200 events).
        Verifies 100% cryptographic SHA-256 hash chain integrity under concurrency.
        """
        num_threads = 20
        events_per_thread = 10
        total_events = num_threads * events_per_thread
        logger = EventLogger(self.repo_root)

        def emit_batch(thread_idx: int):
            for i in range(events_per_thread):
                logger.emit(
                    event_type="FILE_MODIFIED",
                    change_id=self.change_id,
                    agent_id=f"agent-{thread_idx}",
                    target=f"src/mod_{thread_idx}_{i}.py",
                    payload={"index": i},
                )

        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(emit_batch, i) for i in range(num_threads)]
            for f in as_completed(futures):
                f.result()

        valid, msg, broken = logger.verify_integrity()
        self.assertTrue(valid, f"Hash chain broken: {msg}")
        events = logger.query(change_id=self.change_id)
        self.assertEqual(len(events), total_events)


if __name__ == "__main__":
    unittest.main()
