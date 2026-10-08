package nakedagent

import (
	"errors"
	"strings"
)

// shlexSplit splits s with POSIX word-splitting rules (Python shlex.split defaults, spec
// section 6): single quotes are literal; inside double quotes a backslash escapes only
// backslash and double quote; outside quotes a backslash escapes the next character; '#'
// is not a comment; an unterminated quote or trailing backslash is an error.
func shlexSplit(s string) ([]string, error) {
	var tokens []string
	var cur strings.Builder
	inTok := false
	rs := []rune(s)
	for i := 0; i < len(rs); i++ {
		c := rs[i]
		switch {
		case c == ' ' || c == '\t' || c == '\r' || c == '\n':
			if inTok {
				tokens = append(tokens, cur.String())
				cur.Reset()
				inTok = false
			}
		case c == '\\':
			if i+1 >= len(rs) {
				return nil, errors.New("No escaped character")
			}
			i++
			cur.WriteRune(rs[i])
			inTok = true
		case c == '\'':
			inTok = true
			j := i + 1
			for j < len(rs) && rs[j] != '\'' {
				cur.WriteRune(rs[j])
				j++
			}
			if j >= len(rs) {
				return nil, errors.New("No closing quotation")
			}
			i = j
		case c == '"':
			inTok = true
			j := i + 1
			for {
				if j >= len(rs) {
					return nil, errors.New("No closing quotation")
				}
				d := rs[j]
				if d == '"' {
					break
				}
				if d == '\\' {
					if j+1 >= len(rs) {
						return nil, errors.New("No escaped character")
					}
					nx := rs[j+1]
					if nx == '"' || nx == '\\' {
						cur.WriteRune(nx)
					} else {
						cur.WriteRune('\\')
						cur.WriteRune(nx)
					}
					j += 2
					continue
				}
				cur.WriteRune(d)
				j++
			}
			i = j
		default:
			cur.WriteRune(c)
			inTok = true
		}
	}
	if inTok {
		tokens = append(tokens, cur.String())
	}
	return tokens, nil
}

// isAllowedShellCommand reports whether cmd matches any allowlist entry by argv token
// prefix. A command or pattern that fails to split never matches (spec section 6).
func isAllowedShellCommand(cmd string, allowlist []string) bool {
	if len(allowlist) == 0 {
		return false
	}
	cmdArgv, err := shlexSplit(pyStrip(cmd))
	if err != nil || len(cmdArgv) == 0 {
		return false
	}
	for _, pattern := range allowlist {
		item := pyStrip(pattern)
		if item == "" {
			continue
		}
		pat, err := shlexSplit(item)
		if err != nil || len(pat) == 0 {
			continue
		}
		if len(cmdArgv) < len(pat) {
			continue
		}
		match := true
		for i := range pat {
			if cmdArgv[i] != pat[i] {
				match = false
				break
			}
		}
		if match {
			return true
		}
	}
	return false
}
