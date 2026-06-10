"""移行用 shim。実体は ms_data.net.cache_http（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.net import cache_http as _impl

sys.modules[__name__] = _impl
