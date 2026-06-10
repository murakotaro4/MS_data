"""移行用 shim。実体は ms_data.audit.audit_index_vs_msdata（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.audit import audit_index_vs_msdata as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
