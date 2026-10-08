package nakedagent

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"strings"
	"time"
	"unicode/utf8"
)

// ToolFunc is a tool: it gets the fence-line arguments, the fence body and the workspace
// directory, and returns the text fed back to the model. Tool-level failures are returned
// as text (spec section 5); a non-nil error is an unexpected failure the loop reports.
type ToolFunc func(args, content, workspace string) (string, error)

// MaxOutput is the output cap in code points (spec section 5.1).
const MaxOutput = 8000

// Truncate cuts s to MaxOutput code points and appends the truncation notice.
func Truncate(s string) string {
	n := utf8.RuneCountInString(s)
	if n <= MaxOutput {
		return s
	}
	cut := 0
	for i := 0; i < MaxOutput; i++ {
		_, size := utf8.DecodeRuneInString(s[cut:])
		cut += size
	}
	return fmt.Sprintf("%s\n...[truncated, %d more chars]", s[:cut], n-MaxOutput)
}

// ---------------------------------------------------------------- path guard

func isSep(c byte) bool {
	return c == '/' || (runtime.GOOS == "windows" && c == '\\')
}

func splitComponents(p string) []string {
	var out []string
	start := 0
	for i := 0; i <= len(p); i++ {
		if i == len(p) || isSep(p[i]) {
			if i > start {
				if c := p[start:i]; c != "." {
					out = append(out, c)
				}
			}
			start = i + 1
		}
	}
	return out
}

// realpath resolves symlinks like Python's Path.resolve() in non-strict mode: ".." is applied
// after the component before it has been resolved, and components that do not exist are kept
// as written. path must be absolute.
func realpath(path string) string {
	vol := filepath.VolumeName(path)
	rest := path[len(vol):]
	root := vol + string(filepath.Separator)
	cur := root
	comps := splitComponents(rest)
	links := 0
	for len(comps) > 0 {
		c := comps[0]
		comps = comps[1:]
		if c == ".." {
			if cur != root {
				cur = filepath.Dir(cur)
			}
			continue
		}
		next := filepath.Join(cur, c)
		if fi, err := os.Lstat(next); err == nil && fi.Mode()&os.ModeSymlink != 0 {
			target, err := os.Readlink(next)
			links++
			if err != nil || links > 255 {
				cur = next
				continue
			}
			tvol := filepath.VolumeName(target)
			trest := target[len(tvol):]
			if len(trest) > 0 && isSep(trest[0]) {
				if tvol == "" {
					tvol = vol
				}
				cur = tvol + string(filepath.Separator)
			}
			comps = append(splitComponents(trest), comps...)
			continue
		}
		cur = next
	}
	return cur
}

// resolveTarget returns the fully resolved workspace and the resolved target for a tool path.
func resolveTarget(workspace, rel string) (target, ws string, err error) {
	abs, err := filepath.Abs(workspace)
	if err != nil {
		return "", "", err
	}
	ws = realpath(abs)
	var joined string
	switch {
	case filepath.IsAbs(rel):
		joined = rel
	case runtime.GOOS == "windows" && len(rel) > 0 && isSep(rel[0]):
		joined = filepath.VolumeName(ws) + rel
	default:
		joined = ws + string(filepath.Separator) + rel
	}
	return realpath(joined), ws, nil
}

func isInside(target, ws string) bool {
	if runtime.GOOS == "windows" {
		target, ws = strings.ToLower(target), strings.ToLower(ws)
	}
	rel, err := filepath.Rel(ws, target)
	if err != nil {
		return false
	}
	return rel != ".." && !strings.HasPrefix(rel, ".."+string(filepath.Separator))
}

var protectedDirNames = map[string]bool{".git": true, ".nakedagent": true}

// protectedTarget reports whether the first path component under the workspace is protected.
func protectedTarget(target, ws string) (bool, string) {
	rel, err := filepath.Rel(ws, target)
	if err != nil {
		return true, "outside workspace"
	}
	first := strings.Split(filepath.ToSlash(rel), "/")[0]
	if runtime.GOOS == "windows" {
		first = strings.ToLower(first)
	}
	if protectedDirNames[first] {
		return true, first
	}
	return false, ""
}

func missingPath(tool string) string {
	return fmt.Sprintf("Error: %s tool needs a path, e.g. ```%s path/to/file.py```", tool, tool)
}

