package gateway

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
)

// ServeStdio is intentionally log-free on stdout. The only stdout bytes are
// one JSON-RPC response per request; diagnostics belong to the supplied stderr.
func ServeStdio(ctx context.Context, input io.Reader, output io.Writer, diagnostics io.Writer, server *Server) error {
	if server == nil {
		return fmt.Errorf("server is required")
	}
	scanner := bufio.NewScanner(input)
	// The MCP line framing is bounded to avoid an untrusted client forcing an
	// arbitrary allocation. Tool schemas impose substantially smaller limits.
	scanner.Buffer(make([]byte, 4096), 1<<20)
	writer := bufio.NewWriter(output)
	defer writer.Flush()
	for scanner.Scan() {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}
		var request RPCRequest
		if err := json.Unmarshal(scanner.Bytes(), &request); err != nil {
			response := RPCResponse{JSONRPC: "2.0", Error: &RPCError{Code: InvalidParamsCode, Message: "invalid JSON-RPC request"}}
			if err := writeResponse(writer, response); err != nil {
				return err
			}
			continue
		}
		if request.Method == "notifications/initialized" {
			continue
		}
		response := server.Handle(ctx, request)
		if err := writeResponse(writer, response); err != nil {
			return err
		}
	}
	if err := scanner.Err(); err != nil {
		return fmt.Errorf("read MCP input: %w", err)
	}
	return nil
}

func writeResponse(writer *bufio.Writer, response RPCResponse) error {
	payload, err := json.Marshal(response)
	if err != nil {
		return fmt.Errorf("encode JSON-RPC response: %w", err)
	}
	if _, err := writer.Write(payload); err != nil {
		return err
	}
	if err := writer.WriteByte('\n'); err != nil {
		return err
	}
	return writer.Flush()
}
