package leveling

import (
	"testing"
)

func TestCalculateLevel(t *testing.T) {
	tests := []struct {
		xp       int
		expected int
	}{
		{0, 0},
		{50, 0},
		{100, 1},
		{250, 2},
		{500, 3},
		{1000, 5},
		{10000, 18},
	}

	cfg := DefaultConfig()
	for _, tt := range tests {
		actual := CalculateLevel(cfg, tt.xp)
		if actual != tt.expected {
			t.Errorf("CalculateLevel(%d) = %d; want %d", tt.xp, actual, tt.expected)
		}
	}
}

func TestXPForLevel(t *testing.T) {
	tests := []struct {
		level    int
		expected int
	}{
		{0, 100}, // Level 0 requires Base XP
		{1, 350}, // 50*1 + 200*1 + 100
		{2, 700}, // 50*4 + 200*2 + 100
	}

	cfg := DefaultConfig()
	for _, tt := range tests {
		actual := XPForLevel(cfg, tt.level)
		if actual != tt.expected {
			t.Errorf("XPForLevel(%d) = %d; want %d", tt.level, actual, tt.expected)
		}
	}
}
