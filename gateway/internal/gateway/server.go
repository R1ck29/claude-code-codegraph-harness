package gateway

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
)

var qualifiedIdentifierPattern = regexp.MustCompile(`^[A-Za-z_$][A-Za-z0-9_$]*(?:(?:\.|::)(?:[A-Za-z_$][A-Za-z0-9_$]*|[0-9]+))*$`)

type Server struct {
	root     string
	manifest Manifest
	backend  Backend
	checker  FreshnessChecker
}

func NewServer(root string, manifest Manifest, backend Backend) (*Server, error) {
	if backend == nil {
		return nil, fmt.Errorf("backend is required")
	}
	canonical, err := filepath.Abs(root)
	if err != nil {
		return nil, fmt.Errorf("resolve repository root: %w", err)
	}
	return &Server{root: canonical, manifest: manifest, backend: backend}, nil
}

func (s *Server) WithFreshnessChecker(checker FreshnessChecker) *Server {
	s.checker = checker
	return s
}

func noArgumentsSchema() map[string]any {
	return map[string]any{"type": "object", "additionalProperties": false, "properties": map[string]any{}}
}

func boundedSchema(requiredName, description string, depth bool) map[string]any {
	properties := map[string]any{
		requiredName: map[string]any{"type": "string", "description": description, "minLength": 1, "maxLength": 300},
		"limit":      map[string]any{"type": "integer", "minimum": 1, "maximum": 20},
	}
	if depth {
		properties["depth"] = map[string]any{"type": "integer", "minimum": 1, "maximum": 3}
	}
	return map[string]any{
		"type":                 "object",
		"additionalProperties": false,
		"required":             []string{requiredName},
		"properties":           properties,
	}
}

// Tools is the entire public graph action space. Do not add raw backend tools
// here: project selection, indexing, arbitrary graph queries, and code bodies
// are deliberately administrative or unavailable operations.
func (s *Server) Tools() []Tool {
	return []Tool{
		{Name: "codegraph_status", Description: "Report whether the local graph is fresh and usable.", InputSchema: noArgumentsSchema()},
		{Name: "codegraph_search", Description: "Find small graph evidence for a symbol or concept.", InputSchema: boundedSchema("query", "Symbol or concept to search for.", false)},
		{Name: "codegraph_neighbors", Description: "Find bounded graph neighbors of one symbol.", InputSchema: boundedSchema("symbol", "Qualified or local symbol name.", true)},
		{Name: "codegraph_impact", Description: "Find bounded incoming and outgoing impact evidence for one symbol.", InputSchema: boundedSchema("target", "Qualified or local symbol name.", true)},
		{Name: "codegraph_architecture", Description: "Return a bounded repository architecture overview.", InputSchema: noArgumentsSchema()},
	}
}

func (s *Server) Handle(ctx context.Context, request RPCRequest) RPCResponse {
	if !validRequestID(request.ID) {
		return RPCResponse{JSONRPC: "2.0", Error: &RPCError{Code: InvalidParamsCode, Message: "request id must be null, a number, or a bounded string"}}
	}
	response := RPCResponse{JSONRPC: "2.0", ID: request.ID}
	if request.JSONRPC != "2.0" {
		response.Error = &RPCError{Code: InvalidParamsCode, Message: "jsonrpc must be 2.0"}
		return response
	}
	switch request.Method {
	case "initialize":
		response.Result = map[string]any{
			"protocolVersion": "2025-06-18",
			"capabilities":    map[string]any{"tools": map[string]any{}},
			"serverInfo":      map[string]string{"name": "codegraph-gateway", "version": Version},
		}
	case "notifications/initialized":
		// Notification: a server normally emits no response. ServeStdio handles it.
		response.Result = map[string]any{}
	case "tools/list":
		response.Result = map[string]any{"tools": s.Tools()}
	case "tools/call":
		return s.call(ctx, request)
	default:
		response.Error = &RPCError{Code: MethodNotFoundCode, Message: "method is not supported"}
	}
	return response
}

func validRequestID(value any) bool {
	switch id := value.(type) {
	case nil, float64, json.Number, int, int64, uint64:
		return true
	case string:
		if len(id) > 128 {
			return false
		}
		for _, character := range id {
			if character < 0x20 || character == 0x7f {
				return false
			}
		}
		return true
	default:
		return false
	}
}

func decodeObject(raw []byte) (map[string]any, error) {
	var object map[string]any
	decoder := json.NewDecoder(strings.NewReader(string(raw)))
	decoder.UseNumber()
	if err := decoder.Decode(&object); err != nil || object == nil {
		if err == nil {
			err = fmt.Errorf("object is required")
		}
		return nil, err
	}
	return object, nil
}

