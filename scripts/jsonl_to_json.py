"""移行用 shim。実体は ms_data.pipeline.jsonl_to_json（リファクタ完了後に撤去予定）。"""

import sys

from ms_data.pipeline import jsonl_to_json as _impl

if __name__ == "__main__":
    sys.exit(_impl.main())
else:
    sys.modules[__name__] = _impl
