//go:build windows

package gateway

import (
	"fmt"
	"os/exec"
	"syscall"
	"unsafe"
)

const (
	jobObjectExtendedLimitInformation = 9
	jobObjectLimitKillOnJobClose      = 0x00002000
	processSetQuota                   = 0x0100
	processTerminate                  = 0x0001
)

var (
	kernel32                 = syscall.NewLazyDLL("kernel32.dll")
	createJobObjectW         = kernel32.NewProc("CreateJobObjectW")
	setInformationJobObject  = kernel32.NewProc("SetInformationJobObject")
	assignProcessToJobObject = kernel32.NewProc("AssignProcessToJobObject")
	terminateJobObject       = kernel32.NewProc("TerminateJobObject")
)

type jobObjectBasicLimitInformation struct {
	PerProcessUserTimeLimit int64
	PerJobUserTimeLimit     int64
	LimitFlags              uint32
	MinimumWorkingSetSize   uintptr
	MaximumWorkingSetSize   uintptr
	ActiveProcessLimit      uint32
	Affinity                uintptr
	PriorityClass           uint32
	SchedulingClass         uint32
}

type ioCounters struct {
	ReadOperationCount  uint64
	WriteOperationCount uint64
	OtherOperationCount uint64
	ReadTransferCount   uint64
	WriteTransferCount  uint64
	OtherTransferCount  uint64
}

type jobObjectExtendedLimitInfo struct {
	BasicLimitInformation jobObjectBasicLimitInformation
	IoInfo                ioCounters
	ProcessMemoryLimit    uintptr
	JobMemoryLimit        uintptr
	PeakProcessMemoryUsed uintptr
	PeakJobMemoryUsed     uintptr
}

type windowsJobObject struct {
	handle syscall.Handle
}

func prepareChildProcess(command *exec.Cmd) {}

func attachChildProcess(command *exec.Cmd) (childProcessController, error) {
	job, _, createErr := createJobObjectW.Call(0, 0)
	if job == 0 {
		return nil, fmt.Errorf("create Windows Job Object: %w", createErr)
	}
	handle := syscall.Handle(job)
	closeOnError := true
	defer func() {
		if closeOnError {
			_ = syscall.CloseHandle(handle)
		}
	}()
	limits := jobObjectExtendedLimitInfo{}
	limits.BasicLimitInformation.LimitFlags = jobObjectLimitKillOnJobClose
	result, _, setErr := setInformationJobObject.Call(
		job,
		jobObjectExtendedLimitInformation,
		uintptr(unsafe.Pointer(&limits)),
		unsafe.Sizeof(limits),
	)
	if result == 0 {
		return nil, fmt.Errorf("configure Windows Job Object: %w", setErr)
	}
	process, err := syscall.OpenProcess(processSetQuota|processTerminate, false, uint32(command.Process.Pid))
	if err != nil {
		return nil, fmt.Errorf("open child process for Windows Job Object: %w", err)
	}
	defer syscall.CloseHandle(process)
	result, _, assignErr := assignProcessToJobObject.Call(job, uintptr(process))
	if result == 0 {
		return nil, fmt.Errorf("assign child to Windows Job Object: %w", assignErr)
	}
	closeOnError = false
	return &windowsJobObject{handle: handle}, nil
}

func (job *windowsJobObject) Terminate() error {
	result, _, err := terminateJobObject.Call(uintptr(job.handle), 1)
	if result == 0 {
		return fmt.Errorf("terminate Windows Job Object: %w", err)
	}
	return nil
}

func (job *windowsJobObject) Close() error {
	return syscall.CloseHandle(job.handle)
}
