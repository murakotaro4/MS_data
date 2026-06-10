"""移行用 shim。実体は ms_data.gh.cleanup_auto_update_prs（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.gh import cleanup_auto_update_prs as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
