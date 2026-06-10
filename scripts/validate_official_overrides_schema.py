"""移行用 shim。実体は ms_data.validation.validate_official_overrides_schema（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.validation import validate_official_overrides_schema as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
