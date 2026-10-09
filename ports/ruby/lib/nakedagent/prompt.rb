# frozen_string_literal: true

require_relative "tools"

module Nakedagent
  # An entry in the registry: the callable plus the fenced-block example shown to the model
  # (nil usage means the tool is listed by name only).
  Tool = Struct.new(:fn, :usage)

  # Ordered tool registry. It is the port's plugin seam (spec section 9): an embedding program adds or
  # replaces tools with #set and sends foundation tools back with #disable. A Hash keeps insertion order
  # and keeps a replaced key in place.
  class Registry
    def initialize
      @tools = {}
    end

    def get(name)
      @tools[name]
    end

    # Adds a tool, or replaces the tool of the same name in place (keeping its position).
    def set(name, fn = nil, usage: nil, &block)
      @tools[name.downcase] = Tool.new(fn || block, usage)
      self
    end

    # Removes tools by name. Call it after all #set calls so that it wins over them.
    def disable(*names)
      names.each { |n| @tools.delete(n.downcase) }
      self
    end

    def entries
      @tools.to_a
    end
  end

  module Prompt
    USAGE = {
      "shell" => "```shell\nls -la\n```",
      "read" => "```read README.md\n```",
      "write" => "```write hello.txt\nHello, world!\n```",
      "patch" => "```patch hello.txt\n" \
                 "<<<<<<< SEARCH\n" \
                 "Hello, world!\n" \
                 "=======\n" \
                 "Goodbye, world!\n" \
                 ">>>>>>> REPLACE\n" \
                 "```"
    }.freeze

    HEADER = "You are nakedagent, a terminal coding agent. You have these tools, " \
             "invoked as a fenced code block whose language tag is the tool name:"

    RULES = "Rules:\n" \
            "- One tool call at a time is safest; you may emit more than one per message\n" \
            "  if you're confident, but batched calls all run without seeing each other's\n" \
            "  results -- a call that depends on an earlier result must wait for the next\n" \
            "  message.\n" \
            "- Only emit a fenced tool block when you mean to execute it -- every tagged\n" \
            "  fence at column 0 is dispatched, including ones meant as examples.\n" \
            "- `patch`'s SEARCH text must match the file exactly (including whitespace) " \
            "and uniquely -- if it doesn't, you'll get an error back and should read the " \
            "file again before retrying.\n" \
            "- When you have no more tool calls to make, just respond normally -- that " \
            "hands control back to the user.\n"

    module_function

    # The four foundation tools with the given shell policy applied.
    def default_registry(policy = ShellPolicy.default)
      Registry.new
              .set("shell", ->(a, c, w) { Tools.shell(a, c, w, policy) }, usage: USAGE["shell"])
              .set("read", Tools.method(:read), usage: USAGE["read"])
              .set("write", Tools.method(:write), usage: USAGE["write"])
              .set("patch", Tools.method(:patch), usage: USAGE["patch"])
    end

    # Builds the system prompt from the registry (spec section 7).
    def build(registry)
      examples = []
      no_usage = []
      registry.entries.each do |name, tool|
        if tool.usage && !tool.usage.empty?
          examples << tool.usage
        else
          no_usage << name
        end
      end
      parts = [HEADER, examples.join("\n\n")]
      unless no_usage.empty?
        parts << "Additional tools are available (invoked the same way, as a fenced block whose language " \
                 "tag is the tool name): #{no_usage.sort_by(&:bytes).map { |n| "`#{n}`" }.join(", ")}."
      end
      parts << RULES
      parts.join("\n\n")
    end
  end
end
