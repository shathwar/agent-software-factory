#!/usr/bin/env python3
"""Trusted CI entrypoint; the workflow authenticates the operator before calling it.

Run this file from the pinned tool checkout, never from the candidate checkout.
The agent prompt is not responsible for deciding whether these gates execute.
"""
import argparse
from pathlib import Path
import sys

def main(argv=None):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
    from ship.lifecycle.engine import LifecycleEngine
    from ship.lifecycle.evidence import design_fingerprint
    from ship.lifecycle.paths import validate_change_id
    from ship.lifecycle.verification import format_verification_summary

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['prepare', 'delivery'])
    parser.add_argument('--path', default='.')
    parser.add_argument('--change', required=True)
    parser.add_argument('--digest', required=True)
    parser.add_argument('--approved-by', required=True)
    args = parser.parse_args(argv)
    root = Path(args.path).resolve()
    try:
        validate_change_id(args.change)
        if not args.approved_by.strip():
            raise ValueError('Missing authenticated approver')
        if design_fingerprint(root, args.change) != args.digest:
            raise ValueError('Design differs from the explicitly approved digest; obtain approval for the new design')
        engine = LifecycleEngine()
        if args.phase == 'prepare':
            engine.checkpoints.create_checkpoint(root, 'design', change=args.change)
            engine.ledger.approve_design(root, args.change, args.digest, args.approved_by)
            print(f'Approved design for {args.change}: {args.digest}')
            return 0
        records = engine.verify_change(root, change=args.change, tiers=['execution'])
        print(format_verification_summary(records, change=args.change))
        if records['execution'].verdict != 'VERIFIED':
            return 1
        result = engine.evaluate_repository(root, target_change=args.change)
        print(result['state_key'], result['next_action'])
        return 0 if result['state_key'] == 'DELIVERY_READY' else 1
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'CI gate blocked: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
