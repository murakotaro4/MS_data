"""移行用 shim。実体は ms_data.pipeline.restore_snapshot（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.pipeline import restore_snapshot as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
