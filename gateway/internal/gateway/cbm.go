package gateway

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
)

// CBMBackend is an adapter for the native, pinned Codebase-Memory v0.10.8
// executable. It uses only stdio and never invokes a shell. The request
// parameter mappings are intentionally centralized here because upstream's
// private tool schemas still need a release-pinned integration fixture before
// production enablement.
type CBMBackend struct {
	command  *exec.Cmd
	input    io.WriteCloser
	output   *bufio.Reader
	project  string
	mu       sync.Mutex
	process  childProcessController
	close    sync.Once
	closeErr error
}

type CBMOptions struct {
	Binary      string
	GitBinary   string
	WorkingDir  string
	AllowedRoot string
	CacheDir    string
	RuntimeDir  string
	Project     string
	// Arguments exists for hermetic adapter tests. Production leaves it empty,
	// which always starts the fixed restricted analysis profile.
	Arguments []string
}

func StartCBM(options CBMOptions) (*CBMBackend, error) {
	for _, field := range []struct{ name, value string }{
		{"binary", options.Binary}, {"working directory", options.WorkingDir}, {"allowed root", options.AllowedRoot},
		{"managed Git binary", options.GitBinary},
	} {
		if strings.TrimSpace(field.value) == "" {
			return nil, fmt.Errorf("CBM %s is required", field.name)
		}
	}
	binary, err := filepath.Abs(options.Binary)
	if err != nil {
		return nil, err
	}
	if options.Project == "" {
		options.Project = cbmProjectName(options.AllowedRoot)
	}
	env, err := BuildCBMEnvironment(options.AllowedRoot, options.CacheDir, options.RuntimeDir, options.GitBinary)
	if err != nil {
		return nil, err
	}
	arguments := options.Arguments
	if len(arguments) == 0 {
		arguments = []string{"--tool-profile=analysis"}
	}
	command := exec.Command(binary, arguments...) // #nosec G204 -- pinned local binary, no shell.
	command.Dir = options.WorkingDir
	command.Env = env
	input, err := command.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("CBM stdin: %w", err)
	}
	output, err := command.StdoutPipe()
	if err != nil {
		return nil, fmt.Errorf("CBM stdout: %w", err)
	}
	// Vendor diagnostics are discarded so source-derived paths or snippets
	// cannot enter Claude Code or Codex diagnostic collection. Gateway errors
	// remain fixed and source-free.
	command.Stderr = io.Discard
	controller, err := startChildProcess(command)
	if err != nil {
		return nil, fmt.Errorf("start CBM: %w", err)
	}
	backend := &CBMBackend{command: command, input: input, output: bufio.NewReaderSize(output, 1<<20), project: options.Project, process: controller}
	if err := backend.initialize(); err != nil {
		backend.Close()
		return nil, err
	}
	return backend, nil
}