func stringArgument(arguments map[string]any, name string) (string, error) {
	value, ok := arguments[name].(string)
	if !ok || strings.TrimSpace(value) == "" || len(value) > 300 {
		return "", fmt.Errorf("%s must be a non-empty string of at most 300 characters", name)
	}
	return value, nil
}

func integerArgument(arguments map[string]any, name string, fallback, maximum int) (int, error) {
	value, ok := arguments[name]
	if !ok {
		return fallback, nil
	}
	number, ok := value.(json.Number)
	if !ok {
		return 0, fmt.Errorf("%s must be an integer", name)
	}
	parsed, err := number.Int64()
	if err != nil || parsed < 1 || parsed > int64(maximum) {
		return 0, fmt.Errorf("%s must be between 1 and %d", name, maximum)
	}
	return int(parsed), nil
}

func validateArguments(arguments map[string]any, required string, allowDepth bool) (map[string]any, error) {
	allowed := map[string]bool{required: true, "limit": true}
	if allowDepth {
		allowed["depth"] = true
	}
	for key := range arguments {
		if !allowed[key] {
			return nil, fmt.Errorf("unknown input field %q", key)
		}
	}
	value, err := stringArgument(arguments, required)
	if err != nil {
		return nil, err
	}
	limit, err := integerArgument(arguments, "limit", 8, 20)
	if err != nil {
		return nil, err
	}
	validated := map[string]any{required: value, "limit": limit}
	if allowDepth {
		depth, err := integerArgument(arguments, "depth", 1, 3)
		if err != nil {
			return nil, err
		}
		validated["depth"] = depth
	}
	return validated, nil
}

func (s *Server) call(ctx context.Context, request RPCRequest) RPCResponse {
	response := RPCResponse{JSONRPC: "2.0", ID: request.ID}
	if s.checker != nil {
		if err := s.checker(ctx); err != nil {
			response.Result = toolResult(unavailablePayload("local graph freshness could not be verified", s.manifest.Generation))
			return response
		}
	}
	params, err := decodeObject(request.Params)
	if err != nil {
		response.Error = &RPCError{Code: InvalidParamsCode, Message: "tools/call params must be an object"}
		return response
	}
	name, ok := params["name"].(string)
	if !ok {
		response.Error = &RPCError{Code: InvalidParamsCode, Message: "tool name is required"}
		return response
	}
	arguments, ok := params["arguments"]
	if !ok {
		arguments = map[string]any{}
	}
	argumentMap, ok := arguments.(map[string]any)
	if !ok {
		response.Error = &RPCError{Code: InvalidParamsCode, Message: "tool arguments must be an object"}
		return response
	}

	if name == "codegraph_status" {
		if len(argumentMap) != 0 {
			response.Error = &RPCError{Code: InvalidParamsCode, Message: "codegraph_status has no arguments"}
			return response
		}
		response.Result = toolResult(map[string]any{
			"status":       "success",
			"summary":      "local code graph is fresh",
			"freshness":    freshness(true, "fresh", s.manifest.Generation),
			"results":      []any{},
			"page":         page(0, false),
			"next_actions": []string{"Use a bounded graph query when code context is needed."},
		})
		return response
	}
	if name == "codegraph_architecture" {
		if len(argumentMap) != 0 {
			response.Error = &RPCError{Code: InvalidParamsCode, Message: "codegraph_architecture has no arguments"}
			return response
		}
		backendResponse, err := s.backend.Call(ctx, BackendRequest{Operation: "get_architecture", Arguments: map[string]any{}})
		if err != nil {
			response.Result = toolResult(unavailablePayload("local graph query was unavailable", s.manifest.Generation))
			return response
		}
		response.Result = toolResult(s.publicResponse(backendResponse))
		return response
	}

	operation, required, depth := "", "", false
	switch name {
	case "codegraph_search":
		operation, required = "search_graph", "query"
	case "codegraph_neighbors":
		operation, required, depth = "trace_path", "symbol", true
	case "codegraph_impact":
		operation, required, depth = "impact", "target", true
	default:
		response.Error = &RPCError{Code: InvalidParamsCode, Message: "tool is not available"}
		return response
	}
	validated, err := validateArguments(argumentMap, required, depth)
	if err != nil {
		response.Error = &RPCError{Code: InvalidParamsCode, Message: err.Error()}
		return response
	}
	backendResponse, err := s.backend.Call(ctx, BackendRequest{Operation: operation, Arguments: validated})
	if err != nil {
		response.Result = toolResult(unavailablePayload("local graph query was unavailable", s.manifest.Generation))
		return response
	}
	response.Result = toolResult(s.publicResponse(backendResponse))
	return response
}

func unavailablePayload(summary, generation string) map[string]any {
	return map[string]any{"status": "unavailable", "summary": summary, "freshness": freshness(false, "incomplete", generation), "results": []any{}, "page": page(0, false), "next_actions": []string{"Stop graph use and use the normal local exploration workflow."}}
}

