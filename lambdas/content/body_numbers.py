"""The ONE body-number detector (#4993).

The story desk's staging gate and the Panel renderer's fail-closed safety gate both read this object, so a line that
clears one cannot be held by the other. A body number is a spoken weigh-in figure ("318.9 pounds", "145 kg"). Two shapes
are NOT: the tail of a decimal ("2.64") and a weight followed by a rate unit ("2.64 pounds per week").
"""

import re

_RATE_TAIL = r"(?:\s*/\s*(?:week|wk|w)\b|\s+(?:per|a|each|every)\s+week\b)"
BODY_NUM_RE = re.compile(r"(?<![\d.,])\b\d{2,3}(?:\.\d+)?\s?(?:lb|lbs|pound|pounds|kg|kilo|kilos|kilograms)\b(?!" + _RATE_TAIL + ")", re.I)