// BuildCBMEnvironment returns the complete environment for every native CBM
// invocation, including administrative config/index/status commands. It never
// inherits the caller's real user profile, proxy credentials, Git settings, or
// package-manager configuration.
func BuildCBMEnvironment(allowedRoot, cacheDir, runtimeDir, gitBinary string) ([]string, error) {
	for _, field := range []struct{ name, value string }{
		{"allowed root", allowedRoot}, {"cache directory", cacheDir}, {"runtime directory", runtimeDir}, {"managed Git binary", gitBinary},
	} {
		if strings.TrimSpace(field.value) == "" {
			return nil, fmt.Errorf("CBM %s is required", field.name)
		}
	}
	for _, directory := range []string{cacheDir, runtimeDir} {
		if err := os.MkdirAll(directory, 0o700); err != nil {
			return nil, fmt.Errorf("create CBM private directory: %w", err)
		}
	}
	if !filepath.IsAbs(gitBinary) {
		return nil, fmt.Errorf("CBM managed Git binary must be absolute")
	}
	privateHome := filepath.Join(cacheDir, "home")
	localAppData := filepath.Join(privateHome, "AppData", "Local")
	for _, directory := range []string{
		privateHome,
		filepath.Join(privateHome, "AppData", "Roaming"),
		localAppData,
		filepath.Join(localAppData, "Temp"),
	} {
		if err := os.MkdirAll(directory, 0o700); err != nil {
			return nil, fmt.Errorf("create private CBM home: %w", err)
		}
	}
	privateGitConfig := filepath.Join(privateHome, "gitconfig")
	if err := os.WriteFile(privateGitConfig, nil, 0o600); err != nil {
		return nil, fmt.Errorf("create private CBM Git config: %w", err)
	}
	return []string{
		"CBM_ALLOWED_ROOT=" + allowedRoot,
		"CBM_CACHE_DIR=" + cacheDir,
		"CBM_RUNTIME_DIR=" + runtimeDir,
		"CBM_LOG_LEVEL=error",
		"PATH=" + managedToolPath(gitBinary),
		"LANG=C",
		"LC_ALL=C",
		"GIT_CONFIG_NOSYSTEM=1",
		"GIT_CONFIG_GLOBAL=" + privateGitConfig,
		"GIT_TERMINAL_PROMPT=0",
		"GCM_INTERACTIVE=never",
		"GIT_CEILING_DIRECTORIES=" + filepath.Dir(allowedRoot),
		"HOME=" + privateHome,
		"USERPROFILE=" + privateHome,
		"APPDATA=" + filepath.Join(privateHome, "AppData", "Roaming"),
		"LOCALAPPDATA=" + localAppData,
		"TEMP=" + filepath.Join(localAppData, "Temp"),
		"TMP=" + filepath.Join(localAppData, "Temp"),
	}, nil
}

func managedToolPath(gitBinary string) string {
	return filepath.Dir(gitBinary) + string(os.PathListSeparator) + minimalPath()
}

func minimalPath() string {
	if path := os.Getenv("SystemRoot"); path != "" { // Windows processes need system executables only.
		return filepath.Join(path, "System32")
	}
	return "/usr/bin:/bin"
}

func (b *CBMBackend) initialize() error {
	_, err := b.rpc(context.Background(), "initialize", map[string]any{
		"protocolVersion": "2025-06-18",
		"capabilities":    map[string]any{},
		"clientInfo":      map[string]string{"name": "codegraph-gateway", "version": Version},
	})
	if err != nil {
		return err
	}
	return b.notify("notifications/initialized", map[string]any{})
}

func (b *CBMBackend) notify(method string, params map[string]any) error {
	b.mu.Lock()
	defer b.mu.Unlock()
	payload, err := json.Marshal(map[string]any{"jsonrpc": "2.0", "method": method, "params": params})
	if err != nil {
		return err
	}
	if _, err := b.input.Write(append(payload, '\n')); err != nil {
		return fmt.Errorf("write CBM notification: %w", err)
	}
	return nil
}

func (b *CBMBackend) Call(ctx context.Context, request BackendRequest) (BackendResponse, error) {
	tool, arguments, err := cbmToolRequest(request, b.project)
	if err != nil {
		return BackendResponse{}, err
	}
	result, err := b.rpc(ctx, "tools/call", map[string]any{"name": tool, "arguments": arguments})
	if err != nil {
		return BackendResponse{}, err
	}
	response := parseCBMResponse(result)
	normalizeCBMResponse(&response, b.project)
	if len(response.Results) == 0 && response.Summary == "" {
		return BackendResponse{}, fmt.Errorf("CBM response did not match a pinned safe tool contract")
	}
	return response, nil
}

func cbmToolRequest(request BackendRequest, project string) (string, map[string]any, error) {
	arguments := make(map[string]any, len(request.Arguments)+4)
	for key, value := range request.Arguments {
		arguments[key] = value
	}
	arguments["project"] = project
	// CONFIRMED by v0.10.8 CLI help: these tool names and required project,
	// query/function_name fields are accepted by the native analysis profile.
	// The exact JSON response remains isolated in parseCBMResponse until a
	// release-pinned public-fixture MCP transcript is added.
	switch request.Operation {
	case "search_graph":
		arguments["format"] = "json"
		return "search_graph", arguments, nil
	case "get_architecture":
		delete(arguments, "topic")
		arguments["aspects"] = []string{"overview"}
		return "get_architecture", arguments, nil
	case "trace_path":
		arguments["function_name"] = qualifiedCBMSymbol(arguments["symbol"], project)
		delete(arguments, "symbol")
		arguments["direction"] = "both"
		arguments["format"] = "json"
		return "trace_path", arguments, nil
	case "impact":
		// CBM exposes bounded path tracing rather than a separate stable impact
		// operation. This hides that implementation detail from the AI client.
		arguments["function_name"] = qualifiedCBMSymbol(arguments["target"], project)
		delete(arguments, "target")
		arguments["direction"] = "both"
		arguments["format"] = "json"
		return "trace_path", arguments, nil
	default:
		return "", nil, fmt.Errorf("unsupported backend operation")
	}
}

