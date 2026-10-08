using System.Text;
using System.Text.Json;

namespace Nakedagent;

/// <summary>One chat message.</summary>
public sealed record Message(string Role, string Content);

/// <summary>Selects the wire format. The default is Ollama.</summary>
public sealed record LlmOptions(string Api = "ollama", string ApiKeyEnv = Llm.DefaultApiKeyEnv);

/// <summary>The single error kind the model client throws.</summary>
public sealed class LlmException(string message) : Exception(message);

/// <summary>Model chat client (spec section 8): Ollama and OpenAI-compatible wire formats, non-streaming.</summary>
public static class Llm
{
    public const string DefaultHost = "http://localhost:11434";
    public const string DefaultApiKeyEnv = "OPENAI_API_KEY";

    // Redirects are followed by hand so that no request after the first can carry credentials.
    private static readonly HttpClient Client = new(new SocketsHttpHandler { AllowAutoRedirect = false })
    {
        Timeout = TimeSpan.FromSeconds(300),
    };

    private static string FirstChars(string text, int n) =>
        PyUtil.CpLen(text) <= n ? text : text[..PyUtil.CpIndex(text, n)];

    /// <summary>Sends one chat request and returns the assistant reply text.</summary>
    public static async Task<string> ChatAsync(IReadOnlyList<Message> messages, string model, string host = DefaultHost, LlmOptions? options = null)
    {
        var (api, keyEnv) = options ?? new LlmOptions();
        if (api is not ("ollama" or "openai")) throw new LlmException($"--api must be one of ollama, openai, got: {PyUtil.Repr(api)}");
        if (!Uri.TryCreate(host, UriKind.Absolute, out var parsed) || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host.Length == 0)
            throw new LlmException($"--host must be an http:// or https:// URL, got: {PyUtil.Repr(host)}");

        string name, url;
        var payload = new Dictionary<string, object?>
        {
            ["model"] = model,
            ["messages"] = messages.Select(m => new Dictionary<string, string> { ["role"] = m.Role, ["content"] = m.Content }).ToList(),
            ["stream"] = false,
        };
        if (api == "ollama")
        {
            name = "Ollama";
            url = host + "/api/chat";
            payload["think"] = false;
        }
        else
        {
            name = "OpenAI-compatible API";
            url = host.TrimEnd('/') + "/chat/completions";
        }
        string bearer = "";
        if (api == "openai") bearer = Environment.GetEnvironmentVariable(keyEnv) ?? "";

        HttpResponseMessage res;
        try
        {
            string json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
            HttpMethod method = HttpMethod.Post;
            bool first = true;
            for (int hops = 0; ; hops++)
            {
                using var req = new HttpRequestMessage(method, url);
                if (first)
                {
                    req.Content = new StringContent(json, new UTF8Encoding(false), "application/json");
                    if (bearer.Length > 0) req.Headers.TryAddWithoutValidation("Authorization", "Bearer " + bearer);
                }
                res = await Client.SendAsync(req).ConfigureAwait(false);
                int code = (int)res.StatusCode;
                string? location = res.Headers.Location?.ToString();
                if (code is not (301 or 302 or 303) || location is null || hops >= 10) break;
                res.Dispose();
                url = new Uri(new Uri(url), location).ToString();
                method = HttpMethod.Get;
                first = false;
            }
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or InvalidOperationException)
        {
            string tip = api == "ollama" ? " Is `ollama serve` running?" : "";
            string cause = e.InnerException is { } inner ? $": {inner.Message}" : "";
            throw new LlmException($"could not reach {name} at {host} ({e.Message}{cause}).{tip}");
        }

        using (res)
        {
            byte[] raw = await res.Content.ReadAsByteArrayAsync().ConfigureAwait(false);
            int status = (int)res.StatusCode;
            if (status < 200 || status >= 300)
            {
                string hint = api == "openai" && status is 401 or 403 ? $" (check the key in ${keyEnv})" : "";
                string detail = FirstChars(PyUtil.DecodeReplace(raw), 200);
                string reason = string.Join(" ", new[] { status.ToString(), res.ReasonPhrase ?? "" }.Where(x => x.Length > 0));
                throw new LlmException($"{name} at {host} returned HTTP {reason}{hint}{(detail.Length > 0 ? ": " + detail : "")}");
            }

            string text = PyUtil.DecodeReplace(raw);
            JsonDocument doc;
            try { doc = JsonDocument.Parse(text); }
            catch (JsonException e) { throw new LlmException($"{name} at {host} returned a non-JSON response: {e.Message}"); }
            using (doc)
            {
                LlmException ShapeError() => new($"unexpected {name} response shape: {FirstChars(text, 300)}");
                JsonElement? Obj(JsonElement? e, string key) =>
                    e is { ValueKind: JsonValueKind.Object } o && o.TryGetProperty(key, out var v) ? v : null;

                JsonElement? message;
                if (api == "ollama")
                {
                    message = Obj(doc.RootElement, "message");
                }
                else
                {
                    var choices = Obj(doc.RootElement, "choices");
                    message = choices is { ValueKind: JsonValueKind.Array } arr && arr.GetArrayLength() > 0 ? Obj(arr[0], "message") : null;
                }
                if (message is not { ValueKind: JsonValueKind.Object } m || !m.TryGetProperty("content", out var content)) throw ShapeError();
                return content.ValueKind switch
                {
                    JsonValueKind.Null => "",
                    JsonValueKind.String => content.GetString()!,
                    _ => throw ShapeError(),
                };
            }
        }
    }
}
