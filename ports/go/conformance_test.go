package nakedagent

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"sort"
	"strings"
	"testing"
)

// Runs the language-neutral vectors in spec/conformance/vectors (spec/conformance/README.md).

type vector = map[string]any

func loadSuite(t *testing.T, name string) []vector {
	t.Helper()
	path := filepath.Join("..", "..", "spec", "conformance", "vectors", name+".json")
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	var doc struct {
		Suite string   `json:"suite"`
		Cases []vector `json:"cases"`
	}
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatalf("parse %s: %v", path, err)
	}
	if doc.Suite != name || len(doc.Cases) == 0 {
		t.Fatalf("%s: suite %q with %d cases", path, doc.Suite, len(doc.Cases))
	}
	return doc.Cases
}

// decodeText resolves the vector value encoding (spec section 3) to text.
func decodeText(v any) string {
	switch x := v.(type) {
	case nil:
		return ""
	case string:
		return x
	case map[string]any:
		if r, ok := x["repeat"]; ok {
			pair := r.([]any)
			return strings.Repeat(pair[0].(string), int(pair[1].(float64)))
		}
		if c, ok := x["concat"]; ok {
			var sb strings.Builder
			for _, p := range c.([]any) {
				sb.WriteString(decodeText(p))
			}
			return sb.String()
		}
		if b, ok := x["b64"]; ok {
			raw, _ := base64.StdEncoding.DecodeString(b.(string))
			return string(raw)
		}
	}
	panic("not a text value")
}

func decodeBytes(v any) []byte { return []byte(decodeText(v)) }

func str(c vector, key string) string {
	if v, ok := c[key]; ok {
		return decodeText(v)
	}
	return ""
}

func boolean(c vector, key string) bool { b, _ := c[key].(bool); return b }

func strList(c vector, key string) []string {
	var out []string
	if l, ok := c[key].([]any); ok {
		for _, x := range l {
			out = append(out, x.(string))
		}
	}
	return out
}

func caseName(i int, c vector) string {
	return strings.Map(func(r rune) rune {
		if r == ' ' || r == '/' {
			return '_'
		}
		return r
	}, c["name"].(string))
}

func skipPosix(t *testing.T, c vector) {
	if runtime.GOOS == "windows" && c["requires"] == "posix" {
		t.Skip("POSIX-only vector")
	}
}

func TestToolCall(t *testing.T) {
	for i, c := range loadSuite(t, "toolcall") {
		t.Run(caseName(i, c), func(t *testing.T) {
			got := ParseToolCalls(str(c, "input"))
			var want []ToolCall
			for _, e := range c["expect"].([]any) {
				m := e.(map[string]any)
				want = append(want, ToolCall{Tool: decodeText(m["tool"]), Args: decodeText(m["args"]), Content: decodeText(m["content"])})
			}
			if !reflect.DeepEqual(got, want) {
				t.Fatalf("got %#v\nwant %#v", got, want)
			}
		})
	}
}