func qualifiedCBMSymbol(value any, project string) any {
	symbol, ok := value.(string)
	if !ok || strings.HasPrefix(symbol, project+".") || strings.HasPrefix(symbol, "builtins.") {
		return value
	}
	return project + "." + strings.TrimPrefix(symbol, ".")
}

func cbmProjectName(root string) string {
	clean := filepath.ToSlash(filepath.Clean(root))
	return strings.Trim(strings.ReplaceAll(clean, "/", "-"), "-")
}

func (b *CBMBackend) rpc(ctx context.Context, method string, params map[string]any) (map[string]any, error) {
	b.mu.Lock()
	defer b.mu.Unlock()
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}
	request := map[string]any{"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
	payload, err := json.Marshal(request)
	if err != nil {
		return nil, err
	}
	if _, err := b.input.Write(append(payload, '\n')); err != nil {
		return nil, fmt.Errorf("write CBM request: %w", err)
	}
	type readResult struct {
		line []byte
		err  error
	}
	read := make(chan readResult, 1)
	go func() {
		line, readErr := b.output.ReadSlice('\n')
		read <- readResult{line: append([]byte(nil), line...), err: readErr}
	}()
	var line []byte
	select {
	case result := <-read:
		if result.err != nil {
			return nil, fmt.Errorf("read CBM response: %w", result.err)
		}
		line = result.line
	case <-ctx.Done():
		_ = b.Close()
		return nil, ctx.Err()
	}
	var response struct {
		ID     any            `json:"id"`
		Result map[string]any `json:"result"`
		Error  *RPCError      `json:"error"`
	}
	if err := json.Unmarshal(line, &response); err != nil {
		return nil, fmt.Errorf("parse CBM response: %w", err)
	}
	if fmt.Sprint(response.ID) != "1" {
		return nil, fmt.Errorf("CBM response id did not match request")
	}
	if response.Error != nil {
		return nil, fmt.Errorf("CBM rejected request: %s", response.Error.Message)
	}
	return response.Result, nil
}

func parseCBMResponse(result map[string]any) BackendResponse {
	response := BackendResponse{}
	if structured, ok := result["structuredContent"].(map[string]any); ok {
		response.Results = append(response.Results, parseCBMStructuredRows(structured)...)
		if len(response.Results) == 0 {
			response.Results = append(response.Results, parseCBMFlatSearchRows(structured)...)
		}
		if len(response.Results) == 0 {
			response.Results = append(response.Results, parseCBMTraceRows(structured)...)
		}
		if len(response.Results) == 0 {
			response.Results, response.Summary = parseCBMArchitecture(structured)
		}
		response.Truncated = booleanField(structured, "has_more") || booleanField(structured, "truncated")
	}
	if len(response.Results) == 0 {
		response.Results, response.Summary = parseCBMArchitectureText(result)
	}
	if len(response.Results) != 0 {
		response.Summary = fmt.Sprintf("%d Codebase-Memory graph result(s)", len(response.Results))
	}
	return response
}

func normalizeCBMResponse(response *BackendResponse, project string) {
	prefix := project + "."
	for index := range response.Results {
		response.Results[index].Evidence = strings.TrimPrefix(response.Results[index].Evidence, prefix)
	}
}

func booleanField(value map[string]any, name string) bool {
	result, _ := value[name].(bool)
	return result
}

