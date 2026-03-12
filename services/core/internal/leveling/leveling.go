package leveling

import "math"

// LevelConfig holds the XP curve parameters.
type LevelConfig struct {
	A     float64 // Quadratic coefficient
	B     float64 // Linear coefficient
	CBase float64 // Base XP constant
}

// DefaultConfig returns the default leveling configuration.
func DefaultConfig() LevelConfig {
	return LevelConfig{
		A:     50,
		B:     200,
		CBase: 100,
	}
}

// CalculateLevel returns the level for a given XP amount.
func CalculateLevel(cfg LevelConfig, xp int) int {
	if float64(xp) < cfg.CBase {
		return 0
	}
	c := cfg.CBase - float64(xp)
	d := (cfg.B * cfg.B) - (4 * cfg.A * c)
	if d < 0 {
		return 0
	}
	level := (-cfg.B + math.Sqrt(d)) / (2 * cfg.A)
	return int(level)
}

// XPForLevel returns the total XP required to reach a given level.
func XPForLevel(cfg LevelConfig, level int) int {
	return int(cfg.A*float64(level*level) + cfg.B*float64(level) + cfg.CBase)
}
