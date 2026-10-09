// Runs the language-neutral vectors in spec/conformance/vectors (spec/conformance/README.md).
// A tiny console test runner: .NET ships no test framework in the BCL and the port takes no NuGet packages.
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json;
using Nakedagent;

// `dotnet Nakedagent.Tests.dll --diff cases.jsonl > out.jsonl` (after a build) is the differential-test harness
// (spec/conformance/differential); with no arguments it runs the conformance vectors.
if (args.Length == 2 && args[0] == "--diff") return Differential.Run(args[1]);

var runner = new Runner();
Vectors.Register(runner);
return await runner.RunAllAsync();

internal static class Differential
{
    public static int Run(string path)
    {
        var o = new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping };
        var stdout = new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { NewLine = "\n" };
        foreach (string line in File.ReadLines(path))
        {
            if (line.Length == 0) continue;
            using var doc = JsonDocument.Parse(line);
            var c = doc.RootElement;
            string Str(string k) => c.GetProperty(k).GetString()!;
            object? result = c.GetProperty("op").GetString() switch
            {
                "toolcall" => ToolCallParser.Parse(Str("input")).Select(x => new[] { x.Tool, x.Args, x.Content }).ToList(),
                "patch_split" => PatchSplit(Str("input")),
                "allowlist" => Shlex.Allowed(Str("cmd"), c.GetProperty("allowlist").EnumerateArray().Select(x => x.GetString()!).ToList()),
                "strip" => PyUtil.Strip(Str("input")),
                "decode" => PyUtil.DecodeReplace(Convert.FromBase64String(Str("b64"))),
                "trunc" => Tools.Truncate(string.Concat(Enumerable.Repeat(Str("unit"), c.GetProperty("n").GetInt32()))),
                var op => throw new InvalidOperationException("unknown op " + op),
            };
            stdout.WriteLine(JsonSerializer.Serialize(result, o));
        }
        stdout.Flush();
        return 0;
    }

    private static object PatchSplit(string input)
    {
        try { var (s, r) = Tools.SplitSearchReplace(input); return new[] { s, r }; }
        catch (Tools.PatchException e) { return new Dictionary<string, string> { ["error"] = e.Message }; }
    }
}

internal sealed class Runner
{
    private readonly List<(string Name, Func<Task> Fn, bool Skip)> _tests = [];
    public void Add(string name, Func<Task> fn, bool skip = false) => _tests.Add((name, fn, skip));

    public async Task<int> RunAllAsync()
    {
        int pass = 0, fail = 0, skip = 0;
        foreach (var (name, fn, skipIt) in _tests)
        {
            if (skipIt) { skip++; continue; }
            try { await fn(); pass++; }
            catch (SkipException e) { skip++; Console.WriteLine($"skip  {name}: {e.Message}"); }
            catch (Exception e) { fail++; Console.WriteLine($"FAIL  {name}\n      {e.Message.ReplaceLineEndings("\n      ")}"); }
        }
        Console.WriteLine($"{pass} passed, {fail} failed, {skip} skipped ({_tests.Count} tests)");
        return fail == 0 ? 0 : 1;
    }
}

internal sealed class SkipException(string message) : Exception(message);

internal sealed class AssertionException(string message) : Exception(message);

internal static class Check
{
    public static void Equal<T>(T want, T got, string? what = null)
    {
        if (!EqualityComparer<T>.Default.Equals(want, got))
            throw new AssertionException($"{what ?? "values"} differ:\n  want {Clip(want)}\n  got  {Clip(got)}");
    }

    public static void True(bool cond, string message)
    {
        if (!cond) throw new AssertionException(message);
    }

    public static string Clip<T>(T v)
    {
        string s = v?.ToString() ?? "null";
        return (s.Length > 200 ? s[..200] + "..." : s).ReplaceLineEndings("\\n");
    }
}

internal static class Vectors
{
    private static readonly string Dir = FindVectors();
    private static readonly bool IsWin = OperatingSystem.IsWindows();
    private static readonly bool ForcePosix = Environment.GetEnvironmentVariable("NAKEDAGENT_FORCE_POSIX_VECTORS") == "1";

    private static string FindVectors()
    {
        for (var d = new DirectoryInfo(AppContext.BaseDirectory); d is not null; d = d.Parent)
        {
            string candidate = Path.Combine(d.FullName, "spec", "conformance", "vectors");
            if (Directory.Exists(candidate)) return candidate;
        }
        throw new DirectoryNotFoundException("spec/conformance/vectors not found above " + AppContext.BaseDirectory);
    }