func parseCBMArchitecture(content map[string]any) ([]Result, string) {
	languages, ok := stringSlice(content["languages"])
	if !ok {
		return nil, ""
	}
	if len(languages) > 10 {
		languages = languages[:10]
	}
	results := make([]Result, 0, len(languages))
	for _, language := range languages {
		if language = safeIdentifier(language, 64); language != "" {
			results = append(results, Result{Relation: "ARCHITECTURE", Evidence: "language." + language})
		}
	}
	return results, "local architecture overview"
}

var architectureCount = regexp.MustCompile(`(?m)^total_(nodes|edges): ([0-9]+)$`)
var architectureLanguage = regexp.MustCompile(`(?m)^  ([A-Za-z0-9_+-]+) [0-9]+$`)
var architectureEntrypoint = regexp.MustCompile(`^  ([A-Za-z0-9_.-]+) ([^\s]+)$`)

func parseCBMArchitectureText(result map[string]any) ([]Result, string) {
	content, ok := result["content"].([]any)
	if !ok {
		return nil, ""
	}
	var text string
	for _, item := range content {
		if entry, ok := item.(map[string]any); ok {
			if kind, _ := entry["type"].(string); kind == "text" {
				text, _ = entry["text"].(string)
				break
			}
		}
	}
	if text == "" || !strings.Contains(text, "total_nodes:") {
		return nil, ""
	}
	counts := architectureCount.FindAllStringSubmatch(text, -1)
	if len(counts) == 0 {
		return nil, ""
	}
	nodes, edges := "", ""
	for _, count := range counts {
		if count[1] == "nodes" {
			nodes = count[2]
		} else {
			edges = count[2]
		}
	}
	results := make([]Result, 0, 12)
	if nodes != "" {
		results = append(results, Result{Relation: "ARCHITECTURE", Evidence: "metric.nodes." + nodes})
	}
	if edges != "" {
		results = append(results, Result{Relation: "ARCHITECTURE", Evidence: "metric.edges." + edges})
	}
	lines := strings.Split(text, "\n")
	inLanguages, inEntrypoints := false, false
	for _, line := range lines {
		if strings.HasPrefix(line, "languages:") {
			inLanguages = true
			inEntrypoints = false
			continue
		}
		if strings.HasPrefix(line, "entry_points:") {
			inLanguages = false
			inEntrypoints = true
			continue
		}
		if line != "" && !strings.HasPrefix(line, "  ") {
			inLanguages = false
			inEntrypoints = false
		}
		if inLanguages {
			if match := architectureLanguage.FindStringSubmatch(line); len(match) != 0 {
				results = append(results, Result{Relation: "ARCHITECTURE", Evidence: "language." + match[1]})
			}
		}
		if inEntrypoints {
			if match := architectureEntrypoint.FindStringSubmatch(line); len(match) != 0 {
				results = append(results, Result{Path: match[2], Relation: "ARCHITECTURE", Evidence: match[1]})
			}
		}
	}
	return results, "local architecture overview"
}

// parseCBMTraceRows implements the observed v0.10.8 trace_path contract.
// trace responses do not provide file locations, so they retain only a
// qualified-name evidence record and resolver confidence, never code text.
func parseCBMTraceRows(content map[string]any) []Result {
	var results []Result
	for _, side := range []string{"callers", "callees"} {
		section, ok := content[side].(map[string]any)
		if !ok {
			continue
		}
		columns, ok := stringSlice(section["cols"])
		if !ok {
			continue
		}
		nameIndex := indexOf(columns, "name")
		if nameIndex < 0 {
			continue
		}
		groups, ok := section["groups"].([]any)
		if !ok {
			continue
		}
		for _, item := range groups {
			group, ok := item.(map[string]any)
			if !ok {
				continue
			}
			prefix, _ := group["qn_prefix"].(string)
			rows, ok := group["rows"].([]any)
			if !ok {
				continue
			}
			for _, item := range rows {
				row, ok := item.([]any)
				if !ok || nameIndex >= len(row) {
					continue
				}
				name, ok := row[nameIndex].(string)
				if !ok || name == "" {
					continue
				}
				evidence := strings.Trim(prefix+"."+name, ".")
				relation := "CALLS_OUTBOUND"
				if side == "callers" {
					relation = "CALLS_INBOUND"
				}
				results = append(results, Result{Relation: relation, Evidence: evidence})
			}
		}
	}
	return results
}

