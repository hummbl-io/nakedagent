# frozen_string_literal: true

require_relative "pyutil"

module Nakedagent
  # POSIX word splitting as Python's shlex.split defaults (spec section 6). Ruby's Shellwords
  # differs in edge cases, so the rules are implemented here.
  module Shlex
    class Error < StandardError; end

    module_function

    # Raises Shlex::Error on an unterminated quote or a trailing backslash.
    def split(str)
      tokens = []
      cur = +""
      in_tok = false
      rs = str.chars
      i = 0
      while i < rs.length
        c = rs[i]
        case c
        when " ", "\t", "\r", "\n"
          if in_tok
            tokens << cur
            cur = +""
            in_tok = false
          end
        when "\\"
          raise Error, "No escaped character" if i + 1 >= rs.length

          i += 1
          cur << rs[i]
          in_tok = true
        when "'"
          in_tok = true
          j = i + 1
          while j < rs.length && rs[j] != "'"
            cur << rs[j]
            j += 1
          end
          raise Error, "No closing quotation" if j >= rs.length

          i = j
        when '"'
          in_tok = true
          j = i + 1
          loop do
            raise Error, "No closing quotation" if j >= rs.length

            d = rs[j]
            break if d == '"'

            if d == "\\"
              raise Error, "No escaped character" if j + 1 >= rs.length

              nx = rs[j + 1]
              cur << (nx == '"' || nx == "\\" ? nx : "\\#{nx}")
              j += 2
              next
            end
            cur << d
            j += 1
          end
          i = j
        else
          cur << c
          in_tok = true
        end
        i += 1
      end
      tokens << cur if in_tok
      tokens
    end

    # Token-prefix match against the allowlist; anything that fails to split never matches.
    def allowed?(cmd, allowlist)
      return false if allowlist.nil? || allowlist.empty?

      argv = begin
        split(PyUtil.strip(cmd))
      rescue Error
        return false
      end
      return false if argv.empty?

      allowlist.each do |pattern|
        item = PyUtil.strip(pattern)
        next if item.empty?

        pat = begin
          split(item)
        rescue Error
          next
        end
        next if pat.empty? || argv.length < pat.length
        return true if pat.each_with_index.all? { |tok, k| argv[k] == tok }
      end
      false
    end
  end
end
