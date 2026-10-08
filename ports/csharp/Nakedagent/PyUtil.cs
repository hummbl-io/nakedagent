using System.Text;

namespace Nakedagent;

/// <summary>
/// Helpers that reproduce the few Python string behaviours the reference relies on, so the port matches it
/// exactly. .NET strings are UTF-16; every length here is in code points.
/// </summary>
public static class PyUtil
{
    /// <summary>Python str.isspace(): JS-style whitespace plus U+0085 and U+001C..U+001F, minus U+FEFF.</summary>
    public static bool IsPySpace(int c) =>
        (c >= 0x09 && c <= 0x0d) || (c >= 0x1c && c <= 0x20) || c == 0x85 || c == 0xa0 || c == 0x1680 ||
        (c >= 0x2000 && c <= 0x200a) || c == 0x2028 || c == 0x2029 || c == 0x202f || c == 0x205f || c == 0x3000;

    public static string RStrip(string s)
    {
        int end = s.Length;
        while (end > 0 && IsPySpace(s[end - 1])) end--;
        return s[..end];
    }

    public static string Strip(string s)
    {
        int start = 0;
        while (start < s.Length && IsPySpace(s[start])) start++;
        return RStrip(s[start..]);
    }

    private static bool IsLineBreak(int c) =>
        c is 0x0a or 0x0d or 0x0b or 0x0c or 0x1c or 0x1d or 0x1e or 0x85 or 0x2028 or 0x2029;

    /// <summary>Python str.splitlines(): splits on more than LF (spec section 11, quirk 3).</summary>
    public static List<string> SplitLines(string s)
    {
        var output = new List<string>();
        int start = 0;
        for (int i = 0; i < s.Length;)
        {
            int c = s[i];
            if (IsLineBreak(c))
            {
                output.Add(s[start..i]);
                i += c == 0x0d && i + 1 < s.Length && s[i + 1] == 0x0a ? 2 : 1;
                start = i;
                continue;
            }
            i++;
        }
        if (start < s.Length) output.Add(s[start..]);
        return output;
    }

    /// <summary>Length in code points.</summary>
    public static int CpLen(string s)
    {
        int n = 0;
        for (int i = 0; i < s.Length; i++)
        {
            if (char.IsHighSurrogate(s[i]) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1])) i++;
            n++;
        }
        return n;
    }

    /// <summary>Index just after the first n code points.</summary>
    public static int CpIndex(string s, int n)
    {
        int i = 0;
        for (int k = 0; k < n && i < s.Length; k++)
        {
            i += char.IsHighSurrogate(s[i]) && i + 1 < s.Length && char.IsLowSurrogate(s[i + 1]) ? 2 : 1;
        }
        return i;
    }

    private static readonly UTF8Encoding Lenient = new(false, false);
    private static readonly UTF8Encoding Strict = new(false, true);

    /// <summary>bytes.decode("utf-8", errors="replace"): .NET replaces maximal subparts, like Python.</summary>
    public static string DecodeReplace(byte[] bytes) => Lenient.GetString(bytes);

    /// <summary>Strict UTF-8 decode; null if the bytes are not valid UTF-8.</summary>
    public static string? DecodeStrict(byte[] bytes)
    {
        try { return Strict.GetString(bytes); }
        catch (DecoderFallbackException) { return null; }
    }

    /// <summary>Code point order comparison (Python's sorted() on str), unlike .NET's UTF-16 ordinal order.</summary>
    public static int CompareCodePoints(string a, string b)
    {
        byte[] x = Encoding.UTF8.GetBytes(a), y = Encoding.UTF8.GetBytes(b);
        return x.AsSpan().SequenceCompareTo(y);
    }

    /// <summary>repr() for plain strings, enough for error messages.</summary>
    public static string Repr(string s)
    {
        char q = '\'';
        if (s.Contains('\'') && !s.Contains('"')) q = '"';
        var sb = new StringBuilder().Append(q);
        foreach (var rune in s.EnumerateRunes())
        {
            int c = rune.Value;
            if (c == q || c == '\\') sb.Append('\\').Append(rune.ToString());
            else if (c == '\n') sb.Append("\\n");
            else if (c == '\r') sb.Append("\\r");
            else if (c == '\t') sb.Append("\\t");
            else if (c < 0x20 || c == 0x7f) sb.Append("\\x").Append(c.ToString("x2"));
            else sb.Append(rune.ToString());
        }
        return sb.Append(q).ToString();
    }
}
