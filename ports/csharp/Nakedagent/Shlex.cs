using System.Text;

namespace Nakedagent;

/// <summary>Raised on an unterminated quote or a trailing backslash.</summary>
public sealed class ShlexException(string message) : Exception(message);

/// <summary>POSIX word splitting as Python's shlex.split defaults (spec section 6).</summary>
public static class Shlex
{
    public static List<string> Split(string s)
    {
        var tokens = new List<string>();
        var cur = new StringBuilder();
        bool inTok = false;
        var rs = s.EnumerateRunes().Select(r => r.ToString()).ToList();
        for (int i = 0; i < rs.Count; i++)
        {
            string c = rs[i];
            switch (c)
            {
                case " " or "\t" or "\r" or "\n":
                    if (inTok) { tokens.Add(cur.ToString()); cur.Clear(); inTok = false; }
                    break;
                case "\\":
                    if (i + 1 >= rs.Count) throw new ShlexException("No escaped character");
                    cur.Append(rs[++i]);
                    inTok = true;
                    break;
                case "'":
                {
                    inTok = true;
                    int j = i + 1;
                    while (j < rs.Count && rs[j] != "'") cur.Append(rs[j++]);
                    if (j >= rs.Count) throw new ShlexException("No closing quotation");
                    i = j;
                    break;
                }
                case "\"":
                {
                    inTok = true;
                    int j = i + 1;
                    for (;;)
                    {
                        if (j >= rs.Count) throw new ShlexException("No closing quotation");
                        string d = rs[j];
                        if (d == "\"") break;
                        if (d == "\\")
                        {
                            if (j + 1 >= rs.Count) throw new ShlexException("No escaped character");
                            string nx = rs[j + 1];
                            cur.Append(nx is "\"" or "\\" ? nx : "\\" + nx);
                            j += 2;
                            continue;
                        }
                        cur.Append(d);
                        j++;
                    }
                    i = j;
                    break;
                }
                default:
                    cur.Append(c);
                    inTok = true;
                    break;
            }
        }
        if (inTok) tokens.Add(cur.ToString());
        return tokens;
    }

    /// <summary>Token-prefix match against the allowlist; anything that fails to split never matches.</summary>
    public static bool Allowed(string cmd, IReadOnlyList<string>? allowlist)
    {
        if (allowlist is null || allowlist.Count == 0) return false;
        List<string> argv;
        try { argv = Split(PyUtil.Strip(cmd)); }
        catch (ShlexException) { return false; }
        if (argv.Count == 0) return false;
        foreach (string pattern in allowlist)
        {
            string item = PyUtil.Strip(pattern);
            if (item.Length == 0) continue;
            List<string> pat;
            try { pat = Split(item); }
            catch (ShlexException) { continue; }
            if (pat.Count == 0 || argv.Count < pat.Count) continue;
            bool match = true;
            for (int k = 0; k < pat.Count; k++)
            {
                if (argv[k] != pat[k]) { match = false; break; }
            }
            if (match) return true;
        }
        return false;
    }
}
