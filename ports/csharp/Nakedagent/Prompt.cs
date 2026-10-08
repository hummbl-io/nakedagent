namespace Nakedagent;

/// <summary>A registry entry: the function plus the fenced-block example shown to the model (null: listed by name only).</summary>
public sealed record Tool(ToolFunc Fn, string? Usage = null);

/// <summary>
/// Ordered tool registry. It is the port's plugin seam (spec section 9): an embedding program adds or replaces
/// tools with <see cref="Set"/> and sends foundation tools back with <see cref="Disable"/>.
/// </summary>
public sealed class Registry
{
    private readonly OrderedDictionary<string, Tool> _tools = new();

    public Tool? Get(string name) => _tools.TryGetValue(name, out var t) ? t : null;

    /// <summary>Adds a tool, or replaces the tool of the same name in place (keeping its position).</summary>
    public Registry Set(string name, Tool tool)
    {
        _tools[name.ToLowerInvariant()] = tool;
        return this;
    }

    /// <summary>Removes tools by name. Call it after all Set calls so that it wins over them.</summary>
    public Registry Disable(params string[] names)
    {
        foreach (string n in names) _tools.Remove(n.ToLowerInvariant());
        return this;
    }

    public IEnumerable<KeyValuePair<string, Tool>> Entries => _tools;
}

public static class Prompt
{
    private const string UsageShell = "```shell\nls -la\n```";
    private const string UsageRead = "```read README.md\n```";
    private const string UsageWrite = "```write hello.txt\nHello, world!\n```";
    private const string UsagePatch =
        "```patch hello.txt\n" +
        "<<<<<<< SEARCH\n" +
        "Hello, world!\n" +
        "=======\n" +
        "Goodbye, world!\n" +
        ">>>>>>> REPLACE\n" +
        "```";

    private const string Header =
        "You are nakedagent, a terminal coding agent. You have these tools, " +
        "invoked as a fenced code block whose language tag is the tool name:";

    private const string Rules =
        "Rules:\n" +
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
        "hands control back to the user.\n";

    /// <summary>The four foundation tools with the given shell policy applied.</summary>
    public static Registry DefaultRegistry(ShellPolicy? policy = null)
    {
        var p = policy ?? ShellPolicy.Default();
        return new Registry()
            .Set("shell", new Tool((a, c, w) => Tools.Shell(a, c, w, p), UsageShell))
            .Set("read", new Tool(Tools.Read, UsageRead))
            .Set("write", new Tool(Tools.Write, UsageWrite))
            .Set("patch", new Tool(Tools.Patch, UsagePatch));
    }

    /// <summary>Builds the system prompt from the registry (spec section 7).</summary>
    public static string Build(Registry registry)
    {
        var examples = new List<string>();
        var noUsage = new List<string>();
        foreach (var (name, tool) in registry.Entries)
        {
            if (!string.IsNullOrEmpty(tool.Usage)) examples.Add(tool.Usage);
            else noUsage.Add(name);
        }
        var parts = new List<string> { Header, string.Join("\n\n", examples) };
        if (noUsage.Count > 0)
        {
            noUsage.Sort(PyUtil.CompareCodePoints);
            parts.Add("Additional tools are available (invoked the same way, as a fenced block whose language tag is the tool name): " +
                      string.Join(", ", noUsage.Select(n => $"`{n}`")) + ".");
        }
        parts.Add(Rules);
        return string.Join("\n\n", parts);
    }
}
