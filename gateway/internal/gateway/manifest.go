package gateway

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func LoadFreshManifest(stateDir string, expected FreshnessExpectation) (Manifest, error) {
	pointer, err := os.ReadFile(filepath.Join(stateDir, "current"))
	if err != nil {
		return Manifest{}, fmt.Errorf("read current generation pointer: %w", err)
	}
	generation := strings.TrimSpace(string(pointer))
	if generation == "" || filepath.Base(generation) != generation || strings.ContainsAny(generation, `/\\`) {
		return Manifest{}, fmt.Errorf("invalid current generation pointer")
	}
	payload, err := os.ReadFile(filepath.Join(stateDir, "generations", generation, ManifestFilename))
	if err != nil {
		return Manifest{}, fmt.Errorf("read index manifest: %w", err)
	}
	var manifest Manifest
	if err := json.Unmarshal(payload, &manifest); err != nil {
		return Manifest{}, fmt.Errorf("parse index manifest: %w", err)
	}
	if manifest.SchemaVersion != ManifestSchemaVersion || manifest.Status != "complete" || manifest.Generation == "" {
		return Manifest{}, fmt.Errorf("index manifest is incomplete or has an unsupported schema")
	}
	if manifest.Generation != generation {
		return Manifest{}, fmt.Errorf("index manifest generation does not match current pointer")
	}
	if expected.RepositoryID != "" && manifest.RepositoryID != expected.RepositoryID {
		return Manifest{}, fmt.Errorf("index manifest repository identity does not match")
	}
	if manifest.Dirty {
		return Manifest{}, fmt.Errorf("index manifest is dirty")
	}
	if expected.HeadCommit != "" && manifest.IndexedCommit != expected.HeadCommit {
		return Manifest{}, fmt.Errorf("index manifest commit is stale")
	}
	if expected.FileManifest != "" && manifest.FileManifest != expected.FileManifest {
		return Manifest{}, fmt.Errorf("index manifest file set differs")
	}
	if expected.ConfigSHA256 != "" && manifest.ConfigSHA256 != expected.ConfigSHA256 {
		return Manifest{}, fmt.Errorf("index manifest configuration differs")
	}
	if expected.Backend.ID != "" && manifest.Backend != expected.Backend {
		return Manifest{}, fmt.Errorf("index manifest backend differs")
	}
	if expected.Gateway.ID != "" && manifest.Gateway != expected.Gateway {
		return Manifest{}, fmt.Errorf("index manifest gateway differs")
	}
	return manifest, nil
}

func WriteManifestAtomic(state string, manifest Manifest) error {
	if manifest.Status != "complete" || manifest.SchemaVersion != ManifestSchemaVersion || manifest.Generation == "" {
		return fmt.Errorf("refuse to write incomplete manifest")
	}
	if err := os.MkdirAll(state, 0o700); err != nil {
		return fmt.Errorf("create state directory: %w", err)
	}
	payload, err := json.Marshal(manifest)
	if err != nil {
		return fmt.Errorf("encode manifest: %w", err)
	}
	generationDir := filepath.Join(state, "generations", manifest.Generation)
	if err := os.MkdirAll(generationDir, 0o700); err != nil {
		return fmt.Errorf("create generation directory: %w", err)
	}
	temporary, err := os.CreateTemp(generationDir, ".manifest-*")
	if err != nil {
		return fmt.Errorf("create temporary manifest: %w", err)
	}
	temporaryName := temporary.Name()
	defer os.Remove(temporaryName)
	if err := temporary.Chmod(0o600); err != nil {
		temporary.Close()
		return err
	}
	if _, err := temporary.Write(payload); err != nil {
		temporary.Close()
		return fmt.Errorf("write manifest: %w", err)
	}
	if err := temporary.Sync(); err != nil {
		temporary.Close()
		return fmt.Errorf("sync manifest: %w", err)
	}
	if err := temporary.Close(); err != nil {
		return err
	}
	if err := os.Rename(temporaryName, filepath.Join(generationDir, ManifestFilename)); err != nil {
		return fmt.Errorf("install manifest: %w", err)
	}
	pointer, err := os.CreateTemp(state, ".current-*")
	if err != nil {
		return err
	}
	pointerName := pointer.Name()
	defer os.Remove(pointerName)
	if _, err := pointer.WriteString(manifest.Generation); err != nil {
		_ = pointer.Close()
		return err
	}
	if err := pointer.Close(); err != nil {
		return err
	}
	if err := os.Rename(pointerName, filepath.Join(state, "current")); err != nil {
		return fmt.Errorf("install current pointer: %w", err)
	}
	return nil
}
