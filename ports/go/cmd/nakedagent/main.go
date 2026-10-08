// Command nakedagent is the Go port of the nakedagent terminal coding agent.
package main

import (
	"bufio"
	"errors"
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	nakedagent "github.com/hummbl-io/nakedagent/ports/go"
)

const version = "0.1.0-dev"

type listFlag []string

func (l *listFlag) String() string     { return strings.Join(*l, ",") }
func (l *listFlag) Set(v string) error { *l = append(*l, v); return nil }

func main() { os.Exit(run(os.Args[1:])) }

func run(args []string) int {
	fs := flag.NewFlagSet("nakedagent", flag.ContinueOnError)
	model := fs.String("m", "qwen2.5-coder:7b", "model name or Ollama tag")
	fs.StringVar(model, "model", "qwen2.5-coder:7b", "model name or Ollama tag")
	workspace := fs.String("w", "", "workspace directory (default: current directory)")
	fs.StringVar(workspace, "workspace", "", "workspace directory (default: current directory)")
	host := fs.String("host", "", "model server URL (default http://localhost:11434 for ollama; required for --api openai, including the version path)")
	api := fs.String("api", "ollama", "wire format: ollama (local, default) or openai (any OpenAI-compatible server)")
	keyEnv := fs.String("api-key-env", nakedagent.DefaultAPIKeyEnv, "environment variable holding the API key for --api openai")
	allowShell := fs.Bool("allow-shell", false, "allow shell tool execution (non-interactive, allowlisted commands only)")
	var allowlist listFlag
	fs.Var(&allowlist, "shell-allowlist", "allowed shell command prefix when --allow-shell is set (repeatable)")
	timeout := fs.Int("shell-timeout", nakedagent.DefaultShellTimeout, "timeout in seconds for shell tool execution")
	showVersion := fs.Bool("version", false, "print the version and exit")

	// Like argparse, accept the prompt before, between or after flags.
	var prompt string
	rest := args
	for {
		if err := fs.Parse(rest); err != nil {
			if errors.Is(err, flag.ErrHelp) {
				return 0
			}
			return 2
		}
		if fs.NArg() == 0 {
			break
		}
		if prompt == "" {
			prompt = fs.Arg(0)
		} else {
			fmt.Fprintln(os.Stderr, "error: only one prompt argument is allowed")
			return 2
		}
		rest = fs.Args()[1:]
	}
	if *showVersion {
		fmt.Println(version)
		return 0
	}
	if *api != "ollama" && *api != "openai" {
		fmt.Fprintf(os.Stderr, "error: --api must be one of ollama, openai, got: %q\n", *api)
		return 2
	}
	if *timeout <= 0 {
		fmt.Fprintln(os.Stderr, "error: --shell-timeout must be greater than 0")
		return 1
	}
	h := *host
	if h == "" {
		if *api != "ollama" {
			fmt.Fprintln(os.Stderr, "error: --api openai needs --host (e.g. https://api.openai.com/v1)")
			return 1
		}
		h = nakedagent.DefaultHost
	}
	ws := *workspace
	if ws == "" {
		wd, err := os.Getwd()
		if err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			return 1
		}
		ws = wd
	}
	ws, err := filepath.Abs(ws)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		return 1
	}

	var patterns []string
	for _, p := range allowlist {
		if p = strings.TrimSpace(p); p != "" {
			patterns = append(patterns, p)
		}
	}
	o := &nakedagent.Options{
		Model:     *model,
		Host:      h,
		Workspace: ws,
		LLM:       nakedagent.LLMOptions{API: *api, APIKeyEnv: *keyEnv},
		Shell:     nakedagent.ShellPolicy{AllowShell: *allowShell, Allowlist: patterns, TimeoutSeconds: *timeout},
	}

	if prompt != "" {
		if _, err := nakedagent.Run(prompt, o); err != nil {
			fmt.Fprintf(os.Stderr, "error: %v\n", err)
			return 1
		}
		return 0
	}
	return interactive(o)
}

func interactive(o *nakedagent.Options) int {
	messages := nakedagent.NewConversation(o)
	fmt.Printf("nakedagent -- workspace: %s -- model: %s\nCtrl-D to exit.\n\n", o.Workspace, o.Model)
	in := bufio.NewReader(os.Stdin)
	for {
		fmt.Print("> ")
		line, err := in.ReadString('\n')
		if text := strings.TrimSpace(line); text != "" {
			messages = append(messages, nakedagent.Message{Role: "user", Content: text})
			if rerr := nakedagent.RunUntilDone(&messages, o); rerr != nil {
				fmt.Fprintf(os.Stderr, "error: %v\n", rerr)
				return 1
			}
		}
		if err != nil {
			fmt.Println()
			return 0
		}
	}
}
