"""移行用 shim。実体は ms_data.validation.validate_generated_reports（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.validation import validate_generated_reports as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
