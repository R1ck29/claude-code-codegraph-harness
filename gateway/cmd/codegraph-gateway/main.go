// codegraph-gateway is the only executable registered with AI clients.
// Administrative indexing is a separate explicit command, never an MCP tool.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"

	"github.com/R1ck29/claude-code-codegraph-harness/gateway/internal/gateway"
)

const (
	fixtureRecordPrefix = "CODEGRAPH_APPROVED_FIXTURES:"
	fixtureRecordSuffix = ":END"
)

// allowedFixtureManifests is injected by the controlled release build with
// -ldflags "-X main.allowedFixtureManifests=CODEGRAPH_APPROVED_FIXTURES:<sha256>[,<sha256>...]:END".
// The stable record is also scanned by the offline bundle gate, tying the
// profile allowlist to every executable. An ordinary source build contains an
// empty record and therefore cannot index or serve any repository.
var allowedFixtureManifests = "CODEGRAPH_APPROVED_FIXTURES::END"

func main() {
	if err := run(context.Background(), os.Args[1:]); err != nil {
		fmt.Fprintln(os.Stderr, "codegraph-gateway:", err)
		os.Exit(1)
	}
}

func run(ctx context.Context, arguments []string) error {
	if len(arguments) == 0 {
		return errors.New("usage: codegraph-gateway serve | index build|status | fixture fingerprint")
	}
	switch arguments[0] {
	case "serve":
		return serve(ctx, arguments[1:])
	case "index":
		return index(ctx, arguments[1:])
	case "fixture":
		return fixture(ctx, arguments[1:], os.Stdout)
	default:
		return errors.New("usage: codegraph-gateway serve | index build|status | fixture fingerprint")
	}
}

type commonOptions struct {
	root           string
	allowedRoots   string
	cbmBinary      string
	backendSHA     string
	configFile     string
	configSHA      string
	stateDir       string
	cacheDir       string
	runtimeDir     string
	gitBinary      string
	gitSHA         string
	classification string
}

func addCommonFlags(flags *flag.FlagSet, options *commonOptions) {
	flags.StringVar(&options.root, "root", "", "repository root (default: current working directory)")
	flags.StringVar(&options.allowedRoots, "allowed-root", os.Getenv("CODEGRAPH_ALLOWED_ROOT"), "approved repository root; may be repeated as path-list")
	flags.StringVar(&options.cbmBinary, "cbm-binary", os.Getenv("CODEGRAPH_CBM_BINARY"), "pinned Codebase-Memory native executable")
	flags.StringVar(&options.backendSHA, "backend-sha256", os.Getenv("CODEGRAPH_CBM_SHA256"), "expected native backend SHA-256")
	flags.StringVar(&options.configFile, "config", os.Getenv("CODEGRAPH_CONFIG_FILE"), "approved local routing policy file")
	flags.StringVar(&options.configSHA, "config-sha256", os.Getenv("CODEGRAPH_CONFIG_SHA256"), "approved graph configuration SHA-256")
	flags.StringVar(&options.stateDir, "state-dir", firstEnvironment("CODEGRAPH_STATE_DIR", "CODEGRAPH_STATE_ROOT"), "private state directory outside the repository")
	flags.StringVar(&options.cacheDir, "cache-dir", os.Getenv("CODEGRAPH_CACHE_DIR"), "private local cache directory")
	flags.StringVar(&options.runtimeDir, "runtime-dir", os.Getenv("CODEGRAPH_RUNTIME_DIR"), "private local runtime directory")
	flags.StringVar(&options.gitBinary, "git-binary", os.Getenv("CODEGRAPH_GIT_BINARY"), "managed absolute git executable")
	flags.StringVar(&options.gitSHA, "git-sha256", os.Getenv("CODEGRAPH_GIT_SHA256"), "expected managed git SHA-256")
	flags.StringVar(&options.classification, "data-classification", "public-fixture", "must be public-fixture in this release")
}

func requirePublicFixture(options commonOptions) error {
	if options.classification == "public-fixture" {
		return nil
	}
	return errors.New("company-source is disabled in this release; public-fixture is required")
}

func requireApprovedFixture(fileManifest string) error {
	if len(fileManifest) != 64 {
		return errors.New("repository manifest is not a valid SHA-256")
	}
	approvedManifests, err := compiledFixtureManifests()
	if err != nil {
		return err
	}
	for _, approved := range approvedManifests {
		approved = strings.TrimSpace(approved)
		if strings.EqualFold(approved, fileManifest) {
			return nil
		}
	}
	return errors.New("repository is not a compile-time approved public fixture")
}

