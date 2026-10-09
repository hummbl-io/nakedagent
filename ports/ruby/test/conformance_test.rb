# frozen_string_literal: true

# Runs the language-neutral vectors in spec/conformance/vectors (spec/conformance/README.md).
require "fileutils"
require "json"
require "minitest/autorun"
require "socket"
require "tmpdir"
require_relative "../lib/nakedagent"

module Conformance
  VECTORS = File.expand_path("../../../spec/conformance/vectors", __dir__)
  IS_WIN = Gem.win_platform?

  module_function

  def load_suite(name)
    doc = JSON.parse(File.read(File.join(VECTORS, "#{name}.json"), encoding: "UTF-8"))
    raise "bad suite #{name}" unless doc["suite"] == name && !doc["cases"].empty?

    doc["cases"]
  end

  # Vector value encoding (spec section 3).
  def text(v)
    case v
    when nil then ""
    when String then v
    when Hash
      if v.key?("repeat") then v["repeat"][0] * v["repeat"][1]
      elsif v.key?("concat") then v["concat"].map { |p| text(p) }.join
      elsif v.key?("b64") then v["b64"].unpack1("m").force_encoding("UTF-8")
      else raise "not a text value"
      end
    end
  end

  def bytes(v)
    return v["b64"].unpack1("m") if v.is_a?(Hash) && v.key?("b64")

    text(v).b
  end

  def write_files(dir, files)
    (files || {}).each do |rel, v|
      path = File.join(dir, *rel.split("/"))
      FileUtils.mkdir_p(File.dirname(path))
      File.binwrite(path, bytes(v))
    end
  end

  def new_workspace(files = {})
    root = File.realpath(Dir.mktmpdir("ng-ruby-"))
    ws = File.join(root, "ws")
    Dir.mkdir(ws)
    write_files(ws, files)
    ws
  end

  # Workspace plus, for cases with `outside` or `symlinks`, the sibling `outside` directory and the symlink
  # fixtures. Returns [ws, outside, skip]; skip is true if symlinks cannot be created here.
  def new_case_root(c)
    ws = new_workspace(c["files"])
    return [ws, nil, false] unless c.key?("outside") || c.key?("symlinks")

    outside = File.join(File.dirname(ws), "outside")
    Dir.mkdir(outside)
    write_files(outside, c["outside"])
    (c["symlinks"] || {}).each do |rel, target|
      lp = File.join(ws, *rel.split("/"))
      FileUtils.mkdir_p(File.dirname(lp))
      begin
        File.symlink(target, lp)
      rescue NotImplementedError, SystemCallError
        return [ws, outside, true]
      end
    end
    [ws, outside, false]
  end

  def snapshot(root)
    out = {}
    Dir.glob("**/*", File::FNM_DOTMATCH, base: root).each do |rel|
      next if rel.end_with?("/.") || rel == "."

      path = File.join(root, rel)
      next if File.symlink?(path) || !File.file?(path)
      next if rel.start_with?(".nakedagent/")

      out[rel] = File.binread(path)
    end
    out
  end

  def expected_files(expected)
    expected.transform_values { |v| bytes(v) }
  end

  # NAKEDAGENT_FORCE_POSIX_VECTORS=1 runs the POSIX-only vectors on Windows too (needs POSIX tools on PATH).
  def skip_posix?(c)
    IS_WIN && ENV["NAKEDAGENT_FORCE_POSIX_VECTORS"] != "1" && c["requires"] == "posix"
  end

  # Scripted HTTP server on a TCPServer: replays `script` in order and records every request.
  class ScriptedServer
    REASONS = { 200 => "OK", 302 => "Found", 401 => "Unauthorized", 403 => "Forbidden", 500 => "Internal Server Error" }.freeze
    attr_reader :requests, :port

    def initialize(script)
      @script = script.dup
      @requests = []
      @server = TCPServer.new("127.0.0.1", 0)
      @port = @server.addr[1]
      @thread = Thread.new do
        loop do
          client = begin
            @server.accept
          rescue IOError, SystemCallError
            break
          end
          handle(client)
        end
      end
    end

    def addr
      "127.0.0.1:#{@port}"
    end

    def url
      "http://#{addr}"
    end

    def close
      @server.close
      @thread.kill
    end

    private

    def handle(client)
      request_line = client.gets.to_s
      headers = {}
      while (l = client.gets) && l != "\r\n"
        k, v = l.chomp.split(": ", 2)
        headers[k.downcase] = v
      end
      raw = headers["content-length"] ? client.read(headers["content-length"].to_i).to_s.force_encoding("UTF-8") : ""
      body = if raw.empty?
               nil
             else
               begin
                 JSON.parse(raw)
               rescue JSON::ParserError
                 { "__raw__" => raw }
               end
             end
      method, path = request_line.split(" ")
      @requests << { "method" => method, "path" => path, "body" => body, "authorization" => headers["authorization"] }
      step = @script.shift || { "status" => 500, "body" => "script exhausted" }
      status = step["status"] || 200
      payload = step["body"].is_a?(String) ? step["body"] : JSON.generate(step["body"])
      extra = (step["headers"] || {}).map { |k, v| "#{k}: #{v}\r\n" }.join
      client.write("HTTP/1.1 #{status} #{REASONS[status] || "Status"}\r\n#{extra}" \
                   "Content-Length: #{payload.bytesize}\r\nConnection: close\r\n\r\n#{payload}")
    ensure
      client.close
    end
  end

  def closed_address
    s = TCPServer.new("127.0.0.1", 0)
    addr = "127.0.0.1:#{s.addr[1]}"
    s.close
    addr
  end

  def with_env(env)
    names = ["OPENAI_API_KEY", "CUSTOM_KEY", *env.keys]
    saved = names.to_h { |n| [n, ENV.fetch(n, nil)] }
    %w[OPENAI_API_KEY CUSTOM_KEY].each { |n| ENV.delete(n) }
    env.each { |k, v| ENV[k] = v }
    yield
  ensure
    saved.each { |n, v| v.nil? ? ENV.delete(n) : ENV[n] = v }
  end