// ---------------------------------------------------------------- read / write / patch

// ToolRead returns a file's text, or a directory's entry names (spec section 5).
func ToolRead(args, content, workspace string) (string, error) {
	path := pyStrip(args)
	if path == "" {
		return missingPath("read"), nil
	}
	target, ws, err := resolveTarget(workspace, path)
	if err != nil {
		return "", err
	}
	if !isInside(target, ws) {
		return fmt.Sprintf("Error: %s is outside the workspace.", path), nil
	}
	fi, err := os.Stat(target)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return fmt.Sprintf("Error: %s does not exist.", path), nil
		}
		return "", err
	}
	if fi.IsDir() {
		entries, err := os.ReadDir(target)
		if err != nil {
			return "", err
		}
		names := make([]string, 0, len(entries))
		for _, e := range entries {
			names = append(names, e.Name())
		}
		sort.Strings(names) // byte order of UTF-8 equals code point order
		return path + " is a directory:\n" + strings.Join(names, "\n"), nil
	}
	data, err := os.ReadFile(target)
	if err != nil {
		return "", err
	}
	return Truncate(decodeReplace(data)), nil
}

// ToolWrite creates or overwrites a file under the workspace.
func ToolWrite(args, content, workspace string) (string, error) {
	path := pyStrip(args)
	if path == "" {
		return missingPath("write"), nil
	}
	target, ws, err := resolveTarget(workspace, path)
	if err != nil {
		return "", err
	}
	if !isInside(target, ws) {
		return fmt.Sprintf("Error: %s is outside the workspace.", path), nil
	}
	if bad, name := protectedTarget(target, ws); bad {
		return fmt.Sprintf("Error: %s is in protected directory '%s'.", path, name), nil
	}
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return "", err
	}
	if err := os.WriteFile(target, []byte(content), 0o644); err != nil {
		return "", err
	}
	return fmt.Sprintf("Wrote %d chars to %s.", utf8.RuneCountInString(content), path), nil
}

// splitSearchReplace splits a <<<<<<< SEARCH / ======= / >>>>>>> REPLACE block (spec 5.2).
func splitSearchReplace(block string) (search, replace string, err error) {
	lines := pySplitLines(block)
	start, sep, end := -1, -1, -1
	for i, ln := range lines {
		if pyStrip(ln) == "<<<<<<< SEARCH" {
			start = i
			break
		}
	}
	if start >= 0 {
		for i := start + 1; i < len(lines); i++ {
			if pyStrip(lines[i]) == "=======" {
				sep = i
				break
			}
		}
	}
	if sep >= 0 {
		for i := sep + 1; i < len(lines); i++ {
			if pyStrip(lines[i]) == ">>>>>>> REPLACE" {
				end = i
				break
			}
		}
	}
	if end < 0 {
		return "", "", errors.New("expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order")
	}
	for i := start + 1; i < end; i++ {
		if strings.HasPrefix(pyStrip(lines[i]), "<<<<<<<") {
			return "", "", errors.New("a second <<<<<<< marker appears before the matching >>>>>>>")
		}
	}
	for _, ln := range lines[end+1:] {
		if pyStrip(ln) != "" {
			return "", "", errors.New("unexpected content after >>>>>>> REPLACE; use one patch block per call")
		}
	}
	return strings.Join(lines[start+1:sep], "\n"), strings.Join(lines[sep+1:end], "\n"), nil
}

// ToolPatch applies one SEARCH/REPLACE block to an existing file.
func ToolPatch(args, content, workspace string) (string, error) {
	path := pyStrip(args)
	if path == "" {
		return missingPath("patch"), nil
	}
	target, ws, err := resolveTarget(workspace, path)
	if err != nil {
		return "", err
	}
	if !isInside(target, ws) {
		return fmt.Sprintf("Error: %s is outside the workspace.", path), nil
	}
	if bad, name := protectedTarget(target, ws); bad {
		return fmt.Sprintf("Error: %s is in protected directory '%s'.", path, name), nil
	}
	if _, err := os.Stat(target); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return fmt.Sprintf("Error: %s does not exist. Use write to create it.", path), nil
		}
		return "", err
	}
	search, replace, serr := splitSearchReplace(content)
	if serr != nil {
		return fmt.Sprintf("Error: malformed patch block (%s).", serr.Error()), nil
	}
	data, err := os.ReadFile(target)
	if err != nil {
		return "", err
	}
	if !utf8.Valid(data) {
		return fmt.Sprintf("Error: %s is not valid UTF-8; patch refused without changing the file.", path), nil
	}
	original := string(data)
	switch count := strings.Count(original, search); {
	case count == 0:
		return fmt.Sprintf("Error: SEARCH text not found in %s. It must match exactly, including whitespace.", path), nil
	case count > 1:
		return fmt.Sprintf("Error: SEARCH text matches %d locations in %s; make it more specific.", count, path), nil
	}
	updated := strings.Replace(original, search, replace, 1)
	if err := os.WriteFile(target, []byte(updated), 0o644); err != nil {
		return "", err
	}
	return fmt.Sprintf("Patched %s.", path), nil
}

