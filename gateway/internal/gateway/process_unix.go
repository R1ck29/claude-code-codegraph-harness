//go:build !windows

package gateway

import (
	"errors"
	"os/exec"
	"syscall"
)

type unixProcessGroup struct {
	pid int
}

func prepareChildProcess(command *exec.Cmd) {
	command.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
}

func attachChildProcess(command *exec.Cmd) (childProcessController, error) {
	return &unixProcessGroup{pid: command.Process.Pid}, nil
}

func (group *unixProcessGroup) Terminate() error {
	err := syscall.Kill(-group.pid, syscall.SIGKILL)
	if errors.Is(err, syscall.ESRCH) {
		return nil
	}
	return err
}

func (group *unixProcessGroup) Close() error { return nil }
