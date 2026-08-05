"""Detection class indices, matching the model's training order and
RearAware-Chrome's offscreen.js ([cat, face, butt])."""

CAT = 0
CAT_FACE = 1
CAT_BUTT = 2

DEBUG_CLASS_INFO = [
    {"name": "CAT_00", "color": (255, 100, 59)},    # BGR: blue-ish, matches #3b82f6
    {"name": "CAT_FACE", "color": (85, 197, 34)},    # matches #22c55e
    {"name": "CAT_BUTT", "color": (68, 68, 239)},    # matches #ef4444
]
