// Package nakedagent is the Go port of the nakedagent foundation (spec/SPEC.md v0.1).
//
// It uses only the Go standard library. The helpers in this file reproduce the few
// Python string behaviours the reference relies on, so the port matches it exactly.
package nakedagent

import (
	"strings"
	"unicode"
	"unicode/utf8"
)

// pyIsSpace reports whether r is whitespace in the sense of Python's str.isspace,
// which is unicode.IsSpace plus the C0 separators U+001C..U+001F.
func pyIsSpace(r rune) bool {
	return unicode.IsSpace(r) || (r >= 0x1c && r <= 0x1f)
}

// pyStrip is Python's str.strip() with no arguments.
func pyStrip(s string) string { return strings.TrimFunc(s, pyIsSpace) }

// pyRstrip is Python's str.rstrip() with no arguments.
func pyRstrip(s string) string { return strings.TrimRightFunc(s, pyIsSpace) }

func isLineBreak(r rune) bool {
	switch r {
	case '\n', '\r', 0x0b, 0x0c, 0x1c, 0x1d, 0x1e, 0x85, 0x2028, 0x2029:
		return true
	}
	return false
}

// pySplitLines is Python's str.splitlines(): it splits on more than LF (spec section 11,
// quirk 3) and drops a final empty segment.
func pySplitLines(s string) []string {
	var out []string
	start := 0
	for i := 0; i < len(s); {
		r, size := utf8.DecodeRuneInString(s[i:])
		if isLineBreak(r) {
			out = append(out, s[start:i])
			if r == '\r' && i+size < len(s) && s[i+size] == '\n' {
				size++
			}
			i += size
			start = i
			continue
		}
		i += size
	}
	if start < len(s) {
		out = append(out, s[start:])
	}
	return out
}

// maximalSubpart returns how many bytes Python's "replace" error handler consumes for
// one invalid sequence starting at b[0]: the longest prefix that could begin a valid
// UTF-8 sequence (at least 1).
func maximalSubpart(b []byte) int {
	c := b[0]
	var need int
	var lo, hi byte = 0x80, 0xBF
	switch {
	case c >= 0xC2 && c <= 0xDF:
		need = 1
	case c == 0xE0:
		need, lo = 2, 0xA0
	case (c >= 0xE1 && c <= 0xEC) || c == 0xEE || c == 0xEF:
		need = 2
	case c == 0xED:
		need, hi = 2, 0x9F
	case c == 0xF0:
		need, lo = 3, 0x90
	case c >= 0xF1 && c <= 0xF3:
		need = 3
	case c == 0xF4:
		need, hi = 3, 0x8F
	default:
		return 1
	}
	n := 1
	for k := 1; k <= need && k < len(b); k++ {
		l, h := byte(0x80), byte(0xBF)
		if k == 1 {
			l, h = lo, hi
		}
		if b[k] < l || b[k] > h {
			break
		}
		n++
	}
	return n
}

// decodeReplace decodes UTF-8 like Python's bytes.decode("utf-8", errors="replace").
func decodeReplace(b []byte) string {
	var sb strings.Builder
	for i := 0; i < len(b); {
		r, size := utf8.DecodeRune(b[i:])
		if r == utf8.RuneError && size <= 1 {
			sb.WriteRune(utf8.RuneError)
			i += maximalSubpart(b[i:])
			continue
		}
		sb.WriteRune(r)
		i += size
	}
	return sb.String()
}

// pyRepr renders s like Python's repr() for the plain cases error messages need.
func pyRepr(s string) string {
	q := '\''
	if strings.ContainsRune(s, '\'') && !strings.ContainsRune(s, '"') {
		q = '"'
	}
	var sb strings.Builder
	sb.WriteRune(q)
	for _, r := range s {
		switch {
		case r == q || r == '\\':
			sb.WriteRune('\\')
			sb.WriteRune(r)
		case r == '\n':
			sb.WriteString(`\n`)
		case r == '\r':
			sb.WriteString(`\r`)
		case r == '\t':
			sb.WriteString(`\t`)
		case r < 0x20 || r == 0x7f:
			sb.WriteString(`\x`)
			sb.WriteString(string("0123456789abcdef"[r>>4]))
			sb.WriteString(string("0123456789abcdef"[r&0xf]))
		default:
			sb.WriteRune(r)
		}
	}
	sb.WriteRune(q)
	return sb.String()
}