func TestPatchSplit(t *testing.T) {
	for i, c := range loadSuite(t, "patch_split") {
		t.Run(caseName(i, c), func(t *testing.T) {
			search, replace, err := splitSearchReplace(str(c, "input"))
			exp := c["expect"].(map[string]any)
			if msg, bad := exp["error"]; bad {
				if err == nil || err.Error() != msg.(string) {
					t.Fatalf("got err %v, want %q", err, msg)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if search != decodeText(exp["search"]) || replace != decodeText(exp["replace"]) {
				t.Fatalf("got %q / %q", search, replace)
			}
		})
	}
}

func newWorkspace(t *testing.T, files map[string]any) string {
	t.Helper()
	root, err := filepath.EvalSymlinks(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	ws := filepath.Join(root, "ws")
	if err := os.Mkdir(ws, 0o755); err != nil {
		t.Fatal(err)
	}
	for rel, v := range files {
		p := filepath.Join(ws, filepath.FromSlash(rel))
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, decodeBytes(v), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	return ws
}

func snapshot(t *testing.T, ws string) map[string]string {
	t.Helper()
	out := map[string]string{}
	filepath.Walk(ws, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return nil
		}
		rel, _ := filepath.Rel(ws, p)
		rel = filepath.ToSlash(rel)
		if strings.HasPrefix(rel, ".nakedagent/") {
			return nil
		}
		data, _ := os.ReadFile(p)
		out[rel] = string(data)
		return nil
	})
	return out
}

func TestFsTools(t *testing.T) {
	fns := map[string]ToolFunc{"read": ToolRead, "write": ToolWrite, "patch": ToolPatch}
	for i, c := range loadSuite(t, "fs_tools") {
		t.Run(caseName(i, c), func(t *testing.T) {
			files, _ := c["files"].(map[string]any)
			ws := newWorkspace(t, files)
			got, err := fns[c["tool"].(string)](str(c, "args"), str(c, "content"), ws)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			exp := c["expect"].(map[string]any)
			if want := decodeText(exp["result"]); got != want {
				t.Fatalf("result:\n got %q\nwant %q", clip(got), clip(want))
			}
			wantFiles := map[string]string{}
			for rel, v := range exp["files"].(map[string]any) {
				wantFiles[rel] = decodeText(v)
			}
			if gotFiles := snapshot(t, ws); !reflect.DeepEqual(gotFiles, wantFiles) {
				t.Fatalf("files:\n got %v\nwant %v", keys(gotFiles), keys(wantFiles))
			}
		})
	}
}

func clip(s string) string {
	if len(s) > 200 {
		return s[:200] + "..."
	}
	return s
}

func keys(m map[string]string) []string {
	var k []string
	for x := range m {
		k = append(k, x)
	}
	sort.Strings(k)
	return k
}

func TestShellAllowlist(t *testing.T) {
	for i, c := range loadSuite(t, "shell_allowlist") {
		t.Run(caseName(i, c), func(t *testing.T) {
			got := isAllowedShellCommand(c["command"].(string), strList(c, "allowlist"))
			if want := c["expect"].(bool); got != want {
				t.Fatalf("got %v, want %v", got, want)
			}
		})
	}
}

func TestShellPolicy(t *testing.T) {
	for i, c := range loadSuite(t, "shell_policy") {
		t.Run(caseName(i, c), func(t *testing.T) {
			skipPosix(t, c)
			p := ShellPolicy{AllowShell: boolean(c, "allow_shell"), Allowlist: strList(c, "shell_allowlist"), TimeoutSeconds: DefaultShellTimeout}
			if v, ok := c["shell_timeout"].(float64); ok {
				p.TimeoutSeconds = int(v)
			}
			got, err := ToolShell(str(c, "args"), str(c, "content"), t.TempDir(), p)
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if want := decodeText(c["expect"]); got != want {
				t.Fatalf("got %q\nwant %q", clip(got), clip(want))
			}
		})
	}
}

func TestPrompt(t *testing.T) {
	for i, c := range loadSuite(t, "prompt") {
		t.Run(caseName(i, c), func(t *testing.T) {
			reg := DefaultRegistry(NewShellPolicy())
			for _, n := range strList(c, "extra_tools_without_usage") {
				reg.Set(Tool{Name: n, Fn: func(a, c, w string) (string, error) { return "", nil }})
			}
			if got, want := BuildSystemPrompt(reg), decodeText(c["expect"]); got != want {
				t.Fatalf("got:\n%s\nwant:\n%s", got, want)
			}
		})
	}
}

// ---------------------------------------------------------------- llm_wire and loop

type recorded struct {
	Method string
	Path   string
	Body   any
	Auth   any
}

type scripted struct {
	srv  *httptest.Server
	reqs []recorded
}

func newScripted(script []any) *scripted {
	s := &scripted{}
	pending := append([]any(nil), script...)
	s.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		var body any
		if len(raw) > 0 {
			if err := json.Unmarshal(raw, &body); err != nil {
				body = map[string]any{"__raw__": string(raw)}
			}
		}
		var auth any
		if a := r.Header.Get("Authorization"); a != "" {
			auth = a
		}
		s.reqs = append(s.reqs, recorded{r.Method, r.URL.RequestURI(), body, auth})
		step := map[string]any{"status": float64(500), "body": "script exhausted"}
		if len(pending) > 0 {
			step = pending[0].(map[string]any)
			pending = pending[1:]
		}
		if h, ok := step["headers"].(map[string]any); ok {
			for k, v := range h {
				w.Header().Set(k, v.(string))
			}
		}
		status := 200
		if v, ok := step["status"].(float64); ok {
			status = int(v)
		}
		var payload []byte
		if sv, ok := step["body"].(string); ok {
			payload = []byte(sv)
		} else {
			payload, _ = json.Marshal(step["body"])
		}
		w.WriteHeader(status)
		w.Write(payload)
	}))
	return s
}

func toMessages(v any) []Message {
	var out []Message
	for _, m := range v.([]any) {
		mm := m.(map[string]any)
		out = append(out, Message{Role: mm["role"].(string), Content: mm["content"].(string)})
	}
	return out
}

