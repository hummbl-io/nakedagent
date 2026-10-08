# frozen_string_literal: true

require "json"
require "net/http"
require "uri"
require_relative "pyutil"

module Nakedagent
  # Model chat client (spec section 8): Ollama and OpenAI-compatible wire formats, non-streaming.
  DEFAULT_HOST = "http://localhost:11434"
  DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"

  class LLMError < StandardError; end

  module LLM
    REDIRECTS = [301, 302, 303].freeze
    TIMEOUT = 300

    module_function

    def first_chars(text, count)
      text.length <= count ? text : text[0, count]
    end

    def one_request(uri, method, headers, body)
      http = Net::HTTP.new(uri.host, uri.port)
      http.use_ssl = uri.scheme == "https"
      http.open_timeout = TIMEOUT
      http.read_timeout = TIMEOUT
      req = (method == "POST" ? Net::HTTP::Post : Net::HTTP::Get).new(uri.request_uri)
      headers.each { |k, v| req[k] = v }
      req.body = body if body
      http.start { |h| h.request(req) }
    end

    # Sends one chat request and returns the assistant reply text. Bearer credentials go to the initial
    # URL only: redirects are followed by hand (301/302/303 become a GET without body or credentials).
    # messages are hashes with "role" and "content".
    def chat(messages, model, host = DEFAULT_HOST, api: "ollama", api_key_env: DEFAULT_API_KEY_ENV)
      unless %w[ollama openai].include?(api)
        raise LLMError, "--api must be one of ollama, openai, got: #{PyUtil.repr(api)}"
      end

      parsed = begin
        URI.parse(host)
      rescue URI::InvalidURIError
        nil
      end
      unless parsed && %w[http https].include?(parsed.scheme) && !parsed.host.to_s.empty?
        raise LLMError, "--host must be an http:// or https:// URL, got: #{PyUtil.repr(host)}"
      end

      if api == "ollama"
        name = "Ollama"
        url = "#{host}/api/chat"
        payload = { "model" => model, "messages" => messages, "stream" => false, "think" => false }
      else
        name = "OpenAI-compatible API"
        url = "#{host.sub(%r{/+\z}, "")}/chat/completions"
        payload = { "model" => model, "messages" => messages, "stream" => false }
      end
      headers = { "Content-Type" => "application/json" }
      if api == "openai"
        key = ENV.fetch(api_key_env, "")
        headers["Authorization"] = "Bearer #{key}" unless key.empty?
      end

      res = begin
        method = "POST"
        body = JSON.generate(payload)
        hdrs = headers
        hops = 0
        loop do
          resp = one_request(URI.parse(url), method, hdrs, body)
          location = resp["location"]
          return_now = !REDIRECTS.include?(resp.code.to_i) || location.nil? || hops >= 10
          break resp if return_now

          url = URI.join(url, location).to_s
          method = "GET"
          body = nil
          hdrs = {}
          hops += 1
        end
      rescue StandardError => e
        tip = api == "ollama" ? " Is `ollama serve` running?" : ""
        raise LLMError, "could not reach #{name} at #{host} (#{e.class}: #{e.message}).#{tip}"
      end

      raw = res.body.to_s
      code = res.code.to_i
      if code < 200 || code >= 300
        hint = api == "openai" && [401, 403].include?(code) ? " (check the key in $#{api_key_env})" : ""
        detail = first_chars(PyUtil.decode_replace(raw), 200)
        msg = "#{name} at #{host} returned HTTP #{[code, res.message].reject { |x| x.to_s.empty? }.join(" ")}#{hint}"
        msg += ": #{detail}" unless detail.empty?
        raise LLMError, msg
      end

      text = PyUtil.decode_replace(raw)
      data = begin
        JSON.parse(text)
      rescue JSON::ParserError => e
        raise LLMError, "#{name} at #{host} returned a non-JSON response: #{e.message}"
      end
      shape_error = -> { LLMError.new("unexpected #{name} response shape: #{first_chars(text, 300)}") }
      hash = ->(v) { v.is_a?(Hash) ? v : nil }

      message = if api == "ollama"
                  hash.call(hash.call(data)&.fetch("message", nil))
                else
                  choices = hash.call(data)&.fetch("choices", nil)
                  choices.is_a?(Array) && !choices.empty? ? hash.call(hash.call(choices[0])&.fetch("message", nil)) : nil
                end
      raise shape_error.call if message.nil? || !message.key?("content")

      content = message["content"]
      return "" if content.nil?
      raise shape_error.call unless content.is_a?(String)

      content
    end
  end
end
