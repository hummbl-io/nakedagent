package nakedagent

import (
	"bufio"
	"encoding/base64"
	"encoding/json"
	"os"
	"strings"
	"testing"
)

// Differential-test harness (spec/conformance/differential): reads DIFF_IN, writes DIFF_OUT; skipped otherwise.
func TestDifferentialHarness(t *testing.T) {
	in, out := os.Getenv("DIFF_IN"), os.Getenv("DIFF_OUT")
	if in == "" {
		t.Skip("no DIFF_IN")
	}
	f, _ := os.Open(in)
	defer f.Close()
	o, _ := os.Create(out)
	defer o.Close()
	w := bufio.NewWriter(o)
	defer w.Flush()
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<24)
	for sc.Scan() {
		var c map[string]any
		json.Unmarshal(sc.Bytes(), &c)
		var r any
		switch c["op"] {
		case "toolcall":
			res := [][]string{}
			for _, x := range ParseToolCalls(c["input"].(string)) {
				res = append(res, []string{x.Tool, x.Args, x.Content})
			}
			r = res
		case "patch_split":
			s, rep, err := splitSearchReplace(c["input"].(string))
			if err != nil {
				r = map[string]string{"error": err.Error()}
			} else {
				r = []string{s, rep}
			}
		case "allowlist":
			var al []string
			for _, x := range c["allowlist"].([]any) {
				al = append(al, x.(string))
			}
			r = isAllowedShellCommand(c["cmd"].(string), al)
		case "strip":
			r = pyStrip(c["input"].(string))
		case "decode":
			b, _ := base64.StdEncoding.DecodeString(c["b64"].(string))
			r = decodeReplace(b)
		default:
			r = Truncate(strings.Repeat(c["unit"].(string), int(c["n"].(float64))))
		}
		b, _ := json.Marshal(r)
		w.WriteString(string(b) + "\n")
	}
}
