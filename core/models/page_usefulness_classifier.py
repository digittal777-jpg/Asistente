from __future__ import annotations

from typing import Dict


class PageUsefulnessClassifier:
    """Clasificador heurístico de utilidad con futuro slot ONNX."""

    POOR_TOKENS = (
        "subscribe",
        "register to continue",
        "sign in to continue",
        "advertisement",
        "cookie policy",
        "lorem ipsum",
        "paywall",
        "anuncio",
        "cookies",
    )

    def classify(self, text: str) -> Dict[str, object]:
        content = str(text or "").strip()
        lowered = content.lower()
        poor_hits = sum(1 for token in self.POOR_TOKENS if token in lowered)
        char_score = min(1.0, len(content) / 1600.0)
        penalty = min(0.8, poor_hits * 0.18)
        score = round(max(0.0, char_score - penalty), 4)
        if len(content) < 200 or poor_hits >= 3:
            label = "poor"
        elif score >= 0.65:
            label = "useful"
        else:
            label = "mixed"
        return {
            "label": label,
            "score": score,
            "poor_token_hits": poor_hits,
            "char_count": len(content),
        }