func compiledFixtureManifests() ([]string, error) {
	if !strings.HasPrefix(allowedFixtureManifests, fixtureRecordPrefix) ||
		!strings.HasSuffix(allowedFixtureManifests, fixtureRecordSuffix) {
		return nil, errors.New("binary contains an invalid approved public fixture record")
	}
	payload := strings.TrimSuffix(strings.TrimPrefix(allowedFixtureManifests, fixtureRecordPrefix), fixtureRecordSuffix)
	if payload == "" {
		return nil, nil
	}
	manifests := strings.Split(payload, ",")
	for index, manifest := range manifests {
		if len(manifest) != 64 || strings.ToLower(manifest) != manifest {
			return nil, errors.New("binary contains an invalid approved public fixture manifest")
		}
		if index > 0 && manifests[index-1] >= manifest {
			return nil, errors.New("binary approved public fixture manifests must be sorted and unique")
		}
	}
	return manifests, nil
}

func fixtureReleaseRecord(manifests ...string) string {
	return fixtureRecordPrefix + strings.Join(manifests, ",") + fixtureRecordSuffix
}

func firstEnvironment(names ...string) string {
	for _, name := range names {
		if value := os.Getenv(name); value != "" {
			return value
		}
	}
	return ""
}

func fixture(ctx context.Context, arguments []string, output io.Writer) error {
	if len(arguments) == 0 || arguments[0] != "fingerprint" {
		return errors.New("usage: codegraph-gateway fixture fingerprint")
	}
	flags := flag.NewFlagSet("fixture fingerprint", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	var options commonOptions
	addCommonFlags(flags, &options)
	if err := flags.Parse(arguments[1:]); err != nil {
		return err
	}
	options, err := resolveOptions(options)
	if err != nil {
		return err
	}
	if err := requirePublicFixture(options); err != nil {
		return err
	}
	managedGit, err := validateGit(options)
	if err != nil {
		return err
	}
	options.gitBinary = managedGit
	if err := normalizeRepositoryRoot(ctx, &options); err != nil {
		return err
	}
	_, dirty, err := gitState(ctx, options)
	if err != nil {
		return err
	}
	if dirty {
		return errors.New("fixture must contain only clean tracked regular files")
	}
	manifest, files, err := gitFileManifest(ctx, options)
	if err != nil {
		return err
	}
	return json.NewEncoder(output).Encode(map[string]any{
		"status": "success", "summary": "public fixture fingerprint computed", "file_manifest_sha256": manifest, "files": files,
	})
}

func resolveOptions(options commonOptions) (commonOptions, error) {
	if options.root == "" {
		cwd, err := os.Getwd()
		if err != nil {
			return options, err
		}
		options.root = cwd
	}
	allowed := filepath.SplitList(options.allowedRoots)
	if len(allowed) == 0 || options.allowedRoots == "" {
		return options, errors.New("--allowed-root or CODEGRAPH_ALLOWED_ROOT is required")
	}
	for index, candidate := range allowed {
		if candidate == "." {
			allowed[index] = options.root
		}
	}
	root, err := gateway.ResolveRoot(options.root, allowed)
	if err != nil {
		return options, err
	}
	options.root = root
	if options.stateDir == "" {
		dataRoot, err := os.UserConfigDir()
		if err != nil {
			return options, fmt.Errorf("resolve private state directory: %w", err)
		}
		options.stateDir = filepath.Join(dataRoot, "ClaudeCodeCodegraphHarness", "state")
	}
	options.stateDir, err = canonicalExternalBase(root, options.stateDir, "state")
	if err != nil {
		return options, err
	}
	// One external state root may serve many repositories; identities prevent
	// manifests, caches and runtime sockets from crossing repository boundaries.
	options.stateDir = filepath.Join(options.stateDir, repositoryIdentity(root))
	for _, directory := range []*string{&options.cacheDir, &options.runtimeDir} {
		if *directory == "" {
			continue
		}
		absolute, err := canonicalExternalBase(root, *directory, "cache or runtime")
		if err != nil {
			return options, err
		}
		*directory = absolute
	}
	return options, nil
}

func canonicalExternalBase(root, candidate, label string) (string, error) {
	absolute, err := filepath.Abs(candidate)
	if err != nil {
		return "", err
	}
	existing := absolute
	for {
		info, statErr := os.Lstat(existing)
		if statErr == nil {
			if info.Mode()&os.ModeSymlink != 0 {
				return "", fmt.Errorf("%s directory must not contain a symlink or reparse point", label)
			}
			if existing == absolute && !info.IsDir() {
				return "", fmt.Errorf("%s path must be a directory", label)
			}
			break
		}
		if !os.IsNotExist(statErr) {
			return "", fmt.Errorf("inspect %s directory: %w", label, statErr)
		}
		parent := filepath.Dir(existing)
		if parent == existing {
			return "", fmt.Errorf("resolve %s directory", label)
		}
		existing = parent
	}
	canonicalExisting, err := filepath.EvalSymlinks(existing)
	if err != nil {
		return "", fmt.Errorf("resolve %s directory: %w", label, err)
	}
	suffix, err := filepath.Rel(existing, absolute)
	if err != nil {
		return "", fmt.Errorf("resolve %s directory suffix: %w", label, err)
	}
	canonical := filepath.Join(canonicalExisting, suffix)
	if repositoryContains(root, canonical) {
		return "", fmt.Errorf("%s directory must be outside the repository", label)
	}
	return canonical, nil
}

func repositoryContains(root, candidate string) bool {
	relative, err := filepath.Rel(root, candidate)
	return err == nil && relative != ".." && !strings.HasPrefix(relative, ".."+string(filepath.Separator))
}

func serve(ctx context.Context, arguments []string) error {
	flags := flag.NewFlagSet("serve", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	var options commonOptions
	addCommonFlags(flags, &options)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	options, err := resolveOptions(options)
	if err != nil {
		return err
	}
	if err := requirePublicFixture(options); err != nil {
		return err
	}
	if options.cbmBinary == "" || options.backendSHA == "" || options.configFile == "" || options.configSHA == "" {
		return errors.New("serve requires pinned CBM binary, backend SHA-256, configuration file, and configuration SHA-256")
	}
	if err := validateBackend(&options); err != nil {
		return err
	}
	actualHash := options.backendSHA
	managedGit, err := validateGit(options)
	if err != nil {
		return err
	}
	options.gitBinary = managedGit
	if err := normalizeRepositoryRoot(ctx, &options); err != nil {
		return err
	}
	if err := validateConfiguration(&options); err != nil {
		return err
	}
	head, dirty, err := gitState(ctx, options)
	if err != nil {
		return err
	}
	if dirty {
		return errors.New("refuse to serve a dirty repository; rebuild after committing or use normal local exploration")
	}
	fileManifest, _, err := gitFileManifest(ctx, options)
	if err != nil {
		return err
	}
	if err := requireApprovedFixture(fileManifest); err != nil {
		return err
	}
	gatewayHash, err := executableHash()
	if err != nil {
		return err
	}
	expected := gateway.FreshnessExpectation{
		Backend:      gateway.BackendIdentity{ID: "codebase-memory", Version: "0.10.8", SHA256: actualHash},
		Gateway:      gateway.BackendIdentity{ID: "codegraph-gateway", Version: gateway.Version, SHA256: gatewayHash},
		RepositoryID: repositoryIdentity(options.root),
		ConfigSHA256: options.configSHA,
		HeadCommit:   head,
		FileManifest: fileManifest,
	}
	manifest, err := gateway.LoadFreshManifest(options.stateDir, expected)
	if err != nil {
		return err
	}
	options.cacheDir = generationCacheDir(options.stateDir, options.cacheDir, manifest.Generation)
	options.runtimeDir, err = generationRuntimeDir(options.stateDir, options.runtimeDir, manifest.Generation)
	if err != nil {
		return err
	}
	backend, err := gateway.StartCBM(gateway.CBMOptions{
		Binary: options.cbmBinary, WorkingDir: options.root, AllowedRoot: options.root,
		CacheDir: options.cacheDir, RuntimeDir: options.runtimeDir, Project: cbmProjectName(options.root), GitBinary: options.gitBinary,
	})
	if err != nil {
		return err
	}
	defer backend.Close()
	server, err := gateway.NewServer(options.root, manifest, backend)
	if err != nil {
		return err
	}
	server.WithFreshnessChecker(func(checkContext context.Context) error {
		currentHead, currentDirty, checkErr := gitState(checkContext, options)
		if checkErr != nil {
			return checkErr
		}
		if currentDirty || currentHead != expected.HeadCommit {
			return errors.New("repository changed since indexing")
		}
		currentManifest, _, checkErr := gitFileManifest(checkContext, options)
		if checkErr != nil {
			return checkErr
		}
		if currentManifest != expected.FileManifest {
			return errors.New("repository changed since indexing")
		}
		_, checkErr = gateway.LoadFreshManifest(options.stateDir, expected)
		return checkErr
	})
	return gateway.ServeStdio(ctx, os.Stdin, os.Stdout, os.Stderr, server)
}

func index(ctx context.Context, arguments []string) error {
	if len(arguments) == 0 {
		return errors.New("usage: codegraph-gateway index build|status")
	}
	switch arguments[0] {
	case "build":
		return indexBuild(ctx, arguments[1:])
	case "status":
		return indexStatus(ctx, arguments[1:])
	default:
		return errors.New("usage: codegraph-gateway index build|status")
	}
}

func indexBuild(ctx context.Context, arguments []string) error {
	started := time.Now()
	flags := flag.NewFlagSet("index build", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	var options commonOptions
	addCommonFlags(flags, &options)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	options, err := resolveOptions(options)
	if err != nil {
		return err
	}
	if err := requirePublicFixture(options); err != nil {
		return err
	}
	if options.cbmBinary == "" || options.backendSHA == "" || options.configFile == "" || options.configSHA == "" {
		return errors.New("index build requires pinned CBM binary, backend SHA-256, configuration file, and configuration SHA-256")
	}
	if err := validateBackend(&options); err != nil {
		return err
	}
	actualHash := options.backendSHA
	managedGit, err := validateGit(options)
	if err != nil {
		return err
	}
	options.gitBinary = managedGit
	if err := normalizeRepositoryRoot(ctx, &options); err != nil {
		return err
	}
	if err := validateConfiguration(&options); err != nil {
		return err
	}
	head, dirty, err := gitState(ctx, options)
	if err != nil {
		return err
	}
	if dirty {
		return errors.New("refuse to index a dirty repository; commit or clean it first")
	}
	fileManifest, fileCount, err := gitFileManifest(ctx, options)
	if err != nil {
		return err
	}
	if err := requireApprovedFixture(fileManifest); err != nil {
		return err
	}
	lock, err := acquireIndexLock(options.stateDir)
	if err != nil {
		return err
	}
	defer func() { _ = lock.Close() }()
	generation := fmt.Sprintf("%d", time.Now().UTC().UnixNano())
	options.cacheDir = generationCacheDir(options.stateDir, options.cacheDir, generation)
	options.runtimeDir, err = generationRuntimeDir(options.stateDir, options.runtimeDir, generation)
	if err != nil {
		return err
	}
	if err := os.MkdirAll(options.cacheDir, 0o700); err != nil {
		return err
	}
	if err := os.MkdirAll(options.runtimeDir, 0o700); err != nil {
		return err
	}
	cbmEnvironment, err := gateway.BuildCBMEnvironment(options.root, options.cacheDir, options.runtimeDir, options.gitBinary)
	if err != nil {
		return err
	}
	for _, setting := range [][2]string{{"auto_index", "false"}, {"auto_watch", "false"}, {"ui_enabled", "false"}} {
		if err := configureCBM(ctx, options, cbmEnvironment, setting[0], setting[1]); err != nil {
			return err
		}
	}
	// The native CLI receives an explicit root and a minimal environment. This
	// is an administrative, user-started operation; it is never callable via MCP.
	command := exec.Command(options.cbmBinary, "cli", "index_repository", "--repo-path", options.root) // #nosec G204 -- validated local binary and root.
	command.Dir = options.root
	command.Env = cbmEnvironment
	command.Stdout = io.Discard
	command.Stderr = io.Discard
	if err := gateway.RunChildCommand(ctx, command); err != nil {
		return fmt.Errorf("CBM index failed: %w", err)
	}
	counts, err := cbmIndexCounts(ctx, options, fileCount)
	if err != nil {
		return err
	}
	gatewayHash, err := executableHash()
	if err != nil {
		return err
	}
	manifest := gateway.Manifest{
		SchemaVersion: gateway.ManifestSchemaVersion, Generation: generation, Status: "complete",
		Gateway: gateway.BackendIdentity{ID: "codegraph-gateway", Version: gateway.Version, SHA256: gatewayHash}, RepositoryID: repositoryIdentity(options.root), IndexedCommit: head, Dirty: false,
		Backend:      gateway.BackendIdentity{ID: "codebase-memory", Version: "0.10.8", SHA256: actualHash},
		ConfigSHA256: options.configSHA, FileManifest: fileManifest, BuiltAt: time.Now().UTC().Format(time.RFC3339), DurationMS: int(time.Since(started).Milliseconds()), Counts: counts,
	}
	return gateway.WriteManifestAtomic(options.stateDir, manifest)
}

func configureCBM(ctx context.Context, options commonOptions, environment []string, key, value string) error {
	command := exec.Command(options.cbmBinary, "config", "set", key, value) // #nosec G204 -- fixed native executable and fixed setting name/value.
	command.Dir = options.root
	command.Env = environment
	command.Stdout = io.Discard
	command.Stderr = io.Discard
	if err := gateway.RunChildCommand(ctx, command); err != nil {
		return fmt.Errorf("set CBM %s: %w", key, err)
	}
	return nil
}

func cbmProjectName(root string) string {
	clean := filepath.ToSlash(filepath.Clean(root))
	return strings.Trim(strings.ReplaceAll(clean, "/", "-"), "-")
}

func indexStatus(ctx context.Context, arguments []string) error {
	flags := flag.NewFlagSet("index status", flag.ContinueOnError)
	flags.SetOutput(os.Stderr)
	var options commonOptions
	addCommonFlags(flags, &options)
	if err := flags.Parse(arguments); err != nil {
		return err
	}
	options, err := resolveOptions(options)
	if err != nil {
		return err
	}
	if err := requirePublicFixture(options); err != nil {
		return err
	}
	if options.cbmBinary == "" || options.backendSHA == "" || options.configFile == "" || options.configSHA == "" {
		return errors.New("index status requires pinned CBM binary, backend SHA-256, configuration file, and configuration SHA-256")
	}
	if err := validateBackend(&options); err != nil {
		return err
	}
	managedGit, err := validateGit(options)
	if err != nil {
		return err
	}
	options.gitBinary = managedGit
	if err := normalizeRepositoryRoot(ctx, &options); err != nil {
		return err
	}
	if err := validateConfiguration(&options); err != nil {
		return err
	}
	head, dirty, err := gitState(ctx, options)
	if err != nil {
		return err
	}
	if dirty {
		return errors.New("repository changed since indexing")
	}
	fileManifest, _, err := gitFileManifest(ctx, options)
	if err != nil {
		return err
	}
	if err := requireApprovedFixture(fileManifest); err != nil {
		return err
	}
	var expected gateway.FreshnessExpectation
	if options.cbmBinary != "" && options.backendSHA != "" && options.configSHA != "" {
		gatewayHash, err := executableHash()
		if err != nil {
			return err
		}
		expected = gateway.FreshnessExpectation{Backend: gateway.BackendIdentity{ID: "codebase-memory", Version: "0.10.8", SHA256: options.backendSHA}, Gateway: gateway.BackendIdentity{ID: "codegraph-gateway", Version: gateway.Version, SHA256: gatewayHash}, RepositoryID: repositoryIdentity(options.root), ConfigSHA256: options.configSHA, HeadCommit: head, FileManifest: fileManifest}
	}
	manifest, err := gateway.LoadFreshManifest(options.stateDir, expected)
	if err != nil {
		return err
	}
	return json.NewEncoder(os.Stdout).Encode(map[string]any{"status": "success", "summary": "local graph is fresh", "manifest": manifest})
}

func validateConfiguration(options *commonOptions) error {
	if options.configFile == "" || !filepath.IsAbs(options.configFile) {
		return errors.New("configuration file must be an absolute path")
	}
	info, err := os.Lstat(options.configFile)
	if err != nil {
		return fmt.Errorf("inspect configuration file: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("configuration file must be a regular file, not a symlink or reparse point")
	}
	canonical, err := filepath.EvalSymlinks(options.configFile)
	if err != nil {
		return fmt.Errorf("resolve configuration file: %w", err)
	}
	actual, err := sha256File(canonical)
	if err != nil {
		return fmt.Errorf("hash configuration file: %w", err)
	}
	if !strings.EqualFold(actual, options.configSHA) {
		return errors.New("configuration SHA-256 does not match the actual file")
	}
	options.configFile = canonical
	options.configSHA = actual
	return nil
}

func validateBackend(options *commonOptions) error {
	if options.cbmBinary == "" || !filepath.IsAbs(options.cbmBinary) {
		return errors.New("backend executable must be an absolute path")
	}
	info, err := os.Lstat(options.cbmBinary)
	if err != nil {
		return fmt.Errorf("inspect backend executable: %w", err)
	}
	if info.Mode()&os.ModeSymlink != 0 || !info.Mode().IsRegular() {
		return errors.New("backend executable must be a regular file, not a symlink or reparse point")
	}
	canonical, err := filepath.EvalSymlinks(options.cbmBinary)
	if err != nil {
		return fmt.Errorf("resolve backend executable: %w", err)
	}
	actual, err := sha256File(canonical)
	if err != nil {
		return fmt.Errorf("hash backend executable: %w", err)
	}
	if !strings.EqualFold(actual, options.backendSHA) {
		return errors.New("pinned backend SHA-256 does not match")
	}
	options.cbmBinary = canonical
	options.backendSHA = actual
	return nil
}

func sha256File(name string) (string, error) {
	file, err := os.Open(name)
	if err != nil {
		return "", err
	}
	defer file.Close()
	hash := sha256.New()
	if _, err := io.Copy(hash, file); err != nil {
		return "", err
	}
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func sha256Text(value string) string {
	sum := sha256.Sum256([]byte(value))
	return hex.EncodeToString(sum[:])
}
func repositoryIdentity(root string) string { return sha256Text(root) }
func executableHash() (string, error) {
	executable, err := os.Executable()
	if err != nil {
		return "", err
	}
	return sha256File(executable)
}

func validateGit(options commonOptions) (string, error) {
	if options.gitBinary == "" || options.gitSHA == "" {
		return "", errors.New("managed absolute git binary and SHA-256 are required")
	}
	if !filepath.IsAbs(options.gitBinary) {
		return "", errors.New("managed git binary must be an absolute path")
	}
	canonical, err := filepath.EvalSymlinks(options.gitBinary)
	if err != nil {
		return "", fmt.Errorf("resolve managed git: %w", err)
	}
	hash, err := sha256File(canonical)
	if err != nil {
		return "", err
	}
	if !strings.EqualFold(hash, options.gitSHA) {
		return "", errors.New("managed git SHA-256 does not match")
	}
	return canonical, nil
}

func gitEnvironment() []string {
	nullDevice := "/dev/null"
	if systemRoot := os.Getenv("SystemRoot"); systemRoot != "" {
		nullDevice = "NUL"
	}
	return []string{"PATH=" + systemPath(), "LANG=C", "LC_ALL=C", "GIT_CONFIG_NOSYSTEM=1", "GIT_CONFIG_GLOBAL=" + nullDevice, "GIT_OPTIONAL_LOCKS=0", "GIT_TERMINAL_PROMPT=0"}
}

func managedGitCommand(ctx context.Context, options commonOptions, arguments ...string) *exec.Cmd {
	// Repository-local configuration is untrusted input. In particular,
	// core.fsmonitor may name an arbitrary executable that Git would otherwise
	// launch while answering read-only status queries. Command-scope values have
	// higher precedence than repository config and are applied to every call.
	fixed := []string{"-c", "core.fsmonitor=false", "-c", "core.fsmonitorHookVersion=0", "-C", options.root}
	command := exec.CommandContext(ctx, options.gitBinary, append(fixed, arguments...)...) // #nosec G204 -- validated managed executable and fixed administrative arguments.
	command.Env = gitEnvironment()
	return command
}

func gitState(ctx context.Context, options commonOptions) (string, bool, error) {
	headCommand := managedGitCommand(ctx, options, "rev-parse", "--verify", "HEAD^{commit}")
	headOutput, err := headCommand.Output()
	if err != nil {
		return "", false, fmt.Errorf("read repository commit: %w", err)
	}
	indexEntries, err := gitIndexEntries(ctx, options)
	if err != nil {
		return "", false, err
	}
	headEntries, err := gitHeadEntries(ctx, options)
	if err != nil {
		return "", false, err
	}
	dirty := !equalTrackedEntries(indexEntries, headEntries)
	workingTreeDirty, err := workingTreeHasExtraEntries(options.root, indexEntries)
	if err != nil {
		return "", false, err
	}
	dirty = dirty || workingTreeDirty
	return strings.TrimSpace(string(headOutput)), dirty, nil
}

type trackedEntry struct {
	mode     string
	objectID string
	path     string
}

func validateTrackedPath(relative string) error {
	if relative == "" || filepath.IsAbs(relative) || filepath.VolumeName(relative) != "" || strings.Contains(relative, "\\") {
		return errors.New("repository contains an unsafe tracked path")
	}
	for _, character := range relative {
		if character < 0x20 || character == 0x7f {
			return errors.New("repository contains a control character in a tracked path")
		}
	}
	clean := filepath.ToSlash(filepath.Clean(filepath.FromSlash(relative)))
	if clean != relative || clean == "." || strings.HasPrefix(clean, "../") {
		return errors.New("repository contains a non-canonical tracked path")
	}
	return nil
}

func gitIndexEntries(ctx context.Context, options commonOptions) ([]trackedEntry, error) {
	command := managedGitCommand(ctx, options, "ls-files", "-s", "-z")
	output, err := command.Output()
	if err != nil {
		return nil, fmt.Errorf("read repository index: %w", err)
	}
	entries := make([]trackedEntry, 0)
	for _, record := range bytes.Split(output, []byte{0}) {
		if len(record) == 0 {
			continue
		}
		header, rawPath, ok := bytes.Cut(record, []byte{'\t'})
		if !ok {
			return nil, errors.New("managed Git returned an invalid index entry")
		}
		fields := strings.Fields(string(header))
		if len(fields) != 3 || fields[2] != "0" {
			return nil, errors.New("repository contains an unresolved index stage")
		}
		if fields[0] != "100644" && fields[0] != "100755" {
			return nil, errors.New("approved fixtures may contain only regular tracked files")
		}
		relative := string(rawPath)
		if err := validateTrackedPath(relative); err != nil {
			return nil, err
		}
		entries = append(entries, trackedEntry{mode: fields[0], objectID: fields[1], path: relative})
	}
	return entries, nil
}

func gitHeadEntries(ctx context.Context, options commonOptions) ([]trackedEntry, error) {
	command := managedGitCommand(ctx, options, "ls-tree", "-r", "-z", "--full-tree", "HEAD")
	output, err := command.Output()
	if err != nil {
		return nil, fmt.Errorf("read repository HEAD tree: %w", err)
	}
	entries := make([]trackedEntry, 0)
	for _, record := range bytes.Split(output, []byte{0}) {
		if len(record) == 0 {
			continue
		}
		header, rawPath, ok := bytes.Cut(record, []byte{'\t'})
		if !ok {
			return nil, errors.New("managed Git returned an invalid HEAD tree entry")
		}
		fields := strings.Fields(string(header))
		if len(fields) != 3 || fields[1] != "blob" {
			return nil, errors.New("approved fixtures may contain only regular tracked files")
		}
		if fields[0] != "100644" && fields[0] != "100755" {
			return nil, errors.New("approved fixtures may contain only regular tracked files")
		}
		relative := string(rawPath)
		if err := validateTrackedPath(relative); err != nil {
			return nil, err
		}
		entries = append(entries, trackedEntry{mode: fields[0], objectID: fields[2], path: relative})
	}
	return entries, nil
}

func equalTrackedEntries(left, right []trackedEntry) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func workingTreeHasExtraEntries(root string, tracked []trackedEntry) (bool, error) {
	trackedPaths := make(map[string]struct{}, len(tracked))
	for _, entry := range tracked {
		trackedPaths[entry.path] = struct{}{}
	}
	dirty := false
	err := filepath.WalkDir(root, func(path string, entry fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		relative, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		relative = filepath.ToSlash(relative)
		if relative == "." {
			return nil
		}
		if relative == ".git" {
			info, err := entry.Info()
			if err != nil {
				return err
			}
			if info.Mode()&os.ModeSymlink != 0 || (!info.IsDir() && !info.Mode().IsRegular()) {
				return errors.New("repository administrative path must not be a symlink or special file")
			}
			if info.IsDir() {
				return filepath.SkipDir
			}
			return nil
		}
		info, err := entry.Info()
		if err != nil {
			return err
		}
		if info.Mode()&os.ModeSymlink != 0 || (!info.IsDir() && !info.Mode().IsRegular()) {
			return errors.New("approved fixtures may not contain symlinks or special files")
		}
		if info.IsDir() {
			return nil
		}
		if _, ok := trackedPaths[relative]; !ok {
			dirty = true
		}
		return nil
	})
	return dirty, err
}

func normalizeRepositoryRoot(ctx context.Context, options *commonOptions) error {
	requestedRoot := options.root
	command := managedGitCommand(ctx, *options, "rev-parse", "--show-toplevel")
	output, err := command.Output()
	if err != nil {
		return fmt.Errorf("derive repository root: %w", err)
	}
	top, err := filepath.EvalSymlinks(strings.TrimSpace(string(output)))
	if err != nil {
		return err
	}
	allowed := filepath.SplitList(options.allowedRoots)
	for index, candidate := range allowed {
		if candidate == "." {
			// A relative allow entry means the caller's original directory. It
			// must never expand to a repository-controlled core.worktree value.
			allowed[index] = requestedRoot
		}
	}
	resolved, err := gateway.ResolveRoot(top, allowed)
	if err != nil {
		return err
	}
	if resolved != options.root {
		// stateDir currently ends in the identity of the working subdirectory.
		// Replace it atomically in memory before opening any state or backend files.
		stateBase := filepath.Dir(options.stateDir)
		options.root = resolved
		options.stateDir = filepath.Join(stateBase, repositoryIdentity(resolved))
	}
	stateBase, err := canonicalExternalBase(options.root, filepath.Dir(options.stateDir), "state")
	if err != nil {
		return err
	}
	options.stateDir = filepath.Join(stateBase, repositoryIdentity(options.root))
	for _, directory := range []*string{&options.cacheDir, &options.runtimeDir} {
		if *directory == "" {
			continue
		}
		canonical, err := canonicalExternalBase(options.root, *directory, "cache or runtime")
		if err != nil {
			return err
		}
		*directory = canonical
	}
	return nil
}

func generationCacheDir(stateDir, configuredBase, generation string) string {
	if configuredBase == "" {
		return filepath.Join(stateDir, "generations", generation, "cache")
	}
	return filepath.Join(configuredBase, sha256Text(stateDir)[:16], generation)
}

func generationRuntimeDir(stateDir, configuredBase, generation string) (string, error) {
	base := configuredBase
	if base == "" {
		if os.PathSeparator == '/' {
			// Native CBM uses Unix-domain sockets whose complete path is limited
			// on macOS. Keep only local IPC in this short, private path; graph
			// data and manifests remain in the persistent external state root.
			base = "/tmp/cgh"
		} else {
			base = filepath.Join(os.TempDir(), "cgh")
		}
	}
	runtimeID := sha256Text(stateDir + "\x00" + generation)[:20]
	path := filepath.Join(base, runtimeID)
	if os.PathSeparator == '/' {
		canonical := path
		if strings.HasPrefix(path, "/tmp/") {
			canonical = "/private" + path
		}
		if len(canonical) > 48 {
			return "", errors.New("runtime directory is too long for secure local IPC")
		}
	}
	return path, nil
}

func gitFileManifest(ctx context.Context, options commonOptions) (string, int, error) {
	entries, err := gitIndexEntries(ctx, options)
	if err != nil {
		return "", 0, err
	}
	manifestHash := sha256.New()
	for _, entry := range entries {
		fullPath := filepath.Join(options.root, filepath.FromSlash(entry.path))
		info, err := os.Lstat(fullPath)
		if err != nil {
			return "", 0, fmt.Errorf("inspect tracked fixture file: %w", err)
		}
		if !info.Mode().IsRegular() {
			return "", 0, errors.New("approved fixtures may not contain symlinks or special files")
		}
		contentHash, err := sha256File(fullPath)
		if err != nil {
			return "", 0, fmt.Errorf("hash tracked fixture file: %w", err)
		}
		_, _ = fmt.Fprintf(manifestHash, "%s\x00%s\x00%s\x00", entry.mode, entry.path, contentHash)
	}
	return hex.EncodeToString(manifestHash.Sum(nil)), len(entries), nil
}

type cbmStatus struct {
	Nodes        int    `json:"nodes"`
	Edges        int    `json:"edges"`
	Status       string `json:"status"`
	ParsePartial struct {
		Count     int  `json:"count"`
		Truncated bool `json:"truncated"`
	} `json:"parse_partial"`
	Skipped struct {
		Count     int  `json:"count"`
		Truncated bool `json:"truncated"`
	} `json:"skipped"`
	NotIndexed struct {
		Dirs       []string `json:"dirs"`
		DirsCount  int      `json:"dirs_count"`
		Files      []string `json:"files"`
		FilesCount int      `json:"files_count"`
		Truncated  bool     `json:"truncated"`
	} `json:"not_indexed"`
}

func cbmIndexCounts(ctx context.Context, options commonOptions, files int) (gateway.ManifestCounts, error) {
	command := exec.Command(options.cbmBinary, "cli", "index_status", "--project", cbmProjectName(options.root)) // #nosec G204 -- validated native binary and fixed command.
	command.Dir = options.root
	environment, err := gateway.BuildCBMEnvironment(options.root, options.cacheDir, options.runtimeDir, options.gitBinary)
	if err != nil {
		return gateway.ManifestCounts{}, err
	}
	command.Env = environment
	var output boundedBuffer
	output.limit = 1 << 20
	command.Stdout = &output
	command.Stderr = io.Discard
	if err := gateway.RunChildCommand(ctx, command); err != nil {
		return gateway.ManifestCounts{}, fmt.Errorf("read CBM index status: %w", err)
	}
	var status cbmStatus
	if err := json.Unmarshal(output.Bytes(), &status); err != nil {
		return gateway.ManifestCounts{}, fmt.Errorf("parse CBM index status: %w", err)
	}
	if status.Status != "ready" ||
		status.ParsePartial.Truncated || status.ParsePartial.Count != 0 ||
		status.Skipped.Truncated || status.Skipped.Count != 0 ||
		status.NotIndexed.Truncated || status.NotIndexed.FilesCount != 0 ||
		!onlyAdministrativeGitDirectory(status.NotIndexed.Dirs, status.NotIndexed.DirsCount) {
		return gateway.ManifestCounts{}, errors.New("CBM index status is not complete")
	}
	return gateway.ManifestCounts{Files: files, Nodes: status.Nodes, Edges: status.Edges, ParseFailures: status.ParsePartial.Count, SkippedFiles: status.Skipped.Count, UnsupportedLanguages: []string{}}, nil
}

type boundedBuffer struct {
	bytes.Buffer
	limit int
}

func (buffer *boundedBuffer) Write(payload []byte) (int, error) {
	if buffer.Len()+len(payload) > buffer.limit {
		return 0, errors.New("CBM output exceeded the administrative limit")
	}
	return buffer.Buffer.Write(payload)
}

func onlyAdministrativeGitDirectory(directories []string, count int) bool {
	if count != len(directories) {
		return false
	}
	for _, directory := range directories {
		if filepath.ToSlash(filepath.Clean(directory)) != ".git" {
			return false
		}
	}
	return true
}

func systemPath() string {
	if systemRoot := os.Getenv("SystemRoot"); systemRoot != "" {
		return filepath.Join(systemRoot, "System32")
	}
	return "/usr/bin:/bin"
}
