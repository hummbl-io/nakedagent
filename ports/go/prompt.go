package nakedagent

import (
	"sort"
	"strings"
)

// Tool is one entry in the registry: a name (lower-case), the function and the fenced-block
// example shown to the model ("usage"; empty means the tool is listed by name only).
type Tool struct {
	Name  string
	Usage string
	Fn    ToolFunc
}

// Registry is an ordered tool registry. It is the port's plugin seam (spec section 9): an
// embedding program adds or overrides tools with Set and removes tools with Disable.
type Registry struct {
	tools []Tool
}

// Get looks a tool up by its lower-case name.
func (r *Registry) Get(name string) (Tool, bool) {
	for _, t := range r.tools {
		if t.Name == name {
			return t, true
		}
	}
	return Tool{}, false
}

// Set adds a tool, or replaces the tool of the same name in place (keeping its position).
func (r *Registry) Set(t Tool) {
	t.Name = strings.ToLower(t.Name)
	for i := range r.tools {
		if r.tools[i].Name == t.Name {
			r.tools[i] = t
			return
		}
	}
	r.tools = append(r.tools, t)
}

// Disable removes tools by name. Call it after all Set calls so that it wins over them.
func (r *Registry) Disable(names ...string) {
	drop := map[string]bool{}
	for _, n := range names {
		drop[strings.ToLower(n)] = true
	}
	kept := r.tools[:0]
	for _, t := range r.tools {
		if !drop[t.Name] {
			kept = append(kept, t)
		}
	}
	r.tools = kept
}

// Names lists the registered tool names in order.
func (r *Registry) Names() []string {
	out := make([]string, len(r.tools))
	for i, t := range r.tools {
		out[i] = t.Name
	}
	return out
}

const (
	usageShell = "```shell\nls -la\n```"
	usageRead  = "```read README.md\n```"
	usageWrite = "```write hello.txt\nHello, world!\n```"
	usagePatch = "```patch hello.txt\n" +
		"<<<<<<< SEARCH\n" +
		"Hello, world!\n" +
		"=======\n" +
		"Goodbye, world!\n" +
		">>>>>>> REPLACE\n" +
		"```"
)

// DefaultRegistry returns the four foundation tools with the given shell policy applied.
func DefaultRegistry(p ShellPolicy) *Registry {
	r := &Registry{}
	r.Set(Tool{Name: "shell", Usage: usageShell, Fn: func(a, c, w string) (string, error) {
		return ToolShell(a, c, w, p)
	}})
	r.Set(Tool{Name: "read", Usage: usageRead, Fn: ToolRead})
	r.Set(Tool{Name: "write", Usage: usageWrite, Fn: ToolWrite})
	r.Set(Tool{Name: "patch", Usage: usagePatch, Fn: ToolPatch})
	return r
}

const promptHeader = "You are nakedagent, a terminal coding agent. You have these tools, " +
	"invoked as a fenced code block whose language tag is the tool name:"

const promptRules = "Rules:\n" +
	"- One tool call at a time is safest; you may emit more than one per message\n" +
	"  if you're confident, but batched calls all run without seeing each other's\n" +
	"  results -- a call that depends on an earlier result must wait for the next\n" +
	"  message.\n" +
	"- Only emit a fenced tool block when you mean to execute it -- every tagged\n" +
	"  fence at column 0 is dispatched, including ones meant as examples.\n" +
	"- `patch`'s SEARCH text must match the file exactly (including whitespace) " +
	"and uniquely -- if it doesn't, you'll get an error back and should read the " +
	"file again before retrying.\n" +
	"- When you have no more tool calls to make, just respond normally -- that " +
	"hands control back to the user.\n"

// BuildSystemPrompt builds the system prompt from the registry (spec section 7).
func BuildSystemPrompt(r *Registry) string {
	var examples, noUsage []string
	for _, t := range r.tools {
		if t.Usage != "" {
			examples = append(examples, t.Usage)
		} else {
			noUsage = append(noUsage, t.Name)
		}
	}
	parts := []string{promptHeader, strings.Join(examples, "\n\n")}
	if len(noUsage) > 0 {
		sort.Strings(noUsage)
		quoted := make([]string, len(noUsage))
		for i, n := range noUsage {
			quoted[i] = "`" + n + "`"
		}
		parts = append(parts, "Additional tools are available (invoked the same way, as a fenced "+
			"block whose language tag is the tool name): "+strings.Join(quoted, ", ")+".")
	}
	parts = append(parts, promptRules)
	return strings.Join(parts, "\n\n")
}
