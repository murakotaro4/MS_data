"""移行用 shim。実体は ms_data.audit.detect_msdata_rollbacks（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.audit import detect_msdata_rollbacks as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
