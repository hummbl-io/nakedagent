# frozen_string_literal: true

require_relative "pyutil"

module Nakedagent
  # Fenced tool-call parser (spec section 4).
  ToolCall = Struct.new(:tool, :args, :content)

  module ToolCallParser
    OPEN_RE = /\A```([A-Za-z0-9_]+)(?: ([^\n`]*))?\z/
    ALL_TICKS = /\A`+\z/

    module_function

    # Length of a column-0 all-backtick line (trailing whitespace allowed), else 0.
    def bare_ticks(line)
      s = PyUtil.rstrip(line)
      ALL_TICKS.match?(s) ? s.length : 0
    end

    # Length of the opening backtick run of a column-0 fence marker (>= 3), else 0.
    def fence_ticks(line)
      n = line[/\A`+/]&.length || 0
      n >= 3 ? n : 0
    end

    # Every tool call in text, in order. An unclosed block yields a single refusal call
    # (tool "__refused__") and consumes the rest of the input.
    def parse(text)
      lines = text.gsub("\r\n", "\n").split("\n", -1)
      calls = []
      i = 0
      n = lines.length
      while i < n
        m = OPEN_RE.match(lines[i])
        unless m
          i += 1
          next
        end
        tool = m[1]
        args = PyUtil.strip(m[2] || "")
        body = []
        stack = [3]
        i += 1
        closed = false
        while i < n
          line = lines[i]
          bare = bare_ticks(line)
          if bare.positive?
            if bare == stack.last
              stack.pop
              i += 1
              if stack.empty?
                closed = true
                break
              end
              body << line
              next
            end
            body << line
            i += 1
            next
          end
          ticks = fence_ticks(line)
          stack << ticks if ticks.positive?
          body << line
          i += 1
        end
        calls << if closed
                   ToolCall.new(tool, args, body.join("\n"))
                 else
                   ToolCall.new("__refused__", tool, "unclosed fence for '#{tool}'; call refused")
                 end
      end
      calls
    end
  end
end
