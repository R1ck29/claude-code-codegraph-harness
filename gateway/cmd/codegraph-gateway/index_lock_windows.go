//go:build windows

package main

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"syscall"
	"unsafe"
)

const (
	lockfileFailImmediately = 0x00000001
	lockfileExclusiveLock   = 0x00000002
)

var (
	indexKernel32 = syscall.NewLazyDLL("kernel32.dll")
	lockFileEx    = indexKernel32.NewProc("LockFileEx")
	unlockFileEx  = indexKernel32.NewProc("UnlockFileEx")
)

type indexLock struct {
	file       *os.File
	overlapped syscall.Overlapped
}

func acquireIndexLock(stateDir string) (*indexLock, error) {
	if err := os.MkdirAll(stateDir, 0o700); err != nil {
		return nil, err
	}
	file, err := os.OpenFile(filepath.Join(stateDir, ".index.lock"), os.O_RDWR|os.O_CREATE, 0o600)
	if err != nil {
		return nil, err
	}
	lock := &indexLock{file: file}
	result, _, callErr := lockFileEx.Call(
		file.Fd(), lockfileFailImmediately|lockfileExclusiveLock, 0, 1, 0,
		uintptr(unsafe.Pointer(&lock.overlapped)),
	)
	if result == 0 {
		_ = file.Close()
		return nil, fmt.Errorf("another index build is active: %w", callErr)
	}
	return lock, nil
}

func (lock *indexLock) Close() error {
	if lock == nil || lock.file == nil {
		return nil
	}
	file := lock.file
	lock.file = nil
	result, _, callErr := unlockFileEx.Call(
		file.Fd(), 0, 1, 0, uintptr(unsafe.Pointer(&lock.overlapped)),
	)
	var unlockErr error
	if result == 0 {
		unlockErr = fmt.Errorf("unlock index build: %w", callErr)
	}
	return errors.Join(unlockErr, file.Close())
}
