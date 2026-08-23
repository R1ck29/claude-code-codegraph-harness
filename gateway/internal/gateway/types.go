// Package gateway implements the deliberately narrow, company-owned MCP
// boundary between an AI client and a local code graph backend.
package gateway

import (
	"context"
	"encoding/json"
)

const (
	Version               = "0.2.0-rc.1"
	ManifestSchemaVersion = 1
	ManifestFilename      = "index-manifest.json"
	InvalidParamsCode     = -32602
	MethodNotFoundCode    = -32601
	InternalErrorCode     = -32603
	maxOutputCharacters   = 12000
)

// BackendIdentity pins the graph engine that created an index.
type BackendIdentity struct {
	ID      string `json:"id"`
	Version string `json:"version"`
	SHA256  string `json:"sha256"`
}

// Manifest records one atomically-created graph generation. A graph whose
// identity does not exactly match this record is never served.
type Manifest struct {
	SchemaVersion int             `json:"schema_version"`
	Generation    string          `json:"generation"`
	Status        string          `json:"status"`
	Gateway       BackendIdentity `json:"gateway"`
	RepositoryID  string          `json:"repository_identity_sha256"`
	IndexedCommit string          `json:"indexed_commit"`
	Dirty         bool            `json:"dirty"`
	Backend       BackendIdentity `json:"backend"`
	ConfigSHA256  string          `json:"config_sha256"`
	FileManifest  string          `json:"file_manifest_sha256"`
	BuiltAt       string          `json:"built_at"`
	DurationMS    int             `json:"duration_ms"`
	Counts        ManifestCounts  `json:"counts"`
}

type ManifestCounts struct {
	Files                int      `json:"files"`
	Nodes                int      `json:"nodes"`
	Edges                int      `json:"edges"`
	ParseFailures        int      `json:"parse_failures"`
	SkippedFiles         int      `json:"skipped_files"`
	UnsupportedLanguages []string `json:"unsupported_languages"`
}

// FreshnessExpectation is supplied by the locally managed launcher, never by
// an MCP caller.
type FreshnessExpectation struct {
	Backend      BackendIdentity
	Gateway      BackendIdentity
	RepositoryID string
	ConfigSHA256 string
	HeadCommit   string
	FileManifest string
}

// Result is intentionally smaller than a backend result. Source bodies,
// external links, raw queries, and absolute paths are never a public contract.
type Result struct {
	Path      string `json:"path,omitempty"`
	StartLine int    `json:"start_line,omitempty"`
	EndLine   int    `json:"end_line,omitempty"`
	Relation  string `json:"relation,omitempty"`
	Evidence  string `json:"evidence,omitempty"`
	Source    string `json:"source,omitempty"`
	URL       string `json:"url,omitempty"`
}

type BackendRequest struct {
	Operation string         `json:"operation"`
	Arguments map[string]any `json:"arguments"`
}

type BackendResponse struct {
	Summary   string   `json:"summary,omitempty"`
	Results   []Result `json:"results,omitempty"`
	Truncated bool     `json:"truncated,omitempty"`
}

// Backend is implemented by the pinned native backend adapter. Tests use a
// fake so that no vendor executable is necessary to prove gateway behavior.
type Backend interface {
	Call(context.Context, BackendRequest) (BackendResponse, error)
}

// FreshnessChecker is invoked before every MCP tool call. It must return an
// error rather than serving stale graph evidence.
type FreshnessChecker func(context.Context) error

type Tool struct {
	Name        string         `json:"name"`
	Description string         `json:"description"`
	InputSchema map[string]any `json:"inputSchema"`
}

type RPCRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      any             `json:"id,omitempty"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

type RPCError struct {
	Code    int    `json:"code"`
	Message string `json:"message"`
}

type RPCResponse struct {
	JSONRPC string    `json:"jsonrpc"`
	ID      any       `json:"id,omitempty"`
	Result  any       `json:"result,omitempty"`
	Error   *RPCError `json:"error,omitempty"`
}
