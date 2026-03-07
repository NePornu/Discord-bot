
import sys
import os

def test_formatting():
    # Simple logic test
    def format_nsfw_score(score: float) -> str:
        percentage = min(max(score * 100, 0), 100)
        if score < 0.2:
            level = "Velmi nízká"
        elif score < 0.5:
            level = "Nízká"
        elif score < 0.8:
            level = "Možná"
        elif score < 0.95:
            level = "Vysoká"
        else:
            level = "Kritická"
        return f"{level} ({percentage:.1f}%)"

    test_cases = [
        (0.05, "Velmi nízká (5.0%)"),
        (0.35, "Nízká (35.0%)"),
        (0.65, "Možná (65.0%)"),
        (0.85, "Vysoká (85.0%)"),
        (0.98, "Kritická (98.0%)"),
        (1.0, "Kritická (100.0%)"),
        (-0.1, "Velmi nízká (0.0%)"),
        (1.1, "Kritická (100.0%)")
    ]

    for score, expected in test_cases:
        result = format_nsfw_score(score)
        print(f"Score: {score:.2f} -> {result}")
        assert result == expected, f"Expected {expected}, got {result}"
    
    print("Formatting tests passed!")

if __name__ == "__main__":
    test_formatting()
