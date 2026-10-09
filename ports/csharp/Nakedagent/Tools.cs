using System.Diagnostics;
using System.Text;

namespace Nakedagent;

/// <summary>
/// A tool: (args, content, workspace) to text. Tool-level failures are returned as text (spec section 5);
/// a thrown exception is an unexpected failure the loop reports.
/// </summary>
public delegate string ToolFunc(string args, string content, string workspace);

/// <summary>The non-interactive shell policy (spec section 6).</summary>
public sealed record ShellPolicy(bool AllowShell, IReadOnlyList<string> Allowlist, int TimeoutSeconds)
{
    public static ShellPolicy Default() => new(false, [], Tools.DefaultShellTimeout);
}

public static class Tools
{
    public const int MaxOutput = 8000;
    public const int DefaultShellTimeout = 120;
    private static readonly bool IsWin = OperatingSystem.IsWindows();
    private static readonly char[] Seps = IsWin ? ['\\', '/'] : ['/'];

    public static string Truncate(string s)
    {
        int n = PyUtil.CpLen(s);
        if (n <= MaxOutput) return s;
        return $"{s[..PyUtil.CpIndex(s, MaxOutput)]}\n...[truncated, {n - MaxOutput} more chars]";
    }

    // ---------------------------------------------------------------- path guard

    private static List<string> Components(string p) =>
        p.Split(Seps).Where(c => c.Length > 0 && c != ".").ToList();

    /// <summary>
    /// Like Python's Path.resolve() (non-strict): symlinks are followed, ".." is applied after the component
    /// before it is resolved, and components that do not exist are kept as written. <paramref name="path"/> must be absolute.
    /// </summary>
    public static string RealpathNonStrict(string path)
    {
        string root = Path.GetPathRoot(path) ?? "/";
        string cur = root;
        var comps = Components(path[root.Length..]);
        int links = 0;
        while (comps.Count > 0)
        {
            string c = comps[0];
            comps.RemoveAt(0);
            if (c == "..")
            {
                if (cur != root) cur = Path.GetDirectoryName(cur) ?? root;
                continue;
            }
            string next = Path.Combine(cur, c);
            string? target = null;
            try { target = new FileInfo(next).LinkTarget; }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            if (target is not null)
            {
                links++;
                if (links > 255) { cur = next; continue; }
                string? troot = Path.IsPathRooted(target) ? Path.GetPathRoot(target) : null;
                if (troot is not null)
                {
                    cur = troot is "\\" or "/" ? (Path.GetPathRoot(cur) ?? "/") : troot;
                    comps.InsertRange(0, Components(target[troot.Length..]));
                }
                else
                {
                    comps.InsertRange(0, Components(target));
                }
                continue;
            }
            cur = next;
        }
        return cur;
    }

    private static (string Target, string Ws) ResolveTarget(string workspace, string rel)
    {
        string ws = RealpathNonStrict(Path.GetFullPath(workspace));
        string joined = Path.IsPathRooted(rel) ? rel : ws + Path.DirectorySeparatorChar + rel;
        return (RealpathNonStrict(joined), ws);
    }

    private static bool IsInside(string target, string ws)
    {
        string rel = Path.GetRelativePath(ws, target);
        return rel == "." || (rel != ".." && !rel.StartsWith(".." + Path.DirectorySeparatorChar, StringComparison.Ordinal) && !Path.IsPathRooted(rel));
    }

    private static readonly HashSet<string> Protected = [".git", ".nakedagent"];

    private static string? ProtectedName(string target, string ws)
    {
        string first = Path.GetRelativePath(ws, target).Split(Path.DirectorySeparatorChar)[0];
        if (IsWin) first = first.ToLowerInvariant();
        return Protected.Contains(first) ? first : null;
    }

    private static string MissingPath(string tool) => $"Error: {tool} tool needs a path, e.g. ```{tool} path/to/file.py```";

    // ---------------------------------------------------------------- read / write / patch

    public static string Read(string args, string content, string workspace)
    {
        string p = PyUtil.Strip(args);
        if (p.Length == 0) return MissingPath("read");
        var (target, ws) = ResolveTarget(workspace, p);
        if (!IsInside(target, ws)) return $"Error: {p} is outside the workspace.";
        if (Directory.Exists(target))
        {
            var names = Directory.EnumerateFileSystemEntries(target).Select(Path.GetFileName).Cast<string>().ToList();
            names.Sort(PyUtil.CompareCodePoints);
            return $"{p} is a directory:\n{string.Join("\n", names)}";
        }
        if (!File.Exists(target)) return $"Error: {p} does not exist.";
        return Truncate(PyUtil.DecodeReplace(File.ReadAllBytes(target)));
    }