    private static List<JsonElement> Load(string suite)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Dir, suite + ".json")));
        Check.Equal(suite, doc.RootElement.GetProperty("suite").GetString(), "suite name");
        return doc.RootElement.GetProperty("cases").EnumerateArray().Select(e => e.Clone()).ToList();
    }

    // Vector value encoding (spec section 3).
    private static string Text(JsonElement? v)
    {
        if (v is null || v.Value.ValueKind == JsonValueKind.Null) return "";
        var e = v.Value;
        if (e.ValueKind == JsonValueKind.String) return e.GetString()!;
        if (e.TryGetProperty("repeat", out var r)) return string.Concat(Enumerable.Repeat(r[0].GetString()!, r[1].GetInt32()));
        if (e.TryGetProperty("concat", out var c)) return string.Concat(c.EnumerateArray().Select(x => Text(x)));
        if (e.TryGetProperty("b64", out var b)) return new UTF8Encoding(false).GetString(Convert.FromBase64String(b.GetString()!));
        throw new InvalidOperationException("not a text value");
    }

    private static byte[] Bytes(JsonElement v) =>
        v.ValueKind == JsonValueKind.Object && v.TryGetProperty("b64", out var b)
            ? Convert.FromBase64String(b.GetString()!)
            : new UTF8Encoding(false).GetBytes(Text(v));

    private static JsonElement? Prop(JsonElement c, string key) => c.TryGetProperty(key, out var v) ? v : null;
    private static string Str(JsonElement c, string key) => Text(Prop(c, key));
    private static bool Flag(JsonElement c, string key) => Prop(c, key) is { ValueKind: JsonValueKind.True };

    private static List<string> StrList(JsonElement c, string key) =>
        Prop(c, key) is { ValueKind: JsonValueKind.Array } a ? a.EnumerateArray().Select(x => x.GetString()!).ToList() : [];

    private static bool SkipPosix(JsonElement c) =>
        IsWin && !ForcePosix && Prop(c, "requires") is { ValueKind: JsonValueKind.String } r && r.GetString() == "posix";

    // ---------------------------------------------------------------- fixtures

    private static void WriteFiles(string dir, JsonElement? files)
    {
        if (files is not { ValueKind: JsonValueKind.Object } f) return;
        foreach (var p in f.EnumerateObject())
        {
            string path = Path.Combine(dir, p.Name.Replace('/', Path.DirectorySeparatorChar));
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            File.WriteAllBytes(path, Bytes(p.Value));
        }
    }

    private static string NewWorkspace(JsonElement? files)
    {
        var tmp = Directory.CreateTempSubdirectory("ng-cs-");
        string root = tmp.ResolveLinkTarget(true)?.FullName ?? tmp.FullName;
        string ws = Path.Combine(root, "ws");
        Directory.CreateDirectory(ws);
        WriteFiles(ws, files);
        return ws;
    }

    // Workspace plus, for cases with `outside` or `symlinks`, the sibling `outside` directory and the symlink
    // fixtures. Throws SkipException where symlinks cannot be created.
    private static (string Ws, string? Outside) NewCaseRoot(JsonElement c)
    {
        string ws = NewWorkspace(Prop(c, "files"));
        if (Prop(c, "outside") is null && Prop(c, "symlinks") is null) return (ws, null);
        string outside = Path.Combine(Path.GetDirectoryName(ws)!, "outside");
        Directory.CreateDirectory(outside);
        WriteFiles(outside, Prop(c, "outside"));
        if (Prop(c, "symlinks") is { ValueKind: JsonValueKind.Object } links)
        {
            foreach (var l in links.EnumerateObject())
            {
                string lp = Path.Combine(ws, l.Name.Replace('/', Path.DirectorySeparatorChar));
                Directory.CreateDirectory(Path.GetDirectoryName(lp)!);
                string target = l.Value.GetString()!.Replace('/', Path.DirectorySeparatorChar);
                try
                {
                    string resolved = Path.GetFullPath(Path.Combine(Path.GetDirectoryName(lp)!, target));
                    if (Directory.Exists(resolved)) Directory.CreateSymbolicLink(lp, target);
                    else File.CreateSymbolicLink(lp, target);
                }
                catch (Exception e) when (e is UnauthorizedAccessException or IOException or PlatformNotSupportedException)
                {
                    throw new SkipException("cannot create symlinks here: " + e.Message);
                }
            }
        }
        return (ws, outside);
    }

    private static Dictionary<string, byte[]> Snapshot(string root)
    {
        var output = new Dictionary<string, byte[]>();
        void Walk(string dir)
        {
            foreach (string entry in Directory.EnumerateFileSystemEntries(dir))
            {
                if (new FileInfo(entry).LinkTarget is not null) continue; // fixtures, not tool output
                if (Directory.Exists(entry)) { Walk(entry); continue; }
                string rel = Path.GetRelativePath(root, entry).Replace(Path.DirectorySeparatorChar, '/');
                if (!rel.StartsWith(".nakedagent/", StringComparison.Ordinal)) output[rel] = File.ReadAllBytes(entry);
            }
        }
        Walk(root);
        return output;
    }

    private static void ExpectFiles(string dir, JsonElement expected, string what)
    {
        var got = Snapshot(dir);
        var want = expected.EnumerateObject().ToDictionary(p => p.Name, p => Bytes(p.Value));
        Check.Equal(string.Join(",", want.Keys.Order(StringComparer.Ordinal)), string.Join(",", got.Keys.Order(StringComparer.Ordinal)), what + " (file set)");
        foreach (var (rel, bytes) in want)
            Check.True(bytes.AsSpan().SequenceEqual(got[rel]), $"{what}: content of {rel} differs");
    }

    // ---------------------------------------------------------------- scripted server

    private sealed record Recorded(string Method, string Path, JsonElement? Body, string? Authorization);

    private sealed class ScriptedServer : IDisposable
    {
        private readonly TcpListener _listener = new(IPAddress.Loopback, 0);
        private readonly Queue<JsonElement> _script;
        public List<Recorded> Requests { get; } = [];
        public string Addr { get; }
        public string Url => "http://" + Addr;
        private readonly Task _loop;

        public ScriptedServer(IEnumerable<JsonElement> script)
        {
            _script = new Queue<JsonElement>(script);
            _listener.Start();
            Addr = "127.0.0.1:" + ((IPEndPoint)_listener.LocalEndpoint).Port;
            _loop = Task.Run(AcceptLoop);
        }

        private static readonly Dictionary<int, string> Reasons = new()
        {
            [200] = "OK", [302] = "Found", [401] = "Unauthorized", [403] = "Forbidden", [500] = "Internal Server Error",
        };

        private async Task AcceptLoop()
        {
            while (true)
            {
                TcpClient client;
                try { client = await _listener.AcceptTcpClientAsync(); }
                catch (Exception e) when (e is ObjectDisposedException or SocketException or InvalidOperationException) { return; }
                try { await Handle(client); }
                catch (IOException) { }
                finally { client.Dispose(); }
            }
        }

        private async Task Handle(TcpClient client)
        {
            var stream = client.GetStream();
            var buf = new MemoryStream();
            var one = new byte[1];
            // read headers up to the blank line
            while (!EndsWithBlankLine(buf)) { if (await stream.ReadAsync(one) == 0) return; buf.WriteByte(one[0]); }
            string head = Encoding.ASCII.GetString(buf.ToArray());
            string[] lines = head.Split("\r\n", StringSplitOptions.RemoveEmptyEntries);
            string[] first = lines[0].Split(' ');
            var headers = lines.Skip(1).Select(l => l.Split(": ", 2)).Where(p => p.Length == 2).ToDictionary(p => p[0].ToLowerInvariant(), p => p[1]);
            int len = headers.TryGetValue("content-length", out var cl) ? int.Parse(cl) : 0;
            var body = new byte[len];
            for (int got = 0; got < len;) { int n = await stream.ReadAsync(body.AsMemory(got, len - got)); if (n == 0) break; got += n; }
            JsonElement? parsed = null;
            if (len > 0)
            {
                try { parsed = JsonDocument.Parse(body).RootElement.Clone(); }
                catch (JsonException) { parsed = JsonDocument.Parse(JsonSerializer.Serialize(new { __raw__ = Encoding.UTF8.GetString(body) })).RootElement.Clone(); }
            }
            lock (Requests) Requests.Add(new Recorded(first[0], first[1], parsed, headers.GetValueOrDefault("authorization")));

            JsonElement step = _script.Count > 0 ? _script.Dequeue() : JsonDocument.Parse("""{"status":500,"body":"script exhausted"}""").RootElement;
            int status = step.TryGetProperty("status", out var s) ? s.GetInt32() : 200;
            string payload = step.GetProperty("body") is { ValueKind: JsonValueKind.String } bs ? bs.GetString()! : step.GetProperty("body").GetRawText();
            byte[] payloadBytes = Encoding.UTF8.GetBytes(payload);
            var sb = new StringBuilder($"HTTP/1.1 {status} {Reasons.GetValueOrDefault(status, "Status")}\r\n");
            if (step.TryGetProperty("headers", out var hs))
                foreach (var h in hs.EnumerateObject()) sb.Append($"{h.Name}: {h.Value.GetString()}\r\n");
            sb.Append($"Content-Length: {payloadBytes.Length}\r\nConnection: close\r\n\r\n");
            await stream.WriteAsync(Encoding.ASCII.GetBytes(sb.ToString()));
            await stream.WriteAsync(payloadBytes);
            await stream.FlushAsync();
        }

        private static bool EndsWithBlankLine(MemoryStream m)
        {
            if (m.Length < 4) return false;
            var b = m.GetBuffer();
            long l = m.Length;
            return b[l - 4] == '\r' && b[l - 3] == '\n' && b[l - 2] == '\r' && b[l - 1] == '\n';
        }

        public void Dispose()
        {
            _listener.Stop();
            try { _loop.Wait(1000); } catch (AggregateException) { }
        }
    }

    private static string ClosedAddress()
    {
        var l = new TcpListener(IPAddress.Loopback, 0);
        l.Start();
        string addr = "127.0.0.1:" + ((IPEndPoint)l.LocalEndpoint).Port;
        l.Stop();
        return addr;
    }

    private static async Task WithEnv(JsonElement? env, Func<Task> body)
    {
        var set = env is { ValueKind: JsonValueKind.Object } e ? e.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!) : [];
        string[] names = ["OPENAI_API_KEY", "CUSTOM_KEY", .. set.Keys];
        var saved = names.Distinct().ToDictionary(n => n, n => Environment.GetEnvironmentVariable(n));
        foreach (string n in new[] { "OPENAI_API_KEY", "CUSTOM_KEY" }) Environment.SetEnvironmentVariable(n, null);
        foreach (var (k, v) in set) Environment.SetEnvironmentVariable(k, v);
        try { await body(); }
        finally { foreach (var (n, v) in saved) Environment.SetEnvironmentVariable(n, v); }
    }

    private static void CheckRequest(Recorded got, JsonElement want)
    {
        Check.Equal(want.GetProperty("method").GetString(), got.Method, "method");
        Check.Equal(want.GetProperty("path").GetString(), got.Path, "path");
        string wantBody = want.GetProperty("body").GetRawText();
        string gotBody = got.Body?.GetRawText() ?? "null";
        Check.True(JsonEquals(want.GetProperty("body"), got.Body), $"body differs:\n  want {Check.Clip(wantBody)}\n  got  {Check.Clip(gotBody)}");
        string? wantAuth = want.GetProperty("authorization").ValueKind == JsonValueKind.Null ? null : want.GetProperty("authorization").GetString();
        Check.Equal(wantAuth, got.Authorization, "authorization");
    }

    private static bool JsonEquals(JsonElement a, JsonElement? bn)
    {
        if (bn is null) return a.ValueKind == JsonValueKind.Null;
        var b = bn.Value;
        if (a.ValueKind != b.ValueKind) return false;
        switch (a.ValueKind)
        {
            case JsonValueKind.Object:
                var pa = a.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal).ToList();
                var pb = b.EnumerateObject().OrderBy(p => p.Name, StringComparer.Ordinal).ToList();
                return pa.Count == pb.Count && pa.Zip(pb).All(t => t.First.Name == t.Second.Name && JsonEquals(t.First.Value, t.Second.Value));
            case JsonValueKind.Array:
                var la = a.EnumerateArray().ToList();
                var lb = b.EnumerateArray().ToList();
                return la.Count == lb.Count && la.Zip(lb).All(t => JsonEquals(t.First, t.Second));
            case JsonValueKind.String: return a.GetString() == b.GetString();
            case JsonValueKind.Number: return a.GetDouble() == b.GetDouble();
            default: return true;
        }
    }

    // ---------------------------------------------------------------- suites

    public static void Register(Runner r)
    {
        foreach (var c in Load("toolcall"))
            r.Add($"toolcall: {Str(c, "name")}", () =>
            {
                var got = ToolCallParser.Parse(Str(c, "input")).Select(x => (x.Tool, x.Args, x.Content)).ToList();
                var want = c.GetProperty("expect").EnumerateArray().Select(e => (Text(e.GetProperty("tool")), Text(e.GetProperty("args")), Text(e.GetProperty("content")))).ToList();
                Check.Equal(want.Count, got.Count, "call count");
                for (int i = 0; i < want.Count; i++) Check.Equal(want[i], got[i], $"call {i}");
                return Task.CompletedTask;
            });

        foreach (var c in Load("patch_split"))
            r.Add($"patch_split: {Str(c, "name")}", () =>
            {
                var exp = c.GetProperty("expect");
                try
                {
                    var (s, rep) = Tools.SplitSearchReplace(Str(c, "input"));
                    Check.True(!exp.TryGetProperty("error", out _), "expected an error");
                    Check.Equal(Text(exp.GetProperty("search")), s, "search");
                    Check.Equal(Text(exp.GetProperty("replace")), rep, "replace");
                }
                catch (Tools.PatchException e)
                {
                    Check.True(exp.TryGetProperty("error", out var msg), "unexpected error " + e.Message);
                    Check.Equal(msg.GetString(), e.Message, "error message");
                }
                return Task.CompletedTask;
            });

        foreach (var c in Load("fs_tools"))
            r.Add($"fs_tools: {Str(c, "name")}", () =>
            {
                if (SkipPosix(c)) throw new SkipException("POSIX-only vector");
                var (ws, outside) = NewCaseRoot(c);
                ToolFunc fn = c.GetProperty("tool").GetString() switch { "read" => Tools.Read, "write" => Tools.Write, _ => Tools.Patch };
                string got = fn(Str(c, "args"), Str(c, "content"), ws);
                var exp = c.GetProperty("expect");
                Check.Equal(Text(exp.GetProperty("result")), got, "result");
                ExpectFiles(ws, exp.GetProperty("files"), "files");
                if (outside is not null) ExpectFiles(outside, exp.GetProperty("outside_files"), "outside files");
                return Task.CompletedTask;
            });

        foreach (var c in Load("shell_allowlist"))
            r.Add($"shell_allowlist: {Str(c, "name")}", () =>
            {
                Check.Equal(c.GetProperty("expect").GetBoolean(), Shlex.Allowed(Str(c, "command"), StrList(c, "allowlist")), "match");
                return Task.CompletedTask;
            });

        foreach (var c in Load("shell_policy"))
            r.Add($"shell_policy: {Str(c, "name")}", () =>
            {
                if (SkipPosix(c)) throw new SkipException("POSIX-only vector");
                int timeout = Prop(c, "shell_timeout") is { ValueKind: JsonValueKind.Number } t ? t.GetInt32() : Tools.DefaultShellTimeout;
                var policy = new ShellPolicy(Flag(c, "allow_shell"), StrList(c, "shell_allowlist"), timeout);
                string ws = Directory.CreateTempSubdirectory("ng-cs-").FullName;
                Check.Equal(Text(c.GetProperty("expect")), Tools.Shell(Str(c, "args"), Str(c, "content"), ws, policy), "result");
                return Task.CompletedTask;
            });

        foreach (var c in Load("prompt"))
            r.Add($"prompt: {Str(c, "name")}", () =>
            {
                var reg = Prompt.DefaultRegistry();
                foreach (string n in StrList(c, "extra_tools_without_usage")) reg.Set(n, new Tool((_, _, _) => ""));
                Check.Equal(Text(c.GetProperty("expect")), Prompt.Build(reg), "prompt");
                return Task.CompletedTask;
            });

        foreach (var c in Load("llm_wire"))
            r.Add($"llm_wire: {Str(c, "name")}", async () =>
            {
                await WithEnv(Prop(c, "env"), async () =>
                {
                    string api = c.GetProperty("api").GetString()!;
                    var opts = new LlmOptions(api, Prop(c, "api_key_env") is { ValueKind: JsonValueKind.String } k ? k.GetString()! : Llm.DefaultApiKeyEnv);
                    var messages = c.GetProperty("messages").EnumerateArray().Select(m => new Message(m.GetProperty("role").GetString()!, m.GetProperty("content").GetString()!)).ToList();
                    string? reply = null;
                    LlmException? error = null;
                    List<Recorded> reqs = [];
                    string addr = "";
                    ScriptedServer? srv = null;
                    try
                    {
                        string host;
                        if (Prop(c, "host") is { ValueKind: JsonValueKind.String } lit) host = lit.GetString()!;
                        else if (Flag(c, "unreachable")) { addr = ClosedAddress(); host = "http://" + addr; }
                        else
                        {
                            srv = new ScriptedServer(Prop(c, "server") is { ValueKind: JsonValueKind.Array } sv ? sv.EnumerateArray() : []);
                            addr = srv.Addr;
                            host = srv.Url + Str(c, "host_path");
                        }
                        try { reply = await Llm.ChatAsync(messages, c.GetProperty("model").GetString()!, host, opts); }
                        catch (LlmException e) { error = e; }
                        if (srv is not null) lock (srv.Requests) reqs = [.. srv.Requests];
                    }
                    finally { srv?.Dispose(); }

                    var exp = c.GetProperty("expect");
                    if (Flag(c, "lenient_requests"))
                    {
                        CheckRequest(reqs[0], exp.GetProperty("first_request"));
                        foreach (var later in reqs.Skip(1)) Check.True(later.Authorization is null, $"credentials forwarded to {later.Path}");
                        return;
                    }
                    var wantReqs = exp.GetProperty("requests").EnumerateArray().ToList();
                    Check.Equal(wantReqs.Count, reqs.Count, "request count");
                    for (int i = 0; i < reqs.Count; i++) CheckRequest(reqs[i], wantReqs[i]);
                    if (exp.TryGetProperty("reply", out var wantReply))
                    {
                        Check.True(error is null, "unexpected error: " + error?.Message);
                        Check.Equal(wantReply.GetString(), reply, "reply");
                        return;
                    }
                    Check.True(error is not null, "expected an error, got reply " + Check.Clip(reply));
                    string msg = addr.Length > 0 ? error!.Message.Replace(addr, "HOST:PORT") : error!.Message;
                    foreach (var sub in exp.GetProperty("error_contains").EnumerateArray()) Check.True(msg.Contains(sub.GetString()!), $"error {Check.Clip(msg)} lacks {sub.GetString()}");
                    if (exp.TryGetProperty("error_absent", out var absent))
                        foreach (var sub in absent.EnumerateArray()) Check.True(!msg.Contains(sub.GetString()!), $"error {Check.Clip(msg)} contains {sub.GetString()}");
                });
            });

        foreach (var c in Load("loop"))
            r.Add($"loop: {Str(c, "name")}", async () =>
            {
                var script = c.GetProperty("replies").EnumerateArray().Select(x => JsonDocument.Parse(JsonSerializer.Serialize(new { status = 200, body = new { message = new { content = x.GetString() } } })).RootElement.Clone()).ToList();
                string ws = NewWorkspace(Prop(c, "files"));
                using var srv = new ScriptedServer(script);
                var options = new Options
                {
                    Model = "test-model", Host = srv.Url, Workspace = ws, Out = _ => { },
                    Shell = new ShellPolicy(Flag(c, "allow_shell"), StrList(c, "shell_allowlist"), Tools.DefaultShellTimeout),
                };
                await Agent.RunAsync(Str(c, "prompt"), options);
                var exp = c.GetProperty("expect");
                List<Recorded> reqs;
                lock (srv.Requests) reqs = [.. srv.Requests];
                Check.Equal(exp.GetProperty("request_count").GetInt32(), reqs.Count, "request count");
                var lastMessages = reqs[^1].Body!.Value.GetProperty("messages").EnumerateArray().ToList();
                var want = exp.GetProperty("last_request_messages").EnumerateArray().ToList();
                Check.Equal(want.Count, lastMessages.Count, "message count");
                for (int i = 0; i < want.Count; i++)
                {
                    string role = lastMessages[i].GetProperty("role").GetString()!;
                    string content = role == "system" ? "$SYSTEM" : lastMessages[i].GetProperty("content").GetString()!;
                    Check.Equal(want[i].GetProperty("role").GetString(), role, $"message {i} role");
                    Check.Equal(Text(want[i].GetProperty("content")), content, $"message {i} content");
                }
                ExpectFiles(ws, exp.GetProperty("files"), "files");
            });
    }
}
