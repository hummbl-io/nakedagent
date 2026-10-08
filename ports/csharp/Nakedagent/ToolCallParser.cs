using System.Text.RegularExpressions;

namespace Nakedagent;

/// <summary>One fenced tool invocation found in a model reply (spec section 4).</summary>
public sealed record ToolCall(string Tool, string Args, string Content);

public static partial class ToolCallParser
{
    [GeneratedRegex("^```([A-Za-z0-9_]+)(?: ([^\\n`]*))?\\z")]
    private static partial Regex OpenRe();

    /// <summary>Length of a column-0 all-backtick line (trailing whitespace allowed), else 0.</summary>
    private static int BareTicks(string line)
    {
        string s = PyUtil.RStrip(line);
        if (s.Length == 0) return 0;
        foreach (char c in s) if (c != '`') return 0;
        return s.Length;
    }

    /// <summary>Length of the opening backtick run of a column-0 fence marker (>= 3), else 0.</summary>
    private static int FenceTicks(string line)
    {
        int n = 0;
        while (n < line.Length && line[n] == '`') n++;
        return n >= 3 ? n : 0;
    }

    /// <summary>
    /// Every tool call in <paramref name="text"/>, in order. An unclosed block yields a single refusal call
    /// (Tool "__refused__") and consumes the rest of the input.
    /// </summary>
    public static List<ToolCall> Parse(string text)
    {
        string[] lines = text.Replace("\r\n", "\n").Split('\n');
        var calls = new List<ToolCall>();
        int i = 0, n = lines.Length;
        while (i < n)
        {
            Match m = OpenRe().Match(lines[i]);
            if (!m.Success) { i++; continue; }
            string tool = m.Groups[1].Value;
            string args = PyUtil.Strip(m.Groups[2].Success ? m.Groups[2].Value : "");
            var body = new List<string>();
            var stack = new List<int> { 3 };
            i++;
            bool closed = false;
            while (i < n)
            {
                string line = lines[i];
                int bare = BareTicks(line);
                if (bare > 0)
                {
                    if (bare == stack[^1])
                    {
                        stack.RemoveAt(stack.Count - 1);
                        i++;
                        if (stack.Count == 0) { closed = true; break; }
                        body.Add(line);
                        continue;
                    }
                    body.Add(line);
                    i++;
                    continue;
                }
                int ticks = FenceTicks(line);
                if (ticks > 0) stack.Add(ticks);
                body.Add(line);
                i++;
            }
            calls.Add(closed
                ? new ToolCall(tool, args, string.Join("\n", body))
                : new ToolCall("__refused__", tool, $"unclosed fence for '{tool}'; call refused"));
        }
        return calls;
    }
}
