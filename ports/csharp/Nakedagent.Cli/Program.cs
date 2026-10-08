using Nakedagent;

const string Version = "0.1.0-dev";

static int Fail(string message, int code = 1)
{
    Console.Error.WriteLine($"error: {message}");
    return code;
}

static async Task<int> RunAsync(string[] argv)
{
    string model = "qwen2.5-coder:7b", api = "ollama", keyEnv = Llm.DefaultApiKeyEnv, timeoutArg = Tools.DefaultShellTimeout.ToString();
    string? workspace = null, host = null, prompt = null;
    bool allowShell = false;
    var allowlist = new List<string>();

    for (int i = 0; i < argv.Length; i++)
    {
        string a = argv[i];
        string? Value()
        {
            if (a.Contains('=') && a.StartsWith("--", StringComparison.Ordinal)) return a[(a.IndexOf('=') + 1)..];
            return i + 1 < argv.Length ? argv[++i] : null;
        }
        string flag = a.StartsWith("--", StringComparison.Ordinal) && a.Contains('=') ? a[..a.IndexOf('=')] : a;
        switch (flag)
        {
            case "--version": Console.WriteLine(Version); return 0;
            case "--allow-shell": allowShell = true; break;
            case "-m" or "--model": model = Value() ?? ""; break;
            case "-w" or "--workspace": workspace = Value(); break;
            case "--host": host = Value(); break;
            case "--api": api = Value() ?? ""; break;
            case "--api-key-env": keyEnv = Value() ?? ""; break;
            case "--shell-allowlist": allowlist.Add(Value() ?? ""); break;
            case "--shell-timeout": timeoutArg = Value() ?? ""; break;
            default:
                if (a.StartsWith('-') && a.Length > 1) return Fail($"unknown option {a}", 2);
                if (prompt is not null) return Fail("only one prompt argument is allowed", 2);
                prompt = a;
                break;
        }
    }
    if (api is not ("ollama" or "openai")) return Fail($"--api must be one of ollama, openai, got: '{api}'", 2);
    if (!int.TryParse(timeoutArg, out int timeout) || timeout <= 0) return Fail("--shell-timeout must be greater than 0");
    if (string.IsNullOrEmpty(host))
    {
        if (api != "ollama") return Fail("--api openai needs --host (e.g. https://api.openai.com/v1)");
        host = Llm.DefaultHost;
    }
    var options = new Options
    {
        Model = model,
        Host = host,
        Workspace = Path.GetFullPath(workspace ?? Directory.GetCurrentDirectory()),
        Llm = new LlmOptions(api, keyEnv),
        Shell = new ShellPolicy(allowShell, allowlist.Select(p => p.Trim()).Where(p => p.Length > 0).ToList(), timeout),
    };

    try
    {
        if (prompt is not null)
        {
            await Agent.RunAsync(prompt, options);
            return 0;
        }
        var messages = Agent.NewConversation(options);
        Console.WriteLine($"nakedagent -- workspace: {options.Workspace} -- model: {options.Model}\nCtrl-D to exit.\n");
        while (true)
        {
            Console.Write("> ");
            string? line = Console.ReadLine();
            if (line is null) break;
            if (line.Trim().Length == 0) continue;
            messages.Add(new Message("user", line.Trim()));
            await Agent.RunUntilDoneAsync(messages, options);
        }
        Console.WriteLine();
        return 0;
    }
    catch (LlmException e)
    {
        return Fail(e.Message);
    }
}

return await RunAsync(args);