func toolResult(payload map[string]any) map[string]any {
	serialized, err := json.Marshal(payload)
	if err != nil {
		return map[string]any{"content": []map[string]string{{"type": "text", "text": "{\"status\":\"error\",\"summary\":\"response encoding failed\"}"}}, "isError": true}
	}
	if len(serialized) > maxOutputCharacters {
		serialized = []byte(`{"status":"success","summary":"response exceeded the safe output limit","freshness":{"usable":true,"reason":"fresh","generation":null},"results":[],"page":{"returned":0,"truncated":true,"next_cursor":null},"next_actions":["Narrow the query and retry."]}`)
	}
	return map[string]any{"content": []map[string]string{{"type": "text", "text": string(serialized)}}}
}

func (s *Server) publicResponse(backendResponse BackendResponse) map[string]any {
	results := make([]map[string]any, 0, min(len(backendResponse.Results), 50))
	for _, result := range backendResponse.Results {
		if len(results) == 50 {
			break
		}
		path := safeRelativePath(s.root, result.Path)
		evidence := safeIdentifier(result.Evidence, 256)
		if path == "" && evidence == "" {
			continue
		}
		lineStart := result.StartLine
		if lineStart < 1 {
			lineStart = 1
		}
		lineEnd := result.EndLine
		if lineEnd < lineStart {
			lineEnd = lineStart
		}
		name := symbolName(evidence)
		kind := "symbol"
		if name == "" {
			name = "location"
			evidence = "location"
			kind = "location"
		}
		entry := map[string]any{
			"symbol_id": localSymbolID(evidence, path, lineStart), "name": name, "kind": kind, "path": path,
			"line_start": lineStart, "line_end": lineEnd, "relation": publicRelation(result.Relation), "evidence": evidence,
		}
		results = append(results, entry)
	}
	summary := fmt.Sprintf("%d local graph result(s)", len(results))
	return map[string]any{
		"status":       "success",
		"summary":      summary,
		"freshness":    freshness(true, "fresh", s.manifest.Generation),
		"results":      results,
		"page":         page(len(results), backendResponse.Truncated || len(backendResponse.Results) > len(results)),
		"next_actions": []string{"Use the listed relative locations for local review."},
	}
}

func freshness(usable bool, reason, generation string) map[string]any {
	return map[string]any{"usable": usable, "reason": reason, "generation": generation}
}
func page(returned int, truncated bool) map[string]any {
	return map[string]any{"returned": returned, "truncated": truncated, "next_cursor": nil}
}
func symbolName(evidence string) string {
	return safeIdentifier(evidence, 128)
}

func safeIdentifier(value string, limit int) string {
	if value == "" || len(value) > limit || !qualifiedIdentifierPattern.MatchString(value) {
		return ""
	}
	return value
}

func localSymbolID(identifier, path string, line int) string {
	sum := sha256.Sum256([]byte(identifier + "\x00" + path + "\x00" + strconv.Itoa(line)))
	return fmt.Sprintf("local:%x", sum[:12])
}
func publicRelation(value string) string {
	value = strings.ToUpper(value)
	switch {
	case strings.Contains(value, "INBOUND"):
		return "caller"
	case strings.Contains(value, "OUTBOUND"):
		return "callee"
	case strings.Contains(value, "IMPORT"):
		return "import"
	case strings.Contains(value, "TEST"):
		return "test"
	case strings.Contains(value, "IMPACT"):
		return "impact"
	case strings.Contains(value, "ARCHITECT"):
		return "architecture"
	case strings.Contains(value, "CALL"):
		return "reference"
	default:
		return "definition"
	}
}

func safeRelativePath(root, candidate string) string {
	if candidate == "" || filepath.VolumeName(candidate) != "" || strings.HasPrefix(candidate, `\\`) {
		return ""
	}
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		return ""
	}
	path := candidate
	if !filepath.IsAbs(path) {
		path = filepath.Join(root, path)
	}
	path, err = filepath.EvalSymlinks(path)
	if err != nil {
		return ""
	}
	relative, err := filepath.Rel(root, path)
	if err != nil || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return ""
	}
	clean := filepath.Clean(relative)
	if clean == "." || clean == ".." || strings.HasPrefix(clean, ".."+string(filepath.Separator)) {
		return ""
	}
	portable := filepath.ToSlash(clean)
	if len(portable) > 1024 {
		return ""
	}
	for _, character := range portable {
		if (character >= 'a' && character <= 'z') || (character >= 'A' && character <= 'Z') ||
			(character >= '0' && character <= '9') || strings.ContainsRune("._/@+$#-", character) {
			continue
		}
		return ""
	}
	return portable
}
