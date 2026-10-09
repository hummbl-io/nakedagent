package nakedagent

import (
	"fmt"
	"io"
	"os"
	"strings"
)

// MaxSteps is the number of tool-call rounds per human turn before control returns.
const MaxSteps = 25

// Options configures a run.
type Options struct {
	Model     string
	Host      string
	Workspace string
	LLM       LLMOptions
	Shell     ShellPolicy
	Registry  *Registry // nil means DefaultRegistry(Shell)
	Out       io.Writer // nil means os.Stdout
}

func (o *Options) registry() *Registry {
	if o.Registry == nil {
		o.Registry = DefaultRegistry(o.Shell)
	}
	return o.Registry
}

func (o *Options) out() io.Writer {
	if o.Out == nil {
		return os.Stdout
	}
	return o.Out
}

// Step makes one model call and runs any tool calls in its reply. It appends the reply and
// the tool results to messages and reports whether a tool ran (the caller should loop again
// without new user input).
func Step(messages *[]Message, o *Options) (bool, error) {
	reg := o.registry()
	reply, err := Chat(*messages, o.Model, o.Host, o.LLM)
	if err != nil {
		return false, err
	}
	*messages = append(*messages, Message{Role: "assistant", Content: reply})
	fmt.Fprintf(o.out(), "\n--- assistant ---\n%s\n", reply)

	calls := ParseToolCalls(reply)
	if len(calls) == 0 {
		return false, nil
	}
	for _, call := range calls {
		var result string
		tool, ok := reg.Get(strings.ToLower(call.Tool))
		if !ok {
			result = fmt.Sprintf("Error: unknown tool '%s'.", call.Tool)
		} else {
			out, err := tool.Fn(call.Args, call.Content, o.Workspace)
			if err != nil {
				result = fmt.Sprintf("Error: %T: %v", err, err)
			} else {
				result = out
			}
		}
		fmt.Fprintf(o.out(), "--- %s %s ---\n%s\n", call.Tool, call.Args, result)
		*messages = append(*messages, Message{Role: "user", Content: fmt.Sprintf("[%s output]\n%s", call.Tool, result)})
	}
	return true, nil
}

// RunUntilDone calls Step while it keeps running tools, capped at MaxSteps rounds.
func RunUntilDone(messages *[]Message, o *Options) error {
	for i := 0; i < MaxSteps; i++ {
		ran, err := Step(messages, o)
		if err != nil {
			return err
		}
		if !ran {
			return nil
		}
	}
	fmt.Fprintf(o.out(), "\n--- stopped after %d tool-call rounds; your turn ---\n", MaxSteps)
	return nil
}

// NewConversation starts a conversation with the system prompt built from the registry.
func NewConversation(o *Options) []Message {
	return []Message{{Role: "system", Content: BuildSystemPrompt(o.registry())}}
}

// Run is the one-shot mode: run prompt to completion and return the transcript.
func Run(prompt string, o *Options) ([]Message, error) {
	messages := NewConversation(o)
	messages = append(messages, Message{Role: "user", Content: prompt})
	err := RunUntilDone(&messages, o)
	return messages, err
}