    public static string Write(string args, string content, string workspace)
    {
        string p = PyUtil.Strip(args);
        if (p.Length == 0) return MissingPath("write");
        var (target, ws) = ResolveTarget(workspace, p);
        if (!IsInside(target, ws)) return $"Error: {p} is outside the workspace.";
        if (ProtectedName(target, ws) is { } bad) return $"Error: {p} is in protected directory '{bad}'.";
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        File.WriteAllBytes(target, new UTF8Encoding(false).GetBytes(content));
        return $"Wrote {PyUtil.CpLen(content)} chars to {p}.";
    }

    /// <summary>Raised for a malformed SEARCH/REPLACE block.</summary>
    public sealed class PatchException(string message) : Exception(message);

    /// <summary>Splits a &lt;&lt;&lt;&lt;&lt;&lt;&lt; SEARCH / ======= / &gt;&gt;&gt;&gt;&gt;&gt;&gt; REPLACE block (spec 5.2).</summary>
    public static (string Search, string Replace) SplitSearchReplace(string block)
    {
        var lines = PyUtil.SplitLines(block);
        int Find(int from, string text)
        {
            for (int i = from; i < lines.Count; i++) if (PyUtil.Strip(lines[i]) == text) return i;
            return -1;
        }
        int start = Find(0, "<<<<<<< SEARCH");
        int sep = start >= 0 ? Find(start + 1, "=======") : -1;
        int end = sep >= 0 ? Find(sep + 1, ">>>>>>> REPLACE") : -1;
        if (end < 0) throw new PatchException("expected <<<<<<< SEARCH / ======= / >>>>>>> REPLACE markers, in that order");
        for (int i = start + 1; i < end; i++)
        {
            if (PyUtil.Strip(lines[i]).StartsWith("<<<<<<<", StringComparison.Ordinal))
                throw new PatchException("a second <<<<<<< marker appears before the matching >>>>>>>");
        }
        if (lines.Skip(end + 1).Any(l => PyUtil.Strip(l).Length != 0))
            throw new PatchException("unexpected content after >>>>>>> REPLACE; use one patch block per call");
        return (string.Join("\n", lines.Skip(start + 1).Take(sep - start - 1)), string.Join("\n", lines.Skip(sep + 1).Take(end - sep - 1)));
    }

    /// <summary>Non-overlapping occurrences; an empty needle matches len+1 times, like Python's str.count.</summary>
    private static int CountOccurrences(string hay, string needle)
    {
        if (needle.Length == 0) return PyUtil.CpLen(hay) + 1;
        int n = 0;
        for (int i = hay.IndexOf(needle, StringComparison.Ordinal); i >= 0; i = hay.IndexOf(needle, i + needle.Length, StringComparison.Ordinal)) n++;
        return n;
    }

    public static string Patch(string args, string content, string workspace)
    {
        string p = PyUtil.Strip(args);
        if (p.Length == 0) return MissingPath("patch");
        var (target, ws) = ResolveTarget(workspace, p);
        if (!IsInside(target, ws)) return $"Error: {p} is outside the workspace.";
        if (ProtectedName(target, ws) is { } bad) return $"Error: {p} is in protected directory '{bad}'.";
        if (!File.Exists(target) && !Directory.Exists(target)) return $"Error: {p} does not exist. Use write to create it.";
        string search, replace;
        try { (search, replace) = SplitSearchReplace(content); }
        catch (PatchException e) { return $"Error: malformed patch block ({e.Message})."; }
        string? original = PyUtil.DecodeStrict(File.ReadAllBytes(target));
        if (original is null) return $"Error: {p} is not valid UTF-8; patch refused without changing the file.";
        int count = CountOccurrences(original, search);
        if (count == 0) return $"Error: SEARCH text not found in {p}. It must match exactly, including whitespace.";
        if (count > 1) return $"Error: SEARCH text matches {count} locations in {p}; make it more specific.";
        int at = search.Length == 0 ? 0 : original.IndexOf(search, StringComparison.Ordinal);
        File.WriteAllBytes(target, new UTF8Encoding(false).GetBytes(original[..at] + replace + original[(at + search.Length)..]));
        return $"Patched {p}.";
    }

    // ---------------------------------------------------------------- shell