end

class ConformanceTest < Minitest::Test
  include Nakedagent

  def self.define_case(suite, index, c, &block)
    slug = c["name"].gsub(/[^A-Za-z0-9]+/, "_")[0, 60]
    define_method("test_#{suite}_#{format("%02d", index)}_#{slug}") do
      skip "POSIX-only vector" if Conformance.skip_posix?(c)
      instance_exec(c, &block)
    end
  end

  Conformance.load_suite("toolcall").each_with_index do |c, i|
    define_case("toolcall", i, c) do |cs|
      got = ToolCallParser.parse(Conformance.text(cs["input"])).map { |x| [x.tool, x.args, x.content] }
      want = cs["expect"].map { |e| [Conformance.text(e["tool"]), Conformance.text(e["args"]), Conformance.text(e["content"])] }
      assert_equal want, got
    end
  end

  Conformance.load_suite("patch_split").each_with_index do |c, i|
    define_case("patch_split", i, c) do |cs|
      if cs["expect"].key?("error")
        e = assert_raises(Tools::PatchError) { Tools.split_search_replace(Conformance.text(cs["input"])) }
        assert_equal cs["expect"]["error"], e.message
      else
        got = Tools.split_search_replace(Conformance.text(cs["input"]))
        assert_equal [Conformance.text(cs["expect"]["search"]), Conformance.text(cs["expect"]["replace"])], got
      end
    end
  end

  Conformance.load_suite("fs_tools").each_with_index do |c, i|
    define_case("fs_tools", i, c) do |cs|
      ws, outside, skip_links = Conformance.new_case_root(cs)
      skip "cannot create symlinks here" if skip_links
      got = Tools.public_send(cs["tool"], cs["args"] || "", Conformance.text(cs["content"]), ws)
      assert_equal Conformance.text(cs["expect"]["result"]), got
      assert_equal Conformance.expected_files(cs["expect"]["files"]), Conformance.snapshot(ws)
      assert_equal Conformance.expected_files(cs["expect"]["outside_files"]), Conformance.snapshot(outside) if outside
    end
  end

  Conformance.load_suite("shell_allowlist").each_with_index do |c, i|
    define_case("shell_allowlist", i, c) do |cs|
      assert_equal cs["expect"], Shlex.allowed?(cs["command"], cs["allowlist"])
    end
  end

  Conformance.load_suite("shell_policy").each_with_index do |c, i|
    define_case("shell_policy", i, c) do |cs|
      policy = ShellPolicy.new(cs["allow_shell"] || false, cs["shell_allowlist"] || [],
                               cs["shell_timeout"] || DEFAULT_SHELL_TIMEOUT)
      ws = File.realpath(Dir.mktmpdir("ng-ruby-"))
      assert_equal Conformance.text(cs["expect"]), Tools.shell(cs["args"] || "", Conformance.text(cs["content"]), ws, policy)
    end
  end

  Conformance.load_suite("prompt").each_with_index do |c, i|
    define_case("prompt", i, c) do |cs|
      reg = Prompt.default_registry(ShellPolicy.default)
      (cs["extra_tools_without_usage"] || []).each { |n| reg.set(n) { "" } }
      assert_equal Conformance.text(cs["expect"]), Prompt.build(reg)
    end
  end

  def check_request(got, want)
    assert_equal want["method"], got["method"]
    assert_equal want["path"], got["path"]
    want["body"].nil? ? assert_nil(got["body"]) : assert_equal(want["body"], got["body"])
    want["authorization"].nil? ? assert_nil(got["authorization"]) : assert_equal(want["authorization"], got["authorization"])
  end

  Conformance.load_suite("llm_wire").each_with_index do |c, i|
    define_case("llm_wire", i, c) do |cs|
      Conformance.with_env(cs["env"] || {}) do
        opts = { api: cs["api"] }
        opts[:api_key_env] = cs["api_key_env"] if cs["api_key_env"]
        reply = error = nil
        reqs = []
        addr = ""
        srv = nil
        begin
          host = if cs.key?("host")
                   cs["host"]
                 elsif cs["unreachable"]
                   addr = Conformance.closed_address
                   "http://#{addr}"
                 else
                   srv = Conformance::ScriptedServer.new(cs["server"] || [])
                   addr = srv.addr
                   srv.url + (cs["host_path"] || "")
                 end
          begin
            reply = LLM.chat(cs["messages"], cs["model"], host, **opts)
          rescue LLMError => e
            error = e
          end
          reqs = srv ? srv.requests : []
        ensure
          srv&.close
        end

        exp = cs["expect"]
        if cs["lenient_requests"]
          check_request(reqs[0], exp["first_request"])
          reqs[1..].each { |r| assert_nil r["authorization"], "credentials forwarded to #{r["path"]}" }
          next
        end
        assert_equal exp["requests"].length, reqs.length
        reqs.each_with_index { |r, k| check_request(r, exp["requests"][k]) }
        if exp.key?("reply")
          assert_nil error, error&.message
          assert_equal exp["reply"], reply
          next
        end
        refute_nil error, "expected an error, got reply #{reply.inspect}"
        msg = addr.empty? ? error.message : error.message.gsub(addr, "HOST:PORT")
        exp["error_contains"].each { |sub| assert_includes msg, sub }
        (exp["error_absent"] || []).each { |sub| refute_includes msg, sub }
      end
    end
  end

  Conformance.load_suite("loop").each_with_index do |c, i|
    define_case("loop", i, c) do |cs|
      script = cs["replies"].map { |r| { "status" => 200, "body" => { "message" => { "content" => r } } } }
      ws = Conformance.new_workspace(cs["files"])
      srv = Conformance::ScriptedServer.new(script)
      begin
        policy = ShellPolicy.new(cs["allow_shell"] || false, cs["shell_allowlist"] || [], DEFAULT_SHELL_TIMEOUT)
        Agent.run(cs["prompt"], Options.new(model: "test-model", host: srv.url, workspace: ws, shell: policy,
                                            out: ->(_) {}))
        exp = cs["expect"]
        assert_equal exp["request_count"], srv.requests.length
        last = srv.requests.last["body"]["messages"].map do |m|
          { "role" => m["role"], "content" => m["role"] == "system" ? "$SYSTEM" : m["content"] }
        end
        want = exp["last_request_messages"].map { |m| { "role" => m["role"], "content" => Conformance.text(m["content"]) } }
        assert_equal want, last
        assert_equal Conformance.expected_files(exp["files"]), Conformance.snapshot(ws)
      ensure
        srv.close
      end
    end
  end
end
