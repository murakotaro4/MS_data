"""移行用 shim。実体は ms_data.skills.build_skills（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.skills import build_skills as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