// parseCBMFlatSearchRows implements the second observed v0.10.8 BM25 JSON
// contract: cols=[qn,label,file,lines,rank] plus top-level rows. It is kept
// separate from the grouped symbol-name contract so response drift still fails
// closed instead of recursively exposing arbitrary vendor fields.
func parseCBMFlatSearchRows(content map[string]any) []Result {
	columns, ok := stringSlice(content["cols"])
	if !ok {
		return nil
	}
	qnIndex, fileIndex, linesIndex := indexOf(columns, "qn"), indexOf(columns, "file"), indexOf(columns, "lines")
	if qnIndex < 0 || fileIndex < 0 {
		return nil
	}
	rows, ok := content["rows"].([]any)
	if !ok {
		return nil
	}
	var results []Result
	for _, item := range rows {
		row, ok := item.([]any)
		if !ok || qnIndex >= len(row) || fileIndex >= len(row) {
			continue
		}
		qualifiedName, nameOK := row[qnIndex].(string)
		path, pathOK := row[fileIndex].(string)
		if !nameOK || !pathOK || qualifiedName == "" || path == "" {
			continue
		}
		result := Result{Path: path, Evidence: qualifiedName}
		if linesIndex >= 0 && linesIndex < len(row) {
			if lines, ok := row[linesIndex].(string); ok {
				_, _ = fmt.Sscanf(lines, "%d-%d", &result.StartLine, &result.EndLine)
			}
		}
		results = append(results, result)
	}
	return results
}

// parseCBMStructuredRows implements the observed v0.10.8 search_graph MCP
// contract: cols plus groups[{qn_prefix,file,rows}]. It is intentionally
// separate from the conservative generic fallback so a vendor response drift
// cannot silently turn arbitrary fields into public output.
func parseCBMStructuredRows(content map[string]any) []Result {
	columns, ok := stringSlice(content["cols"])
	if !ok {
		return nil
	}
	nameIndex, linesIndex := indexOf(columns, "name"), indexOf(columns, "lines")
	if nameIndex < 0 {
		return nil
	}
	groups, ok := content["groups"].([]any)
	if !ok {
		return nil
	}
	var results []Result
	for _, item := range groups {
		group, ok := item.(map[string]any)
		if !ok {
			continue
		}
		path, _ := group["file"].(string)
		prefix, _ := group["qn_prefix"].(string)
		rows, ok := group["rows"].([]any)
		if !ok {
			continue
		}
		for _, item := range rows {
			row, ok := item.([]any)
			if !ok || nameIndex >= len(row) {
				continue
			}
			name, ok := row[nameIndex].(string)
			if !ok || path == "" || name == "" {
				continue
			}
			result := Result{Path: path, Evidence: strings.Trim(prefix+"."+name, ".")}
			if linesIndex >= 0 && linesIndex < len(row) {
				if lines, ok := row[linesIndex].(string); ok {
					_, _ = fmt.Sscanf(lines, "%d-%d", &result.StartLine, &result.EndLine)
				}
			}
			results = append(results, result)
		}
	}
	return results
}

func stringSlice(value any) ([]string, bool) {
	values, ok := value.([]any)
	if !ok {
		return nil, false
	}
	result := make([]string, 0, len(values))
	for _, value := range values {
		text, ok := value.(string)
		if !ok {
			return nil, false
		}
		result = append(result, text)
	}
	return result, true
}

func indexOf(values []string, target string) int {
	for index, value := range values {
		if value == target {
			return index
		}
	}
	return -1
}

func (b *CBMBackend) Close() error {
	if b == nil || b.command == nil || b.command.Process == nil {
		return nil
	}
	b.close.Do(func() {
		_ = b.input.Close()
		if b.process != nil {
			_ = b.process.Terminate()
		}
		b.closeErr = b.command.Wait()
		if b.process != nil {
			_ = b.process.Close()
		}
	})
	return b.closeErr
}
