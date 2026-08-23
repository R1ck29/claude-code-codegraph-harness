package gateway

import (
	"fmt"
	"path/filepath"
	"strings"
)

// ResolveRoot canonicalizes the request working directory and verifies that it
// is contained by an approved canonical root. EvalSymlinks before containment
// prevents a symlink below an approved root from escaping it.
func ResolveRoot(cwd string, allowedRoots []string) (string, error) {
	if strings.TrimSpace(cwd) == "" {
		return "", fmt.Errorf("working directory is required")
	}
	canonical, err := filepath.EvalSymlinks(cwd)
	if err != nil {
		return "", fmt.Errorf("resolve working directory: %w", err)
	}
	canonical, err = filepath.Abs(canonical)
	if err != nil {
		return "", fmt.Errorf("absolute working directory: %w", err)
	}
	for _, candidate := range allowedRoots {
		allowed, err := filepath.EvalSymlinks(candidate)
		if err != nil {
			continue
		}
		allowed, err = filepath.Abs(allowed)
		if err != nil {
			continue
		}
		rel, err := filepath.Rel(allowed, canonical)
		if err == nil && rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator)) {
			return canonical, nil
		}
	}
	return "", fmt.Errorf("working directory is outside an allowed root")
}
