"""Explicit passing execution receipts for synthetic lifecycle fixtures.

These test fixtures model verifier output; they do not test project test runners.
Real subprocess execution is covered by test_verification and test_stabilization.
"""
def verify_fixture(root, change=None):
    from lifecycle.ledger import FileLedgerStore
    from lifecycle.vcs import GitClient
    changes = [change] if change else [p.name for p in (root / 'openspec/changes').iterdir() if p.is_dir()]
    for cid in changes:
        FileLedgerStore.record_verification(root, {'execution': {
            'verdict': 'VERIFIED', 'method': 'synthetic_test_fixture',
            'metadata': {'snapshot_fingerprint': GitClient().compute_working_tree_fingerprint(root)},
        }}, change_id=cid)
