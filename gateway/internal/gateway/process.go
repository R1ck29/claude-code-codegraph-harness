package gateway

import (
	"context"
	"os/exec"
)

type childProcessController interface {
	Terminate() error
	Close() error
}

func startChildProcess(command *exec.Cmd) (childProcessController, error) {
	prepareChildProcess(command)
	if err := command.Start(); err != nil {
		return nil, err
	}
	controller, err := attachChildProcess(command)
	if err != nil {
		_ = command.Process.Kill()
		_ = command.Wait()
		return nil, err
	}
	return controller, nil
}

// RunChildCommand waits for a bounded administrative child command and always
// tears down the complete process tree, including descendants left after the
// direct child exits. Callers supply a minimal environment and bounded writers.
func RunChildCommand(ctx context.Context, command *exec.Cmd) error {
	controller, err := startChildProcess(command)
	if err != nil {
		return err
	}
	done := make(chan error, 1)
	go func() { done <- command.Wait() }()
	select {
	case err = <-done:
	case <-ctx.Done():
		_ = controller.Terminate()
		<-done
		_ = controller.Close()
		return ctx.Err()
	}
	terminateErr := controller.Terminate()
	closeErr := controller.Close()
	if err != nil {
		return err
	}
	if terminateErr != nil {
		return terminateErr
	}
	return closeErr
}
