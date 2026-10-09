package nakedagent

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"
	"unicode/utf8"
)

// Defaults from the reference (spec section 8).
const (
	DefaultHost      = "http://localhost:11434"
	DefaultAPIKeyEnv = "OPENAI_API_KEY"
)

// Message is one chat message.
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// LLMOptions selects the wire format. The zero value is Ollama.
type LLMOptions struct {
	API       string // "ollama" (default) or "openai"
	APIKeyEnv string // environment variable holding the key for "openai"
}

// LLMError is the single error kind the model client returns.
type LLMError struct{ Msg string }

func (e *LLMError) Error() string { return e.Msg }

func llmErr(format string, a ...any) error { return &LLMError{Msg: fmt.Sprintf(format, a...)} }

var httpClient = &http.Client{
	Timeout: 300 * time.Second,
	CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if len(via) >= 10 {
			return errors.New("stopped after 10 redirects")
		}
		req.Header.Del("Authorization") // credentials go to the initial URL only
		return nil
	},
}

type ollamaBody struct {
	Model    string    `json:"model"`
	Messages []Message `json:"messages"`
	Stream   bool      `json:"stream"`
	Think    bool      `json:"think"`
}

type openaiBody struct {
	Model    string    `json:"model"`
	Messages []Message `json:"messages"`
	Stream   bool      `json:"stream"`
}

func marshal(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil {
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

func firstChars(b []byte, n int) string {
	s := decodeReplace(b)
	if utf8.RuneCountInString(s) <= n {
		return s
	}
	i := 0
	for k := 0; k < n; k++ {
		_, size := utf8.DecodeRuneInString(s[i:])
		i += size
	}
	return s[:i]
}

// Chat sends one non-streaming chat request and returns the assistant reply text.
// Bearer credentials are sent only to the initial URL, never on a redirect.
func Chat(messages []Message, model, host string, opt LLMOptions) (string, error) {
	api := opt.API
	if api == "" {
		api = "ollama"
	}
	keyEnv := opt.APIKeyEnv
	if keyEnv == "" {
		keyEnv = DefaultAPIKeyEnv
	}
	if api != "ollama" && api != "openai" {
		return "", llmErr("--api must be one of ollama, openai, got: %s", pyRepr(api))
	}
	if host == "" {
		host = DefaultHost
	}
	if u, err := url.Parse(host); err != nil || (u.Scheme != "http" && u.Scheme != "https") || u.Host == "" {
		return "", llmErr("--host must be an http:// or https:// URL, got: %s", pyRepr(host))
	}

	var name, endpoint string
	var body []byte
	var err error
	if api == "ollama" {
		name = "Ollama"
		endpoint = host + "/api/chat"
		body, err = marshal(ollamaBody{Model: model, Messages: messages, Stream: false, Think: false})
	} else {
		name = "OpenAI-compatible API"
		endpoint = strings.TrimRight(host, "/") + "/chat/completions"
		body, err = marshal(openaiBody{Model: model, Messages: messages, Stream: false})
	}
	if err != nil {
		return "", err
	}
	req, err := http.NewRequest(http.MethodPost, endpoint, bytes.NewReader(body))
	if err != nil {
		return "", llmErr("--host must be an http:// or https:// URL, got: %s", pyRepr(host))
	}
	req.Header.Set("Content-Type", "application/json")
	if api == "openai" {
		if key := os.Getenv(keyEnv); key != "" {
			req.Header.Set("Authorization", "Bearer "+key)
		}
	}

	resp, err := httpClient.Do(req)
	if err != nil {
		tip := ""
		if api == "ollama" {
			tip = " Is `ollama serve` running?"
		}
		return "", llmErr("could not reach %s at %s (%v).%s", name, host, err, tip)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		return "", llmErr("could not reach %s at %s (%v).", name, host, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		hint := ""
		if api == "openai" && (resp.StatusCode == 401 || resp.StatusCode == 403) {
			hint = fmt.Sprintf(" (check the key in $%s)", keyEnv)
		}
		msg := fmt.Sprintf("%s at %s returned HTTP %d %s%s", name, host, resp.StatusCode,
			http.StatusText(resp.StatusCode), hint)
		if detail := firstChars(raw, 200); detail != "" {
			msg += ": " + detail
		}
		return "", &LLMError{Msg: msg}
	}

	var data any
	if err := json.Unmarshal(raw, &data); err != nil {
		return "", llmErr("%s at %s returned a non-JSON response: %v", name, host, err)
	}
	shapeErr := func() error {
		return llmErr("unexpected %s response shape: %s", name, firstChars(raw, 300))
	}
	var content any
	if api == "ollama" {
		m, _ := data.(map[string]any)
		msg, ok := m["message"].(map[string]any)
		if !ok {
			return "", shapeErr()
		}
		c, ok := msg["content"]
		if !ok {
			return "", shapeErr()
		}
		content = c
	} else {
		m, _ := data.(map[string]any)
		choices, ok := m["choices"].([]any)
		if !ok || len(choices) == 0 {
			return "", shapeErr()
		}
		first, ok := choices[0].(map[string]any)
		if !ok {
			return "", shapeErr()
		}
		msg, ok := first["message"].(map[string]any)
		if !ok {
			return "", shapeErr()
		}
		c, ok := msg["content"]
		if !ok {
			return "", shapeErr()
		}
		content = c
	}
	switch c := content.(type) {
	case nil:
		return "", nil
	case string:
		return c, nil
	default:
		return "", shapeErr()
	}
}
