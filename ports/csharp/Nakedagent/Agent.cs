namespace Nakedagent;

/// <summary>Configuration for a run.</summary>
public sealed class Options
{
    public required string Model { get; init; }
    public string Host { get; init; } = Nakedagent.Llm.DefaultHost;
    public required string Workspace { get; init; }
    public LlmOptions Llm { get; init; } = new();
    public ShellPolicy Shell { get; init; } = ShellPolicy.Default();
    /// <summary>Defaults to the foundation tools with <see cref="Shell"/> applied.</summary>
    public Registry? Registry { get; set; }
    /// <summary>Where progress text goes; defaults to stdout.</summary>
    public Action<string>? Out { get; init; }

    internal Registry Reg => Registry ??= Prompt.DefaultRegistry(Shell);
    internal void Write(string text) { if (Out is null) Console.Out.Write(text); else Out(text); }
}

/// <summary>The agent loop (spec section 9).</summary>
public static class Agent
{
    public const int MaxSteps = 25;

    /// <summary>One model call plus any tool calls in its reply. Returns true if a tool ran.</summary>
    public static async Task<bool> StepAsync(List<Message> messages, Options o)
    {
        string reply = await Nakedagent.Llm.ChatAsync(messages, o.Model, o.Host, o.Llm).ConfigureAwait(false);
        messages.Add(new Message("assistant", reply));
        o.Write($"\n--- assistant ---\n{reply}\n");

        var calls = ToolCallParser.Parse(reply);
        if (calls.Count == 0) return false;
        foreach (var call in calls)
        {
            string result;
            var tool = o.Reg.Get(call.Tool.ToLowerInvariant());
            if (tool is null)
            {
                result = $"Error: unknown tool '{call.Tool}'.";
            }
            else
            {
                try { result = tool.Fn(call.Args, call.Content, o.Workspace); }
                catch (Exception e) { result = $"Error: {e.GetType().Name}: {e.Message}"; }
            }
            o.Write($"--- {call.Tool} {call.Args} ---\n{result}\n");
            messages.Add(new Message("user", $"[{call.Tool} output]\n{result}"));
        }
        return true;
    }

    /// <summary>Calls <see cref="StepAsync"/> while it keeps running tools, capped at <see cref="MaxSteps"/> rounds.</summary>
    public static async Task RunUntilDoneAsync(List<Message> messages, Options o)
    {
        for (int i = 0; i < MaxSteps; i++)
        {
            if (!await StepAsync(messages, o).ConfigureAwait(false)) return;
        }
        o.Write($"\n--- stopped after {MaxSteps} tool-call rounds; your turn ---\n");
    }

    public static List<Message> NewConversation(Options o) => [new Message("system", Prompt.Build(o.Reg))];

    /// <summary>One-shot: run the prompt to completion and return the transcript.</summary>
    public static async Task<List<Message>> RunAsync(string prompt, Options o)
    {
        var messages = NewConversation(o);
        messages.Add(new Message("user", prompt));
        await RunUntilDoneAsync(messages, o).ConfigureAwait(false);
        return messages;
    }
}
