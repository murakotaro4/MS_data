"""移行用 shim。実体は ms_data.skills.preview_params（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.skills import preview_params as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
