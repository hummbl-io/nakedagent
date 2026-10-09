# frozen_string_literal: true

# Differential-test harness (spec/conformance/differential):
#   ruby tools/diff_harness.rb cases.jsonl > out.jsonl
require "json"
require_relative "../lib/nakedagent"

include Nakedagent # rubocop:disable Style/MixinUsage

File.foreach(ARGV[0], encoding: "UTF-8") do |line|
  next if line.strip.empty?

  c = JSON.parse(line)
  result =
    case c["op"]
    when "toolcall"
      ToolCallParser.parse(c["input"]).map { |x| [x.tool, x.args, x.content] }
    when "patch_split"
      begin
        Tools.split_search_replace(c["input"])
      rescue Tools::PatchError => e
        { "error" => e.message }
      end
    when "allowlist" then Shlex.allowed?(c["cmd"], c["allowlist"])
    when "strip" then PyUtil.strip(c["input"])
    when "decode" then PyUtil.decode_replace(c["b64"].unpack1("m"))
    when "trunc" then Tools.truncate(c["unit"] * c["n"])
    else raise "unknown op #{c["op"]}"
    end
  puts JSON.generate(result)
end
