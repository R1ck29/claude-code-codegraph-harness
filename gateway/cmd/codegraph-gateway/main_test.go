package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestIndexBuildAndStatusWithFakeNativeBackend(t *testing.T) {
	root := t.TempDir()
	git(t, root, "init")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "Codegraph Test")
	if err := os.WriteFile(filepath.Join(root, "README.md"), []byte("fixture\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	git(t, root, "add", "README.md")
	git(t, root, "commit", "-m", "fixture")
	fake := filepath.Join(t.TempDir(), "fake-cbm")
	if err := os.WriteFile(fake, []byte("#!/bin/sh\nif [ \"$1\" = \"cli\" ] && [ \"$2\" = \"index_status\" ]; then printf '%s\\n' '{\"nodes\":1,\"edges\":0,\"status\":\"ready\",\"parse_partial\":{\"count\":0,\"truncated\":false},\"skipped\":{\"count\":0,\"truncated\":false},\"not_indexed\":{\"dirs_count\":0,\"files_count\":0,\"truncated\":false}}'; fi\nexit 0\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	writeTestConfig(t, fake)
	hash, err := sha256File(fake)
	if err != nil {
		t.Fatal(err)
	}
	state := t.TempDir()
	gitBinary, gitHash := managedGit(t)
	approveFixture(t, root, gitBinary)
	arguments := argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "build")
	if err := run(context.Background(), arguments); err != nil {
		t.Fatalf("index build: %v", err)
	}
	canonicalRoot, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	stateDir := filepath.Join(state, repositoryIdentity(canonicalRoot))
	generation, err := os.ReadFile(filepath.Join(stateDir, "current"))
	if err != nil {
		t.Fatalf("current generation pointer missing: %v", err)
	}
	if _, err := os.Stat(filepath.Join(stateDir, "generations", string(generation), "index-manifest.json")); err != nil {
		t.Fatalf("manifest was not created: %v", err)
	}
	if _, err := os.Stat(filepath.Join(root, ".codegraph-state")); !os.IsNotExist(err) {
		t.Fatalf("repository must not receive gateway state, stat error = %v", err)
	}
	arguments[1] = "status"
	if err := run(context.Background(), arguments); err != nil {
		t.Fatalf("index status: %v", err)
	}
}

func TestManagedGitIgnoresAttackerControlledPATH(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	marker := filepath.Join(t.TempDir(), "attacker-was-run")
	attackerDir := t.TempDir()
	attacker := filepath.Join(attackerDir, "git")
	if err := os.WriteFile(attacker, []byte("#!/bin/sh\ntouch '"+marker+"'\nexit 1\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", attackerDir)
	if err := run(context.Background(), argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "status")); err != nil {
		t.Fatalf("managed git should work despite attacker PATH: %v", err)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("attacker git was executed: %v", err)
	}
}

func TestRepositoryLocalFsmonitorIsNeverExecuted(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	marker := filepath.Join(t.TempDir(), "repository-fsmonitor-was-run")
	hook := filepath.Join(t.TempDir(), "malicious-fsmonitor")
	if err := os.WriteFile(hook, []byte("#!/bin/sh\ntouch '"+marker+"'\nexit 0\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	git(t, root, "config", "core.fsmonitor", hook)
	if err := run(context.Background(), argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "status")); err != nil {
		t.Fatalf("index status with repository-local fsmonitor config: %v", err)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("repository-local fsmonitor was executed: %v", err)
	}
}

func TestRepositoryLocalCleanFilterIsNeverExecuted(t *testing.T) {
	root := t.TempDir()
	git(t, root, "init")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "Codegraph Test")
	if err := os.WriteFile(filepath.Join(root, ".gitattributes"), []byte("*.txt filter=reviewfilter\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "fixture.txt"), []byte("public fixture\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	git(t, root, "add", ".gitattributes", "fixture.txt")
	git(t, root, "commit", "-m", "fixture")
	marker := filepath.Join(t.TempDir(), "repository-filter-was-run")
	filter := filepath.Join(t.TempDir(), "malicious-filter")
	if err := os.WriteFile(filter, []byte("#!/bin/sh\ntouch '"+marker+"'\ncat\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	git(t, root, "config", "filter.reviewfilter.clean", filter)
	gitBinary, gitHash := managedGit(t)
	var output bytes.Buffer
	if err := fixture(context.Background(), []string{
		"fingerprint", "--root", root, "--allowed-root", root, "--state-dir", t.TempDir(), "--git-binary", gitBinary, "--git-sha256", gitHash,
	}, &output); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(marker); !os.IsNotExist(err) {
		t.Fatalf("repository-local clean filter was executed: %v", err)
	}
}

func TestRepositoryLocalCoreWorktreeCannotEscapeAllowedRoot(t *testing.T) {
	root := t.TempDir()
	outside := t.TempDir()
	git(t, root, "init")
	git(t, root, "config", "core.worktree", outside)
	gitBinary, gitHash := managedGit(t)
	var output bytes.Buffer
	err := fixture(context.Background(), []string{
		"fingerprint", "--root", root, "--allowed-root", ".", "--state-dir", t.TempDir(), "--git-binary", gitBinary, "--git-sha256", gitHash,
	}, &output)
	if err == nil || !strings.Contains(err.Error(), "allowed root") {
		t.Fatalf("external core.worktree error = %v; want allowed-root rejection", err)
	}
}

func TestIgnoredFilesInvalidateAnApprovedFixture(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	exclude := filepath.Join(root, ".git", "info", "exclude")
	file, err := os.OpenFile(exclude, os.O_APPEND|os.O_WRONLY, 0o600)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := file.WriteString("\nsecret.bin\n"); err != nil {
		_ = file.Close()
		t.Fatal(err)
	}
	if err := file.Close(); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, "secret.bin"), []byte("company data"), 0o600); err != nil {
		t.Fatal(err)
	}
	err = run(context.Background(), argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "status"))
	if err == nil || !strings.Contains(err.Error(), "changed since indexing") {
		t.Fatalf("ignored file error = %v; want stale fixture rejection", err)
	}
}

func TestTrackedFileChangesInvalidateAnApprovedFixture(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	if err := os.WriteFile(filepath.Join(root, "README.md"), []byte("changed\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := run(context.Background(), argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "status"))
	if err == nil || !strings.Contains(err.Error(), "approved public fixture") {
		t.Fatalf("tracked file error = %v; want manifest rejection", err)
	}
}

func TestConfigurationHashIsVerifiedFromTheActualFile(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	if err := os.WriteFile(fake+".config", []byte("tampered\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	err := run(context.Background(), argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "status"))
	if err == nil || !strings.Contains(err.Error(), "configuration SHA-256") {
		t.Fatalf("tampered configuration error = %v; want hash rejection", err)
	}
}

func TestBackendIdentityRejectsSymlinksAndPinsTheCanonicalFile(t *testing.T) {
	directory := t.TempDir()
	backend := filepath.Join(directory, "backend")
	if err := os.WriteFile(backend, []byte("approved backend"), 0o700); err != nil {
		t.Fatal(err)
	}
	hash, err := sha256File(backend)
	if err != nil {
		t.Fatal(err)
	}
	linked := filepath.Join(directory, "backend-link")
	if err := os.Symlink(backend, linked); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	options := commonOptions{cbmBinary: linked, backendSHA: hash}
	if err := validateBackend(&options); err == nil || !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("symlinked backend error = %v; want symlink rejection", err)
	}
	options = commonOptions{cbmBinary: backend, backendSHA: hash}
	if err := validateBackend(&options); err != nil {
		t.Fatal(err)
	}
	canonical, err := filepath.EvalSymlinks(backend)
	if err != nil {
		t.Fatal(err)
	}
	if options.cbmBinary != canonical || options.backendSHA != hash {
		t.Fatalf("backend identity was not canonicalized: %#v", options)
	}
}

func TestNestedWorkingDirectoryUsesManagedGitTopLevel(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	nested := filepath.Join(root, "nested", "work")
	if err := os.MkdirAll(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	arguments := argumentsFor(nested, state, fake, hash, gitBinary, gitHash, "index", "status")
	for index, value := range arguments {
		if value == "--allowed-root" {
			arguments[index+1] = root
			break
		}
	}
	if err := run(context.Background(), arguments); err != nil {
		t.Fatalf("nested root status: %v", err)
	}
	canonical, err := filepath.EvalSymlinks(root)
	if err != nil {
		t.Fatal(err)
	}
	stateDir := filepath.Join(state, repositoryIdentity(canonical))
	generation, err := os.ReadFile(filepath.Join(stateDir, "current"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(stateDir, "generations", string(generation), "index-manifest.json")); err != nil {
		t.Fatalf("top-level identity state missing: %v", err)
	}
}

func TestNestedWorkingDirectoryRejectsStateInsideGitTopLevel(t *testing.T) {
	root := t.TempDir()
	git(t, root, "init")
	nested := filepath.Join(root, "nested", "work")
	if err := os.MkdirAll(nested, 0o700); err != nil {
		t.Fatal(err)
	}
	gitBinary, gitHash := managedGit(t)
	backendHash, err := sha256File(os.Args[0])
	if err != nil {
		t.Fatal(err)
	}
	arguments := argumentsFor(nested, filepath.Join(root, ".codegraph-state"), os.Args[0], backendHash, gitBinary, gitHash, "index", "status")
	for index, value := range arguments {
		if value == "--allowed-root" {
			arguments[index+1] = root
			break
		}
	}
	err = run(context.Background(), arguments)
	if err == nil || !strings.Contains(err.Error(), "outside the repository") {
		t.Fatalf("nested repository state error = %v; want outside-repository rejection", err)
	}
}

func TestResolveOptionsRejectsSymlinkedExternalState(t *testing.T) {
	root := t.TempDir()
	target := t.TempDir()
	linked := filepath.Join(t.TempDir(), "linked-state")
	if err := os.Symlink(target, linked); err != nil {
		t.Skipf("symlink unavailable: %v", err)
	}
	_, err := resolveOptions(commonOptions{root: root, allowedRoots: root, stateDir: linked})
	if err == nil || !strings.Contains(err.Error(), "symlink") {
		t.Fatalf("symlinked state error = %v; want symlink rejection", err)
	}
}

func TestRunRejectsUnknownCommandAndUnapprovedRoot(t *testing.T) {
	if err := run(context.Background(), []string{"unknown"}); err == nil {
		t.Fatal("unknown command was accepted")
	}
	if _, err := resolveOptions(commonOptions{root: t.TempDir(), allowedRoots: t.TempDir()}); err == nil || !strings.Contains(err.Error(), "allowed root") {
		t.Fatalf("resolveOptions() error = %v; want allowed-root rejection", err)
	}
}

func TestCompanySourceCannotBeEnabledByRuntimeFlags(t *testing.T) {
	err := requirePublicFixture(commonOptions{classification: "company-source"})
	if err == nil || !strings.Contains(err.Error(), "disabled") {
		t.Fatalf("company-source error = %v; want unconditional rejection", err)
	}
}

func TestPublicFixtureRequiresACompileTimeApprovedManifest(t *testing.T) {
	previous := allowedFixtureManifests
	t.Cleanup(func() { allowedFixtureManifests = previous })
	allowedFixtureManifests = ""
	if err := requireApprovedFixture(strings.Repeat("a", 64)); err == nil {
		t.Fatal("binary without an approved fixture manifest was accepted")
	}
	allowedFixtureManifests = fixtureReleaseRecord(strings.Repeat("a", 64), strings.Repeat("b", 64))
	if err := requireApprovedFixture(strings.Repeat("a", 64)); err != nil {
		t.Fatalf("approved fixture was rejected: %v", err)
	}
	if err := requireApprovedFixture(strings.Repeat("c", 64)); err == nil {
		t.Fatal("unapproved fixture was accepted")
	}
}

func TestFixtureFingerprintCanBeComputedWithoutEnablingIt(t *testing.T) {
	root := t.TempDir()
	git(t, root, "init")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "Codegraph Test")
	if err := os.WriteFile(filepath.Join(root, "fixture.txt"), []byte("public\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	git(t, root, "add", "fixture.txt")
	git(t, root, "commit", "-m", "fixture")
	gitBinary, gitHash := managedGit(t)
	var output bytes.Buffer
	err := fixture(context.Background(), []string{
		"fingerprint", "--root", root, "--allowed-root", root, "--state-dir", t.TempDir(), "--git-binary", gitBinary, "--git-sha256", gitHash,
	}, &output)
	if err != nil {
		t.Fatal(err)
	}
	var result struct {
		Manifest string `json:"file_manifest_sha256"`
		Files    int    `json:"files"`
	}
	if err := json.Unmarshal(output.Bytes(), &result); err != nil {
		t.Fatal(err)
	}
	if len(result.Manifest) != 64 || result.Files != 1 {
		t.Fatalf("fixture fingerprint result = %#v", result)
	}
	previous := allowedFixtureManifests
	t.Cleanup(func() { allowedFixtureManifests = previous })
	allowedFixtureManifests = ""
	if err := requireApprovedFixture(result.Manifest); err == nil {
		t.Fatal("computing a fingerprint unexpectedly enabled the fixture")
	}
}

func TestIndexLockIsExclusiveAndAutomaticallyRecoverable(t *testing.T) {
	state := t.TempDir()
	first, err := acquireIndexLock(state)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := acquireIndexLock(state); err == nil {
		t.Fatal("a concurrent index build acquired the same state lock")
	}
	if err := first.Close(); err != nil {
		t.Fatal(err)
	}
	recovered, err := acquireIndexLock(state)
	if err != nil {
		t.Fatalf("released index lock did not recover: %v", err)
	}
	if err := recovered.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestIndexRejectsPrivateRootMislabeledAsPublicFixture(t *testing.T) {
	root := t.TempDir()
	git(t, root, "init")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "Codegraph Test")
	if err := os.WriteFile(filepath.Join(root, "private.txt"), []byte("not an approved fixture\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	git(t, root, "add", "private.txt")
	git(t, root, "commit", "-m", "private")
	fake := filepath.Join(t.TempDir(), "fake-cbm")
	if err := os.WriteFile(fake, []byte("#!/bin/sh\nexit 0\n"), 0o700); err != nil {
		t.Fatal(err)
	}
	writeTestConfig(t, fake)
	backendHash, err := sha256File(fake)
	if err != nil {
		t.Fatal(err)
	}
	gitBinary, gitHash := managedGit(t)
	previous := allowedFixtureManifests
	t.Cleanup(func() { allowedFixtureManifests = previous })
	allowedFixtureManifests = fixtureReleaseRecord(strings.Repeat("0", 64))
	err = run(context.Background(), argumentsFor(root, t.TempDir(), fake, backendHash, gitBinary, gitHash, "index", "build"))
	if err == nil || !strings.Contains(err.Error(), "approved public fixture") {
		t.Fatalf("mislabeled private root error = %v; want approved-fixture rejection", err)
	}
}

func TestGenerationRuntimeDirectoryIsShortAndGenerationIsolated(t *testing.T) {
	first, err := generationRuntimeDir("/a/very/long/external/state/root", "", "generation-one")
	if err != nil {
		t.Fatal(err)
	}
	second, err := generationRuntimeDir("/a/very/long/external/state/root", "", "generation-two")
	if err != nil {
		t.Fatal(err)
	}
	if first == second {
		t.Fatal("distinct generations shared one runtime directory")
	}
	if os.PathSeparator == '/' && (len(first) > 40 || !strings.HasPrefix(first, "/tmp/cgh/")) {
		t.Fatalf("Unix runtime path is not short and private: %q", first)
	}
	if repositoryContains("/a/very/long/external/state/root", first) {
		t.Fatalf("runtime path must be outside persistent state: %q", first)
	}
}

func TestIndexCompletenessAllowsOnlyAdministrativeGitDirectory(t *testing.T) {
	for _, test := range []struct {
		directories []string
		count       int
		want        bool
	}{
		{directories: nil, count: 0, want: true},
		{directories: []string{".git"}, count: 1, want: true},
		{directories: []string{".git", "vendor"}, count: 2, want: false},
		{directories: []string{".git"}, count: 2, want: false},
	} {
		if got := onlyAdministrativeGitDirectory(test.directories, test.count); got != test.want {
			t.Fatalf("onlyAdministrativeGitDirectory(%v, %d) = %t; want %t", test.directories, test.count, got, test.want)
		}
	}
}

func TestServeUsesOnlyGatewayMCPProtocol(t *testing.T) {
	root, state, fake, hash, gitBinary, gitHash := preparedIndex(t)
	inputRead, inputWrite, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	outputRead, outputWrite, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	oldInput, oldOutput := os.Stdin, os.Stdout
	os.Stdin, os.Stdout = inputRead, outputWrite
	t.Cleanup(func() { os.Stdin, os.Stdout = oldInput, oldOutput })
	_, _ = io.WriteString(inputWrite, "{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{}}\n")
	_ = inputWrite.Close()
	arguments := argumentsFor(root, state, fake, hash, gitBinary, gitHash, "serve")
	if err := run(context.Background(), arguments); err != nil {
		t.Fatalf("serve: %v", err)
	}
	_ = outputWrite.Close()
	payload, err := io.ReadAll(outputRead)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(payload), "codegraph-gateway") || strings.Contains(string(payload), "fake-cbm") {
		t.Fatalf("unexpected MCP stdout: %s", payload)
	}
}

func preparedIndex(t *testing.T) (string, string, string, string, string, string) {
	t.Helper()
	root := t.TempDir()
	git(t, root, "init")
	git(t, root, "config", "user.email", "test@example.invalid")
	git(t, root, "config", "user.name", "Codegraph Test")
	if err := os.WriteFile(filepath.Join(root, "README.md"), []byte("fixture\n"), 0o600); err != nil {
		t.Fatal(err)
	}
	git(t, root, "add", "README.md")
	git(t, root, "commit", "-m", "fixture")
	fake := filepath.Join(t.TempDir(), "fake-cbm")
	const source = "#!/bin/sh\n" +
		"if [ \"$1\" = \"cli\" ] && [ \"$2\" = \"index_status\" ]; then printf '%s\\n' '{\"nodes\":1,\"edges\":0,\"status\":\"ready\",\"parse_partial\":{\"count\":0,\"truncated\":false},\"skipped\":{\"count\":0,\"truncated\":false},\"not_indexed\":{\"dirs_count\":0,\"files_count\":0,\"truncated\":false}}'; exit 0; fi\n" +
		"if [ \"$1\" = \"--tool-profile=analysis\" ]; then\n" +
		"  while IFS= read -r line; do\n" +
		"    case \"$line\" in\n" +
		"      *\"\\\"initialize\\\"\"*) printf '%s\\n' '{\"jsonrpc\":\"2.0\",\"id\":1,\"result\":{}}' ;;\n" +
		"    esac\n" +
		"  done\n" +
		"fi\nexit 0\n"
	if err := os.WriteFile(fake, []byte(source), 0o700); err != nil {
		t.Fatal(err)
	}
	writeTestConfig(t, fake)
	hash, err := sha256File(fake)
	if err != nil {
		t.Fatal(err)
	}
	state := t.TempDir()
	gitBinary, gitHash := managedGit(t)
	approveFixture(t, root, gitBinary)
	arguments := argumentsFor(root, state, fake, hash, gitBinary, gitHash, "index", "build")
	if err := run(context.Background(), arguments); err != nil {
		t.Fatalf("index build: %v", err)
	}
	return root, state, fake, hash, gitBinary, gitHash
}

func argumentsFor(root, state, cbm, cbmHash, gitBinary, gitHash string, prefix ...string) []string {
	arguments := append([]string{}, prefix...)
	return append(arguments, "--root", root, "--allowed-root", root, "--state-dir", state, "--cbm-binary", cbm, "--backend-sha256", cbmHash, "--config", cbm+".config", "--config-sha256", sha256Text("test-config\n"), "--git-binary", gitBinary, "--git-sha256", gitHash)
}

func writeTestConfig(t *testing.T, cbm string) {
	t.Helper()
	if err := os.WriteFile(cbm+".config", []byte("test-config\n"), 0o600); err != nil {
		t.Fatal(err)
	}
}

func managedGit(t *testing.T) (string, string) {
	t.Helper()
	path, err := exec.LookPath("git")
	if err != nil {
		t.Fatal(err)
	}
	path, err = filepath.EvalSymlinks(path)
	if err != nil {
		t.Fatal(err)
	}
	hash, err := sha256File(path)
	if err != nil {
		t.Fatal(err)
	}
	return path, hash
}

func approveFixture(t *testing.T, root, gitBinary string) {
	t.Helper()
	manifest, _, err := gitFileManifest(context.Background(), commonOptions{root: root, gitBinary: gitBinary})
	if err != nil {
		t.Fatal(err)
	}
	previous := allowedFixtureManifests
	allowedFixtureManifests = fixtureReleaseRecord(manifest)
	t.Cleanup(func() { allowedFixtureManifests = previous })
}

func git(t *testing.T, root string, arguments ...string) {
	t.Helper()
	command := exec.Command("git", append([]string{"-C", root}, arguments...)...)
	if output, err := command.CombinedOutput(); err != nil {
		t.Fatalf("git %v: %v: %s", arguments, err, output)
	}
}
