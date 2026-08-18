"""Bug 分类器 — BugKey → BugType"""

from ..models import CrashFeatures
from ..bug_types import BUG_KEY_TO_TYPE, classify_kasan_subtype


def classify_bug_type(feature: CrashFeatures) -> str:
    if feature.bug_type:
        return feature.bug_type
    if not feature.bug_key:
        return "unknown"
    for key, btype in BUG_KEY_TO_TYPE.items():
        if key in feature.bug_key:
            return classify_kasan_subtype(feature.bug) if btype == "kasan" else btype
    if feature.bug:
        for key, btype in BUG_KEY_TO_TYPE.items():
            if key in feature.bug:
                return classify_kasan_subtype(feature.bug) if btype == "kasan" else btype
    return "unknown"
