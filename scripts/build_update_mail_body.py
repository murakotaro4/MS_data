"""移行用 shim。実体は ms_data.reporting.build_update_mail_body（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.reporting import build_update_mail_body as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