func TestLLMWire(t *testing.T) {
	for i, c := range loadSuite(t, "llm_wire") {
		t.Run(caseName(i, c), func(t *testing.T) {
			t.Setenv("OPENAI_API_KEY", "")
			t.Setenv("CUSTOM_KEY", "")
			if env, ok := c["env"].(map[string]any); ok {
				for k, v := range env {
					t.Setenv(k, v.(string))
				}
			}
			opt := LLMOptions{API: c["api"].(string)}
			if k, ok := c["api_key_env"].(string); ok {
				opt.APIKeyEnv = k
			}
			msgs := toMessages(c["messages"])
			model := c["model"].(string)

			var reply string
			var err error
			var reqs []recorded
			addr := ""
			switch {
			case c["host"] != nil:
				reply, err = Chat(msgs, model, c["host"].(string), opt)
			case boolean(c, "unreachable"):
				l, lerr := net.Listen("tcp", "127.0.0.1:0")
				if lerr != nil {
					t.Fatal(lerr)
				}
				addr = l.Addr().String()
				l.Close()
				reply, err = Chat(msgs, model, "http://"+addr, opt)
			default:
				script, _ := c["server"].([]any)
				s := newScripted(script)
				defer s.srv.Close()
				addr = strings.TrimPrefix(s.srv.URL, "http://")
				hostPath, _ := c["host_path"].(string)
				reply, err = Chat(msgs, model, s.srv.URL+hostPath, opt)
				reqs = s.reqs
			}
			exp := c["expect"].(map[string]any)

			if boolean(c, "lenient_requests") {
				first := exp["first_request"].(map[string]any)
				if len(reqs) == 0 {
					t.Fatal("no request recorded")
				}
				checkRequest(t, reqs[0], first)
				for _, later := range reqs[1:] {
					if later.Auth != nil {
						t.Fatalf("credentials forwarded to %s", later.Path)
					}
				}
				return
			}

			wantReqs, _ := exp["requests"].([]any)
			if len(reqs) != len(wantReqs) {
				t.Fatalf("got %d requests, want %d", len(reqs), len(wantReqs))
			}
			for k := range reqs {
				checkRequest(t, reqs[k], wantReqs[k].(map[string]any))
			}
			if want, ok := exp["reply"]; ok {
				if err != nil {
					t.Fatalf("unexpected error: %v", err)
				}
				if reply != want.(string) {
					t.Fatalf("reply %q, want %q", reply, want)
				}
				return
			}
			if err == nil {
				t.Fatalf("expected an error, got reply %q", reply)
			}
			msg := err.Error()
			if addr != "" {
				msg = strings.ReplaceAll(msg, addr, "HOST:PORT")
			}
			for _, sub := range strList(exp, "error_contains") {
				if !strings.Contains(msg, sub) {
					t.Errorf("error %q lacks %q", msg, sub)
				}
			}
			for _, sub := range strList(exp, "error_absent") {
				if strings.Contains(msg, sub) {
					t.Errorf("error %q unexpectedly contains %q", msg, sub)
				}
			}
		})
	}
}

func checkRequest(t *testing.T, got recorded, want map[string]any) {
	t.Helper()
	if got.Method != want["method"].(string) || got.Path != want["path"].(string) {
		t.Fatalf("request %s %s, want %s %s", got.Method, got.Path, want["method"], want["path"])
	}
	if !reflect.DeepEqual(got.Body, want["body"]) {
		t.Fatalf("body %v, want %v", got.Body, want["body"])
	}
	if !reflect.DeepEqual(got.Auth, want["authorization"]) {
		t.Fatalf("authorization %v, want %v", got.Auth, want["authorization"])
	}
}

func TestLoop(t *testing.T) {
	for i, c := range loadSuite(t, "loop") {
		t.Run(caseName(i, c), func(t *testing.T) {
			var script []any
			for _, r := range c["replies"].([]any) {
				script = append(script, map[string]any{"status": float64(200), "body": map[string]any{"message": map[string]any{"content": r.(string)}}})
			}
			files, _ := c["files"].(map[string]any)
			ws := newWorkspace(t, files)
			s := newScripted(script)
			defer s.srv.Close()
			o := &Options{
				Model: "test-model", Host: s.srv.URL, Workspace: ws, Out: io.Discard,
				Shell: ShellPolicy{AllowShell: boolean(c, "allow_shell"), Allowlist: strList(c, "shell_allowlist"), TimeoutSeconds: DefaultShellTimeout},
			}
			if _, err := Run(str(c, "prompt"), o); err != nil {
				t.Fatalf("run: %v", err)
			}
			exp := c["expect"].(map[string]any)
			if got, want := len(s.reqs), int(exp["request_count"].(float64)); got != want {
				t.Fatalf("%d requests, want %d", got, want)
			}
			last := s.reqs[len(s.reqs)-1].Body.(map[string]any)["messages"].([]any)
			wantMsgs := exp["last_request_messages"].([]any)
			if len(last) != len(wantMsgs) {
				t.Fatalf("%d messages in last request, want %d", len(last), len(wantMsgs))
			}
			for k := range last {
				g := last[k].(map[string]any)
				w := wantMsgs[k].(map[string]any)
				content := g["content"].(string)
				if g["role"] == "system" {
					content = "$SYSTEM"
				}
				if g["role"] != w["role"] || content != decodeText(w["content"]) {
					t.Fatalf("message %d: got %v %q, want %v %q", k, g["role"], clip(content), w["role"], clip(decodeText(w["content"])))
				}
			}
			wantFiles := map[string]string{}
			for rel, v := range exp["files"].(map[string]any) {
				wantFiles[rel] = decodeText(v)
			}
			if gotFiles := snapshot(t, ws); !reflect.DeepEqual(gotFiles, wantFiles) {
				t.Fatalf("files: got %v, want %v", keys(gotFiles), keys(wantFiles))
			}
		})
	}
}
