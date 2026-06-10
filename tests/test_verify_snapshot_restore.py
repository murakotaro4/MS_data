from pathlib import Path

from ms_data.validation import verify_snapshot_restore


def test_verify_snapshot_restore_round_trip_with_current_contract():
    verify_snapshot_restore.verify(Path("."))