    private static bool IsExecutable(string file)
    {
        if (!File.Exists(file)) return false;
        if (OperatingSystem.IsWindows()) return true;
        return (File.GetUnixFileMode(file) & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute)) != 0;
    }

    /// <summary>shutil.which: a name with a directory part is checked directly, otherwise PATH is searched.</summary>
    private static string? Which(string name)
    {
        if (name.Length == 0) return null;
        string[] exts = IsWin ? (Environment.GetEnvironmentVariable("PATHEXT") ?? ".COM;.EXE;.BAT;.CMD").Split(';') : [""];
        bool direct = name.Contains('/') || (IsWin && name.Contains('\\'));
        string[] dirs = direct ? [""] : (Environment.GetEnvironmentVariable("PATH") ?? "").Split(Path.PathSeparator);
        foreach (string dir in dirs)
        {
            string b = direct ? name : Path.Combine(dir.Length == 0 ? "." : dir, name);
            IEnumerable<string> candidates = IsWin && exts.Any(e => b.EndsWith(e, StringComparison.OrdinalIgnoreCase)) ? [b] : exts.Select(e => b + e);
            foreach (string c in candidates) if (IsExecutable(c)) return c;
        }
        return null;
    }

    public static string Shell(string args, string content, string workspace, ShellPolicy policy)
    {
        string cmd = PyUtil.Strip(content);
        if (cmd.Length == 0) cmd = PyUtil.Strip(args);
        if (cmd.Length == 0) return "Error: shell tool got no command.";
        int timeout = policy.TimeoutSeconds;
        if (timeout <= 0) return "Error: --shell-timeout must be a positive integer.";
        if (!policy.AllowShell) return "Error: shell execution blocked (non-interactive shell execution requires --allow-shell).";
        if (!Shlex.Allowed(cmd, policy.Allowlist)) return "Error: shell execution blocked (non-interactive command is not in --shell-allowlist).";
        List<string> argv;
        try { argv = Shlex.Split(cmd); }
        catch (ShlexException e) { return $"Error: malformed command ({e.Message})."; }
        string name = argv.Count > 0 ? argv[0] : "";
        string? exe = Which(name);
        if (exe is null)
        {
            return $"Error: '{name}' is not an executable on PATH. " +
                   "Non-interactive mode runs programs directly without a shell, so " +
                   "shell built-ins (e.g. cmd's echo/dir) and operators (|, &&, ;) " +
                   "are not available.";
        }
        if (IsWin && (exe.EndsWith(".bat", StringComparison.OrdinalIgnoreCase) || exe.EndsWith(".cmd", StringComparison.OrdinalIgnoreCase))
            && argv.Skip(1).Any(a => a.IndexOfAny(['&', '|', '<', '>', '^', '%', '!', '"']) >= 0))
        {
            return "Error: shell execution blocked (cmd.exe metacharacters in arguments to a batch file); " +
                   "Windows runs .bat/.cmd files through cmd.exe, which would interpret them.";
        }
        return RunCommand(exe, argv.Skip(1), workspace, timeout);
    }

    private static string RunCommand(string exe, IEnumerable<string> args, string workspace, int timeout)
    {
        var psi = new ProcessStartInfo(exe)
        {
            WorkingDirectory = workspace,
            UseShellExecute = false, // arguments go in ArgumentList: no shell, no re-parsing
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
        };
        foreach (string a in args) psi.ArgumentList.Add(a);
        using var proc = new Process { StartInfo = psi };
        try { proc.Start(); }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or IOException or InvalidOperationException)
        {
            return $"Error: command execution failed: {e.GetType().Name}: {e.Message}";
        }
        proc.StandardInput.Close();
        var outMs = new MemoryStream();
        var errMs = new MemoryStream();
        Task outTask = proc.StandardOutput.BaseStream.CopyToAsync(outMs);
        Task errTask = proc.StandardError.BaseStream.CopyToAsync(errMs);
        bool timedOut = false;
        if (!proc.WaitForExit(timeout * 1000))
        {
            timedOut = true;
            try { proc.Kill(true); } catch (InvalidOperationException) { }
            proc.WaitForExit();
        }
        Task.WaitAll([outTask, errTask], 5000);
        if (timedOut) return $"Error: command timed out after {timeout}s.";
        var parts = new List<string> { $"(exit {proc.ExitCode})" };
        if (outMs.Length > 0) parts.Add(PyUtil.DecodeReplace(outMs.ToArray()));
        if (errMs.Length > 0) parts.Add("--- stderr ---\n" + PyUtil.DecodeReplace(errMs.ToArray()));
        return Truncate(string.Join("\n", parts));
    }
}
