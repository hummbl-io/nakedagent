# frozen_string_literal: true

require_relative "llm"
require_relative "toolcall"
require_relative "prompt"

module Nakedagent
  # The agent loop (spec section 9).
  MAX_STEPS = 25

  # Configuration for a run. out is a callable taking text (default: stdout).
  Options = Struct.new(:model, :host, :workspace, :llm, :shell, :registry, :out, keyword_init: true) do
    def settled
      dup.tap do |o|
        o.host ||= DEFAULT_HOST
        o.llm ||= {}
        o.shell ||= ShellPolicy.default
        o.registry ||= Prompt.default_registry(o.shell)
        o.out ||= ->(text) { $stdout.write(text) }
      end
    end
  end

  module Agent
    module_function

    # One model call plus any tool calls in its reply. Returns true if a tool ran.
    def step(messages, options)
      o = options.settled
      reply = LLM.chat(messages, o.model, o.host, **o.llm)
      messages << { "role" => "assistant", "content" => reply }
      o.out.call("\n--- assistant ---\n#{reply}\n")

      calls = ToolCallParser.parse(reply)
      return false if calls.empty?

      calls.each do |call|
        tool = o.registry.get(call.tool.downcase)
        result = if tool.nil?
                   "Error: unknown tool '#{call.tool}'."
                 else
                   begin
                     tool.fn.call(call.args, call.content, o.workspace)
                   rescue StandardError => e
                     "Error: #{e.class}: #{e.message}"
                   end
                 end
        o.out.call("--- #{call.tool} #{call.args} ---\n#{result}\n")
        messages << { "role" => "user", "content" => "[#{call.tool} output]\n#{result}" }
      end
      true
    end

    # Calls step while it keeps running tools, capped at MAX_STEPS rounds.
    def run_until_done(messages, options)
      o = options.settled
      MAX_STEPS.times { return unless step(messages, o) }
      o.out.call("\n--- stopped after #{MAX_STEPS} tool-call rounds; your turn ---\n")
    end

    def new_conversation(options)
      [{ "role" => "system", "content" => Prompt.build(options.settled.registry) }]
    end

    # One-shot: run prompt to completion and return the transcript.
    def run(prompt, options)
      o = options.settled
      messages = new_conversation(o)
      messages << { "role" => "user", "content" => prompt }
      run_until_done(messages, o)
      messages
    end
  end
end
