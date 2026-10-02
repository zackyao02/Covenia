from __future__ import annotations

import re
from typing import Any


def mask_model_text(value: Any) -> tuple[str, int]:
    text = str(value or "")
    count = 0
    patterns = (
        r"(?<!\d)1[3-9]\d{9}(?!\d)",
        r"(?<!\d)\d{15,19}(?!\d)",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
        r"(?:地址|住址|收货地址|支付宝(?:账号)?)[：:\s]*[^，。,；;\n]+",
        r"(?:就医|不良反应|过敏)[^，。,；;\n]*",
    )
    for pattern in patterns:
        text, matches = re.subn(pattern, "[已脱敏]", text)
        count += matches
    return text, count