// ---------------------------------------------------------------- shell

// ShellPolicy is the non-interactive shell policy (spec section 6).
type ShellPolicy struct {
	AllowShell     bool
	Allowlist      []string
	TimeoutSeconds int // must be positive; DefaultShellTimeout is 120
}

// DefaultShellTimeout is the reference default, in seconds.
const DefaultShellTimeout = 120

// NewShellPolicy returns a policy with the default timeout and shell disabled.
func NewShellPolicy() ShellPolicy { return ShellPolicy{TimeoutSeconds: DefaultShellTimeout} }

// ToolShell runs one allowlisted command directly, without a shell.
func ToolShell(args, content, workspace string, p ShellPolicy) (string, error) {
	cmd := pyStrip(content)
	if cmd == "" {
		cmd = pyStrip(args)
	}
	if cmd == "" {
		return "Error: shell tool got no command.", nil
	}
	timeout := p.TimeoutSeconds
	if timeout <= 0 {
		return "Error: --shell-timeout must be a positive integer.", nil
	}
	if !p.AllowShell {
		return "Error: shell execution blocked (non-interactive shell execution requires --allow-shell).", nil
	}
	if !isAllowedShellCommand(cmd, p.Allowlist) {
		return "Error: shell execution blocked (non-interactive command is not in --shell-allowlist).", nil
	}
	argv, err := shlexSplit(cmd)
	if err != nil {
		return fmt.Sprintf("Error: malformed command (%s).", err.Error()), nil
	}
	name := ""
	if len(argv) > 0 {
		name = argv[0]
	}
	exe, lerr := exec.LookPath(name)
	if name == "" || lerr != nil {
		return fmt.Sprintf("Error: '%s' is not an executable on PATH. "+
			"Non-interactive mode runs programs directly without a shell, so "+
			"shell built-ins (e.g. cmd's echo/dir) and operators (|, &&, ;) "+
			"are not available.", name), nil
	}
	if runtime.GOOS == "windows" {
		lower := strings.ToLower(exe)
		if strings.HasSuffix(lower, ".bat") || strings.HasSuffix(lower, ".cmd") {
			for _, a := range argv[1:] {
				if strings.ContainsAny(a, `&|<>^%!"`) {
					return "Error: shell execution blocked (cmd.exe metacharacters in arguments to a batch file); " +
						"Windows runs .bat/.cmd files through cmd.exe, which would interpret them.", nil
				}
			}
		}
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Duration(timeout)*time.Second)
	defer cancel()
	c := exec.CommandContext(ctx, exe, argv[1:]...)
	c.Dir = workspace
	var stdout, stderr bytes.Buffer
	c.Stdout, c.Stderr = &stdout, &stderr
	c.WaitDelay = 2 * time.Second
	runErr := c.Run()
	if ctx.Err() == context.DeadlineExceeded {
		return fmt.Sprintf("Error: command timed out after %ds.", timeout), nil
	}
	code := 0
	if runErr != nil {
		var ee *exec.ExitError
		if errors.As(runErr, &ee) {
			code = ee.ExitCode()
		} else {
			return fmt.Sprintf("Error: command execution failed: %T: %v", runErr, runErr), nil
		}
	}
	parts := []string{fmt.Sprintf("(exit %d)", code)}
	if stdout.Len() > 0 {
		parts = append(parts, decodeReplace(stdout.Bytes()))
	}
	if stderr.Len() > 0 {
		parts = append(parts, "--- stderr ---\n"+decodeReplace(stderr.Bytes()))
	}
	return Truncate(strings.Join(parts, "\n")), nil
}
