package nakedagent

import (
	"fmt"
	"regexp"
	"strings"
)

// ToolCall is one fenced tool invocation found in a model reply (spec section 4).
type ToolCall struct {
	Tool    string
	Args    string
	Content string
}

var openRe = regexp.MustCompile("^```([A-Za-z0-9_]+)(?: ([^\\n`]*))?$")

// bareTicks is the length of a column-0 all-backtick line (trailing whitespace allowed), else 0.
func bareTicks(line string) int {
	s := pyRstrip(line)
	if s == "" {
		return 0
	}
	for i := 0; i < len(s); i++ {
		if s[i] != '`' {
			return 0
		}
	}
	return len(s)
}

// fenceTicks is the length of the opening backtick run of a column-0 fence marker (>= 3), else 0.
func fenceTicks(line string) int {
	n := 0
	for n < len(line) && line[n] == '`' {
		n++
	}
	if n >= 3 {
		return n
	}
	return 0
}

// ParseToolCalls returns every tool call in text, in order. An unclosed block yields a single
// refusal call (Tool "__refused__") and consumes the rest of the input.
func ParseToolCalls(text string) []ToolCall {
	text = strings.ReplaceAll(text, "\r\n", "\n")
	lines := strings.Split(text, "\n")
	var calls []ToolCall
	i, n := 0, len(lines)
	for i < n {
		m := openRe.FindStringSubmatch(lines[i])
		if m == nil {
			i++
			continue
		}
		tool := m[1]
		args := pyStrip(m[2])
		var body []string
		stack := []int{3}
		i++
		closed := false
		for i < n {
			line := lines[i]
			if bare := bareTicks(line); bare > 0 {
				if bare == stack[len(stack)-1] {
					stack = stack[:len(stack)-1]
					i++
					if len(stack) == 0 {
						closed = true
						break
					}
					body = append(body, line)
					continue
				}
				body = append(body, line)
				i++
				continue
			}
			if t := fenceTicks(line); t > 0 {
				stack = append(stack, t)
			}
			body = append(body, line)
			i++
		}
		if closed {
			calls = append(calls, ToolCall{Tool: tool, Args: args, Content: strings.Join(body, "\n")})
		} else {
			calls = append(calls, ToolCall{
				Tool:    "__refused__",
				Args:    tool,
				Content: fmt.Sprintf("unclosed fence for '%s'; call refused", tool),
			})
		}
	}
	return calls
}
