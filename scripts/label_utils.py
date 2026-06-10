"""移行用 shim。実体は ms_data.core.labels（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.core import labels as _impl

sys.modules[__name__] = _impl
